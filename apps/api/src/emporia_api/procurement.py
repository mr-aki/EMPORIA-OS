"""Workspace-scoped supplier and purchase-order receiving APIs."""

import hashlib
import json
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from emporia_api.auth import Principal, get_current_principal, require_write_access
from emporia_api.costing import create_inbound_cost_layer
from emporia_api.database import get_session
from emporia_api.models import (
    AuditEvent,
    InventoryMovement,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderReceipt,
    PurchaseOrderReceiptLine,
    Supplier,
)
from emporia_api.schemas import (
    ProcurementSpendRead,
    PurchaseOrderCreate,
    PurchaseOrderRead,
    PurchaseOrderReceiptCreate,
    PurchaseOrderReceiptRead,
    SupplierCreate,
    SupplierRead,
    SupplierUpdate,
)

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]
AuthDep = Annotated[Principal, Depends(get_current_principal)]
OrderStatus = Literal["draft", "ordered", "partially_received", "received", "cancelled"]


def _supplier_or_404(session: Session, supplier_id: str, workspace_id: str) -> Supplier:
    supplier = session.scalar(
        select(Supplier).where(
            Supplier.id == supplier_id,
            Supplier.workspace_id == workspace_id,
        )
    )
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return supplier


def _order_or_404(session: Session, order_id: str, workspace_id: str) -> PurchaseOrder:
    order = session.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.id == order_id,
            PurchaseOrder.workspace_id == workspace_id,
        )
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return order


def _order_read(session: Session, order: PurchaseOrder) -> dict[str, object]:
    lines = list(
        session.scalars(
            select(PurchaseOrderLine)
            .where(
                PurchaseOrderLine.workspace_id == order.workspace_id,
                PurchaseOrderLine.purchase_order_id == order.id,
            )
            .order_by(PurchaseOrderLine.created_at.asc(), PurchaseOrderLine.id.asc())
        )
    )
    ordered_subtotal = sum(
        (line.unit_cost * line.quantity_ordered for line in lines),
        Decimal(0),
    )
    received_subtotal = sum(
        (line.unit_cost * line.quantity_received for line in lines),
        Decimal(0),
    )
    return {
        "id": order.id,
        "order_number": order.order_number,
        "supplier_id": order.supplier_id,
        "currency": order.currency,
        "status": order.status,
        "notes": order.notes,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "ordered_subtotal": ordered_subtotal,
        "received_subtotal": received_subtotal,
        "outstanding_subtotal": ordered_subtotal - received_subtotal,
        "lines": lines,
    }


def _receipt_read(
    session: Session,
    receipt: PurchaseOrderReceipt,
    order: PurchaseOrder,
) -> dict[str, object]:
    lines = session.scalars(
        select(PurchaseOrderReceiptLine)
        .where(
            PurchaseOrderReceiptLine.workspace_id == receipt.workspace_id,
            PurchaseOrderReceiptLine.receipt_id == receipt.id,
        )
        .order_by(PurchaseOrderReceiptLine.id.asc())
    )
    return {
        "id": receipt.id,
        "purchase_order_id": receipt.purchase_order_id,
        "purchase_order_status": order.status,
        "idempotency_key": receipt.idempotency_key,
        "created_at": receipt.created_at,
        "lines": list(lines),
    }


