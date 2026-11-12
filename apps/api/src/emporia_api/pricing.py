from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from emporia_api.models import WorkspaceModelPrice


def snapshot_model_price(session: Session, run: object) -> None:
    """Copy configured workspace rates onto a run before provider execution begins."""
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
    run: object,
    prompt_tokens: int | None,
    completion_tokens: int | None,
):
    """Calculate a USD estimate only when both rates and both usage counters are known."""
    from decimal import Decimal

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
        Decimal(prompt_tokens) * Decimal(input_rate)
        + Decimal(completion_tokens) * Decimal(output_rate)
    ) / Decimal(1000000)
    run.estimated_cost_usd = amount
    return amount
