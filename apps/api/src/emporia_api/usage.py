from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from emporia_api.auth import Principal, get_current_principal
from emporia_api.database import get_session
from emporia_api.models import AgentRun, AuditEvent, SkillRun, WorkspaceModelPrice, utcnow
from emporia_api.output_budgets import (
    get_workspace_output_budget_state,
    set_workspace_output_budget,
)
from emporia_api.schemas import ModelName

router = APIRouter(prefix="/api/v1/usage", tags=["usage"])
SessionDep = Annotated[Session, Depends(get_session)]
AuthDep = Annotated[Principal, Depends(get_current_principal)]


class UsageTotals(BaseModel):
    runs: int = 0
    completed_runs: int = 0
    failed_runs: int = 0
    running_runs: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ProviderModelUsage(UsageTotals):
    execution_type: str
    provider: str
    model: str


class DailyUsage(UsageTotals):
    date: date


class UsageSummary(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    totals: UsageTotals
    by_execution_type: dict[str, UsageTotals]
    by_provider_model: list[ProviderModelUsage]
    by_day: list[DailyUsage]


def _date_scope(
    run_model: Any,
    workspace_id: str,
    start_date: date | None,
    end_date: date | None,
):
    scope = [run_model.workspace_id == workspace_id]
    if start_date is not None:
        scope.append(
            run_model.created_at
            >= datetime.combine(start_date, time.min, tzinfo=UTC)
        )
    if end_date is not None:
        scope.append(
            run_model.created_at
            < datetime.combine(
                end_date + timedelta(days=1), time.min, tzinfo=UTC
            )
        )
    return scope


def _aggregate(
    session: Session,
    run_model: Any,
    workspace_id: str,
    execution_type: str,
    start_date: date | None,
    end_date: date | None,
) -> tuple[UsageTotals, list[ProviderModelUsage], list[DailyUsage]]:
    scope = _date_scope(run_model, workspace_id, start_date, end_date)
    total_row = session.execute(
        select(
            func.count(run_model.id),
            func.coalesce(func.sum(run_model.prompt_tokens), 0),
            func.coalesce(func.sum(run_model.completion_tokens), 0),
            func.coalesce(func.sum(run_model.total_tokens), 0),
        ).where(*scope)
    ).one()
    status_rows = session.execute(
        select(run_model.status, func.count(run_model.id))
        .where(*scope)
        .group_by(run_model.status)
    ).all()
    statuses = {status: count for status, count in status_rows}
    totals = UsageTotals(
        runs=total_row[0],
        completed_runs=statuses.get("completed", 0),
        failed_runs=statuses.get("failed", 0),
        running_runs=statuses.get("running", 0),
        prompt_tokens=total_row[1],
        completion_tokens=total_row[2],
        total_tokens=total_row[3],
    )

    grouped_rows = session.execute(
        select(
            run_model.provider,
            run_model.model,
            run_model.status,
            func.count(run_model.id),
            func.coalesce(func.sum(run_model.prompt_tokens), 0),
            func.coalesce(func.sum(run_model.completion_tokens), 0),
            func.coalesce(func.sum(run_model.total_tokens), 0),
        )
        .where(*scope)
        .group_by(run_model.provider, run_model.model, run_model.status)
        .order_by(run_model.provider, run_model.model, run_model.status)
    ).all()
    grouped: dict[tuple[str, str], dict[str, int]] = {}
    for provider, model, status, count, prompt, completion, total in grouped_rows:
        row = grouped.setdefault(
            (provider, model),
            {
                "runs": 0,
                "completed_runs": 0,
                "failed_runs": 0,
                "running_runs": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        )
        row["runs"] += count
        status_key = f"{status}_runs"
        if status_key in row:
            row[status_key] += count
        row["prompt_tokens"] += prompt
        row["completion_tokens"] += completion
        row["total_tokens"] += total
    breakdown = [
        ProviderModelUsage(
            execution_type=execution_type,
            provider=provider,
            model=model,
            **values,
        )
        for (provider, model), values in grouped.items()
    ]

    daily_rows = session.execute(
        select(
            func.date(run_model.created_at),
            run_model.status,
            func.count(run_model.id),
            func.coalesce(func.sum(run_model.prompt_tokens), 0),
            func.coalesce(func.sum(run_model.completion_tokens), 0),
            func.coalesce(func.sum(run_model.total_tokens), 0),
        )
        .where(*scope)
        .group_by(func.date(run_model.created_at), run_model.status)
    ).all()
    daily_map: dict[date, dict[str, int]] = {}
    for day_value, status, count, prompt, completion, total in daily_rows:
        day = date.fromisoformat(str(day_value)[:10])
        values = daily_map.setdefault(
            day,
            {
                "runs": 0,
                "completed_runs": 0,
                "failed_runs": 0,
                "running_runs": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        )
        values["runs"] += count
        status_key = f"{status}_runs"
        if status_key in values:
            values[status_key] += count
        values["prompt_tokens"] += prompt
        values["completion_tokens"] += completion
        values["total_tokens"] += total
    daily = [
        DailyUsage(date=day, **values)
        for day, values in sorted(daily_map.items())
    ]
    return totals, breakdown, daily


@router.get("/summary", response_model=UsageSummary)
def get_usage_summary(
    session: SessionDep,
    actor: AuthDep,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
) -> UsageSummary:
    """Return workspace-scoped token usage, optionally filtered by inclusive UTC dates."""
    if start_date is not None and end_date is not None and end_date < start_date:
        raise HTTPException(
            status_code=422, detail="end_date must be on or after start_date"
        )

    agent_totals, agent_breakdown, agent_daily = _aggregate(
        session, AgentRun, actor.workspace_id, "agent", start_date, end_date
    )
    skill_totals, skill_breakdown, skill_daily = _aggregate(
        session, SkillRun, actor.workspace_id, "skill", start_date, end_date
    )
    totals = UsageTotals(
        runs=agent_totals.runs + skill_totals.runs,
        completed_runs=agent_totals.completed_runs + skill_totals.completed_runs,
        failed_runs=agent_totals.failed_runs + skill_totals.failed_runs,
        running_runs=agent_totals.running_runs + skill_totals.running_runs,
        prompt_tokens=agent_totals.prompt_tokens + skill_totals.prompt_tokens,
        completion_tokens=(
            agent_totals.completion_tokens + skill_totals.completion_tokens
        ),
        total_tokens=agent_totals.total_tokens + skill_totals.total_tokens,
    )
    daily_map: dict[date, UsageTotals] = {}
    for item in agent_daily + skill_daily:
        aggregate = daily_map.setdefault(item.date, UsageTotals())
        aggregate.runs += item.runs
        aggregate.completed_runs += item.completed_runs
        aggregate.failed_runs += item.failed_runs
        aggregate.running_runs += item.running_runs
        aggregate.prompt_tokens += item.prompt_tokens
        aggregate.completion_tokens += item.completion_tokens
        aggregate.total_tokens += item.total_tokens
    by_day = [
        DailyUsage(date=day, **values.model_dump())
        for day, values in sorted(daily_map.items())
    ]
    return UsageSummary(
        start_date=start_date,
        end_date=end_date,
        totals=totals,
        by_execution_type={"agent": agent_totals, "skill": skill_totals},
        by_provider_model=agent_breakdown + skill_breakdown,
        by_day=by_day,
    )


class OutputBudgetUpdate(BaseModel):
    monthly_output_tokens: int = Field(ge=1, le=2_000_000_000)


class OutputBudgetRead(BaseModel):
    configured: bool
    monthly_output_token_limit: int | None
    used_output_tokens: int
    reserved_output_tokens: int
    available_output_tokens: int | None
    period_start: date
    period_end: date


@router.get("/budget", response_model=OutputBudgetRead)
def get_output_budget(session: SessionDep, actor: AuthDep) -> OutputBudgetRead:
    """Read the current month's settled and reserved output-token budget for this workspace."""
    return OutputBudgetRead(**get_workspace_output_budget_state(session, actor.workspace_id))


@router.put("/budget", response_model=OutputBudgetRead)
def update_output_budget(
    payload: OutputBudgetUpdate,
    session: SessionDep,
    actor: AuthDep,
) -> OutputBudgetRead:
    """Set the monthly output-token ceiling; only workspace owners and admins may change it."""
    if actor.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail="Only workspace owners and admins can change the output-token budget",
        )

    set_workspace_output_budget(
        session,
        actor.workspace_id,
        payload.monthly_output_tokens,
    )
    state = get_workspace_output_budget_state(session, actor.workspace_id)
    committed_and_reserved = (
        int(state["used_output_tokens"] or 0)
        + int(state["reserved_output_tokens"] or 0)
    )
    if committed_and_reserved > payload.monthly_output_tokens:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "message": "New output-token budget is below current month usage and reservations",
                "used": state["used_output_tokens"],
                "reserved": state["reserved_output_tokens"],
                "requested_limit": payload.monthly_output_tokens,
            },
        )

    session.add(AuditEvent(
        workspace_id=actor.workspace_id,
        actor=actor.user_id,
        action="usage.output_budget.updated",
        resource_type="workspace_output_token_budget",
        resource_id=actor.workspace_id,
        detail=f"monthly_output_tokens:{payload.monthly_output_tokens}",
        created_at=utcnow(),
    ))
    session.commit()
    return OutputBudgetRead(**state)


