from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from emporia_api.models import AgentRun, SkillRun, WorkspaceModelPrice

MILLION = Decimal(1_000_000)


def snapshot_model_price(session: Session, run: AgentRun | SkillRun) -> None:
    """Copy workspace rates onto a new run before provider execution begins."""
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
    run: AgentRun | SkillRun,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> Decimal | None:
    """Calculate an estimate only when rates and both provider token counts are known."""
    input_rate = run.input_price_usd_per_million_tokens
    output_rate = run.output_price_usd_per_million_tokens
    if (
        input_rate is None
        or output_rate is None
        or prompt_tokens is None
        or completion_tokens is None
    ):
        run.estimated_cost_usd = None
        return None

    amount = (
        Decimal(prompt_tokens) * input_rate
        + Decimal(completion_tokens) * output_rate
    ) / MILLION
    run.estimated_cost_usd = amount
    return amount
