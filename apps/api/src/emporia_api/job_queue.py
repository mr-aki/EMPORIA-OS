from datetime import timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from emporia_api.config import settings
from emporia_api.models import AuditEvent, BackgroundJob, utcnow


def claim_next_job(session: Session, worker_id: str) -> str | None:
    """Claim one available job, with PostgreSQL row locking and a SQLite CAS guard."""
    now = utcnow()
    expired_before = now - timedelta(seconds=settings.worker_lease_seconds)
    eligible = or_(
        and_(
            BackgroundJob.status.in_(("queued", "retry_wait")),
            BackgroundJob.available_at <= now,
        ),
        and_(
            BackgroundJob.status == "running",
            BackgroundJob.locked_at.is_not(None),
            BackgroundJob.locked_at <= expired_before,
        ),
    )

    exhausted_statement = (
        update(BackgroundJob)
        .where(
            BackgroundJob.status == "running",
            BackgroundJob.locked_at.is_not(None),
            BackgroundJob.locked_at <= expired_before,
            BackgroundJob.attempts >= BackgroundJob.max_attempts,
        )
        .values(
            status="failed",
            last_error="Worker lease expired after the maximum number of attempts",
            completed_at=now,
            locked_at=None,
            locked_by=None,
            updated_at=now,
        )
    )
    exhausted_ids = list(session.scalars(
        select(BackgroundJob.id).where(
            BackgroundJob.status == "running",
            BackgroundJob.locked_at.is_not(None),
            BackgroundJob.locked_at <= expired_before,
            BackgroundJob.attempts >= BackgroundJob.max_attempts,
        ).with_for_update(skip_locked=True).limit(100)
    ))
    if exhausted_ids:
        updated = session.execute(
            exhausted_statement.where(BackgroundJob.id.in_(exhausted_ids))
        )
        if updated.rowcount:
            rows = session.scalars(
                select(BackgroundJob).where(BackgroundJob.id.in_(exhausted_ids))
            ).all()
            for job in rows:
                session.add(AuditEvent(
                    workspace_id=job.workspace_id,
                    actor="worker",
                    action="job.failed",
                    resource_type="background_job",
                    resource_id=job.id,
                    detail="worker_lease_expired",
                ))
        session.flush()

    candidate = session.scalar(
        select(BackgroundJob)
        .where(
            eligible,
            BackgroundJob.attempts < BackgroundJob.max_attempts,
        )
        .order_by(BackgroundJob.available_at.asc(), BackgroundJob.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if candidate is None:
        session.commit()
        return None

    claimed = session.execute(
        update(BackgroundJob)
        .where(
            BackgroundJob.id == candidate.id,
            eligible,
            BackgroundJob.attempts < BackgroundJob.max_attempts,
        )
        .values(
            status="running",
            locked_at=now,
            locked_by=worker_id,
            attempts=BackgroundJob.attempts + 1,
            updated_at=now,
            last_error="",
        )
    )
    if claimed.rowcount != 1:
        session.rollback()
        return None

    job_id = candidate.id
    session.commit()
    return job_id


def retry_delay_seconds(attempts: int) -> int:
    """Return a bounded exponential retry delay."""
    exponent = max(0, attempts - 1)
    delay = settings.worker_backoff_base_seconds * (2**exponent)
    return min(delay, settings.worker_backoff_max_seconds)
