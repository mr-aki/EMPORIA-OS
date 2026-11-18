from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from emporia_api.database import SessionLocal, engine
from emporia_api.main import app
from emporia_api.models import InventoryMovement


pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="Inventory row-lock integration tests require PostgreSQL",
)


def _create_product(client, auth_headers, sku):
    response = client.post(
        "/api/v1/products",
        headers=auth_headers,
        json={
            "sku": sku,
            "name": "PostgreSQL concurrency product",
            "unit_price": "10.0000",
            "currency": "USD",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _post_concurrently(url, auth_headers, payloads):
    lock_barrier = Barrier(len(payloads))

    def synchronize_product_updates(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("update products"):
            lock_barrier.wait(timeout=15)

    def post(payload):
        with TestClient(app) as concurrent_client:
            return concurrent_client.post(url, headers=auth_headers, json=payload)

    event.listen(engine, "before_cursor_execute", synchronize_product_updates)
    try:
        with ThreadPoolExecutor(max_workers=len(payloads)) as executor:
            futures = [executor.submit(post, payload) for payload in payloads]
            return [future.result(timeout=30) for future in futures]
    finally:
        event.remove(engine, "before_cursor_execute", synchronize_product_updates)


def _movement(kind, delta, key):
    return {
        "movement_type": kind,
        "quantity_delta": delta,
        "reason": "PostgreSQL concurrent inventory regression",
        "idempotency_key": key,
    }


def test_concurrent_sales_cannot_oversell_a_product(client, auth_headers):
    product = _create_product(client, auth_headers, "PG-OVERSALE-001")
    balance_url = f"/api/v1/products/{product['id']}/inventory"
    movements_url = f"{balance_url}/movements"

    receipt = client.post(
        movements_url,
        headers=auth_headers,
        json=_movement("receipt", 5, "pg-initial-stock-001"),
    )
    assert receipt.status_code == 201, receipt.text

    responses = _post_concurrently(
        movements_url,
        auth_headers,
        [
            _movement("sale", -4, "pg-concurrent-sale-001"),
            _movement("sale", -4, "pg-concurrent-sale-002"),
        ],
    )

    assert sorted(response.status_code for response in responses) == [201, 409]
    successful = next(response for response in responses if response.status_code == 201)
    rejected = next(response for response in responses if response.status_code == 409)
    assert successful.json()["quantity_after"] == 1
    assert rejected.json()["detail"] == "Insufficient stock for this inventory movement"

    balance = client.get(balance_url, headers=auth_headers)
    assert balance.status_code == 200
    assert balance.json()["quantity_on_hand"] == 1
    assert balance.json()["movement_count"] == 2

    with SessionLocal() as session:
        sale_count = session.scalar(
            select(func.count(InventoryMovement.id)).where(
                InventoryMovement.product_id == product["id"],
                InventoryMovement.movement_type == "sale",
            )
        )
    assert sale_count == 1


def test_concurrent_duplicate_idempotency_key_creates_one_movement(client, auth_headers):
    product = _create_product(client, auth_headers, "PG-IDEMPOTENCY-001")
    balance_url = f"/api/v1/products/{product['id']}/inventory"
    movements_url = f"{balance_url}/movements"
    payload = _movement("receipt", 3, "pg-concurrent-receipt-001")

    responses = _post_concurrently(
        movements_url,
        auth_headers,
        [payload, payload],
    )

    assert sorted(response.status_code for response in responses) == [200, 201]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    replayed = [response for response in responses if response.status_code == 200]
    assert len(replayed) == 1
    assert replayed[0].headers["Idempotency-Replayed"] == "true"

    balance = client.get(balance_url, headers=auth_headers)
    assert balance.status_code == 200
    assert balance.json()["quantity_on_hand"] == 3
    assert balance.json()["movement_count"] == 1
