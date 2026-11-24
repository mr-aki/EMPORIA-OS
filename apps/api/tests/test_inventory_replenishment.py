from decimal import Decimal

from emporia_api.database import SessionLocal
from emporia_api.models import AuditEvent, InventoryReorderPolicy


def _create_product(client, auth_headers, sku="REPLENISH-001"):
    response = client.post(
        "/api/v1/products",
        headers=auth_headers,
        json={
            "sku": sku,
            "name": "Replenishment Test Product",
            "unit_price": "25.0000",
            "currency": "USD",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _post_movement(client, auth_headers, product_id, movement_type, quantity, key):
    response = client.post(
        f"/api/v1/products/{product_id}/inventory/movements",
        headers=auth_headers,
        json={
            "movement_type": movement_type,
            "quantity_delta": quantity,
            "reason": "Replenishment planning test",
            "idempotency_key": key,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_replenishment_uses_stock_sales_velocity_and_open_purchase_orders(
    client, auth_headers
):
    product = _create_product(client, auth_headers)
    policy_response = client.put(
        f"/api/v1/products/{product['id']}/reorder-policy",
        headers=auth_headers,
        json={"reorder_point": 5, "target_stock": 12, "lead_time_days": 14},
    )
    assert policy_response.status_code == 200, policy_response.text
    policy_id = policy_response.json()["id"]

    _post_movement(
        client, auth_headers, product["id"], "receipt", 4, "replenishment-stock-in"
    )
    _post_movement(
        client, auth_headers, product["id"], "sale", -3, "replenishment-stock-sale"
    )

    report = client.get(
        "/api/v1/inventory/replenishment?lookback_days=30",
        headers=auth_headers,
    )
    assert report.status_code == 200, report.text
    item = report.json()["items"][0]
    assert item["quantity_on_hand"] == 1
    assert item["quantity_incoming"] == 0
    assert item["projected_available"] == 1
    assert item["units_sold_in_period"] == 3
    assert Decimal(str(item["average_daily_sales"])) == Decimal("0.1000")
    assert item["estimated_lead_time_demand"] == 2
    assert Decimal(str(item["days_of_cover"])) == Decimal("10.00")
    assert item["should_reorder"] is True
    assert item["suggested_order_quantity"] == 11

    supplier = client.post(
        "/api/v1/suppliers",
        headers=auth_headers,
        json={"code": "REPLENISH-SUP", "name": "Replenishment Supplier"},
    )
    assert supplier.status_code == 201, supplier.text
    order = client.post(
        "/api/v1/purchase-orders",
        headers=auth_headers,
        json={
            "order_number": "REPLENISH-PO-001",
            "supplier_id": supplier.json()["id"],
            "currency": "USD",
            "lines": [
                {
                    "product_id": product["id"],
                    "quantity_ordered": 2,
                    "unit_cost": "8.2500",
                }
            ],
        },
    )
    assert order.status_code == 201, order.text
    placed = client.post(
        f"/api/v1/purchase-orders/{order.json()['id']}/order",
        headers=auth_headers,
    )
    assert placed.status_code == 200, placed.text

    with_open_order = client.get(
        "/api/v1/inventory/replenishment?lookback_days=30&reorder_only=true",
        headers=auth_headers,
    )
    assert with_open_order.status_code == 200, with_open_order.text
    item = with_open_order.json()["items"][0]
    assert item["quantity_on_hand"] == 1
    assert item["quantity_incoming"] == 2
    assert item["projected_available"] == 3
    assert item["suggested_order_quantity"] == 9

    receipt = client.post(
        f"/api/v1/purchase-orders/{order.json()['id']}/receipts",
        headers=auth_headers,
        json={
            "idempotency_key": "replenishment-receipt-001",
            "lines": [
                {
                    "purchase_order_line_id": order.json()["lines"][0]["id"],
                    "quantity_received": 2,
                }
            ],
        },
    )
    assert receipt.status_code == 201, receipt.text

    after_receipt = client.get(
        "/api/v1/inventory/replenishment?lookback_days=30",
        headers=auth_headers,
    )
    item = after_receipt.json()["items"][0]
    assert item["quantity_on_hand"] == 3
    assert item["quantity_incoming"] == 0
    assert item["projected_available"] == 3
    assert item["suggested_order_quantity"] == 9

    updated = client.put(
        f"/api/v1/products/{product['id']}/reorder-policy",
        headers=auth_headers,
        json={"reorder_point": 6, "target_stock": 15, "lead_time_days": 21},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["id"] == policy_id
    assert updated.json()["target_stock"] == 15
    assert updated.json()["lead_time_days"] == 21

    read_back = client.get(
        f"/api/v1/products/{product['id']}/reorder-policy",
        headers=auth_headers,
    )
    assert read_back.status_code == 200
    assert read_back.json()["id"] == policy_id


def test_reorder_policy_validation_and_report_bounds(client, auth_headers):
    product = _create_product(client, auth_headers, sku="REPLENISH-VALIDATION")
    invalid = client.put(
        f"/api/v1/products/{product['id']}/reorder-policy",
        headers=auth_headers,
        json={"reorder_point": 10, "target_stock": 10, "lead_time_days": 14},
    )
    assert invalid.status_code == 422

    invalid_lead_time = client.put(
        f"/api/v1/products/{product['id']}/reorder-policy",
        headers=auth_headers,
        json={"reorder_point": 2, "target_stock": 10, "lead_time_days": 366},
    )
    assert invalid_lead_time.status_code == 422

    invalid_lookback = client.get(
        "/api/v1/inventory/replenishment?lookback_days=3",
        headers=auth_headers,
    )
    assert invalid_lookback.status_code == 422


def test_reorder_policy_is_workspace_scoped_and_not_visible_to_other_workspaces(
    client, auth_headers
):
    product = _create_product(client, auth_headers, sku="REPLENISH-PRIVATE")
    configured = client.put(
        f"/api/v1/products/{product['id']}/reorder-policy",
        headers=auth_headers,
        json={"reorder_point": 3, "target_stock": 9, "lead_time_days": 7},
    )
    assert configured.status_code == 200, configured.text

    other = client.post(
        "/api/v1/auth/register",
        json={
            "email": "replenishment-other@example.com",
            "password": "AnotherStrongPassword!2026",
            "display_name": "Other Replenishment Owner",
            "workspace_name": "Other Replenishment Workspace",
        },
    )
    assert other.status_code == 201
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    assert client.get(
        f"/api/v1/products/{product['id']}/reorder-policy",
        headers=other_headers,
    ).status_code == 404
    report = client.get(
        "/api/v1/inventory/replenishment",
        headers=other_headers,
    )
    assert report.status_code == 200
    assert report.json()["items"] == []
    assert report.json()["configured_product_count"] == 0


def test_viewers_cannot_change_reorder_policies(client, auth_headers):
    product = _create_product(client, auth_headers, sku="REPLENISH-VIEWER")
    viewer = client.post(
        "/api/v1/auth/register",
        json={
            "email": "replenishment-viewer@example.com",
            "password": "AnotherStrongPassword!2026",
            "display_name": "Replenishment Viewer",
            "workspace_name": "Temporary Replenishment Workspace",
        },
    )
    assert viewer.status_code == 201
    added = client.post(
        "/api/v1/workspaces/members",
        headers=auth_headers,
        json={"email": "replenishment-viewer@example.com", "role": "viewer"},
    )
    assert added.status_code == 201, added.text
    workspace_id = client.get(
        "/api/v1/auth/me", headers=auth_headers
    ).json()["workspaces"][0]["id"]
    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "replenishment-viewer@example.com",
            "password": "AnotherStrongPassword!2026",
            "workspace_id": workspace_id,
        },
    )
    assert login.status_code == 200, login.text
    viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    denied = client.put(
        f"/api/v1/products/{product['id']}/reorder-policy",
        headers=viewer_headers,
        json={"reorder_point": 4, "target_stock": 10, "lead_time_days": 14},
    )
    assert denied.status_code == 403

    with SessionLocal() as session:
        policies = session.query(InventoryReorderPolicy).filter_by(
            product_id=product["id"]
        ).count()
        assert policies == 0
        assert session.query(AuditEvent).filter_by(
            action="inventory.reorder_policy.created"
        ).count() == 0
