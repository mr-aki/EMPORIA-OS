"""Workspace-scoped min/max inventory replenishment planning."""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from math import ceil
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from emporia_api.auth import Principal, get_current_principal, require_write_access
from emporia_api.database import get_session
from emporia_api.models import (
    AuditEvent,
    InventoryMovement,
    InventoryReorderPolicy,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    utcnow,
)
from emporia_api.schemas import (
    InventoryReorderPolicyRead,
    InventoryReorderPolicyWrite,
    InventoryReplenishmentRead,
)

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]
AuthDep = Annotated[Principal, Depends(get_current_principal)]


def _product_or_404(session: Session, product_id: str, workspace_id: str) -> Product:
    product = session.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.workspace_id == workspace_id,
        )
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.put(
    "/api/v1/products/{product_id}/reorder-policy",
    response_model=InventoryReorderPolicyRead,
    tags=["inventory"],
)
def put_reorder_policy(
    product_id: str,
    payload: InventoryReorderPolicyWrite,
    session: SessionDep,
    actor: AuthDep,
):
    """Create or replace the workspace's min/max policy for one product."""
    require_write_access(actor)

    # Serialize concurrent policy upserts using the same product-row lock
    # convention as inventory movements and purchase-order receipts.
    locked = session.execute(
        update(Product)
        .where(
            Product.id == product_id,
            Product.workspace_id == actor.workspace_id,
        )
        .values(updated_at=Product.updated_at)
    )
    if locked.rowcount != 1:
        session.rollback()
        raise HTTPException(status_code=404, detail="Product not found")

    policy = session.scalar(
        select(InventoryReorderPolicy).where(
            InventoryReorderPolicy.workspace_id == actor.workspace_id,
            InventoryReorderPolicy.product_id == product_id,
        )
    )
    values = payload.model_dump()
    if policy is None:
        policy = InventoryReorderPolicy(
            workspace_id=actor.workspace_id,
            product_id=product_id,
            **values,
        )
        session.add(policy)
        action = "inventory.reorder_policy.created"
    else:
        for field, value in values.items():
            setattr(policy, field, value)
        action = "inventory.reorder_policy.updated"

    try:
        session.flush()
        session.add(
            AuditEvent(
                workspace_id=actor.workspace_id,
                actor=actor.user_id,
                action=action,
                resource_type="inventory_reorder_policy",
                resource_id=policy.id,
                detail=(
                    f"reorder_point={policy.reorder_point};"
                    f"target_stock={policy.target_stock};"
                    f"lead_time_days={policy.lead_time_days}"
                ),
            )
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Reorder policy conflicts with an existing product policy",
        ) from exc

    session.refresh(policy)
    return policy


@router.get(
    "/api/v1/products/{product_id}/reorder-policy",
    response_model=InventoryReorderPolicyRead,
    tags=["inventory"],
)
def get_reorder_policy(
    product_id: str,
    session: SessionDep,
    actor: AuthDep,
):
    """Read the authenticated workspace's policy for one product."""
    _product_or_404(session, product_id, actor.workspace_id)
    policy = session.scalar(
        select(InventoryReorderPolicy).where(
            InventoryReorderPolicy.workspace_id == actor.workspace_id,
            InventoryReorderPolicy.product_id == product_id,
        )
    )
    if policy is None:
        raise HTTPException(status_code=404, detail="Reorder policy not configured")
    return policy


