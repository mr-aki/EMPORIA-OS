from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from emporia_api.database import SessionLocal, engine
from emporia_api.main import app
from emporia_api.models import InventoryMovement, PurchaseOrderReceipt

pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="Procurement receipt locking tests require PostgreSQL",
)


def test_concurrent_identical_purchase_order_receipts_create_one_inventory_movement(
    client, auth_headers
):
    supplier = client.post(
        "/api/v1/suppliers",
        headers=auth_headers,
        json={"code": "PG-SUP-001", "name": "PostgreSQL Supplier"},
    ).json()
    product = client.post(
        "/api/v1/products",
        headers=auth_headers,
        json={
            "sku": "PG-PROC-001",
            "name": "PostgreSQL Procurement Product",
            "unit_price": "10.0000",
            "currency": "USD",
        },
    ).json()
    order = client.post(
        "/api/v1/purchase-orders",
        headers=auth_headers,
        json={
            "order_number": "PG-PO-001",
            "supplier_id": supplier["id"],
            "lines": [
                {
                    "product_id": product["id"],
                    "quantity_ordered": 5,
                    "unit_cost": "3.0000",
                }
            ],
        },
    ).json()
    placed = client.post(f"/api/v1/purchase-orders/{order['id']}/order", headers=auth_headers)
    assert placed.status_code == 200, placed.text

    url = f"/api/v1/purchase-orders/{order['id']}/receipts"
    payload = {
        "idempotency_key": "pg-concurrent-receipt-001",
        "lines": [
            {
                "purchase_order_line_id": order["lines"][0]["id"],
                "quantity_received": 5,
            }
        ],
    }
    barrier = Barrier(2)

    def synchronize_purchase_order_lock(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("update purchase_orders") and "updated_at=purchase_orders.updated_at" in normalized:
            barrier.wait(timeout=15)

    def post_receipt():
        with TestClient(app) as concurrent_client:
            return concurrent_client.post(url, headers=auth_headers, json=payload)

    event.listen(engine, "before_cursor_execute", synchronize_purchase_order_lock)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _index: post_receipt(), range(2)))
    finally:
        event.remove(engine, "before_cursor_execute", synchronize_purchase_order_lock)

    assert sorted(response.status_code for response in responses) == [200, 201]
    assert sum(
        response.headers.get("Idempotency-Replayed") == "true" for response in responses
    ) == 1
    with SessionLocal() as session:
        assert session.scalar(
            select(func.count(PurchaseOrderReceipt.id)).where(
                PurchaseOrderReceipt.purchase_order_id == order["id"]
            )
        ) == 1
        assert session.scalar(
            select(func.count(InventoryMovement.id)).where(
                InventoryMovement.product_id == product["id"]
            )
        ) == 1
    balance = client.get(
        f"/api/v1/products/{product['id']}/inventory",
        headers=auth_headers,
    )
    assert balance.json()["quantity_on_hand"] == 5
