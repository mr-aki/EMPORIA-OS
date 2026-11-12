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
    from datetime import datetime, timezone

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

    today = datetime.now(timezone.utc).date().isoformat()
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
