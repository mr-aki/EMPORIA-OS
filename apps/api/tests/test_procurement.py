from emporia_api.database import SessionLocal
from emporia_api.models import InventoryMovement, PurchaseOrderReceipt


def _create_supplier(client, auth_headers, code="SUP-001"):
    response = client.post(
        "/api/v1/suppliers",
        headers=auth_headers,
        json={
            "code": code,
            "name": "Reliable Supply Co",
            "contact_email": "orders@supplier.example",
            "phone": "+1-555-0100",
            "notes": "Primary test supplier",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_product(client, auth_headers, sku="PROC-001"):
    response = client.post(
        "/api/v1/products",
        headers=auth_headers,
        json={
            "sku": sku,
            "name": "Procurement Test Product",
            "unit_price": "25.0000",
            "currency": "USD",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_order(client, auth_headers, supplier, product, number="PO-2026-001", quantity=10):
    response = client.post(
        "/api/v1/purchase-orders",
        headers=auth_headers,
        json={
            "order_number": number,
            "supplier_id": supplier["id"],
            "currency": "USD",
            "lines": [
                {
                    "product_id": product["id"],
                    "quantity_ordered": quantity,
                    "unit_cost": "8.2500",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_supplier_crud_and_workspace_search(client, auth_headers):
    supplier = _create_supplier(client, auth_headers)
    assert supplier["code"] == "SUP-001"
    assert supplier["status"] == "active"
    assert client.get("/api/v1/suppliers?q=Reliable", headers=auth_headers).json()[0]["id"] == supplier["id"]

    updated = client.patch(
        f"/api/v1/suppliers/{supplier['id']}",
        headers=auth_headers,
        json={"name": "Reliable Supply Group", "phone": None},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Reliable Supply Group"
    assert updated.json()["phone"] is None


def test_purchase_order_receipts_update_inventory_atomically_and_replay(client, auth_headers):
    supplier = _create_supplier(client, auth_headers)
    product = _create_product(client, auth_headers)
    order = _create_order(client, auth_headers, supplier, product)
    order_url = f"/api/v1/purchase-orders/{order['id']}"

    assert order["status"] == "draft"
    assert order["lines"][0]["quantity_received"] == 0
    before_order = client.post(
        f"{order_url}/receipts",
        headers=auth_headers,
        json={
            "idempotency_key": "po-receipt-before-order",
            "lines": [
                {
                    "purchase_order_line_id": order["lines"][0]["id"],
                    "quantity_received": 4,
                }
            ],
        },
    )
    assert before_order.status_code == 409

    placed = client.post(f"{order_url}/order", headers=auth_headers)
    assert placed.status_code == 200, placed.text
    assert placed.json()["status"] == "ordered"

    receipt_payload = {
        "idempotency_key": "po-receipt-partial-001",
        "lines": [
            {
                "purchase_order_line_id": order["lines"][0]["id"],
                "quantity_received": 4,
            }
        ],
    }
    receipt = client.post(f"{order_url}/receipts", headers=auth_headers, json=receipt_payload)
    assert receipt.status_code == 201, receipt.text
    assert receipt.json()["purchase_order_status"] == "partially_received"

    replay = client.post(f"{order_url}/receipts", headers=auth_headers, json=receipt_payload)
    assert replay.status_code == 200, replay.text
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json()["id"] == receipt.json()["id"]

    changed = client.post(
        f"{order_url}/receipts",
        headers=auth_headers,
        json={
            "idempotency_key": "po-receipt-partial-001",
            "lines": [
                {
                    "purchase_order_line_id": order["lines"][0]["id"],
                    "quantity_received": 3,
                }
            ],
        },
    )
    assert changed.status_code == 409

    over_receive = client.post(
        f"{order_url}/receipts",
        headers=auth_headers,
        json={
            "idempotency_key": "po-receipt-over-001",
            "lines": [
                {
                    "purchase_order_line_id": order["lines"][0]["id"],
                    "quantity_received": 7,
                }
            ],
        },
    )
    assert over_receive.status_code == 409

    final_receipt = client.post(
        f"{order_url}/receipts",
        headers=auth_headers,
        json={
            "idempotency_key": "po-receipt-final-001",
            "lines": [
                {
                    "purchase_order_line_id": order["lines"][0]["id"],
                    "quantity_received": 6,
                }
            ],
        },
    )
    assert final_receipt.status_code == 201, final_receipt.text
    assert final_receipt.json()["purchase_order_status"] == "received"

    balance = client.get(f"/api/v1/products/{product['id']}/inventory", headers=auth_headers)
    assert balance.status_code == 200
    assert balance.json()["quantity_on_hand"] == 10
    assert balance.json()["movement_count"] == 2

    order_after = client.get(order_url, headers=auth_headers).json()
    assert order_after["status"] == "received"
    assert order_after["lines"][0]["quantity_received"] == 10

    events = client.get("/api/v1/audit-events", headers=auth_headers).json()
    assert sum(item["action"] == "purchase_order.receipt.posted" for item in events) == 2
    assert sum(item["action"] == "inventory.movement.created" for item in events) == 2


def test_supplier_and_purchase_orders_are_workspace_isolated(client, auth_headers):
    supplier = _create_supplier(client, auth_headers)
    product = _create_product(client, auth_headers)
    order = _create_order(client, auth_headers, supplier, product)

    other = client.post(
        "/api/v1/auth/register",
        json={
            "email": "procurement-other@example.com",
            "password": "AnotherStrongPassword!2026",
            "display_name": "Other Procurement Owner",
            "workspace_name": "Other Procurement Workspace",
        },
    )
    assert other.status_code == 201
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert client.get(f"/api/v1/suppliers/{supplier['id']}", headers=other_headers).status_code == 404
    assert client.get(f"/api/v1/purchase-orders/{order['id']}", headers=other_headers).status_code == 404

    foreign_order = client.post(
        "/api/v1/purchase-orders",
        headers=other_headers,
        json={
            "order_number": "FOREIGN-PO-001",
            "supplier_id": supplier["id"],
            "lines": [
                {
                    "product_id": product["id"],
                    "quantity_ordered": 1,
                    "unit_cost": "1.0000",
                }
            ],
        },
    )
    assert foreign_order.status_code == 404
    foreign_receipt = client.post(
        f"/api/v1/purchase-orders/{order['id']}/receipts",
        headers=other_headers,
        json={
            "idempotency_key": "foreign-po-receipt-001",
            "lines": [
                {
                    "purchase_order_line_id": order["lines"][0]["id"],
                    "quantity_received": 1,
                }
            ],
        },
    )
    assert foreign_receipt.status_code == 404


def test_supplier_code_conflicts_and_archived_suppliers_cannot_receive_orders(client, auth_headers):
    supplier = _create_supplier(client, auth_headers)
    duplicate = client.post(
        "/api/v1/suppliers",
        headers=auth_headers,
        json={"code": "sup-001", "name": "Duplicate Supplier"},
    )
    assert duplicate.status_code == 409

    archived = client.patch(
        f"/api/v1/suppliers/{supplier['id']}",
        headers=auth_headers,
        json={"status": "archived"},
    )
    assert archived.status_code == 200
    product = _create_product(client, auth_headers)
    rejected = client.post(
        "/api/v1/purchase-orders",
        headers=auth_headers,
        json={
            "order_number": "PO-ARCHIVED-SUPPLIER",
            "supplier_id": supplier["id"],
            "lines": [
                {
                    "product_id": product["id"],
                    "quantity_ordered": 1,
                    "unit_cost": "1.0000",
                }
            ],
        },
    )
    assert rejected.status_code == 409


def test_viewers_cannot_create_suppliers_or_receive_purchase_orders(client, auth_headers):
    supplier = _create_supplier(client, auth_headers)
    product = _create_product(client, auth_headers)
    order = _create_order(client, auth_headers, supplier, product)
    placed = client.post(f"/api/v1/purchase-orders/{order['id']}/order", headers=auth_headers)
    assert placed.status_code == 200

    viewer = client.post(
        "/api/v1/auth/register",
        json={
            "email": "procurement-viewer@example.com",
            "password": "AnotherStrongPassword!2026",
            "display_name": "Procurement Viewer",
            "workspace_name": "Temporary Procurement Workspace",
        },
    )
    assert viewer.status_code == 201
    added = client.post(
        "/api/v1/workspaces/members",
        headers=auth_headers,
        json={"email": "procurement-viewer@example.com", "role": "viewer"},
    )
    assert added.status_code == 201, added.text
    workspace_id = client.get("/api/v1/auth/me", headers=auth_headers).json()["workspaces"][0]["id"]
    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "procurement-viewer@example.com",
            "password": "AnotherStrongPassword!2026",
            "workspace_id": workspace_id,
        },
    )
    assert login.status_code == 200, login.text
    viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    denied_supplier = client.post(
        "/api/v1/suppliers",
        headers=viewer_headers,
        json={"name": "Not Allowed Supplier"},
    )
    denied_receipt = client.post(
        f"/api/v1/purchase-orders/{order['id']}/receipts",
        headers=viewer_headers,
        json={
            "idempotency_key": "viewer-po-receipt-001",
            "lines": [
                {
                    "purchase_order_line_id": order["lines"][0]["id"],
                    "quantity_received": 1,
                }
            ],
        },
    )
    assert denied_supplier.status_code == 403
    assert denied_receipt.status_code == 403


def test_procurement_receipt_links_to_immutable_inventory_movement(client, auth_headers):
    supplier = _create_supplier(client, auth_headers)
    product = _create_product(client, auth_headers)
    order = _create_order(client, auth_headers, supplier, product)
    client.post(f"/api/v1/purchase-orders/{order['id']}/order", headers=auth_headers)
    receipt = client.post(
        f"/api/v1/purchase-orders/{order['id']}/receipts",
        headers=auth_headers,
        json={
            "idempotency_key": "po-receipt-link-001",
            "lines": [
                {
                    "purchase_order_line_id": order["lines"][0]["id"],
                    "quantity_received": 2,
                }
            ],
        },
    )
    assert receipt.status_code == 201, receipt.text
    with SessionLocal() as session:
        record = session.get(PurchaseOrderReceipt, receipt.json()["id"])
        assert record is not None
        assert record.request_fingerprint
        movement = session.get(
            InventoryMovement,
            receipt.json()["lines"][0]["inventory_movement_id"],
        )
        assert movement is not None
        assert movement.reference == order["order_number"]
        assert movement.quantity_delta == 2



def test_idempotency_key_cannot_be_reused_for_a_different_purchase_order(client, auth_headers):
    supplier = _create_supplier(client, auth_headers)
    product = _create_product(client, auth_headers)
    first = _create_order(client, auth_headers, supplier, product, number="PO-IDEM-001")
    second = _create_order(client, auth_headers, supplier, product, number="PO-IDEM-002")
    client.post(f"/api/v1/purchase-orders/{first['id']}/order", headers=auth_headers)
    client.post(f"/api/v1/purchase-orders/{second['id']}/order", headers=auth_headers)

    accepted = client.post(
        f"/api/v1/purchase-orders/{first['id']}/receipts",
        headers=auth_headers,
        json={
            "idempotency_key": "po-global-key-001",
            "lines": [
                {
                    "purchase_order_line_id": first["lines"][0]["id"],
                    "quantity_received": 1,
                }
            ],
        },
    )
    assert accepted.status_code == 201, accepted.text

    reused = client.post(
        f"/api/v1/purchase-orders/{second['id']}/receipts",
        headers=auth_headers,
        json={
            "idempotency_key": "po-global-key-001",
            "lines": [
                {
                    "purchase_order_line_id": second["lines"][0]["id"],
                    "quantity_received": 1,
                }
            ],
        },
    )
    assert reused.status_code == 409


def test_purchase_order_cost_totals_and_supplier_spend_are_currency_scoped(
    client, auth_headers
):
    from decimal import Decimal

    supplier = _create_supplier(client, auth_headers)
    product = _create_product(client, auth_headers)
    usd_order = _create_order(
        client, auth_headers, supplier, product, number="PO-COST-USD", quantity=10
    )
    assert Decimal(str(usd_order["ordered_subtotal"])) == Decimal("82.5000")
    assert Decimal(str(usd_order["received_subtotal"])) == Decimal(0))
    assert Decimal(str(usd_order["outstanding_subtotal"])) == Decimal("82.5000")

    spend_url = "/api/v1/procurement/spend"
    assert client.get(spend_url, headers=auth_headers).json() == []

    placed = client.post(
        f"/api/v1/purchase-orders/{usd_order['id']}/order",
        headers=auth_headers,
    )
    assert placed.status_code == 200, placed.text
    usd_receipt = client.post(
        f"/api/v1/purchase-orders/{usd_order['id']}/receipts",
        headers=auth_headers,
        json={
            "idempotency_key": "po-cost-usd-partial",
            "lines": [
                {
                    "purchase_order_line_id": usd_order["lines"][0]["id"],
                    "quantity_received": 4,
                }
            ],
        },
    )
    assert usd_receipt.status_code == 201, usd_receipt.text

    eur_response = client.post(
        "/api/v1/purchase-orders",
        headers=auth_headers,
        json={
            "order_number": "PO-COST-EUR",
            "supplier_id": supplier["id"],
            "currency": "EUR",
            "lines": [
                {
                    "product_id": product["id"],
                    "quantity_ordered": 3,
                    "unit_cost": "1.2345",
                }
            ],
        },
    )
    assert eur_response.status_code == 201, eur_response.text
    eur_order = eur_response.json()
    assert Decimal(str(eur_order["ordered_subtotal"])) == Decimal("3.7035")
    assert client.post(
        f"/api/v1/purchase-orders/{eur_order['id']}/order",
        headers=auth_headers,
    ).status_code == 200
    eur_receipt = client.post(
        f"/api/v1/purchase-orders/{eur_order['id']}/receipts",
        headers=auth_headers,
        json={
            "idempotency_key": "po-cost-eur-partial",
            "lines": [
                {
                    "purchase_order_line_id": eur_order["lines"][0]["id"],
                    "quantity_received": 1,
                }
            ],
        },
    )
    assert eur_receipt.status_code == 201, eur_receipt.text

    report = client.get(spend_url, headers=auth_headers)
    assert report.status_code == 200, report.text
    rows = {row["currency"]: row for row in report.json()}
    assert set(rows) == {"EUR", "USD"}
    assert rows["USD"]["purchase_order_count"] == 1
    assert Decimal(str(rows["USD"]["ordered_subtotal"])) == Decimal("82.5000")
    assert Decimal(str(rows["USD"]["received_subtotal"])) == Decimal("33.0000")
    assert Decimal(str(rows["USD"]["outstanding_subtotal"])) == Decimal("49.5000")
    assert rows["EUR"]["purchase_order_count"] == 1
    assert Decimal(str(rows["EUR"]["ordered_subtotal"])) == Decimal("3.7035")
    assert Decimal(str(rows["EUR"]["received_subtotal"])) == Decimal("1.2345")
    assert Decimal(str(rows["EUR"]["outstanding_subtotal"])) == Decimal("2.4690")

    filtered = client.get(
        f"{spend_url}?supplier_id={supplier['id']}",
        headers=auth_headers,
    )
    assert len(filtered.json()) == 2

    other = client.post(
        "/api/v1/auth/register",
        json={
            "email": "procurement-spend-other@example.com",
            "password": "AnotherStrongPassword!2026",
            "display_name": "Other Spend Owner",
            "workspace_name": "Other Spend Workspace",
        },
    )
    assert other.status_code == 201
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert client.get(spend_url, headers=other_headers).json() == []