ProviderName = Literal["openai", "anthropic", "gemini", "openai-compatible"]


class ModelPriceUpdate(BaseModel):
    """Operator-supplied USD rates; prices are never inferred from model names."""

    input_usd_per_million_tokens: Decimal = Field(
        ge=Decimal(0), max_digits=20, decimal_places=10
    )
    output_usd_per_million_tokens: Decimal = Field(
        ge=Decimal("0"), max_digits=20, decimal_places=10
    )


class ModelPriceRead(BaseModel):
    provider: str
    model: str
    input_usd_per_million_tokens: Decimal
    output_usd_per_million_tokens: Decimal
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CostTotals(BaseModel):
    runs: int = 0
    priced_runs: int = 0
    unpriced_runs: int = 0
    estimated_cost_usd: Decimal = Decimal("0")


class ProviderModelCost(CostTotals):
    execution_type: str
    provider: str
    model: str


class DailyCost(CostTotals):
    date: date


class CostSummary(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    currency: Literal["USD"] = "USD"
    totals: CostTotals
    by_execution_type: dict[str, CostTotals]
    by_provider_model: list[ProviderModelCost]
    by_day: list[DailyCost]


def _cost_aggregate(
    session: Session,
    run_model: Any,
    workspace_id: str,
    execution_type: str,
    start_date: date | None,
    end_date: date | None,
) -> tuple[CostTotals, list[ProviderModelCost], list[DailyCost]]:
    scope = _date_scope(run_model, workspace_id, start_date, end_date)
    row = session.execute(
        select(
            func.count(run_model.id),
            func.count(run_model.estimated_cost_usd),
            func.coalesce(func.sum(run_model.estimated_cost_usd), 0),
        ).where(*scope)
    ).one()
    totals = CostTotals(
        runs=row[0],
        priced_runs=row[1],
        unpriced_runs=row[0] - row[1],
        estimated_cost_usd=Decimal(str(row[2])),
    )

    grouped_rows = session.execute(
        select(
            run_model.provider,
            run_model.model,
            func.count(run_model.id),
            func.count(run_model.estimated_cost_usd),
            func.coalesce(func.sum(run_model.estimated_cost_usd), 0),
        )
        .where(*scope)
        .group_by(run_model.provider, run_model.model)
        .order_by(run_model.provider, run_model.model)
    ).all()
    breakdown = [
        ProviderModelCost(
            execution_type=execution_type,
            provider=provider,
            model=model,
            runs=count,
            priced_runs=priced,
            unpriced_runs=count - priced,
            estimated_cost_usd=Decimal(str(cost)),
        )
        for provider, model, count, priced, cost in grouped_rows
    ]

    daily_rows = session.execute(
        select(
            func.date(run_model.created_at),
            func.count(run_model.id),
            func.count(run_model.estimated_cost_usd),
            func.coalesce(func.sum(run_model.estimated_cost_usd), 0),
        )
        .where(*scope)
        .group_by(func.date(run_model.created_at))
    ).all()
    daily = [
        DailyCost(
            date=date.fromisoformat(str(day_value)[:10]),
            runs=count,
            priced_runs=priced,
            unpriced_runs=count - priced,
            estimated_cost_usd=Decimal(str(cost)),
        )
        for day_value, count, priced, cost in daily_rows
    ]
    return totals, breakdown, daily


def _add_cost_totals(left: CostTotals, right: CostTotals) -> CostTotals:
    return CostTotals(
        runs=left.runs + right.runs,
        priced_runs=left.priced_runs + right.priced_runs,
        unpriced_runs=left.unpriced_runs + right.unpriced_runs,
        estimated_cost_usd=left.estimated_cost_usd + right.estimated_cost_usd,
    )


@router.get("/pricing", response_model=list[ModelPriceRead])
def list_model_prices(session: SessionDep, actor: AuthDep) -> list[ModelPriceRead]:
    """List only the authenticated workspace's operator-configured model rates."""
    return list(
        session.scalars(
            select(WorkspaceModelPrice)
            .where(WorkspaceModelPrice.workspace_id == actor.workspace_id)
            .order_by(WorkspaceModelPrice.provider, WorkspaceModelPrice.model)
        )
    )


@router.put("/pricing/{provider}/{model}", response_model=ModelPriceRead)
def set_model_price(
    provider: ProviderName,
    model: ModelName,
    payload: ModelPriceUpdate,
    session: SessionDep,
    actor: AuthDep,
) -> WorkspaceModelPrice:
    """Create or update the USD rate used for future runs; prior run snapshots do not change."""
    if actor.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail="Only workspace owners and admins can configure model pricing",
        )

    price = session.scalar(
        select(WorkspaceModelPrice).where(
            WorkspaceModelPrice.workspace_id == actor.workspace_id,
            WorkspaceModelPrice.provider == provider,
            WorkspaceModelPrice.model == model,
        )
    )
    if price is None:
        price = WorkspaceModelPrice(
            workspace_id=actor.workspace_id,
            provider=provider,
            model=model,
            input_usd_per_million_tokens=payload.input_usd_per_million_tokens,
            output_usd_per_million_tokens=payload.output_usd_per_million_tokens,
            updated_by=actor.user_id,
        )
        session.add(price)
    else:
        price.input_usd_per_million_tokens = payload.input_usd_per_million_tokens
        price.output_usd_per_million_tokens = payload.output_usd_per_million_tokens
        price.updated_by = actor.user_id
        price.updated_at = utcnow()

    session.flush()
    session.add(AuditEvent(
        workspace_id=actor.workspace_id,
        actor=actor.user_id,
        action="usage.model_price.updated",
        resource_type="workspace_model_price",
        resource_id=price.id,
        detail=f"{provider}:{model};currency:USD",
        created_at=utcnow(),
    ))
    session.commit()
    session.refresh(price)
    return price


