from emporia_api.database import SessionLocal
from emporia_api.models import AgentRun, WorkspaceMembership
from emporia_api.providers import ProviderReply, ProviderRequestError


def test_output_budget_reserves_max_tokens_then_settles_actual_completion_usage(
    client, auth_headers, monkeypatch
):
    configured = client.put(
        "/api/v1/usage/budget",
        headers=auth_headers,
        json={"monthly_output_tokens": 100},
    )
    assert configured.status_code == 200
    assert configured.json()["configured"] is True
    assert configured.json()["monthly_output_token_limit"] == 100

    calls = []

    class FakeGateway:
        def configured(self, provider):
            return provider == "openai"

        async def complete(self, request):
            calls.append(request)
            return ProviderReply(
                provider="openai",
                model="gpt-5",
                content="Validate the market before launch.",
                prompt_tokens=200,
                completion_tokens=30,
                total_tokens=230,
                request_id="budget-settlement-request",
            )

    monkeypatch.setattr("emporia_api.main.provider_gateway", FakeGateway())
    first = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers=auth_headers,
        json={
            "provider": "openai",
            "model": "gpt-5",
            "task": "Prepare a launch strategy.",
            "max_tokens": 80,
        },
    )
    assert first.status_code == 201, first.text

    state = client.get("/api/v1/usage/budget", headers=auth_headers)
    assert state.status_code == 200
    assert state.json()["used_output_tokens"] == 30
    assert state.json()["reserved_output_tokens"] == 0
    assert state.json()["available_output_tokens"] == 70

    blocked = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers=auth_headers,
        json={
            "provider": "openai",
            "model": "gpt-5",
            "task": "Prepare another strategy.",
            "max_tokens": 71,
        },
    )
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["message"] == (
        "Workspace monthly output-token budget exceeded"
    )
    assert blocked.json()["detail"]["used"] == 30
    assert blocked.json()["detail"]["reserved"] == 0
    assert blocked.json()["detail"]["requested"] == 71
    assert int(blocked.headers["retry-after"]) > 0
    assert len(calls) == 1
    assert len(client.get("/api/v1/agent-runs", headers=auth_headers).json()) == 1


def test_output_budget_is_shared_by_agent_and_skill_runs(
    client, auth_headers, monkeypatch
):
    configured = client.put(
        "/api/v1/usage/budget",
        headers=auth_headers,
        json={"monthly_output_tokens": 100},
    )
    assert configured.status_code == 200

    calls = []

    class FakeGateway:
        def configured(self, provider):
            return True

        async def complete(self, request):
            calls.append(request)
            return ProviderReply(
                provider="openai",
                model="gpt-5",
                content="A short evidence-led recommendation.",
                prompt_tokens=20,
                completion_tokens=25,
                total_tokens=45,
                request_id=f"shared-budget-{len(calls)}",
            )

    monkeypatch.setattr("emporia_api.main.provider_gateway", FakeGateway())
    agent_run = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers={**auth_headers, "Idempotency-Key": "monthly-budget-agent-001"},
        json={
            "provider": "openai",
            "model": "gpt-5",
            "task": "Prepare a launch strategy.",
            "max_tokens": 60,
        },
    )
    replay = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers={**auth_headers, "Idempotency-Key": "monthly-budget-agent-001"},
        json={
            "provider": "openai",
            "model": "gpt-5",
            "task": "Prepare a launch strategy.",
            "max_tokens": 60,
        },
    )
    assert agent_run.status_code == 201
    assert replay.status_code == 200
    assert replay.headers["idempotency-replayed"] == "true"

    skill_run = client.post(
        "/api/v1/skills/market-opportunity-scan/runs",
        headers=auth_headers,
        json={
            "provider": "openai",
            "model": "gpt-5",
            "inputs": {
                "market": "Reusable home storage",
                "geography": "United Kingdom",
                "target_customer": "Renters in small urban apartments",
            },
            "max_tokens": 76,
        },
    )
    assert skill_run.status_code == 429
    assert skill_run.json()["detail"]["used"] == 25
    assert skill_run.json()["detail"]["requested"] == 76
    assert len(calls) == 1
    state = client.get("/api/v1/usage/budget", headers=auth_headers).json()
    assert state["used_output_tokens"] == 25
    assert state["reserved_output_tokens"] == 0


