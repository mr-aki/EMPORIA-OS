"""FIFO inventory cost layers and immutable outbound cost allocations."""

from decimal import Decimal

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from emporia_api.models import (
    InventoryCostAllocation,
    InventoryCostLayer,
    InventoryCostReturnAllocation,
    InventoryMovement,
    InventoryReturn,
)


def create_inbound_cost_layer(
    session: Session,
    movement: InventoryMovement,
    *,
    unit_cost: Decimal | None = None,
    currency: str | None = None,
) -> InventoryCostLayer:
    """Create one layer for a positive movement; absent cost stays explicitly unknown."""
    if movement.quantity_delta <= 0:
        raise ValueError("FIFO cost layers require a positive inventory movement")
    if (unit_cost is None) != (currency is None):
        raise ValueError("Unit cost and currency must either both be present or both be absent")

    layer = InventoryCostLayer(
        workspace_id=movement.workspace_id,
        product_id=movement.product_id,
        source_inventory_movement_id=movement.id,
        source_type="inventory_movement",
        quantity_received=movement.quantity_delta,
        quantity_remaining=movement.quantity_delta,
        unit_cost=unit_cost,
        currency=currency.upper() if currency else None,
        created_at=movement.created_at,
    )
    session.add(layer)
    session.flush()
    return layer


def allocate_fifo_cost(session: Session, movement: InventoryMovement) -> list[InventoryCostAllocation]:
    """Consume oldest cost layers for an outbound movement in the same transaction."""
    if movement.quantity_delta >= 0:
        raise ValueError("FIFO cost allocation requires a negative inventory movement")

    remaining = -movement.quantity_delta
    layers = list(
        session.scalars(
            select(InventoryCostLayer)
            .where(
                InventoryCostLayer.workspace_id == movement.workspace_id,
                InventoryCostLayer.product_id == movement.product_id,
                InventoryCostLayer.quantity_remaining > 0,
            )
            .order_by(InventoryCostLayer.created_at.asc(), InventoryCostLayer.id.asc())
            .with_for_update()
        )
    )
    available = sum(layer.quantity_remaining for layer in layers)
    if available < remaining:
        raise ValueError(
            "Inventory cost layers do not reconcile with the stock ledger; "
            "the outbound movement was not posted"
        )

    allocations: list[InventoryCostAllocation] = []
    for layer in layers:
        if remaining == 0:
            break
        quantity = min(layer.quantity_remaining, remaining)
        extended_cost = (
            (layer.unit_cost * Decimal(quantity)).quantize(Decimal("0.00000001"))
            if layer.unit_cost is not None
            else None
        )
        allocation = InventoryCostAllocation(
            workspace_id=movement.workspace_id,
            inventory_movement_id=movement.id,
            cost_layer_id=layer.id,
            quantity_allocated=quantity,
            unit_cost=layer.unit_cost,
            currency=layer.currency,
            extended_cost=extended_cost,
            created_at=movement.created_at,
        )
        layer.quantity_remaining -= quantity
        session.add(allocation)
        allocations.append(allocation)
        remaining -= quantity

    session.flush()
    return allocations


