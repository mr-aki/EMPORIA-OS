import asyncio
from datetime import timedelta
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select

from emporia_api.config import settings
from emporia_api.database import SessionLocal
from emporia_api.job_queue import claim_next_job, retry_delay_seconds
from emporia_api.models import (
    AuditEvent,
    BackgroundJob,
    WorkspaceMembership,
    utcnow,
)
from emporia_api.worker import _renew_job_lease, run_one_job


def create_job(client, **overrides):
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": "queue-owner@example.com",
            "password": "QueueOwnerStrongPassword!2026",
            "display_name": "Queue Owner",
            "workspace_name": "Queue Workspace",
        },
    )
    assert registration.status_code == 201, registration.text
    with SessionLocal() as session:
        membership = session.scalar(select(WorkspaceMembership))
        values = {
            "workspace_id": membership.workspace_id,
            "actor": membership.user_id,
            "kind": "agent",
            "target_id": "commerce-strategist",
            "payload_json": (
                '{"provider":"openai","model":"gpt-5",'
                '"task":"Prepare a launch plan.","max_tokens":128}'
            ),
            "status": "queued",
            "attempts": 0,
            "max_attempts": 3,
            "available_at": utcnow(),
        }
        values.update(overrides)
        job = BackgroundJob(**values)
        session.add(job)
        session.commit()
        session.refresh(job)
        return job.id, membership.workspace_id, membership.user_id


def get_job(job_id):
    with SessionLocal() as session:
        return session.scalar(select(BackgroundJob).where(BackgroundJob.id == job_id))


def test_claim_is_atomic_and_only_one_worker_gets_a_queued_job(client):
    job_id, _, _ = create_job(client)
    with SessionLocal() as session:
        claimed = claim_next_job(session, "worker-a")
    with SessionLocal() as session:
        second_claim = claim_next_job(session, "worker-b")
    assert claimed == job_id
    assert second_claim is None
    job = get_job(job_id)
    assert job.status == "running"
    assert job.attempts == 1
    assert job.locked_by == "worker-a"


def test_claim_recovers_an_expired_worker_lease(client):
    expired = utcnow() - timedelta(seconds=settings.worker_lease_seconds + 10)
    job_id, _, _ = create_job(
        client, status="running", attempts=1, locked_at=expired, locked_by="dead-worker"
    )
    with SessionLocal() as session:
        claimed = claim_next_job(session, "replacement-worker")
    assert claimed == job_id
    job = get_job(job_id)
    assert job.status == "running"
    assert job.attempts == 2
    assert job.locked_by == "replacement-worker"


def test_expired_job_at_attempt_limit_is_failed_and_audited(client):
    expired = utcnow() - timedelta(seconds=settings.worker_lease_seconds + 10)
    job_id, _, _ = create_job(
        client, status="running", attempts=2, max_attempts=2,
        locked_at=expired, locked_by="dead-worker",
    )
    with SessionLocal() as session:
        assert claim_next_job(session, "replacement-worker") is None
    job = get_job(job_id)
    assert job.status == "failed"
    assert job.completed_at is not None
    with SessionLocal() as session:
        events = session.scalars(
            select(AuditEvent).where(
                AuditEvent.resource_type == "background_job",
                AuditEvent.resource_id == job_id,
            )
        ).all()
    assert any(event.detail == "worker_lease_expired" for event in events)


def test_future_job_is_not_claimed_before_available_at(client):
    job_id, _, _ = create_job(client, available_at=utcnow() + timedelta(minutes=1))
    with SessionLocal() as session:
        assert claim_next_job(session, "worker-a") is None
    assert get_job(job_id).status == "queued"


def test_retry_delay_is_bounded_exponential_backoff():
    assert retry_delay_seconds(1) == settings.worker_backoff_base_seconds
    assert retry_delay_seconds(2) == settings.worker_backoff_base_seconds * 2
    assert retry_delay_seconds(20) == settings.worker_backoff_max_seconds


def test_worker_revalidates_user_and_passes_workspace_principal(client, monkeypatch):
    job_id, workspace_id, user_id = create_job(client)
    captured = {}

    async def fake_execute(agent_id, payload, response, session, actor):
        captured.update(
            agent_id=agent_id,
            task=payload.task,
            user_id=actor.user_id,
            workspace_id=actor.workspace_id,
            role=actor.role,
        )
        return SimpleNamespace(id="agent-run-result-1")

    monkeypatch.setattr("emporia_api.main.execute_agent", fake_execute)
    assert asyncio.run(run_one_job("worker-agent")) is True
    job = get_job(job_id)
    assert captured == {
        "agent_id": "commerce-strategist",
        "task": "Prepare a launch plan.",
        "user_id": user_id,
        "workspace_id": workspace_id,
        "role": "owner",
    }
    assert job.status == "succeeded"
    assert job.result_id == "agent-run-result-1"
    assert job.locked_by is None