@router.delete(
    "/pricing/{provider}/{model}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_model_price(
    provider: ProviderName,
    model: ModelName,
    session: SessionDep,
    actor: AuthDep,
) -> Response:
    """Remove a future pricing rule without modifying cost snapshots on prior runs."""
    if actor.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail="Only workspace owners and admins can remove model pricing",
        )
    price = session.scalar(
        select(WorkspaceModelPrice).where(
            WorkspaceModelPrice.workspace_id == actor.workspace_id,
            WorkspaceModelPrice.provider == provider,
            WorkspaceModelPrice.model == model,
        )
    )
    if price is None:
        raise HTTPException(status_code=404, detail="Model pricing not found")

    session.add(AuditEvent(
        workspace_id=actor.workspace_id,
        actor=actor.user_id,
        action="usage.model_price.deleted",
        resource_type="workspace_model_price",
        resource_id=price.id,
        detail=f"{provider}:{model}",
        created_at=utcnow(),
    ))
    session.delete(price)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/costs", response_model=CostSummary)
def get_cost_summary(
    session: SessionDep,
    actor: AuthDep,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
) -> CostSummary:
    """Report immutable USD estimates from explicitly configured price snapshots."""
    if start_date is not None and end_date is not None and end_date < start_date:
        raise HTTPException(
            status_code=422, detail="end_date must be on or after start_date"
        )

    agent_totals, agent_breakdown, agent_daily = _cost_aggregate(
        session, AgentRun, actor.workspace_id, "agent", start_date, end_date
    )
    skill_totals, skill_breakdown, skill_daily = _cost_aggregate(
        session, SkillRun, actor.workspace_id, "skill", start_date, end_date
    )
    daily_map: dict[date, CostTotals] = {}
    for item in agent_daily + skill_daily:
        current = daily_map.setdefault(item.date, CostTotals())
        daily_map[item.date] = _add_cost_totals(
            current,
            CostTotals(
                runs=item.runs,
                priced_runs=item.priced_runs,
                unpriced_runs=item.unpriced_runs,
                estimated_cost_usd=item.estimated_cost_usd,
            ),
        )
    return CostSummary(
        start_date=start_date,
        end_date=end_date,
        totals=_add_cost_totals(agent_totals, skill_totals),
        by_execution_type={"agent": agent_totals, "skill": skill_totals},
        by_provider_model=agent_breakdown + skill_breakdown,
        by_day=[
            DailyCost(date=day, **totals.model_dump())
            for day, totals in sorted(daily_map.items())
        ],
    )
