from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from emporia_api.models import AgentRun, AuditEvent, SkillRun, Workspace


class ConcurrentExecutionLimitExceeded(Exception):
    """Raised when a workspace has reached its active execution ceiling."""

    def __init__(self, active: int, limit: int, retry_after: int) -> None:
        self.active = active
        self.limit = limit
        self.retry_after = retry_after
        super().__init__("Workspace concurrent execution limit reached")


def recover_expired_execution_leases(
    session: Session,
    run_model: type[AgentRun] | type[SkillRun],
    workspace_id: str,
    *,
    now: datetime | None = None,
) -> int:
    """Finalize abandoned runs once their persisted execution lease has expired."""
    current = (now or datetime.now(UTC)).astimezone(UTC)
    expired_result = session.execute(
        update(run_model)
        .where(
            run_model.workspace_id == workspace_id,
            run_model.status == "running",
            run_model.execution_lease_expires_at.is_not(None),
            run_model.execution_lease_expires_at <= current,
        )
        .values(
            status="failed",
            error_message="Execution lease expired before the run completed",
            completed_at=current,
            budget_charged_tokens=run_model.requested_max_tokens,
        )
        .returning(run_model.id)
    )
    expired_ids = expired_result.scalars().all()
    if not expired_ids:
        return 0

    execution_type = "agent" if run_model is AgentRun else "skill"
    resource_type = "agent_run" if run_model is AgentRun else "skill_run"
    session.add_all(
        AuditEvent(
            workspace_id=workspace_id,
            actor="system",
            action=f"{execution_type}.run.failed",
            resource_type=resource_type,
            resource_id=run_id,
            detail="execution_lease_expired",
            created_at=current,
        )
        for run_id in expired_ids
    )
    # Make recovery durable before an idempotent retry can read the old run.
    session.commit()
    return len(expired_ids)


def reserve_execution_slot(
    session: Session,
    run_model: type[AgentRun] | type[SkillRun],
    workspace_id: str,
    limit: int,
    lease_seconds: int,
    *,
    now: datetime | None = None,
) -> datetime:
    """Reserve one active execution slot under a workspace-scoped DB lock.

    Updating the parent workspace row serializes reservations across API workers
    sharing PostgreSQL or SQLite. Expired running rows are finalized as failed
    and charged their full requested output reservation before capacity is
    recalculated. The caller must commit the new run in this same transaction.
    """
    current = (now or datetime.now(UTC)).astimezone(UTC)
    recover_expired_execution_leases(
        session, run_model, workspace_id, now=current
    )
    session.execute(
        update(Workspace)
        .where(Workspace.id == workspace_id)
        .values(name=Workspace.name)
    )

    active = session.scalar(
        select(func.count(run_model.id)).where(
            run_model.workspace_id == workspace_id,
            run_model.status == "running",
            run_model.execution_lease_expires_at > current,
        )
    ) or 0
    if active >= limit:
        raise ConcurrentExecutionLimitExceeded(
            active=int(active),
            limit=limit,
            retry_after=max(1, lease_seconds),
        )

    return current + timedelta(seconds=lease_seconds)
