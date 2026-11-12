# ruff: noqa: I001
from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
import os
import socket
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from emporia_api.auth import Principal, require_write_access
from emporia_api.config import settings
from emporia_api.database import SessionLocal
from emporia_api.job_queue import claim_next_job, retry_delay_seconds
from emporia_api.models import (
    AuditEvent,
    BackgroundJob,
    User,
    WorkspaceMembership,
    utcnow,
)
from emporia_api.schemas import AgentRunCreate, SkillRunCreate


logger = logging.getLogger("emporia.worker")
RETRYABLE_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}


def configured_worker_id() -> str:
    return os.getenv("EMPORIA_WORKER_ID") or (
        f"{socket.gethostname()}-{uuid4().hex[:12]}"
    )


def claim_one_job(worker_id: str) -> str | None:
    with SessionLocal() as session:
        return claim_next_job(session, worker_id)


def _record_job_failure(
    session: Session,
    job: BackgroundJob,
    message: str,
    retryable: bool,
) -> None:
    now = utcnow()
    should_retry = retryable and job.attempts < job.max_attempts
    job.last_error = message[:1000]
    job.locked_at = None
    job.locked_by = None
    job.updated_at = now

    if should_retry:
        delay = retry_delay_seconds(job.attempts)
        job.status = "retry_wait"
        job.available_at = now + timedelta(seconds=delay)
        job.completed_at = None
        action = "job.retry_scheduled"
        detail = f"attempt:{job.attempts};retry_in:{delay}s"
    else:
        job.status = "failed"
        job.completed_at = now
        action = "job.failed"
        detail = f"attempt:{job.attempts};terminal_failure"

    session.add(AuditEvent(
        workspace_id=job.workspace_id,
        actor=job.actor,
        action=action,
        resource_type="background_job",
        resource_id=job.id,
        detail=detail,
    ))
    session.commit()


def _resolve_current_principal(session: Session, job: BackgroundJob) -> Principal:
    """Revalidate the original user's active account and current workspace role."""
    user = session.scalar(
        select(User).where(User.id == job.actor, User.is_active.is_(True))
    )
    if user is None:
        raise HTTPException(status_code=403, detail="Job owner is no longer active")
    membership = session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == job.actor,
            WorkspaceMembership.workspace_id == job.workspace_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Job owner workspace access was revoked")
    principal = Principal(
        user_id=user.id,
        workspace_id=job.workspace_id,
        role=membership.role,
        auth_type="worker",
    )
    require_write_access(principal)
    return principal


async def _renew_job_lease(job_id: str, worker_id: str) -> bool:
    """Extend a running job lease only while the caller still owns it."""
    now = utcnow()
    with SessionLocal() as session:
        result = session.execute(
            update(BackgroundJob)
            .where(
                BackgroundJob.id == job_id,
                BackgroundJob.status == "running",
                BackgroundJob.locked_by == worker_id,
            )
            .values(locked_at=now, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        session.commit()
        return result.rowcount == 1


async def _maintain_job_lease(job_id: str, worker_id: str) -> None:
    """Heartbeat the lease periodically while an upstream execution is in flight."""
    interval = max(1, settings.worker_lease_seconds // 3)
    while True:
        await asyncio.sleep(interval)
        try:
            renewed = await asyncio.to_thread(_renew_job_lease, job_id, worker_id)
        except Exception:
            logger.exception("Could not renew worker lease: id=%s", job_id)
            continue
        if not renewed:
            logger.warning("Worker lost ownership of job lease: id=%s", job_id)
            return


async def _cancel_lease_heartbeat(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def execute_claimed_job(job_id: str, worker_id: str) -> bool:
    """Execute a claimed job while renewing and verifying this worker's lease."""
    with SessionLocal() as session:
        job = session.scalar(
            select(BackgroundJob).where(
                BackgroundJob.id == job_id,
                BackgroundJob.status == "running",
                BackgroundJob.locked_by == worker_id,
            )
        )
        if job is None:
            return False

        heartbeat = asyncio.create_task(_maintain_job_lease(job_id, worker_id))
        try:
            from emporia_api.main import execute_agent, execute_skill

            principal = _resolve_current_principal(session, job)
            if job.kind == "agent":
                request = AgentRunCreate.model_validate(job.payload)
                result = await execute_agent(
                    job.target_id, request, Response(), session, principal
                )
            elif job.kind == "skill":
                request = SkillRunCreate.model_validate(job.payload)
                result = await execute_skill(
                    job.target_id, request, Response(), session, principal
                )
            else:
                await _cancel_lease_heartbeat(heartbeat)
                if not await asyncio.to_thread(_renew_job_lease, job_id, worker_id):
                    session.rollback()
                    return False
                session.refresh(job)
                _record_job_failure(
                    session, job, "Unsupported background job kind", retryable=False
                )
                return True

            await _cancel_lease_heartbeat(heartbeat)
            if not await asyncio.to_thread(_renew_job_lease, job_id, worker_id):
                session.rollback()
                logger.warning("Discarding stale worker completion: id=%s", job_id)
                return False
            session.refresh(job)
            job.status = "succeeded"
            job.result_id = result.id
            job.last_error = ""
            job.completed_at = utcnow()
            job.updated_at = job.completed_at
            job.locked_at = None
            job.locked_by = None
            session.add(AuditEvent(
                workspace_id=job.workspace_id,
                actor=job.actor,
                action="job.succeeded",
                resource_type="background_job",
                resource_id=job.id,
                detail=f"{job.kind}:{job.target_id};result:{result.id}",
            ))
            session.commit()
            logger.info("Background job completed: id=%s kind=%s", job.id, job.kind)
            return True
        except HTTPException as exc:
            await _cancel_lease_heartbeat(heartbeat)
            if not await asyncio.to_thread(_renew_job_lease, job_id, worker_id):
                session.rollback()
                logger.warning("Discarding stale worker failure: id=%s", job_id)
                return False
            session.refresh(job)
            message = exc.detail if isinstance(exc.detail, str) else "Execution request rejected"
            _record_job_failure(
                session, job, message, retryable=exc.status_code in RETRYABLE_HTTP_STATUSES
            )
            logger.warning(
                "Background job failed: id=%s status=%s attempt=%s",
                job.id,
                exc.status_code,
                job.attempts,
            )
            return True
        except Exception:
            await _cancel_lease_heartbeat(heartbeat)
            if not await asyncio.to_thread(_renew_job_lease, job_id, worker_id):
                session.rollback()
                logger.warning("Discarding stale worker error: id=%s", job_id)
                return False
            session.refresh(job)
            logger.exception("Unexpected background job failure: id=%s", job.id)
            _record_job_failure(
                session, job, "Unexpected worker execution failure", retryable=False
            )
            return True
        finally:
            await _cancel_lease_heartbeat(heartbeat)

async def run_one_job(worker_id: str | None = None) -> bool:
    worker = worker_id or configured_worker_id()
    job_id = claim_one_job(worker)
    if job_id is None:
        return False
    return await execute_claimed_job(job_id, worker)


async def run_worker(worker_id: str | None = None) -> None:
    worker = worker_id or configured_worker_id()
    logger.info(
        "Emporia worker started: id=%s poll_seconds=%s lease_seconds=%s",
        worker,
        settings.worker_poll_seconds,
        settings.worker_lease_seconds,
    )
    while True:
        try:
            processed = await run_one_job(worker)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Worker cycle failed: id=%s", worker)
            processed = False
        if not processed:
            await asyncio.sleep(settings.worker_poll_seconds)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("EMPORIA_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("Emporia worker stopped")


if __name__ == "__main__":
    main()
