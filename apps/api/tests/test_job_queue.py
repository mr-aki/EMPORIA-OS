import asyncio
from datetime import timedelta
from types import SimpleNamespace

from fastapi import HTTPException
import jwt
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
from emporia_api.worker import run_one_job


def create_job(**overrides):
    values = {
        "workspace_id": settings.workspace_id,
        "actor": "local-development",
        "kind": "agent",
        "target_id": "commerce-strategist",
        "payload_json": (
            '{"provider":"openai","model":"gpt-5",'
            '"task":"Prepare a launch plan."}'
        ),
        "status": "queued",
        "attempts": 0,
        "max_attempts": 3,
        "available_at": utcnow(),
    }
    values.update(overrides)
    with SessionLocal() as session:
        job = BackgroundJob(**values)
        session.add(job)
        session.commit()
        session.refresh(job)
        return job.id


def get_job(job_id: str) -> BackgroundJob:
    with SessionLocal() as session:
        return session.scalar(
            select(BackgroundJob).where(BackgroundJob.id == job_id)
        )


def test_claim_is_atomic_and_only_one_worker_gets_a_queued_job(client):
    job_id = create_job()

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
    assert job.locked_at is not None


def test_claim_recovers_an_expired_worker_lease(client):
    expired = utcnow() - timedelta(seconds=settings.worker_lease_seconds + 10)
    job_id = create_job(
        status="running",
        attempts=1,
        locked_at=expired,
        locked_by="dead-worker",
    )

    with SessionLocal() as session:
        claimed = claim_next_job(session, "replacement-worker")

    assert claimed == job_id
    job = get_job(job_id)
    assert job.status == "running"
    assert job.attempts == 2
    assert job.locked_by == "replacement-worker"
    assert job.locked_at is not None


def test_expired_job_at_attempt_limit_is_failed_and_audited(client):
    expired = utcnow() - timedelta(seconds=settings.worker_lease_seconds + 10)
    job_id = create_job(
        status="running",
        attempts=2,
        max_attempts=2,
        locked_at=expired,
        locked_by="dead-worker",
    )

    with SessionLocal() as session:
        claimed = claim_next_job(session, "replacement-worker")

    assert claimed is None
    job = get_job(job_id)
    assert job.status == "failed"
    assert job.completed_at is not None
    assert "lease expired" in job.last_error.lower()

    with SessionLocal() as session:
        events = session.scalars(
            select(AuditEvent).where(
                AuditEvent.resource_type == "background_job",
                AuditEvent.resource_id == job_id,
            )
        ).all()
    assert any(event.detail == "worker_lease_expired" for event in events)


def test_future_job_is_not_claimed_before_available_at(client):
    job_id = create_job(available_at=utcnow() + timedelta(minutes=1))
    with SessionLocal() as session:
        claimed = claim_next_job(session, "worker-a")
    assert claimed is None
    assert get_job(job_id).status == "queued"


def test_retry_delay_is_bounded_exponential_backoff():
    assert retry_delay_seconds(1) == settings.worker_backoff_base_seconds
    assert retry_delay_seconds(2) == settings.worker_backoff_base_seconds * 2
    assert retry_delay_seconds(20) == settings.worker_backoff_max_seconds


def test_worker_dispatches_agent_and_persists_success(client, monkeypatch):
    job_id = create_job()
    captured = {}

    async def fake_execute(agent_id, payload, session, actor):
        captured["agent_id"] = agent_id
        captured["task"] = payload.task
        captured["user_id"] = actor.user_id
        captured["role"] = actor.role
        return SimpleNamespace(id="agent-run-result-1")

    monkeypatch.setattr("emporia_api.worker.execute_agent", fake_execute)

    assert asyncio.run(run_one_job("worker-agent")) is True
    job = get_job(job_id)
    assert captured == {
        "agent_id": "commerce-strategist",
        "task": "Prepare a launch plan.",
        "user_id": "local-development",
        "role": "owner",
    }
    assert job.status == "succeeded"
    assert job.attempts == 1
    assert job.result_id == "agent-run-result-1"
    assert job.completed_at is not None
    assert job.locked_by is None