def test_provider_failure_conservatively_charges_reserved_output_tokens(
    client, auth_headers, monkeypatch
):
    configured = client.put(
        "/api/v1/usage/budget",
        headers=auth_headers,
        json={"monthly_output_tokens": 40},
    )
    assert configured.status_code == 200

    class FailingGateway:
        def configured(self, provider):
            return True

        async def complete(self, request):
            raise ProviderRequestError("upstream timed out after submission")

    monkeypatch.setattr("emporia_api.main.provider_gateway", FailingGateway())
    failed = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers=auth_headers,
        json={
            "provider": "openai",
            "model": "gpt-5",
            "task": "Prepare a launch strategy.",
            "max_tokens": 30,
        },
    )
    assert failed.status_code == 502

    state = client.get("/api/v1/usage/budget", headers=auth_headers).json()
    assert state["used_output_tokens"] == 30
    assert state["reserved_output_tokens"] == 0
    assert state["available_output_tokens"] == 10

    blocked = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers=auth_headers,
        json={
            "provider": "openai",
            "model": "gpt-5",
            "task": "A second launch plan.",
            "max_tokens": 11,
        },
    )
    assert blocked.status_code == 429


def test_budget_does_not_charge_runs_that_fail_before_provider_call(client, auth_headers):
    configured = client.put(
        "/api/v1/usage/budget",
        headers=auth_headers,
        json={"monthly_output_tokens": 50},
    )
    assert configured.status_code == 200

    failed = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers=auth_headers,
        json={
            "provider": "openai",
            "model": "gpt-5",
            "task": "Prepare a launch strategy.",
            "max_tokens": 40,
        },
    )
    assert failed.status_code == 503
    state = client.get("/api/v1/usage/budget", headers=auth_headers).json()
    assert state["used_output_tokens"] == 0
    assert state["reserved_output_tokens"] == 0
    assert state["available_output_tokens"] == 50


def test_owner_cannot_lower_budget_below_current_usage_and_viewers_cannot_change_it(
    client, auth_headers, monkeypatch
):
    assert client.put(
        "/api/v1/usage/budget",
        headers=auth_headers,
        json={"monthly_output_tokens": 100},
    ).status_code == 200

    class FakeGateway:
        def configured(self, provider):
            return True

        async def complete(self, request):
            return ProviderReply(
                provider="openai",
                model="gpt-5",
                content="Budgeted output.",
                prompt_tokens=20,
                completion_tokens=40,
                total_tokens=60,
                request_id="budget-lower-limit-check",
            )

    monkeypatch.setattr("emporia_api.main.provider_gateway", FakeGateway())
    execution = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers=auth_headers,
        json={
            "provider": "openai",
            "model": "gpt-5",
            "task": "Prepare a launch strategy.",
            "max_tokens": 60,
        },
    )
    assert execution.status_code == 201

    too_low = client.put(
        "/api/v1/usage/budget",
        headers=auth_headers,
        json={"monthly_output_tokens": 30},
    )
    assert too_low.status_code == 409
    assert too_low.json()["detail"]["used"] == 40
    assert client.get("/api/v1/usage/budget", headers=auth_headers).json()[
        "monthly_output_token_limit"
    ] == 100

    me = client.get("/api/v1/auth/me", headers=auth_headers).json()
    workspace_id = me["workspaces"][0]["id"]

    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": "budget-viewer@example.com",
            "password": "AnotherStrongPassword!2026",
            "display_name": "Budget Viewer",
            "workspace_name": "Viewer Initial Workspace",
        },
    )
    assert registration.status_code == 201
    user_id = registration.json()["user_id"]
    with SessionLocal() as session:
        session.add(
            WorkspaceMembership(
                workspace_id=workspace_id,
                user_id=user_id,
                role="viewer",
            )
        )
        session.commit()

    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "budget-viewer@example.com",
            "password": "AnotherStrongPassword!2026",
            "workspace_id": workspace_id,
        },
    )
    assert login.status_code == 200
    viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    denied = client.put(
        "/api/v1/usage/budget",
        headers=viewer_headers,
        json={"monthly_output_tokens": 200},
    )
    assert denied.status_code == 403

    too_low = client.put(
        "/api/v1/usage/budget",
        headers=auth_headers,
        json={"monthly_output_tokens": 0},
    )
    assert too_low.status_code == 422


