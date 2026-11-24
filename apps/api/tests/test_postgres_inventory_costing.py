from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from emporia_api.database import SessionLocal, engine
from emporia_api.main import app
from emporia_api.models import (
    InventoryCostAllocation,
    InventoryCostLayer,
    InventoryCostReturnAllocation,
    InventoryMovement,
    InventoryReturn,
)

pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="Concurrent FIFO row-lock verification requires PostgreSQL",
)


def test_concurrent_sales_cannot_double_consume_fifo_cost_layers(client, auth_headers):
    supplier = client.post(
        "/api/v1/suppliers",
        headers=auth_headers,
        json={"code": "PG-FIFO-SUP", "name": "PostgreSQL FIFO Supplier"},
    ).json()
    product = client.post(
        "/api/v1/products",
        headers=auth_headers,
        json={
            "sku": "PG-FIFO-001",
            "name": "PostgreSQL FIFO Product",
            "unit_price": "20.0000",
            "currency": "USD",
        },
    ).json()
    order = client.post(
        "/api/v1/purchase-orders",
        headers=auth_headers,
        json={
            "order_number": "PG-FIFO-PO-001",
            "supplier_id": supplier["id"],
            "currency": "USD",
            "lines": [
                {
                    "product_id": product["id"],
                    "quantity_ordered": 10,
                    "unit_cost": "2.0000",
                }
            ],
        },
    ).json()
    placed = client.post(
        f"/api/v1/purchase-orders/{order['id']}/order",
        headers=auth_headers,
    )
    assert placed.status_code == 200, placed.text
    received = client.post(
        f"/api/v1/purchase-orders/{order['id']}/receipts",
        headers=auth_headers,
        json={
            "idempotency_key": "pg-fifo-receipt-001",
            "lines": [
                {
                    "purchase_order_line_id": order["lines"][0]["id"],
                    "quantity_received": 10,
                }
            ],
        },
    )
    assert received.status_code == 201, received.text

    url = f"/api/v1/products/{product['id']}/inventory/movements"
    barrier = Barrier(2)

    def synchronize_product_lock(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("update products") and "updated_at=products.updated_at" in normalized:
            barrier.wait(timeout=15)

    def post_sale(key):
        with TestClient(app) as concurrent_client:
            return concurrent_client.post(
                url,
                headers=auth_headers,
                json={
                    "movement_type": "sale",
                    "quantity_delta": -6,
                    "reason": "Concurrent FIFO sale",
                    "idempotency_key": key,
                },
            )

    event.listen(engine, "before_cursor_execute", synchronize_product_lock)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(
                executor.map(
                    post_sale,
                    ("pg-fifo-sale-a", "pg-fifo-sale-b"),
                )
            )
    finally:
        event.remove(engine, "before_cursor_execute", synchronize_product_lock)

    assert sorted(response.status_code for response in responses) == [201, 409]
    with SessionLocal() as session:
        sale_count = session.scalar(
            select(func.count(InventoryMovement.id)).where(
                InventoryMovement.product_id == product["id"],
                InventoryMovement.movement_type == "sale",
            )
        )
        allocation_quantity = session.scalar(
            select(func.coalesce(func.sum(InventoryCostAllocation.quantity_allocated), 0))
            .join(
                InventoryMovement,
                (
                    InventoryMovement.id == InventoryCostAllocation.inventory_movement_id
                )
                & (
                    InventoryMovement.workspace_id == InventoryCostAllocation.workspace_id
                ),
            )
            .where(
                InventoryMovement.product_id == product["id"],
                InventoryMovement.movement_type == "sale",
            )
        )
    assert sale_count == 1
    assert allocation_quantity == 6

    valuation = client.get(
        f"/api/v1/products/{product['id']}/inventory/valuation",
        headers=auth_headers,
    )
    assert valuation.status_code == 200, valuation.text
    assert valuation.json()["quantity_on_hand"] == 4
    assert valuation.json()["costed_quantity"] == 4


def test_concurrent_partial_returns_cannot_restore_more_than_original_sale(
    client, auth_headers
):
    supplier = client.post(
        "/api/v1/suppliers",
        headers=auth_headers,
        json={"code": "PG-RET-SUP", "name": "PostgreSQL Return Supplier"},
    ).json()
    product = client.post(
        "/api/v1/products",
        headers=auth_headers,
        json={
            "sku": "PG-RETURN-001",
            "name": "PostgreSQL Return Product",
            "unit_price": "20.0000",
            "currency": "USD",
        },
    ).json()
    order = client.post(
        "/api/v1/purchase-orders",
        headers=auth_headers,
        json={
            "order_number": "PG-RETURN-PO-001",
            "supplier_id": supplier["id"],
            "currency": "USD",
            "lines": [
                {
                    "product_id": product["id"],
                    "quantity_ordered": 6,
                    "unit_cost": "2.0000",
                }
            ],
        },
    ).json()
    assert order["id"]
    placed = client.post(
        f"/api/v1/purchase-orders/{order['id']}/order",
        headers=auth_headers,
    )
    assert placed.status_code == 200, placed.text
    received = client.post(
        f"/api/v1/purchase-orders/{order['id']}/receipts",
        headers=auth_headers,
        json={
            "idempotency_key": "pg-return-receipt-001",
            "lines": [
                {
                    "purchase_order_line_id": order["lines"][0]["id"],
                    "quantity_received": 6,
                }
            ],
        },
    )
    assert received.status_code == 201, received.text

    sale = client.post(
        f"/api/v1/products/{product['id']}/inventory/movements",
        headers=auth_headers,
        json={
            "movement_type": "sale",
            "quantity_delta": -6,
            "reason": "Sale before concurrent return test",
            "idempotency_key": "pg-return-sale-001",
        },
    )
    assert sale.status_code == 201, sale.text
    sale_id = sale.json()["id"]
    url = f"/api/v1/products/{product['id']}/inventory/sales/{sale_id}/returns"
    barrier = Barrier(2)

    def synchronize_product_lock(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("update products") and "updated_at=products.updated_at" in normalized:
            barrier.wait(timeout=15)

    def post_return(key):
        with TestClient(app) as concurrent_client:
            return concurrent_client.post(
                url,
                headers=auth_headers,
                json={
                    "quantity_returned": 4,
                    "reason": "Concurrent partial return",
                    "idempotency_key": key,
                },
            )

    event.listen(engine, "before_cursor_execute", synchronize_product_lock)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(
                executor.map(post_return, ("pg-return-a-001", "pg-return-b-001"))
            )
    finally:
        event.remove(engine, "before_cursor_execute", synchronize_product_lock)

    assert sorted(response.status_code for response in responses) == [201, 409]
    with SessionLocal() as session:
        returned_quantity = session.scalar(
            select(func.coalesce(func.sum(InventoryReturn.quantity_returned), 0)).where(
                InventoryReturn.product_id == product["id"]
            )
        )
        return_count = session.scalar(
            select(func.count(InventoryReturn.id)).where(
                InventoryReturn.product_id == product["id"]
            )
        )
        restored_quantity = session.scalar(
            select(
                func.coalesce(func.sum(InventoryCostReturnAllocation.quantity_returned), 0)
            ).where(InventoryCostReturnAllocation.product_id == product["id"])
        )
        remaining_costed = session.scalar(
            select(func.coalesce(func.sum(InventoryCostLayer.quantity_remaining), 0)).where(
                InventoryCostLayer.product_id == product["id"]
            )
        )
    assert returned_quantity == 4
    assert return_count == 1
    assert restored_quantity == 4
    assert remaining_costed == 4

    valuation = client.get(
        f"/api/v1/products/{product['id']}/inventory/valuation",
        headers=auth_headers,
    )
    assert valuation.status_code == 200, valuation.text
    assert valuation.json()["quantity_on_hand"] == 4
    assert valuation.json()["costed_quantity"] == 4
    cogs = client.get(
        f"/api/v1/products/{product['id']}/inventory/cost-of-goods-sold",
        headers=auth_headers,
    )
    assert cogs.status_code == 200, cogs.text
    assert cogs.json()["allocated_quantity_returned"] == 4
    assert cogs.json()["net_quantity_sold"] == 2
