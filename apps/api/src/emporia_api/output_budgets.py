from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from emporia_api.models import (
    AgentRun,
    SkillRun,
    WorkspaceOutputTokenBudget,
)


class OutputTokenBudgetExceeded(Exception):
    """Raised when a workspace cannot reserve the requested output tokens."""

    def __init__(
        self,
        *,
        limit: int,
        used: int,
        reserved: int,
        requested: int,
        retry_after: int,
    ) -> None:
        self.limit = limit
        self.used = used
        self.reserved = reserved
        self.requested = requested
        self.retry_after = retry_after
        super().__init__("Workspace monthly output-token budget exceeded")


def month_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    current = now or datetime.now(UTC)
    current = current.astimezone(UTC)
    start = datetime(current.year, current.month, 1, tzinfo=UTC)
    if current.month == 12:
        end = datetime(current.year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(current.year, current.month + 1, 1, tzinfo=UTC)
    return start, end


def _usage_for_model(
    session: Session,
    run_model: type[AgentRun] | type[SkillRun],
    workspace_id: str,
    period_start: datetime,
    period_end: datetime,
) -> tuple[int, int]:
    scope = (
        (run_model.workspace_id == workspace_id)
        & (run_model.created_at >= period_start)
        & (run_model.created_at < period_end)
    )
    settled_tokens = case(
        (run_model.budget_charged_tokens > 0, run_model.budget_charged_tokens),
        (run_model.status == "completed", run_model.completion_tokens),
        else_=0,
    )
    reserved_tokens = case(
        (run_model.status == "running", run_model.requested_max_tokens),
        else_=0,
    )
    result = session.execute(
        select(
            func.coalesce(func.sum(settled_tokens), 0),
            func.coalesce(func.sum(reserved_tokens), 0),
        ).where(scope)
    ).one()
    return int(result[0] or 0), int(result[1] or 0)


def get_workspace_output_budget_state(
    session: Session,
    workspace_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, int | bool | date | None]:
    period_start, period_end = month_window(now)
    policy = session.scalar(
        select(WorkspaceOutputTokenBudget).where(
            WorkspaceOutputTokenBudget.workspace_id == workspace_id
        )
    )
    agent_used, agent_reserved = _usage_for_model(
        session, AgentRun, workspace_id, period_start, period_end
    )
    skill_used, skill_reserved = _usage_for_model(
        session, SkillRun, workspace_id, period_start, period_end
    )
    used = agent_used + skill_used
    reserved = agent_reserved + skill_reserved
    limit = policy.monthly_output_token_limit if policy is not None else None
    available = max(0, limit - used - reserved) if limit is not None else None
    return {
        "configured": policy is not None,
        "monthly_output_token_limit": limit,
        "used_output_tokens": used,
        "reserved_output_tokens": reserved,
        "available_output_tokens": available,
        "period_start": period_start.date(),
        "period_end": period_end.date(),
    }


def enforce_workspace_output_budget(
    session: Session,
    workspace_id: str,
    requested_tokens: int,
    *,
    now: datetime | None = None,
) -> None:
    """Reserve requested output tokens under a workspace policy if one is configured.

    The policy-row UPDATE obtains a row lock on PostgreSQL and a write lock on
    SQLite. The caller must keep the transaction open until the run row with its
    requested_max_tokens reservation is committed or rolled back.
    """
    current = now or datetime.now(UTC)
    policy_table = WorkspaceOutputTokenBudget.__table__
    lock_result = session.execute(
        update(policy_table)
        .where(policy_table.c.workspace_id == workspace_id)
        .values(updated_at=current)
    )
    if lock_result.rowcount == 0:
        # No configured policy means the workspace is explicitly unlimited.
        return

    state = get_workspace_output_budget_state(session, workspace_id, now=current)
    limit = state["monthly_output_token_limit"]
    used = int(state["used_output_tokens"] or 0)
    reserved = int(state["reserved_output_tokens"] or 0)
    if limit is not None and used + reserved + requested_tokens > limit:
        _, next_period = month_window(current)
        retry_after = max(1, int((next_period - current.astimezone(UTC)).total_seconds()))
        raise OutputTokenBudgetExceeded(
            limit=limit,
            used=used,
            reserved=reserved,
            requested=requested_tokens,
            retry_after=retry_after,
        )


def set_workspace_output_budget(
    session: Session,
    workspace_id: str,
    monthly_output_token_limit: int,
    *,
    now: datetime | None = None,
) -> None:
    """Atomically create or update the workspace output-token policy."""
    current = now or datetime.now(UTC)
    values = {
        "id": str(uuid4()),
        "workspace_id": workspace_id,
        "monthly_output_token_limit": monthly_output_token_limit,
        "updated_at": current,
    }
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        insert_statement = sqlite_insert(WorkspaceOutputTokenBudget.__table__)
    elif dialect == "postgresql":
        insert_statement = postgresql_insert(WorkspaceOutputTokenBudget.__table__)
    else:
        raise RuntimeError(
            "Workspace output-token budgets require SQLite or PostgreSQL"
        )

    table = WorkspaceOutputTokenBudget.__table__
    session.execute(
        insert_statement.values(**values).on_conflict_do_update(
            index_elements=[table.c.workspace_id],
            set_={
                "monthly_output_token_limit": monthly_output_token_limit,
                "updated_at": current,
            },
        )
    )