def _receipt_fingerprint(order_id: str, payload: PurchaseOrderReceiptCreate) -> str:
    canonical = {
        "purchase_order_id": order_id,
        "lines": sorted(
            [
                {
                    "purchase_order_line_id": line.purchase_order_line_id,
                    "quantity_received": line.quantity_received,
                }
                for line in payload.lines
            ],
            key=lambda item: item["purchase_order_line_id"],
        ),
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@router.post(
    "/api/v1/suppliers",
    response_model=SupplierRead,
    status_code=status.HTTP_201_CREATED,
    tags=["procurement"],
)
def create_supplier(payload: SupplierCreate, session: SessionDep, actor: AuthDep):
    require_write_access(actor)
    supplier = Supplier(workspace_id=actor.workspace_id, **payload.model_dump())
    session.add(supplier)
    try:
        session.flush()
        session.add(
            AuditEvent(
                workspace_id=actor.workspace_id,
                actor=actor.user_id,
                action="supplier.created",
                resource_type="supplier",
                resource_id=supplier.id,
                detail=supplier.code or supplier.name,
            )
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A supplier with this code already exists in this workspace",
        ) from exc
    session.refresh(supplier)
    return supplier


@router.get("/api/v1/suppliers", response_model=list[SupplierRead], tags=["procurement"])
def list_suppliers(
    session: SessionDep,
    actor: AuthDep,
    supplier_status: Annotated[Literal["active", "archived"] | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    statement = select(Supplier).where(Supplier.workspace_id == actor.workspace_id)
    if supplier_status is not None:
        statement = statement.where(Supplier.status == supplier_status)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(Supplier.code.ilike(pattern), Supplier.name.ilike(pattern))
        )
    statement = statement.order_by(Supplier.created_at.desc(), Supplier.name.asc()).limit(limit)
    return list(session.scalars(statement))


@router.get("/api/v1/suppliers/{supplier_id}", response_model=SupplierRead, tags=["procurement"])
def get_supplier(supplier_id: str, session: SessionDep, actor: AuthDep):
    return _supplier_or_404(session, supplier_id, actor.workspace_id)


@router.patch("/api/v1/suppliers/{supplier_id}", response_model=SupplierRead, tags=["procurement"])
def update_supplier(
    supplier_id: str,
    payload: SupplierUpdate,
    session: SessionDep,
    actor: AuthDep,
):
    require_write_access(actor)
    supplier = _supplier_or_404(session, supplier_id, actor.workspace_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(supplier, field, value)
    session.add(
        AuditEvent(
            workspace_id=actor.workspace_id,
            actor=actor.user_id,
            action="supplier.updated",
            resource_type="supplier",
            resource_id=supplier.id,
            detail=",".join(sorted(changes)),
        )
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A supplier with this code already exists in this workspace",
        ) from exc
    session.refresh(supplier)
    return supplier


@router.get(
    "/api/v1/procurement/spend",
    response_model=list[ProcurementSpendRead],
    tags=["procurement"],
)
def get_procurement_spend(
    session: SessionDep,
    actor: AuthDep,
    supplier_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
):
    """Summarize placed purchase commitments and received value by supplier/currency."""
    statement = (
        select(
            Supplier.id.label("supplier_id"),
            Supplier.name.label("supplier_name"),
            PurchaseOrder.currency.label("currency"),
            func.count(func.distinct(PurchaseOrder.id)).label("purchase_order_count"),
            func.sum(
                PurchaseOrderLine.unit_cost * PurchaseOrderLine.quantity_ordered
            ).label("ordered_subtotal"),
            func.sum(
                PurchaseOrderLine.unit_cost * PurchaseOrderLine.quantity_received
            ).label("received_subtotal"),
            func.sum(
                PurchaseOrderLine.unit_cost
                * (PurchaseOrderLine.quantity_ordered - PurchaseOrderLine.quantity_received)
            ).label("outstanding_subtotal"),
        )
        .join(
            PurchaseOrder,
            and_(
                PurchaseOrder.supplier_id == Supplier.id,
                PurchaseOrder.workspace_id == Supplier.workspace_id,
            ),
        )
        .join(
            PurchaseOrderLine,
            and_(
                PurchaseOrderLine.purchase_order_id == PurchaseOrder.id,
                PurchaseOrderLine.workspace_id == PurchaseOrder.workspace_id,
            ),
        )
        .where(
            Supplier.workspace_id == actor.workspace_id,
            PurchaseOrder.workspace_id == actor.workspace_id,
            PurchaseOrder.status.in_(("ordered", "partially_received", "received")),
        )
        .group_by(Supplier.id, Supplier.name, PurchaseOrder.currency)
        .order_by(Supplier.name.asc(), PurchaseOrder.currency.asc())
        .limit(limit)
    )
    if supplier_id is not None:
        statement = statement.where(Supplier.id == supplier_id)
    return [dict(row._mapping) for row in session.execute(statement)]


@router.post(
    "/api/v1/purchase-orders",
    response_model=PurchaseOrderRead,
    status_code=status.HTTP_201_CREATED,
    tags=["procurement"],
)
def create_purchase_order(
    payload: PurchaseOrderCreate,
    session: SessionDep,
    actor: AuthDep,
):
    require_write_access(actor)
    supplier = _supplier_or_404(session, payload.supplier_id, actor.workspace_id)
    if supplier.status != "active":
        raise HTTPException(status_code=409, detail="Archived suppliers cannot receive new orders")

    product_ids = [line.product_id for line in payload.lines]
    products = list(
        session.scalars(
            select(Product).where(
                Product.workspace_id == actor.workspace_id,
                Product.id.in_(product_ids),
            )
        )
    )
    if len(products) != len(product_ids):
        raise HTTPException(status_code=404, detail="One or more products were not found")
    if any(product.status == "archived" for product in products):
        raise HTTPException(status_code=409, detail="Archived products cannot be ordered")

    order = PurchaseOrder(
        workspace_id=actor.workspace_id,
        supplier_id=supplier.id,
        order_number=payload.order_number,
        currency=payload.currency,
        notes=payload.notes,
        status="draft",
    )
    session.add(order)
    try:
        session.flush()
        for line in payload.lines:
            session.add(
                PurchaseOrderLine(
                    workspace_id=actor.workspace_id,
                    purchase_order_id=order.id,
                    product_id=line.product_id,
                    quantity_ordered=line.quantity_ordered,
                    unit_cost=line.unit_cost,
                )
            )
        session.flush()
        session.add(
            AuditEvent(
                workspace_id=actor.workspace_id,
                actor=actor.user_id,
                action="purchase_order.created",
                resource_type="purchase_order",
                resource_id=order.id,
                detail=order.order_number,
            )
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Purchase order number or product line conflicts with an existing order",
        ) from exc
    session.refresh(order)
    return _order_read(session, order)


@router.get(
    "/api/v1/purchase-orders",
    response_model=list[PurchaseOrderRead],
    tags=["procurement"],
)
def list_purchase_orders(
    session: SessionDep,
    actor: AuthDep,
    order_status: Annotated[OrderStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    statement = select(PurchaseOrder).where(
        PurchaseOrder.workspace_id == actor.workspace_id
    )
    if order_status is not None:
        statement = statement.where(PurchaseOrder.status == order_status)
    orders = session.scalars(
        statement.order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.order_number.asc())
        .limit(limit)
    )
    return [_order_read(session, order) for order in orders]


@router.get(
    "/api/v1/purchase-orders/{purchase_order_id}",
    response_model=PurchaseOrderRead,
    tags=["procurement"],
)
def get_purchase_order(
    purchase_order_id: str,
    session: SessionDep,
    actor: AuthDep,
):
    order = _order_or_404(session, purchase_order_id, actor.workspace_id)
    return _order_read(session, order)


@router.post(
    "/api/v1/purchase-orders/{purchase_order_id}/order",
    response_model=PurchaseOrderRead,
    tags=["procurement"],
)
def place_purchase_order(
    purchase_order_id: str,
    session: SessionDep,
    actor: AuthDep,
):
    require_write_access(actor)
    locked = session.execute(
        update(PurchaseOrder)
        .where(
            PurchaseOrder.id == purchase_order_id,
            PurchaseOrder.workspace_id == actor.workspace_id,
        )
        .values(updated_at=PurchaseOrder.updated_at)
    )
    if locked.rowcount != 1:
        session.rollback()
        raise HTTPException(status_code=404, detail="Purchase order not found")
    order = _order_or_404(session, purchase_order_id, actor.workspace_id)
    if order.status != "draft":
        session.rollback()
        raise HTTPException(status_code=409, detail="Only draft purchase orders can be placed")
    order.status = "ordered"
    session.add(
        AuditEvent(
            workspace_id=actor.workspace_id,
            actor=actor.user_id,
            action="purchase_order.placed",
            resource_type="purchase_order",
            resource_id=order.id,
            detail=order.order_number,
        )
    )
    session.commit()
    session.refresh(order)
    return _order_read(session, order)


@router.post(
    "/api/v1/purchase-orders/{purchase_order_id}/receipts",
    response_model=PurchaseOrderReceiptRead,
    status_code=status.HTTP_201_CREATED,
    tags=["procurement"],
)
def receive_purchase_order(
    purchase_order_id: str,
    payload: PurchaseOrderReceiptCreate,
    response: Response,
    session: SessionDep,
    actor: AuthDep,
):
    """Post an idempotent partial/full receipt and inventory movements atomically."""
    require_write_access(actor)

    locked = session.execute(
        update(PurchaseOrder)
        .where(
            PurchaseOrder.id == purchase_order_id,
            PurchaseOrder.workspace_id == actor.workspace_id,
        )
        .values(updated_at=PurchaseOrder.updated_at)
    )
    if locked.rowcount != 1:
        session.rollback()
        raise HTTPException(status_code=404, detail="Purchase order not found")

    order = _order_or_404(session, purchase_order_id, actor.workspace_id)
    fingerprint = _receipt_fingerprint(order.id, payload)
    existing = session.scalar(
        select(PurchaseOrderReceipt).where(
            PurchaseOrderReceipt.workspace_id == actor.workspace_id,
            PurchaseOrderReceipt.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        if (
            existing.purchase_order_id == order.id
            and existing.request_fingerprint == fingerprint
        ):
            response.status_code = status.HTTP_200_OK
            response.headers["Idempotency-Replayed"] = "true"
            return _receipt_read(session, existing, order)
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Idempotency key was already used with a different receipt",
        )

    if order.status not in {"ordered", "partially_received"}:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Only ordered or partially received purchase orders can be received",
        )

    order_lines = list(
        session.scalars(
            select(PurchaseOrderLine).where(
                PurchaseOrderLine.workspace_id == actor.workspace_id,
                PurchaseOrderLine.purchase_order_id == order.id,
            )
        )
    )
    line_map = {line.id: line for line in order_lines}
    if any(item.purchase_order_line_id not in line_map for item in payload.lines):
        session.rollback()
        raise HTTPException(status_code=404, detail="One or more purchase-order lines were not found")
    for item in payload.lines:
        line = line_map[item.purchase_order_line_id]
        if item.quantity_received > line.quantity_ordered - line.quantity_received:
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail="Receipt quantity exceeds the remaining ordered quantity",
            )

    product_ids = sorted({line_map[item.purchase_order_line_id].product_id for item in payload.lines})
    for product_id in product_ids:
        product_lock = session.execute(
            update(Product)
            .where(
                Product.id == product_id,
                Product.workspace_id == actor.workspace_id,
            )
            .values(updated_at=Product.updated_at)
        )
        if product_lock.rowcount != 1:
            session.rollback()
            raise HTTPException(status_code=404, detail="One or more products were not found")

    receipt = PurchaseOrderReceipt(
        workspace_id=actor.workspace_id,
        purchase_order_id=order.id,
        idempotency_key=payload.idempotency_key,
        request_fingerprint=fingerprint,
    )
    session.add(receipt)

    try:
        session.flush()
        for item in sorted(
            payload.lines,
            key=lambda entry: line_map[entry.purchase_order_line_id].product_id,
        ):
            line = line_map[item.purchase_order_line_id]
            current_balance = session.scalar(
                select(func.coalesce(func.sum(InventoryMovement.quantity_delta), 0)).where(
                    InventoryMovement.workspace_id == actor.workspace_id,
                    InventoryMovement.product_id == line.product_id,
                )
            )
            quantity_after = int(current_balance or 0) + item.quantity_received
            movement = InventoryMovement(
                workspace_id=actor.workspace_id,
                product_id=line.product_id,
                movement_type="receipt",
                quantity_delta=item.quantity_received,
                quantity_after=quantity_after,
                reason=f"Purchase order {order.order_number} receipt",
                reference=order.order_number,
                idempotency_key=f"po-receipt:{receipt.id}:{line.id}",
            )
            session.add(movement)
            session.flush()
            create_inbound_cost_layer(
                session,
                movement,
                unit_cost=line.unit_cost,
                currency=order.currency,
            )
            session.add(
                PurchaseOrderReceiptLine(
                    workspace_id=actor.workspace_id,
                    receipt_id=receipt.id,
                    purchase_order_line_id=line.id,
                    inventory_movement_id=movement.id,
                    quantity_received=item.quantity_received,
                )
            )
            line.quantity_received += item.quantity_received
            session.add(
                AuditEvent(
                    workspace_id=actor.workspace_id,
                    actor=actor.user_id,
                    action="inventory.movement.created",
                    resource_type="inventory_movement",
                    resource_id=movement.id,
                    detail=f"receipt:{movement.quantity_delta}:{movement.quantity_after}",
                )
            )

        session.flush()
        order.status = (
            "received"
            if all(line.quantity_received == line.quantity_ordered for line in order_lines)
            else "partially_received"
        )
        session.add(
            AuditEvent(
                workspace_id=actor.workspace_id,
                actor=actor.user_id,
                action="purchase_order.receipt.posted",
                resource_type="purchase_order_receipt",
                resource_id=receipt.id,
                detail=f"{order.order_number}:{len(payload.lines)}_lines",
            )
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        existing = session.scalar(
            select(PurchaseOrderReceipt).where(
                PurchaseOrderReceipt.workspace_id == actor.workspace_id,
                PurchaseOrderReceipt.idempotency_key == payload.idempotency_key,
            )
        )
        if (
            existing is not None
            and existing.purchase_order_id == order.id
            and existing.request_fingerprint == fingerprint
        ):
            replay_order = _order_or_404(session, purchase_order_id, actor.workspace_id)
            response.status_code = status.HTTP_200_OK
            response.headers["Idempotency-Replayed"] = "true"
            return _receipt_read(session, existing, replay_order)
        raise HTTPException(
            status_code=409,
            detail="Receipt conflicts with an existing procurement or inventory record",
        ) from exc

    session.refresh(receipt)
    return _receipt_read(session, receipt, order)
