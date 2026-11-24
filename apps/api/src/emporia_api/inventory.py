"""Workspace-scoped append-only inventory ledger for catalogue products."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from emporia_api.auth import Principal, get_current_principal, require_write_access
from emporia_api.costing import (
    allocate_fifo_cost,
    create_inbound_cost_layer,
    inventory_cogs,
    inventory_valuation,
    restore_fifo_cost,
)
from emporia_api.database import get_session
from emporia_api.models import AuditEvent, InventoryMovement, InventoryReturn, Product
from emporia_api.schemas import (
    InventoryBalanceRead,
    InventoryCOGSRead,
    InventoryMovementCreate,
    InventoryMovementRead,
    InventoryReturnCreate,
    InventoryReturnRead,
    InventoryValuationRead,
)

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]
AuthDep = Annotated[Principal, Depends(get_current_principal)]


def _find_replay(
    session: Session,
    workspace_id: str,
    idempotency_key: str,
) -> InventoryMovement | None:
    return session.scalar(
        select(InventoryMovement).where(
            InventoryMovement.workspace_id == workspace_id,
            InventoryMovement.idempotency_key == idempotency_key,
        )
    )


def _matches_request(
    movement: InventoryMovement,
    product_id: str,
    payload: InventoryMovementCreate,
) -> bool:
    return (
        movement.product_id == product_id
        and movement.movement_type == payload.movement_type
        and movement.quantity_delta == payload.quantity_delta
        and movement.reason == payload.reason
        and movement.reference == payload.reference
    )


def _product_or_404(
    session: Session,
    product_id: str,
    workspace_id: str,
) -> Product:
    product = session.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.workspace_id == workspace_id,
        )
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.get(
    "/api/v1/products/{product_id}/inventory",
    response_model=InventoryBalanceRead,
    tags=["inventory"],
)
def get_inventory_balance(
    product_id: str,
    session: SessionDep,
    actor: AuthDep,
):
    """Return stock derived from the immutable movement ledger."""
    product = _product_or_404(session, product_id, actor.workspace_id)
    total, count, last_movement_at = session.execute(
        select(
            func.coalesce(func.sum(InventoryMovement.quantity_delta), 0),
            func.count(InventoryMovement.id),
            func.max(InventoryMovement.created_at),
        ).where(
            InventoryMovement.workspace_id == actor.workspace_id,
            InventoryMovement.product_id == product_id,
        )
    ).one()
    return InventoryBalanceRead(
        product_id=product.id,
        sku=product.sku,
        quantity_on_hand=int(total or 0),
        movement_count=int(count or 0),
        last_movement_at=last_movement_at,
    )


@router.get(
    "/api/v1/products/{product_id}/inventory/movements",
    response_model=list[InventoryMovementRead],
    tags=["inventory"],
)
def list_inventory_movements(
    product_id: str,
    session: SessionDep,
    actor: AuthDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    """List a bounded, newest-first history for one workspace product."""
    _product_or_404(session, product_id, actor.workspace_id)
    statement = (
        select(InventoryMovement)
        .where(
            InventoryMovement.workspace_id == actor.workspace_id,
            InventoryMovement.product_id == product_id,
        )
        .order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc())
        .limit(limit)
    )
    return list(session.scalars(statement))


@router.post(
    "/api/v1/products/{product_id}/inventory/movements",
    response_model=InventoryMovementRead,
    status_code=status.HTTP_201_CREATED,
    tags=["inventory"],
)
def create_inventory_movement(
    product_id: str,
    payload: InventoryMovementCreate,
    response: Response,
    session: SessionDep,
    actor: AuthDep,
):
    """Append a stock movement exactly once and prevent a negative balance."""
    require_write_access(actor)

    existing = _find_replay(session, actor.workspace_id, payload.idempotency_key)
    if existing is not None:
        if not _matches_request(existing, product_id, payload):
            raise HTTPException(
                status_code=409,
                detail="Idempotency key was already used with a different movement",
            )
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotency-Replayed"] = "true"
        return existing

    if payload.movement_type == "return":
        raise HTTPException(
            status_code=422,
            detail="Returns must reference an original sale using the linked return endpoint",
        )

    # A no-op UPDATE acquires a product row lock in PostgreSQL and a write lock in
    # SQLite before reading the balance. This serializes concurrent movements for
    # the same product without relying on SQLite's unsupported SELECT FOR UPDATE.
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

    current_balance = session.scalar(
        select(func.coalesce(func.sum(InventoryMovement.quantity_delta), 0)).where(
            InventoryMovement.workspace_id == actor.workspace_id,
            InventoryMovement.product_id == product_id,
        )
    )
    quantity_after = int(current_balance or 0) + payload.quantity_delta
    if quantity_after < 0:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Insufficient stock for this inventory movement",
        )

    movement = InventoryMovement(
        workspace_id=actor.workspace_id,
        product_id=product_id,
        movement_type=payload.movement_type,
        quantity_delta=payload.quantity_delta,
        quantity_after=quantity_after,
        reason=payload.reason,
        reference=payload.reference,
        idempotency_key=payload.idempotency_key,
    )
    session.add(movement)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        existing = _find_replay(session, actor.workspace_id, payload.idempotency_key)
        if existing is not None and _matches_request(existing, product_id, payload):
            response.status_code = status.HTTP_200_OK
            response.headers["Idempotency-Replayed"] = "true"
            return existing
        raise HTTPException(
            status_code=409,
            detail="Inventory movement conflicts with an existing ledger record",
        ) from exc

    try:
        if movement.quantity_delta > 0:
            create_inbound_cost_layer(session, movement)
        else:
            allocate_fifo_cost(session, movement)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    session.add(
        AuditEvent(
            workspace_id=actor.workspace_id,
            actor=actor.user_id,
            action="inventory.movement.created",
            resource_type="inventory_movement",
            resource_id=movement.id,
            detail=(
                f"{movement.movement_type}:{movement.quantity_delta}:"
                f"{movement.quantity_after}"
            ),
        )
    )
    session.commit()
    session.refresh(movement)
    return movement


@router.post(
    "/api/v1/products/{product_id}/inventory/sales/{sale_movement_id}/returns",
    response_model=InventoryReturnRead,
    status_code=status.HTTP_201_CREATED,
    tags=["inventory"],
)
def create_linked_inventory_return(
    product_id: str,
    sale_movement_id: str,
    payload: InventoryReturnCreate,
    response: Response,
    session: SessionDep,
    actor: AuthDep,
):
    """Record an idempotent return and restore the original sale's FIFO cost layers."""
    require_write_access(actor)

    # Serialize sales and returns on the product row before checking the return cap.
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

    sale = session.scalar(
        select(InventoryMovement).where(
            InventoryMovement.id == sale_movement_id,
            InventoryMovement.workspace_id == actor.workspace_id,
            InventoryMovement.product_id == product_id,
            InventoryMovement.movement_type == "sale",
        )
    )
    if sale is None:
        session.rollback()
        raise HTTPException(status_code=404, detail="Original sale not found")

    existing = _find_replay(session, actor.workspace_id, payload.idempotency_key)
    if existing is not None:
        existing_return = session.scalar(
            select(InventoryReturn).where(
                InventoryReturn.workspace_id == actor.workspace_id,
                InventoryReturn.return_movement_id == existing.id,
            )
        )
        if (
            existing.movement_type == "return"
            and existing.product_id == product_id
            and existing.quantity_delta == payload.quantity_returned
            and existing.reason == payload.reason
            and existing.reference == payload.reference
            and existing_return is not None
            and existing_return.source_sale_movement_id == sale_movement_id
            and existing_return.quantity_returned == payload.quantity_returned
        ):
            response.status_code = status.HTTP_200_OK
            response.headers["Idempotency-Replayed"] = "true"
            return InventoryReturnRead(
                return_movement=existing,
                source_sale_movement_id=existing_return.source_sale_movement_id,
                quantity_returned=existing_return.quantity_returned,
            )
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Idempotency key was already used for a different inventory operation",
        )

    previously_returned = int(
        session.scalar(
            select(func.coalesce(func.sum(InventoryReturn.quantity_returned), 0)).where(
                InventoryReturn.workspace_id == actor.workspace_id,
                InventoryReturn.source_sale_movement_id == sale_movement_id,
            )
        )
        or 0
    )
    if previously_returned + payload.quantity_returned > -sale.quantity_delta:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Return quantity exceeds the unreturned quantity of the original sale",
        )

    current_balance = session.scalar(
        select(func.coalesce(func.sum(InventoryMovement.quantity_delta), 0)).where(
            InventoryMovement.workspace_id == actor.workspace_id,
            InventoryMovement.product_id == product_id,
        )
    )
    quantity_after = int(current_balance or 0) + payload.quantity_returned
    movement = InventoryMovement(
        workspace_id=actor.workspace_id,
        product_id=product_id,
        movement_type="return",
        quantity_delta=payload.quantity_returned,
        quantity_after=quantity_after,
        reason=payload.reason,
        reference=payload.reference,
        idempotency_key=payload.idempotency_key,
    )
    session.add(movement)
    try:
        session.flush()
        return_record = InventoryReturn(
            workspace_id=actor.workspace_id,
            product_id=product_id,
            source_sale_movement_id=sale_movement_id,
            return_movement_id=movement.id,
            quantity_returned=payload.quantity_returned,
        )
        session.add(return_record)
        session.flush()
        restore_fifo_cost(session, return_record, sale, movement)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        session.rollback()
        replay = _find_replay(session, actor.workspace_id, payload.idempotency_key)
        if replay is not None:
            replay_return = session.scalar(
                select(InventoryReturn).where(
                    InventoryReturn.workspace_id == actor.workspace_id,
                    InventoryReturn.return_movement_id == replay.id,
                )
            )
            if (
                replay.movement_type == "return"
                and replay.product_id == product_id
                and replay.quantity_delta == payload.quantity_returned
                and replay.reason == payload.reason
                and replay.reference == payload.reference
                and replay_return is not None
                and replay_return.source_sale_movement_id == sale_movement_id
                and replay_return.quantity_returned == payload.quantity_returned
            ):
                response.status_code = status.HTTP_200_OK
                response.headers["Idempotency-Replayed"] = "true"
                return InventoryReturnRead(
                    return_movement=replay,
                    source_sale_movement_id=replay_return.source_sale_movement_id,
                    quantity_returned=replay_return.quantity_returned,
                )
        raise HTTPException(
            status_code=409,
            detail="Return conflicts with an existing inventory record",
        ) from exc

    session.add(
        AuditEvent(
            workspace_id=actor.workspace_id,
            actor=actor.user_id,
            action="inventory.return.created",
            resource_type="inventory_return",
            resource_id=return_record.id,
            detail=f"{sale_movement_id}:{payload.quantity_returned}",
        )
    )
    session.add(
        AuditEvent(
            workspace_id=actor.workspace_id,
            actor=actor.user_id,
            action="inventory.movement.created",
            resource_type="inventory_movement",
            resource_id=movement.id,
            detail=f"return:{movement.quantity_delta}:{movement.quantity_after}",
        )
    )
    session.commit()
    session.refresh(movement)
    return InventoryReturnRead(
        return_movement=movement,
        source_sale_movement_id=sale_movement_id,
        quantity_returned=payload.quantity_returned,
    )


@router.get(
    "/api/v1/products/{product_id}/inventory/valuation",
    response_model=InventoryValuationRead,
    tags=["inventory"],
)
def get_inventory_valuation(
    product_id: str,
    session: SessionDep,
    actor: AuthDep,
):
    """Return FIFO inventory value without combining or converting currencies."""
    product = _product_or_404(session, product_id, actor.workspace_id)
    return InventoryValuationRead(
        product_id=product.id,
        sku=product.sku,
        **inventory_valuation(session, actor.workspace_id, product_id),
    )


@router.get(
    "/api/v1/products/{product_id}/inventory/cost-of-goods-sold",
    response_model=InventoryCOGSRead,
    tags=["inventory"],
)
def get_inventory_cost_of_goods_sold(
    product_id: str,
    session: SessionDep,
    actor: AuthDep,
):
    """Return FIFO cost allocations for sales posted after costing was enabled."""
    product = _product_or_404(session, product_id, actor.workspace_id)
    return InventoryCOGSRead(
        product_id=product.id,
        sku=product.sku,
        **inventory_cogs(session, actor.workspace_id, product_id),
    )
