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
            "completed_runs": 0,
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