def test_worker_dispatches_skill_jobs_through_skill_handler(client, monkeypatch):
    job_id = create_job(
        kind="skill",
        target_id="market-opportunity-scan",
        payload_json=(
            '{"provider":"openai","model":"gpt-5","inputs":'
            '{"market":"Compact home storage","geography":"Pakistan",'
            '"target_customer":"Small-apartment renters"}}'
        ),
    )
    captured = {}

    async def fake_execute(skill_id, payload, session, actor):
        captured["skill_id"] = skill_id
        captured["inputs"] = payload.inputs
        return SimpleNamespace(id="skill-run-result-1")

    monkeypatch.setattr("emporia_api.worker.execute_skill", fake_execute)

    assert asyncio.run(run_one_job("worker-skill")) is True
    job = get_job(job_id)
    assert captured == {
        "skill_id": "market-opportunity-scan",
        "inputs": {
            "market": "Compact home storage",
            "geography": "Pakistan",
            "target_customer": "Small-apartment renters",
        },
    }
    assert job.status == "succeeded"
    assert job.result_id == "skill-run-result-1"


def test_worker_revalidates_user_membership_before_execution(
    client, auth_headers, monkeypatch
):
    token = auth_headers["Authorization"].split(" ", 1)[1]
    claims = jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        issuer=settings.jwt_issuer,
    )
    job_id = create_job(
        workspace_id=claims["workspace_id"],
        actor=claims["sub"],
    )

    with SessionLocal() as session:
        membership = session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.user_id == claims["sub"],
                WorkspaceMembership.workspace_id == claims["workspace_id"],
            )
        )
        session.delete(membership)
        session.commit()

    async def unexpected_execute(*args, **kwargs):
        raise AssertionError("A revoked workspace member must not execute")

    monkeypatch.setattr("emporia_api.worker.execute_agent", unexpected_execute)
    assert asyncio.run(run_one_job("worker-revoked")) is True

    job = get_job(job_id)
    assert job.status == "failed"
    assert "no longer belongs" in job.last_error


def test_worker_retries_retryable_http_failures_then_succeeds(client, monkeypatch):
    job_id = create_job()
    attempts = {"count": 0}

    async def failing_execute(agent_id, payload, session, actor):
        attempts["count"] += 1
        raise HTTPException(status_code=502, detail="Temporary provider failure")

    monkeypatch.setattr("emporia_api.worker.execute_agent", failing_execute)
    assert asyncio.run(run_one_job("worker-retry")) is True

    job = get_job(job_id)
    assert job.status == "retry_wait"
    assert job.attempts == 1
    assert job.last_error == "Temporary provider failure"
    assert job.available_at > utcnow()

    with SessionLocal() as session:
        retry_job = session.get(BackgroundJob, job_id)
        retry_job.available_at = utcnow() - timedelta(seconds=1)
        session.commit()

    async def succeeding_execute(agent_id, payload, session, actor):
        attempts["count"] += 1
        return SimpleNamespace(id="recovered-agent-run")

    monkeypatch.setattr("emporia_api.worker.execute_agent", succeeding_execute)
    assert asyncio.run(run_one_job("worker-retry")) is True

    completed = get_job(job_id)
    assert attempts["count"] == 2
    assert completed.status == "succeeded"
    assert completed.attempts == 2
    assert completed.result_id == "recovered-agent-run"


def test_worker_stops_retrying_at_max_attempts(client, monkeypatch):
    job_id = create_job(max_attempts=1)

    async def failing_execute(agent_id, payload, session, actor):
        raise HTTPException(status_code=503, detail="Provider still unavailable")

    monkeypatch.setattr("emporia_api.worker.execute_agent", failing_execute)
    assert asyncio.run(run_one_job("worker-terminal")) is True

    job = get_job(job_id)
    assert job.status == "failed"
    assert job.attempts == 1
    assert job.completed_at is not None
    assert job.last_error == "Provider still unavailable"


def test_worker_does_not_claim_or_execute_cancelled_jobs(client, monkeypatch):
    job_id = create_job(status="cancelled", completed_at=utcnow())

    async def unexpected_execute(*args, **kwargs):
        raise AssertionError("Cancelled job must not execute")

    monkeypatch.setattr("emporia_api.worker.execute_agent", unexpected_execute)
    assert asyncio.run(run_one_job("worker-cancelled")) is False
    assert get_job(job_id).status == "cancelled"
