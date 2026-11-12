from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from emporia_api.models import (
    AgentRun,
    SkillRun,
    Workspace,
    WorkspaceMonthlyCostBudget,
)
from emporia_api.output_budgets import month_window


class WorkspaceCostBudgetExceeded(Exception):
    """Raised when an execution would exceed the configured monthly USD budget."""

    def __init__(self, *, limit: Decimal, used: Decimal, reserved: Decimal, requested: Decimal, retry_after: int) -> None:
        self.limit = limit
        self.used = used
        self.reserved = reserved
        self.requested = requested
        self.retry_after = retry_after
        super().__init__("Workspace monthly estimated-cost budget exceeded")


class WorkspaceCostPricingRequired(Exception):
    """Raised when a configured cost budget cannot price the requested model."""


def _cost_usage_for_model(
    session: Session,
    run_model: type[AgentRun] | type[SkillRun],
    workspace_id: str,
    period_start: datetime,
    period_end: datetime,
) -> tuple[Decimal, Decimal, int]:
    scope = (
        (run_model.workspace_id == workspace_id)
        & (run_model.created_at >= period_start)
        & (run_model.created_at < period_end)
    )
    settled_cost = case(
        (run_model.estimated_cost_usd.is_not(None), run_model.estimated_cost_usd),
        (run_model.budget_charged_cost_usd.is_not(None), run_model.budget_charged_cost_usd),
        else_=0,
    )
    reserved_cost = case(
        (run_model.status == "running", func.coalesce(run_model.reserved_output_cost_usd, 0)),
        else_=0,
    )
    unpriced = case(
        (
            (run_model.status == "completed")
            & run_model.estimated_cost_usd.is_(None)
            & run_model.budget_charged_cost_usd.is_(None),
            1,
        ),
        else_=0,
    )
    row = session.execute(
        select(
            func.coalesce(func.sum(settled_cost), 0),
            func.coalesce(func.sum(reserved_cost), 0),
            func.coalesce(func.sum(unpriced), 0),
        ).where(*scope)
    ).one()
    return Decimal(str(row[0])), Decimal(str(row[1])), int(row[2])


def get_workspace_monthly_cost_budget_state(
    session: Session, workspace_id: str, *, now: datetime | None = None
) -> dict[str, object]:
    period_start, period_end = month_window(now)
    policy = session.scalar(
        select(WorkspaceMonthlyCostBudget).where(
            WorkspaceMonthlyCostBudget.workspace_id == workspace_id
        )
    )
    agent = _cost_usage_for_model(session, AgentRun, workspace_id, period_start, period_end)
    skill = _cost_usage_for_model(session, SkillRun, workspace_id, period_start, period_end)
    used = agent[0] + skill[0]
    reserved = agent[1] + skill[1]
    limit = policy.monthly_cost_budget_usd if policy is not None else None
    available = max(Decimal(0), limit - used - reserved) if limit is not None else None
    return {
        "configured": policy is not None,
        "monthly_cost_budget_usd": limit,
        "used_cost_usd": used,
        "reserved_output_cost_usd": reserved,
        "available_cost_usd": available,
        "unpriced_completed_runs": agent[2] + skill[2],
        "period_start": period_start.date(),
        "period_end": period_end.date(),
    }


def enforce_workspace_monthly_cost_budget(
    session: Session, run: AgentRun | SkillRun, requested_output_tokens: int, *, now: datetime | None = None
) -> Decimal | None:
    """Reserve the known maximum output cost before committing a run.

    The workspace-row update serializes budget changes and run reservations. Input
    token usage is unknowable before provider execution, so only output cost can be
    reserved; completed runs settle against both provider-reported token counters.
    The caller commits the run in the same transaction.
    """
    current = now or datetime.now(UTC)
    session.execute(
        update(Workspace).where(Workspace.id == run.workspace_id).values(name=Workspace.name)
    )
    table = WorkspaceMonthlyCostBudget.__table__
    locked = session.execute(
        update(table)
        .where(table.c.workspace_id == run.workspace_id)
        .values(updated_at=current)
    )
    if locked.rowcount == 0:
        return None

    output_rate = run.output_price_usd_per_million_tokens
    if output_rate is None:
        raise WorkspaceCostPricingRequired(
            "Configure an output price for this provider/model before executing under a USD budget"
        )
    requested = (Decimal(requested_output_tokens) * Decimal(output_rate)) / Decimal(1_000_000)
    state = get_workspace_monthly_cost_budget_state(session, run.workspace_id, now=current)
    limit = Decimal(state["monthly_cost_budget_usd"])
    used = Decimal(state["used_cost_usd"])
    reserved = Decimal(state["reserved_output_cost_usd"])
    if used + reserved + requested > limit:
        _, next_period = month_window(current)
        retry_after = max(1, int((next_period - current.astimezone(UTC)).total_seconds()))
        raise WorkspaceCostBudgetExceeded(
            limit=limit, used=used, reserved=reserved, requested=requested, retry_after=retry_after
        )
    run.reserved_output_cost_usd = requested
    return requested


def set_workspace_monthly_cost_budget(
    session: Session, workspace_id: str, monthly_cost_budget_usd: Decimal, *, now: datetime | None = None
) -> None:
    """Create/update a monthly USD budget, serialized with execution reservations."""
    current = now or datetime.now(UTC)
    session.execute(
        update(Workspace).where(Workspace.id == workspace_id).values(name=Workspace.name)
    )
    table = WorkspaceMonthlyCostBudget.__table__
    values = {
        "id": str(uuid4()),
        "workspace_id": workspace_id,
        "monthly_cost_budget_usd": monthly_cost_budget_usd,
        "updated_at": current,
    }
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        insert_statement = sqlite_insert(table)
    elif dialect == "postgresql":
        insert_statement = postgresql_insert(table)
    else:
        raise RuntimeError("Workspace monetary budgets require SQLite or PostgreSQL")
    session.execute(
        insert_statement.values(**values).on_conflict_do_update(
            index_elements=[table.c.workspace_id],
            set_={
                "monthly_cost_budget_usd": monthly_cost_budget_usd,
                "updated_at": current,
            },
        )
    )
