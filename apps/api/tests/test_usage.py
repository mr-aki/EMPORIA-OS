from decimal import Decimal

from emporia_api.providers import ProviderReply


def test_usage_summary_aggregates_provider_reported_tokens_per_workspace(
    client, auth_headers, monkeypatch
):
    class FakeGateway:
        def configured(self, provider):
            return provider == "openai"

        async def complete(self, request):
            return ProviderReply(
                provider=request.provider,
                model=request.model,
                content="A grounded launch strategy.",
                prompt_tokens=123,
                completion_tokens=45,
                total_tokens=168,
                request_id="usage-test-request",
            )

    monkeypatch.setattr("emporia_api.main.provider_gateway", FakeGateway())

    created = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers=auth_headers,
        json={
            "provider": "openai",
            "model": "gpt-5",
            "task": "Prepare a concise launch strategy.",
            "max_tokens": 256,
        },
    )
    assert created.status_code == 201, created.text

    response = client.get("/api/v1/usage/summary", headers=auth_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["totals"] == {
        "runs": 1,
        "completed_runs": 1,
        "failed_runs": 0,
        "running_runs": 0,
        "prompt_tokens": 123,
        "completion_tokens": 45,
        "total_tokens": 168,
    }
    assert payload["by_execution_type"]["agent"]["total_tokens"] == 168
    assert payload["by_execution_type"]["skill"]["runs"] == 0
    assert payload["by_provider_model"] == [
        {
            "execution_type": "agent",
            "provider": "openai",
            "model": "gpt-5",
            "runs": 1,
            "completed_runs": 1,
            "failed_runs": 0,
            "running_runs": 0,
            "prompt_tokens": 123,
            "completion_tokens": 45,
            "total_tokens": 168,
        }
    ]


def test_usage_summary_requires_authentication_and_is_workspace_scoped(
    client, auth_headers
):
    assert client.get("/api/v1/usage/summary").status_code == 401

    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": "other-workspace@example.com",
            "password": "AnotherStrongPassword!2026",
            "display_name": "Other Owner",
            "workspace_name": "Other Workspace",
        },
    )
    assert registration.status_code == 201
    other_headers = {
        "Authorization": f"Bearer {registration.json()['access_token']}"
    }

    response = client.get("/api/v1/usage/summary", headers=other_headers)
    assert response.status_code == 200
    assert response.json()["totals"]["runs"] == 0
    assert response.json()["totals"]["total_tokens"] == 0
    assert response.json()["by_provider_model"] == []