@router.get(
    "/api/v1/inventory/replenishment",
    response_model=InventoryReplenishmentRead,
    tags=["inventory"],
)
def get_replenishment_suggestions(
    session: SessionDep,
    actor: AuthDep,
    lookback_days: Annotated[int, Query(ge=7, le=365)] = 30,
    reorder_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
):
    """Calculate read-only min/max replenishment suggestions from ledger activity."""
    records = list(
        session.execute(
            select(InventoryReorderPolicy, Product)
            .join(
                Product,
                and_(
                    Product.id == InventoryReorderPolicy.product_id,
                    Product.workspace_id == InventoryReorderPolicy.workspace_id,
                ),
            )
            .where(
                InventoryReorderPolicy.workspace_id == actor.workspace_id,
                Product.status != "archived",
            )
            .order_by(Product.sku.asc(), Product.id.asc())
            .limit(limit)
        )
    )
    if not records:
        return InventoryReplenishmentRead(
            lookback_days=lookback_days,
            configured_product_count=0,
            reorder_candidate_count=0,
            items=[],
        )

    product_ids = [product.id for _policy, product in records]
    stock_rows = session.execute(
        select(
            InventoryMovement.product_id,
            func.coalesce(func.sum(InventoryMovement.quantity_delta), 0),
        )
        .where(
            InventoryMovement.workspace_id == actor.workspace_id,
            InventoryMovement.product_id.in_(product_ids),
        )
        .group_by(InventoryMovement.product_id)
    )
    stock_by_product = {product_id: int(quantity or 0) for product_id, quantity in stock_rows}

    incoming_rows = session.execute(
        select(
            PurchaseOrderLine.product_id,
            func.coalesce(
                func.sum(
                    PurchaseOrderLine.quantity_ordered - PurchaseOrderLine.quantity_received
                ),
                0,
            ),
        )
        .join(
            PurchaseOrder,
            and_(
                PurchaseOrder.id == PurchaseOrderLine.purchase_order_id,
                PurchaseOrder.workspace_id == PurchaseOrderLine.workspace_id,
            ),
        )
        .where(
            PurchaseOrderLine.workspace_id == actor.workspace_id,
            PurchaseOrderLine.product_id.in_(product_ids),
            PurchaseOrder.status.in_(("ordered", "partially_received")),
            PurchaseOrderLine.quantity_ordered > PurchaseOrderLine.quantity_received,
        )
        .group_by(PurchaseOrderLine.product_id)
    )
    incoming_by_product = {
        product_id: int(quantity or 0) for product_id, quantity in incoming_rows
    }

    sales_since = utcnow() - timedelta(days=lookback_days)
    sales_rows = session.execute(
        select(
            InventoryMovement.product_id,
            func.coalesce(func.sum(-InventoryMovement.quantity_delta), 0),
        )
        .where(
            InventoryMovement.workspace_id == actor.workspace_id,
            InventoryMovement.product_id.in_(product_ids),
            InventoryMovement.movement_type == "sale",
            InventoryMovement.created_at >= sales_since,
        )
        .group_by(InventoryMovement.product_id)
    )
    sales_by_product = {
        product_id: int(quantity or 0) for product_id, quantity in sales_rows
    }

    items = []
    for policy, product in records:
        on_hand = stock_by_product.get(product.id, 0)
        incoming = incoming_by_product.get(product.id, 0)
        projected_available = on_hand + incoming
        sold = sales_by_product.get(product.id, 0)
        average_daily_sales = (
            Decimal(sold) / Decimal(lookback_days)
        ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        lead_time_demand = (
            ceil(Decimal(sold) * Decimal(policy.lead_time_days) / Decimal(lookback_days))
            if sold and policy.lead_time_days
            else 0
        )
        days_of_cover = (
            (Decimal(projected_available) / average_daily_sales).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if average_daily_sales > 0
            else None
        )
        should_reorder = projected_available <= policy.reorder_point
        suggested_quantity = (
            max(policy.target_stock - projected_available, 0)
            if should_reorder
            else 0
        )
        items.append(
            {
                "product_id": product.id,
                "sku": product.sku,
                "name": product.name,
                "reorder_point": policy.reorder_point,
                "target_stock": policy.target_stock,
                "lead_time_days": policy.lead_time_days,
                "quantity_on_hand": on_hand,
                "quantity_incoming": incoming,
                "projected_available": projected_available,
                "units_sold_in_period": sold,
                "lookback_days": lookback_days,
                "average_daily_sales": average_daily_sales,
                "estimated_lead_time_demand": lead_time_demand,
                "days_of_cover": days_of_cover,
                "should_reorder": should_reorder,
                "suggested_order_quantity": suggested_quantity,
            }
        )

    candidate_count = sum(item["should_reorder"] for item in items)
    if reorder_only:
        items = [item for item in items if item["should_reorder"]]

    return InventoryReplenishmentRead(
        lookback_days=lookback_days,
        configured_product_count=len(records),
        reorder_candidate_count=candidate_count,
        items=items,
    )
