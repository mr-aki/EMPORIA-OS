from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from emporia_api.concurrency import (
    ConcurrentExecutionLimitExceeded,
    reserve_execution_slot,
)
from emporia_api.database import SessionLocal
from emporia_api.models import AgentRun, AuditEvent, SkillRun, Workspace


def _workspace_id() -> str:
    with SessionLocal() as session:
        workspace_id = session.scalar(select(Workspace.id).limit(1))
        assert workspace_id is not None
        return workspace_id


def test_active_agent_run_consumes_workspace_concurrency_slot(client, auth_headers):
    workspace_id = _workspace_id()
    now = datetime.now(UTC)

    with SessionLocal() as session:
        session.add(
            AgentRun(
                workspace_id=workspace_id,
                agent_id="commerce-strategist",
                agent_version="1.0.0",
                provider="openai",
                model="gpt-5",
                status="running",
                task="Existing active run",
                requested_max_tokens=128,
                execution_lease_expires_at=now + timedelta(minutes=5),
            )
        )
        session.commit()

        with pytest.raises(ConcurrentExecutionLimitExceeded) as error:
            reserve_execution_slot(
                session,
                AgentRun,
                workspace_id,
                limit=1,
                lease_seconds=300,
                now=now,
            )
        assert error.value.active == 1
        assert error.value.limit == 1
        assert error.value.retry_after == 300
        session.rollback()


def test_expired_execution_lease_is_finalized_and_capacity_reused(client, auth_headers):
    workspace_id = _workspace_id()
    now = datetime.now(UTC)
    expired_id = "expired-agent-run"

    with SessionLocal() as session:
        session.add(
            AgentRun(
                id=expired_id,
                workspace_id=workspace_id,
                agent_id="commerce-strategist",
                agent_version="1.0.0",
                provider="openai",
                model="gpt-5",
                status="running",
                task="Stale run after worker crash",
                requested_max_tokens=144,
                execution_lease_expires_at=now - timedelta(seconds=1),
            )
        )
        session.commit()

        new_expiry = reserve_execution_slot(
            session,
            AgentRun,
            workspace_id,
            limit=1,
            lease_seconds=300,
            now=now,
        )
        assert new_expiry == now + timedelta(seconds=300)
        session.commit()

        stale = session.get(AgentRun, expired_id)
        assert stale is not None
        assert stale.status == "failed"
        assert stale.error_message == "Execution lease expired before the run completed"
        assert stale.budget_charged_tokens == 144
        assert stale.completed_at is not None
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.workspace_id == workspace_id,
                AuditEvent.resource_id == expired_id,
                AuditEvent.action == "agent.run.failed",
            )
        )
        assert event is not None
        assert event.detail == "execution_lease_expired"


def test_agent_and_skill_concurrency_limits_are_independent(client, auth_headers):
    workspace_id = _workspace_id()
    now = datetime.now(UTC)

    with SessionLocal() as session:
        session.add(
            AgentRun(
                workspace_id=workspace_id,
                agent_id="commerce-strategist",
                agent_version="1.0.0",
                provider="openai",
                model="gpt-5",
                status="running",
                task="Active agent",
                requested_max_tokens=128,
                execution_lease_expires_at=now + timedelta(minutes=5),
            )
        )
        session.commit()

        # The agent slot is occupied, but skill executions have their own ceiling.
        skill_expiry = reserve_execution_slot(
            session,
            SkillRun,
            workspace_id,
            limit=1,
            lease_seconds=300,
            now=now,
        )
        assert skill_expiry > now
        session.rollback()


def test_agent_endpoint_returns_429_when_workspace_concurrency_is_full(
    client, auth_headers, monkeypatch
):
    workspace_id = _workspace_id()
    now = datetime.now(UTC)
    monkeypatch.setattr("emporia_api.main.settings.agent_max_concurrent_runs", 1)
    calls = []

    class FakeGateway:
        def configured(self, provider):
            return True

        async def complete(self, request):
            calls.append(request)
            raise AssertionError("provider must not be called when concurrency is full")

    monkeypatch.setattr("emporia_api.main.provider_gateway", FakeGateway())
    with SessionLocal() as session:
        session.add(
            AgentRun(
                workspace_id=workspace_id,
                agent_id="commerce-strategist",
                agent_version="1.0.0",
                provider="openai",
                model="gpt-5",
                status="running",
                task="Already running",
                requested_max_tokens=128,
                execution_lease_expires_at=now + timedelta(minutes=5),
            )
        )
        session.commit()

    response = client.post(
        "/api/v1/agents/commerce-strategist/runs",
        headers={**auth_headers, "Idempotency-Key": "concurrency-limit-new-run"},
        json={
            "provider": "openai",
            "model": "gpt-5",
            "task": "A second run must be rejected.",
            "max_tokens": 128,
        },
    )
    assert response.status_code == 429
    assert response.json()["detail"]["message"] == (
        "Workspace concurrent agent execution limit reached"
    )
    assert response.json()["detail"]["active"] == 1
    assert response.json()["detail"]["limit"] == 1
    assert response.headers["retry-after"] == "300"
    assert calls == []
