from emporia_api.providers import ProviderReply


def test_agent_run_idempotency_replays_without_calling_provider_twice(
    client, auth_headers, monkeypatch
):
    calls = []

    class FakeGateway:
        def configured(self, provider):
            return provider == "openai"

        async def complete(self, request):
            calls.append(request)
            return ProviderReply(
                provider="openai",
                model="gpt-5",
                content="Persisted launch guidance.",
                prompt_tokens=80,
                completion_tokens=30,
                total_tokens=110,
                request_id="idempotency-agent-request",
            )

    monkeypatch.setattr("emporia_api.main.provider_gateway", FakeGateway())
    headers = {**auth_headers, "Idempotency-Key": "agent-launch-run-0001"}
    body = {
        "provider": "openai",
        "model": "gpt-5",
        "task": "Prepare a launch strategy.",
        "max_tokens": 256,
    }

    first = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers=headers,
        json=body,
    )
    replay = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers=headers,
        json=body,
    )

    assert first.status_code == 201, first.text
    assert replay.status_code == 200, replay.text
    assert replay.headers["idempotency-replayed"] == "true"
    assert replay.json() == first.json()
    assert len(calls) == 1
    history = client.get("/api/v1/agent-runs", headers=auth_headers).json()
    assert len(history) == 1
    events = client.get("/api/v1/audit-events", headers=auth_headers).json()
    assert sum(event["action"] == "agent.run.started" for event in events) == 1


def test_agent_run_idempotency_rejects_key_reuse_for_different_payload(
    client, auth_headers, monkeypatch
):
    calls = []

    class FakeGateway:
        def configured(self, provider):
            return True

        async def complete(self, request):
            calls.append(request)
            return ProviderReply(
                provider="openai",
                model="gpt-5",
                content="One result only.",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                request_id="idempotency-conflict-request",
            )

    monkeypatch.setattr("emporia_api.main.provider_gateway", FakeGateway())
    headers = {**auth_headers, "Idempotency-Key": "agent-conflict-key-0001"}
    original = {
        "provider": "openai",
        "model": "gpt-5",
        "task": "Prepare a launch strategy.",
        "max_tokens": 128,
    }
    changed = {**original, "task": "Prepare a supplier risk assessment."}

    first = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers=headers,
        json=original,
    )
    conflict = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers=headers,
        json=changed,
    )

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == (
        "Idempotency-Key was already used with a different request"
    )
    assert len(calls) == 1
    assert len(client.get("/api/v1/agent-runs", headers=auth_headers).json()) == 1


def test_skill_run_idempotency_replays_without_second_provider_call(
    client, auth_headers, monkeypatch
):
    calls = []

    class FakeGateway:
        def configured(self, provider):
            return True

        async def complete(self, request):
            calls.append(request)
            return ProviderReply(
                provider="openai",
                model="gpt-5",
                content="Validate the market before committing capital.",
                prompt_tokens=95,
                completion_tokens=25,
                total_tokens=120,
                request_id="idempotency-skill-request",
            )

    monkeypatch.setattr("emporia_api.main.provider_gateway", FakeGateway())
    headers = {**auth_headers, "Idempotency-Key": "skill-market-scan-0001"}
    body = {
        "provider": "openai",
        "model": "gpt-5",
        "inputs": {
            "market": "Reusable home storage",
            "geography": "United Kingdom",
            "target_customer": "Renters in small urban apartments",
        },
        "max_tokens": 256,
    }

    first = client.post(
        "/api/v1/skills/market-opportunity-scan/runs",
        headers=headers,
        json=body,
    )
    replay = client.post(
        "/api/v1/skills/market-opportunity-scan/runs",
        headers=headers,
        json=body,
    )

    assert first.status_code == 201, first.text
    assert replay.status_code == 200, replay.text
    assert replay.headers["idempotency-replayed"] == "true"
    assert replay.json() == first.json()
    assert len(calls) == 1
    assert len(client.get("/api/v1/skill-runs", headers=auth_headers).json()) == 1


def test_idempotency_key_is_scoped_to_workspace(client, auth_headers, monkeypatch):
    calls = []

    class FakeGateway:
        def configured(self, provider):
            return True

        async def complete(self, request):
            calls.append(request)
            return ProviderReply(
                provider="openai",
                model="gpt-5",
                content="Workspace-scoped result.",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                request_id=f"workspace-{len(calls)}",
            )

    monkeypatch.setattr("emporia_api.main.provider_gateway", FakeGateway())
    body = {
        "provider": "openai",
        "model": "gpt-5",
        "task": "Prepare a launch strategy.",
        "max_tokens": 128,
    }
    first_headers = {**auth_headers, "Idempotency-Key": "shared-key-per-workspace"}

    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": "idempotency-other@example.com",
            "password": "AnotherStrongPassword!2026",
            "display_name": "Another Owner",
            "workspace_name": "Independent Workspace",
        },
    )
    assert registration.status_code == 201
    other_headers = {
        "Authorization": f"Bearer {registration.json()['access_token']}",
        "Idempotency-Key": "shared-key-per-workspace",
    }

    first = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers=first_headers,
        json=body,
    )
    second_workspace = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers=other_headers,
        json=body,
    )

    assert first.status_code == 201
    assert second_workspace.status_code == 201
    assert first.json()["id"] != second_workspace.json()["id"]
    assert len(calls) == 2


def test_idempotency_header_rejects_invalid_keys(client, auth_headers):
    response = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers={**auth_headers, "Idempotency-Key": "bad key with spaces"},
        json={
            "provider": "openai",
            "model": "gpt-5",
            "task": "Prepare a launch strategy.",
        },
    )
    assert response.status_code == 422
    assert client.get("/api/v1/agent-runs", headers=auth_headers).json() == []