def test_in_progress_run_reserves_its_requested_output_tokens(client, auth_headers):
    configured = client.put(
        "/api/v1/usage/budget",
        headers=auth_headers,
        json={"monthly_output_tokens": 100},
    )
    assert configured.status_code == 200

    me = client.get("/api/v1/auth/me", headers=auth_headers).json()
    workspace_id = me["workspaces"][0]["id"]
    with SessionLocal() as session:
        session.add(AgentRun(
            workspace_id=workspace_id,
            agent_id="commerce-strategist",
            agent_version="1.0.0",
            provider="openai",
            model="gpt-5",
            status="running",
            task="A currently executing task.",
            requested_max_tokens=70,
        ))
        session.commit()

    state = client.get("/api/v1/usage/budget", headers=auth_headers)
    assert state.status_code == 200
    assert state.json()["used_output_tokens"] == 0
    assert state.json()["reserved_output_tokens"] == 70
    assert state.json()["available_output_tokens"] == 30

    blocked = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers=auth_headers,
        json={
            "provider": "openai",
            "model": "gpt-5",
            "task": "Another task while the first is still running.",
            "max_tokens": 31,
        },
    )
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["reserved"] == 70


def test_skill_run_settles_reported_completion_tokens(client, auth_headers, monkeypatch):
    assert client.put(
        "/api/v1/usage/budget",
        headers=auth_headers,
        json={"monthly_output_tokens": 100},
    ).status_code == 200

    class FakeGateway:
        def configured(self, provider):
            return True

        async def complete(self, request):
            return ProviderReply(
                provider="openai",
                model="gpt-5",
                content="A demand validation plan.",
                prompt_tokens=70,
                completion_tokens=22,
                total_tokens=92,
                request_id="skill-budget-settlement",
            )

    monkeypatch.setattr("emporia_api.main.provider_gateway", FakeGateway())
    result = client.post(
        "/api/v1/skills/market-opportunity-scan/runs",
        headers=auth_headers,
        json={
            "provider": "openai",
            "model": "gpt-5",
            "inputs": {
                "market": "Reusable home storage",
                "geography": "United Kingdom",
                "target_customer": "Renters in small urban apartments",
            },
            "max_tokens": 60,
        },
    )
    assert result.status_code == 201, result.text
    state = client.get("/api/v1/usage/budget", headers=auth_headers).json()
    assert state["used_output_tokens"] == 22
    assert state["reserved_output_tokens"] == 0
    assert state["available_output_tokens"] == 78


def test_output_budget_reads_are_authenticated_and_workspace_scoped(
    client, auth_headers
):
    assert client.get("/api/v1/usage/budget").status_code == 401
    configured = client.put(
        "/api/v1/usage/budget",
        headers=auth_headers,
        json={"monthly_output_tokens": 250},
    )
    assert configured.status_code == 200

    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": "budget-isolation@example.com",
            "password": "AnotherStrongPassword!2026",
            "display_name": "Separate Owner",
            "workspace_name": "Separate Workspace",
        },
    )
    assert registration.status_code == 201
    other_headers = {
        "Authorization": f"Bearer {registration.json()['access_token']}"
    }
    other_state = client.get("/api/v1/usage/budget", headers=other_headers)
    assert other_state.status_code == 200
    assert other_state.json()["configured"] is False
    assert other_state.json()["monthly_output_token_limit"] is None
    assert other_state.json()["available_output_tokens"] is None
