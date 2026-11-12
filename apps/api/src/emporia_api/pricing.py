from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from emporia_api.models import AgentRun, SkillRun, WorkspaceModelPrice

RunWithCost = AgentRun | SkillRun


def snapshot_model_price(session: Session, run: RunWithCost) -> None:
    """Copy the active workspace rate onto a run before its provider call starts."""
    price = session.scalar(
        select(WorkspaceModelPrice).where(
            WorkspaceModelPrice.workspace_id == run.workspace_id,
            WorkspaceModelPrice.provider == run.provider,
            WorkspaceModelPrice.model == run.model,
        )
    )
    if price is None:
        return
    run.input_price_usd_per_million_tokens = price.input_usd_per_million_tokens
    run.output_price_usd_per_million_tokens = price.output_usd_per_million_tokens


def settle_run_cost(
    run: RunWithCost,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> Decimal | None:
    """Estimate USD only when both rate snapshots and both provider counters are known."""
    input_rate = run.input_price_usd_per_million_tokens
    output_rate = run.output_price_usd_per_million_tokens
    if (
        input_rate is None
        or output_rate is None
        or prompt_tokens is None
        or completion_tokens is None
        or prompt_tokens < 0
        or completion_tokens < 0
    ):
        run.estimated_cost_usd = None
        return None

    amount = (
        Decimal(prompt_tokens) * input_rate
        + Decimal(completion_tokens) * output_rate
    ) / Decimal(1_000_000)
    run.estimated_cost_usd = amount
    return amount
