from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from emporia_api.auth import Principal, get_current_principal
from emporia_api.database import get_session
from emporia_api.models import AgentRun, AuditEvent, SkillRun, utcnow
from emporia_api.output_budgets import (
    get_workspace_output_budget_state,
    set_workspace_output_budget,
)

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


class UsageSummary(BaseModel):
    totals: UsageTotals
    by_execution_type: dict[str, UsageTotals]
    by_provider_model: list[ProviderModelUsage]


def _aggregate(
    session: Session,
    run_model: Any,
    workspace_id: str,
    execution_type: str,
) -> tuple[UsageTotals, list[ProviderModelUsage]]:
    scope = run_model.workspace_id == workspace_id
    total_row = session.execute(
        select(
            func.count(run_model.id),
            func.coalesce(func.sum(run_model.prompt_tokens), 0),
            func.coalesce(func.sum(run_model.completion_tokens), 0),
            func.coalesce(func.sum(run_model.total_tokens), 0),
        ).where(scope)
    ).one()
    status_rows = session.execute(
        select(run_model.status, func.count(run_model.id))
        .where(scope)
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
            func.count(run_model.id),
            func.sum(run_model.prompt_tokens),
            func.sum(run_model.completion_tokens),
            func.sum(run_model.total_tokens),
        )
        .where(scope)
        .group_by(run_model.provider, run_model.model)
        .order_by(run_model.provider, run_model.model)
    ).all()
    breakdown = [
        ProviderModelUsage(
            execution_type=execution_type,
            provider=row[0],
            model=row[1],
            runs=row[2],
            prompt_tokens=row[3] or 0,
            completion_tokens=row[4] or 0,
            total_tokens=row[5] or 0,
        )
        for row in grouped_rows
    ]
    return totals, breakdown


@router.get("/summary", response_model=UsageSummary)
def get_usage_summary(session: SessionDep, actor: AuthDep) -> UsageSummary:
    """Return persisted agent and skill token usage for the authenticated workspace only."""
    agent_totals, agent_breakdown = _aggregate(
        session, AgentRun, actor.workspace_id, "agent"
    )
    skill_totals, skill_breakdown = _aggregate(
        session, SkillRun, actor.workspace_id, "skill"
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
    return UsageSummary(
        totals=totals,
        by_execution_type={"agent": agent_totals, "skill": skill_totals},
        by_provider_model=agent_breakdown + skill_breakdown,
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
