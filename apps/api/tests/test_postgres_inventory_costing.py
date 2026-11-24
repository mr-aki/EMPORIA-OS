from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from emporia_api.database import SessionLocal, engine
from emporia_api.main import app
from emporia_api.models import InventoryCostAllocation, InventoryMovement

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
