from datetime import UTC, datetime

import pytest

from emporia_api.database import SessionLocal
from emporia_api.providers import ProviderReply
from emporia_api.rate_limits import RateLimitExceeded, consume_workspace_rate_limit


def test_database_rate_limit_is_workspace_and_execution_scoped_and_resets_by_minute(client):
    first_window = datetime(2026, 11, 12, 15, 40, 10, tzinfo=UTC)

    with SessionLocal() as session:
        assert consume_workspace_rate_limit(
            session, "workspace-a", "agent", 1, now=first_window
        ) == 1
        session.commit()

        with pytest.raises(RateLimitExceeded):
            consume_workspace_rate_limit(
                session,
                "workspace-a",
                "agent",
                1,
                now=first_window.replace(second=20),
            )
        session.rollback()

        # A different execution family and a different workspace have independent buckets.
        assert consume_workspace_rate_limit(
            session, "workspace-a", "skill", 1, now=first_window
        ) == 1
        session.commit()
        assert consume_workspace_rate_limit(
            session, "workspace-b", "agent", 1, now=first_window
        ) == 1
        session.commit()

        next_window = first_window.replace(minute=41, second=0)
        assert consume_workspace_rate_limit(
            session, "workspace-a", "agent", 1, now=next_window
        ) == 1
        session.commit()


def test_agent_rate_limit_returns_429_but_idempotent_replay_does_not_consume_slot(
    client, auth_headers, monkeypatch
):
    monkeypatch.setattr("emporia_api.main.settings.agent_runs_per_minute", 1)
    calls = []

    class FakeGateway:
        def configured(self, provider):
            return provider == "openai"

        async def complete(self, request):
            calls.append(request)
            return ProviderReply(
                provider="openai",
                model="gpt-5",
                content="Rate-limited workspace run.",
                prompt_tokens=20,
                completion_tokens=10,
                total_tokens=30,
                request_id="rate-limit-test-request",
            )

    monkeypatch.setattr("emporia_api.main.provider_gateway", FakeGateway())
    body = {
        "provider": "openai",
        "model": "gpt-5",
        "task": "Prepare a launch strategy.",
        "max_tokens": 128,
    }
    first_headers = {
        **auth_headers,
        "Idempotency-Key": "rate-limit-original-run",
    }

    first = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers=first_headers,
        json=body,
    )
    replay = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers=first_headers,
        json=body,
    )
    throttled = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers={
            **auth_headers,
            "Idempotency-Key": "rate-limit-second-run",
        },
        json=body,
    )

    assert first.status_code == 201, first.text
    assert replay.status_code == 200, replay.text
    assert replay.headers["idempotency-replayed"] == "true"
    assert replay.json()["id"] == first.json()["id"]
    assert throttled.status_code == 429
    assert throttled.json()["detail"] == "Workspace agent execution rate limit reached"
    assert 1 <= int(throttled.headers["retry-after"]) <= 60
    assert len(calls) == 1
    assert len(client.get("/api/v1/agent-runs", headers=auth_headers).json()) == 1