def inventory_valuation(
    session: Session,
    workspace_id: str,
    product_id: str,
) -> dict[str, object]:
    """Summarize current FIFO layers without converting currencies."""
    summary = session.execute(
        select(
            func.coalesce(func.sum(InventoryCostLayer.quantity_remaining), 0),
            func.coalesce(
                func.sum(
                    case(
                        (
                            InventoryCostLayer.unit_cost.is_not(None),
                            InventoryCostLayer.quantity_remaining,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            InventoryCostLayer.unit_cost.is_(None),
                            InventoryCostLayer.quantity_remaining,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        ).where(
            InventoryCostLayer.workspace_id == workspace_id,
            InventoryCostLayer.product_id == product_id,
        )
    ).one()
    buckets = session.execute(
        select(
            InventoryCostLayer.currency,
            func.sum(InventoryCostLayer.quantity_remaining),
            func.sum(
                InventoryCostLayer.unit_cost * InventoryCostLayer.quantity_remaining
            ),
        )
        .where(
            InventoryCostLayer.workspace_id == workspace_id,
            InventoryCostLayer.product_id == product_id,
            InventoryCostLayer.unit_cost.is_not(None),
        )
        .group_by(InventoryCostLayer.currency)
        .order_by(InventoryCostLayer.currency.asc())
    )
    return {
        "quantity_on_hand": int(summary[0] or 0),
        "costed_quantity": int(summary[1] or 0),
        "uncosted_quantity": int(summary[2] or 0),
        "by_currency": [
            {
                "currency": row[0],
                "quantity": int(row[1] or 0),
                "total_cost": row[2] or Decimal(0),
            }
            for row in buckets
        ],
    }


def inventory_cogs(
    session: Session,
    workspace_id: str,
    product_id: str,
) -> dict[str, object]:
    """Summarize gross sales, linked returns, and net FIFO COGS by currency."""
    join_condition = and_(
        InventoryMovement.id == InventoryCostAllocation.inventory_movement_id,
        InventoryMovement.workspace_id == InventoryCostAllocation.workspace_id,
    )
    base = (
        select(
            func.coalesce(func.sum(InventoryCostAllocation.quantity_allocated), 0),
            func.coalesce(
                func.sum(
                    case(
                        (
                            InventoryCostAllocation.currency.is_not(None),
                            InventoryCostAllocation.quantity_allocated,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            InventoryCostAllocation.currency.is_(None),
                            InventoryCostAllocation.quantity_allocated,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .join(InventoryMovement, join_condition)
        .where(
            InventoryCostAllocation.workspace_id == workspace_id,
            InventoryMovement.workspace_id == workspace_id,
            InventoryMovement.product_id == product_id,
            InventoryMovement.movement_type == "sale",
        )
    )
    totals = session.execute(base).one()
    sale_buckets = session.execute(
        select(
            InventoryCostAllocation.currency,
            func.sum(InventoryCostAllocation.quantity_allocated),
            func.sum(InventoryCostAllocation.extended_cost),
        )
        .join(InventoryMovement, join_condition)
        .where(
            InventoryCostAllocation.workspace_id == workspace_id,
            InventoryMovement.workspace_id == workspace_id,
            InventoryMovement.product_id == product_id,
            InventoryMovement.movement_type == "sale",
            InventoryCostAllocation.currency.is_not(None),
        )
        .group_by(InventoryCostAllocation.currency)
        .order_by(InventoryCostAllocation.currency.asc())
    ).all()

    returned_quantity = int(
        session.scalar(
            select(func.coalesce(func.sum(InventoryReturn.quantity_returned), 0)).where(
                InventoryReturn.workspace_id == workspace_id,
                InventoryReturn.product_id == product_id,
            )
        )
        or 0
    )
    return_totals = session.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (
                            InventoryCostReturnAllocation.unit_cost.is_not(None),
                            InventoryCostReturnAllocation.quantity_returned,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            InventoryCostReturnAllocation.unit_cost.is_(None),
                            InventoryCostReturnAllocation.quantity_returned,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .where(
            InventoryCostReturnAllocation.workspace_id == workspace_id,
            InventoryCostReturnAllocation.product_id == product_id,
        )
    ).one()
    return_buckets = session.execute(
        select(
            InventoryCostReturnAllocation.currency,
            func.sum(InventoryCostReturnAllocation.quantity_returned),
            func.sum(InventoryCostReturnAllocation.extended_cost),
        )
        .where(
            InventoryCostReturnAllocation.workspace_id == workspace_id,
            InventoryCostReturnAllocation.product_id == product_id,
            InventoryCostReturnAllocation.currency.is_not(None),
        )
        .group_by(InventoryCostReturnAllocation.currency)
        .order_by(InventoryCostReturnAllocation.currency.asc())
    ).all()

    gross_by_currency = {
        row[0]: (int(row[1] or 0), row[2] or Decimal(0))
        for row in sale_buckets
    }
    returned_by_currency = {
        row[0]: (int(row[1] or 0), row[2] or Decimal(0))
        for row in return_buckets
    }
    net_by_currency = []
    for currency in sorted(set(gross_by_currency) | set(returned_by_currency)):
        sold_quantity, sold_cost = gross_by_currency.get(currency, (0, Decimal(0)))
        returned_units, returned_cost = returned_by_currency.get(
            currency, (0, Decimal(0))
        )
        net_by_currency.append(
            {
                "currency": currency,
                "quantity": sold_quantity - returned_units,
                "total_cost": sold_cost - returned_cost,
            }
        )

    total_sold = int(
        session.scalar(
            select(
                func.coalesce(func.sum(-InventoryMovement.quantity_delta), 0)
            ).where(
                InventoryMovement.workspace_id == workspace_id,
                InventoryMovement.product_id == product_id,
                InventoryMovement.movement_type == "sale",
            )
        )
        or 0
    )
    return {
        "allocated_quantity_sold": int(totals[0] or 0),
        "costed_quantity_sold": int(totals[1] or 0),
        "uncosted_quantity_sold": int(totals[2] or 0),
        "allocated_quantity_returned": returned_quantity,
        "costed_quantity_returned": int(return_totals[0] or 0),
        "uncosted_quantity_returned": int(return_totals[1] or 0),
        "net_quantity_sold": total_sold - returned_quantity,
        "by_currency": [
            {
                "currency": row[0],
                "quantity": int(row[1] or 0),
                "total_cost": row[2] or Decimal(0),
            }
            for row in sale_buckets
        ],
        "by_currency_returns": [
            {
                "currency": row[0],
                "quantity": int(row[1] or 0),
                "total_cost": row[2] or Decimal(0),
            }
            for row in return_buckets
        ],
        "by_currency_net": net_by_currency,
    }


def restore_fifo_cost(
    session: Session,
    return_record: InventoryReturn,
    sale_movement: InventoryMovement,
    return_movement: InventoryMovement,
) -> list[InventoryCostReturnAllocation]:
    """Restore cost from the original sale allocations; unknown historical cost stays unknown."""
    source_allocations = list(
        session.scalars(
            select(InventoryCostAllocation)
            .join(
                InventoryCostLayer,
                and_(
                    InventoryCostLayer.id == InventoryCostAllocation.cost_layer_id,
                    InventoryCostLayer.workspace_id == InventoryCostAllocation.workspace_id,
                ),
            )
            .where(
                InventoryCostAllocation.workspace_id == return_record.workspace_id,
                InventoryCostAllocation.inventory_movement_id == sale_movement.id,
            )
            .order_by(InventoryCostLayer.created_at.asc(), InventoryCostLayer.id.asc())
            .with_for_update()
        )
    )

    if not source_allocations:
        # Sales created before FIFO costing have no auditable source cost. Restore
        # their returned stock as uncosted rather than inventing a historical value.
        layer = create_inbound_cost_layer(session, return_movement)
        row = InventoryCostReturnAllocation(
            workspace_id=return_record.workspace_id,
            product_id=return_record.product_id,
            inventory_return_id=return_record.id,
            source_cost_allocation_id=None,
            cost_layer_id=layer.id,
            quantity_returned=return_record.quantity_returned,
            unit_cost=None,
            currency=None,
            extended_cost=None,
            created_at=return_movement.created_at,
        )
        session.add(row)
        session.flush()
        return [row]

    allocated_quantity = sum(item.quantity_allocated for item in source_allocations)
    if allocated_quantity != -sale_movement.quantity_delta:
        raise ValueError(
            "Original sale cost allocations do not reconcile with the sold quantity"
        )

    source_ids = [item.id for item in source_allocations]
    returned_rows = session.execute(
        select(
            InventoryCostReturnAllocation.source_cost_allocation_id,
            func.sum(InventoryCostReturnAllocation.quantity_returned),
        )
        .where(
            InventoryCostReturnAllocation.workspace_id == return_record.workspace_id,
            InventoryCostReturnAllocation.source_cost_allocation_id.in_(source_ids),
        )
        .group_by(InventoryCostReturnAllocation.source_cost_allocation_id)
    ).all()
    returned_by_source = {row[0]: int(row[1] or 0) for row in returned_rows}

    remaining = return_record.quantity_returned
    restored: list[InventoryCostReturnAllocation] = []
    for source in source_allocations:
        if remaining == 0:
            break
        available = source.quantity_allocated - returned_by_source.get(source.id, 0)
        if available <= 0:
            continue
        quantity = min(available, remaining)
        layer = session.scalar(
            select(InventoryCostLayer)
            .where(
                InventoryCostLayer.id == source.cost_layer_id,
                InventoryCostLayer.workspace_id == return_record.workspace_id,
                InventoryCostLayer.product_id == return_record.product_id,
            )
            .with_for_update()
        )
        if layer is None or layer.quantity_remaining + quantity > layer.quantity_received:
            raise ValueError("Original FIFO cost layer cannot accept the requested return quantity")

        layer.quantity_remaining += quantity
        extended_cost = (
            (source.unit_cost * Decimal(quantity)).quantize(Decimal("0.00000001"))
            if source.unit_cost is not None
            else None
        )
        row = InventoryCostReturnAllocation(
            workspace_id=return_record.workspace_id,
            product_id=return_record.product_id,
            inventory_return_id=return_record.id,
            source_cost_allocation_id=source.id,
            cost_layer_id=source.cost_layer_id,
            quantity_returned=quantity,
            unit_cost=source.unit_cost,
            currency=source.currency,
            extended_cost=extended_cost,
            created_at=return_movement.created_at,
        )
        session.add(row)
        restored.append(row)
        remaining -= quantity

    if remaining:
        raise ValueError(
            "Original sale allocations do not have enough unreturned quantity to restore"
        )
    session.flush()
    return restored