def test_worker_fails_job_when_membership_has_been_revoked(client):
    job_id, _, user_id = create_job(client)
    with SessionLocal() as session:
        membership = session.scalar(
            select(WorkspaceMembership).where(WorkspaceMembership.user_id == user_id)
        )
        session.delete(membership)
        session.commit()
    assert asyncio.run(run_one_job("worker-revoked")) is True
    job = get_job(job_id)
    assert job.status == "failed"
    assert "access was revoked" in job.last_error


def test_worker_retries_retryable_http_failures_then_succeeds(client, monkeypatch):
    job_id, _, _ = create_job(client)

    async def failing_execute(*args):
        raise HTTPException(status_code=502, detail="Temporary provider failure")

    monkeypatch.setattr("emporia_api.main.execute_agent", failing_execute)
    assert asyncio.run(run_one_job("worker-retry")) is True
    job = get_job(job_id)
    assert job.status == "retry_wait"
    assert job.attempts == 1
    assert job.last_error == "Temporary provider failure"

    with SessionLocal() as session:
        retry_job = session.get(BackgroundJob, job_id)
        retry_job.available_at = utcnow() - timedelta(seconds=1)
        session.commit()

    async def succeeding_execute(*args):
        return SimpleNamespace(id="recovered-agent-run")

    monkeypatch.setattr("emporia_api.main.execute_agent", succeeding_execute)
    assert asyncio.run(run_one_job("worker-retry")) is True
    completed = get_job(job_id)
    assert completed.status == "succeeded"
    assert completed.attempts == 2
    assert completed.result_id == "recovered-agent-run"


def test_worker_stops_retrying_at_max_attempts(client, monkeypatch):
    job_id, _, _ = create_job(client, max_attempts=1)

    async def failing_execute(*args):
        raise HTTPException(status_code=503, detail="Provider still unavailable")

    monkeypatch.setattr("emporia_api.main.execute_agent", failing_execute)
    assert asyncio.run(run_one_job("worker-terminal")) is True
    job = get_job(job_id)
    assert job.status == "failed"
    assert job.attempts == 1
    assert job.completed_at is not None


def test_cancelled_jobs_are_not_claimed_or_executed(client, monkeypatch):
    job_id, _, _ = create_job(client, status="cancelled", completed_at=utcnow())

    async def unexpected_execute(*args, **kwargs):
        raise AssertionError("Cancelled job must not execute")

    monkeypatch.setattr("emporia_api.main.execute_agent", unexpected_execute)
    assert asyncio.run(run_one_job("worker-cancelled")) is False
    assert get_job(job_id).status == "cancelled"



def test_worker_lease_heartbeat_renews_only_the_current_owner(client):
    job_id, _, _ = create_job(client)
    with SessionLocal() as session:
        assert claim_next_job(session, "worker-heartbeat") == job_id
    with SessionLocal() as session:
        job = session.get(BackgroundJob, job_id)
        job.locked_at = utcnow() - timedelta(seconds=90)
        session.commit()
    before = get_job(job_id).locked_at

    assert _renew_job_lease(job_id, "worker-heartbeat") is True
    after = get_job(job_id).locked_at
    assert after != before
    assert _renew_job_lease(job_id, "different-worker") is False


def test_worker_does_not_finalize_job_after_losing_lease(client, monkeypatch):
    job_id, _, _ = create_job(client)

    async def steal_lease(agent_id, payload, response, session, actor):
        with SessionLocal() as other_session:
            job = other_session.get(BackgroundJob, job_id)
            job.locked_by = "replacement-worker"
            job.locked_at = utcnow()
            other_session.commit()
        return SimpleNamespace(id="stale-agent-run")

    monkeypatch.setattr("emporia_api.main.execute_agent", steal_lease)
    assert asyncio.run(run_one_job("original-worker")) is False
    job = get_job(job_id)
    assert job.status == "running"
    assert job.locked_by == "replacement-worker"
    assert job.result_id is None