def test_usage_summary_supports_inclusive_date_filters_and_daily_breakdown(
    client, auth_headers, monkeypatch
):
    from datetime import UTC, datetime

    class FakeGateway:
        def configured(self, provider):
            return provider == "openai"

        async def complete(self, request):
            return ProviderReply(
                provider=request.provider,
                model=request.model,
                content="Daily usage test.",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                request_id="daily-usage-test",
            )

    monkeypatch.setattr("emporia_api.main.provider_gateway", FakeGateway())
    created = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers=auth_headers,
        json={
            "provider": "openai",
            "model": "gpt-5",
            "task": "Test date-scoped usage.",
            "max_tokens": 64,
        },
    )
    assert created.status_code == 201, created.text

    today = datetime.now(UTC).date().isoformat()
    response = client.get(
        f"/api/v1/usage/summary?start_date={today}&end_date={today}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["start_date"] == today
    assert payload["end_date"] == today
    assert payload["totals"]["runs"] == 1
    assert payload["by_day"] == [
        {
            "date": today,
            "runs": 1,
            "completed_runs": 1,
            "failed_runs": 0,
            "running_runs": 0,
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }
    ]

    empty = client.get(
        "/api/v1/usage/summary?start_date=2099-01-01",
        headers=auth_headers,
    )
    assert empty.status_code == 200
    assert empty.json()["totals"]["runs"] == 0
    assert empty.json()["by_day"] == []


def test_usage_summary_rejects_reversed_date_range(client, auth_headers):
    response = client.get(
        "/api/v1/usage/summary?start_date=2026-11-13&end_date=2026-11-12",
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "end_date must be on or after start_date"


def test_configured_model_prices_are_snapshotted_and_costs_are_reported(
    client, auth_headers, monkeypatch
):
    class FakeGateway:
        def configured(self, provider):
            return provider == "openai"

        async def complete(self, request):
            return ProviderReply(
                provider=request.provider,
                model=request.model,
                content="Cost ledger test.",
                prompt_tokens=123,
                completion_tokens=45,
                total_tokens=168,
                request_id="cost-ledger-test",
            )

    monkeypatch.setattr("emporia_api.main.provider_gateway", FakeGateway())

    configured = client.put(
        "/api/v1/usage/pricing/openai/gpt-5",
        headers=auth_headers,
        json={
            "input_usd_per_million_tokens": "2",
            "output_usd_per_million_tokens": "8",
        },
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["input_usd_per_million_tokens"] == "2.0000000000"

    first = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers=auth_headers,
        json={
            "provider": "openai",
            "model": "gpt-5",
            "task": "Calculate a cost estimate.",
            "max_tokens": 128,
        },
    )
    assert first.status_code == 201, first.text
    first_cost = Decimal(str(first.json()["estimated_cost_usd"]))
    assert first_cost == Decimal("0.0006060000000000")
    assert first.json()["input_price_usd_per_million_tokens"] == "2.0000000000"
    assert first.json()["output_price_usd_per_million_tokens"] == "8.0000000000"

    updated = client.put(
        "/api/v1/usage/pricing/openai/gpt-5",
        headers=auth_headers,
        json={
            "input_usd_per_million_tokens": "100",
            "output_usd_per_million_tokens": "200",
        },
    )
    assert updated.status_code == 200, updated.text

    second = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers=auth_headers,
        json={
            "provider": "openai",
            "model": "gpt-5",
            "task": "Calculate with the revised rates.",
            "max_tokens": 128,
        },
    )
    assert second.status_code == 201, second.text
    assert Decimal(str(second.json()["estimated_cost_usd"])) == Decimal(
        "0.0213000000000000"
    )
    assert Decimal(str(first.json()["estimated_cost_usd"])) == first_cost

    costs = client.get("/api/v1/usage/costs", headers=auth_headers)
    assert costs.status_code == 200, costs.text
    summary = costs.json()
    assert summary["currency"] == "USD"
    assert summary["totals"]["runs"] == 2
    assert summary["totals"]["priced_runs"] == 2
    assert summary["totals"]["unpriced_runs"] == 0
    assert Decimal(str(summary["totals"]["estimated_cost_usd"])) == Decimal(
        "0.0219060000000000"
    )
    assert len(summary["by_provider_model"]) == 1
    assert len(summary["by_day"]) == 1
    assert summary["by_day"][0]["priced_runs"] == 2

    rates = client.get("/api/v1/usage/pricing", headers=auth_headers)
    assert rates.status_code == 200
    assert rates.json()[0]["input_usd_per_million_tokens"] == "100.0000000000"


def test_costs_remain_explicitly_unpriced_without_rates_and_are_workspace_scoped(
    client, auth_headers, monkeypatch
):
    class FakeGateway:
        def configured(self, provider):
            return provider == "openai"

        async def complete(self, request):
            return ProviderReply(
                provider=request.provider,
                model=request.model,
                content="Unknown price test.",
                prompt_tokens=50,
                completion_tokens=25,
                total_tokens=75,
                request_id="unknown-price-test",
            )

    monkeypatch.setattr("emporia_api.main.provider_gateway", FakeGateway())
    created = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers=auth_headers,
        json={
            "provider": "openai",
            "model": "unpriced-model",
            "task": "Do not invent a cost.",
            "max_tokens": 64,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["estimated_cost_usd"] is None

    own_costs = client.get("/api/v1/usage/costs", headers=auth_headers)
    assert own_costs.status_code == 200
    assert own_costs.json()["totals"]["runs"] == 1
    assert own_costs.json()["totals"]["priced_runs"] == 0
    assert own_costs.json()["totals"]["unpriced_runs"] == 1
    assert Decimal(str(own_costs.json()["totals"]["estimated_cost_usd"])) == Decimal(0)

    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": "price-isolation@example.com",
            "password": "AnotherStrongPassword!2026",
            "display_name": "Price Isolation",
            "workspace_name": "Isolated Pricing Workspace",
        },
    )
    assert registration.status_code == 201
    other_headers = {
        "Authorization": f"Bearer {registration.json()['access_token']}"
    }
    other_rates = client.get("/api/v1/usage/pricing", headers=other_headers)
    other_costs = client.get("/api/v1/usage/costs", headers=other_headers)
    assert other_rates.status_code == 200
    assert other_rates.json() == []
    assert other_costs.status_code == 200
    assert other_costs.json()["totals"]["runs"] == 0


def test_only_workspace_owners_and_admins_can_change_model_prices(
    client, auth_headers
):
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": "pricing-viewer@example.com",
            "password": "AnotherStrongPassword!2026",
            "display_name": "Pricing Viewer",
            "workspace_name": "Pricing Viewer Workspace",
        },
    )
    assert registration.status_code == 201
    token = registration.json()["access_token"]
    from emporia_api.database import SessionLocal
    from emporia_api.models import WorkspaceMembership

    with SessionLocal() as session:
        membership = session.query(WorkspaceMembership).filter_by(
            user_id=registration.json()["user_id"],
            workspace_id=registration.json()["workspace_id"],
        ).one()
        membership.role = "viewer"
        session.commit()

    viewer_headers = {"Authorization": f"Bearer {token}"}
    denied = client.put(
        "/api/v1/usage/pricing/openai/gpt-5",
        headers=viewer_headers,
        json={
            "input_usd_per_million_tokens": "1",
            "output_usd_per_million_tokens": "2",
        },
    )
    assert denied.status_code == 403
