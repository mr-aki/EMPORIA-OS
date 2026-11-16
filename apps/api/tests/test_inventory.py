
def _create_product(client, auth_headers, sku="STOCK-001"):
    response = client.post(
        "/api/v1/products",
        headers=auth_headers,
        json={
            "sku": sku,
            "name": "Inventory Test Product",
            "description": "Discrete stock item",
            "unit_price": "12.5000",
            "currency": "USD",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _movement(
    movement_type,
    quantity_delta,
    idempotency_key,
    **overrides,
):
    payload = {
        "movement_type": movement_type,
        "quantity_delta": quantity_delta,
        "reason": "Inventory operation",
        "idempotency_key": idempotency_key,
    }
    payload.update(overrides)
    return payload


def test_inventory_ledger_receipts_sales_balance_history_and_audit(client, auth_headers):
    product = _create_product(client, auth_headers)
    url = f"/api/v1/products/{product['id']}/inventory"

    empty = client.get(url, headers=auth_headers)
    assert empty.status_code == 200
    assert empty.json()["quantity_on_hand"] == 0
    assert empty.json()["movement_count"] == 0
    assert empty.json()["last_movement_at"] is None

    receipt = client.post(
        f"{url}/movements",
        headers=auth_headers,
        json=_movement("receipt", 12, "receipt-stock-001", reference="PO-100"),
    )
    assert receipt.status_code == 201, receipt.text
    assert receipt.json()["quantity_after"] == 12

    sale = client.post(
        f"{url}/movements",
        headers=auth_headers,
        json=_movement("sale", -5, "sale-stock-001", reference="ORDER-200"),
    )
    assert sale.status_code == 201, sale.text
    assert sale.json()["quantity_after"] == 7

    balance = client.get(url, headers=auth_headers).json()
    assert balance["sku"] == "STOCK-001"
    assert balance["quantity_on_hand"] == 7
    assert balance["movement_count"] == 2
    assert balance["last_movement_at"] is not None

    history = client.get(f"{url}/movements?limit=10", headers=auth_headers)
    assert history.status_code == 200
    assert [item["movement_type"] for item in history.json()] == ["sale", "receipt"]
    assert [item["quantity_after"] for item in history.json()] == [7, 12]

    events = client.get("/api/v1/audit-events", headers=auth_headers).json()
    assert sum(event["action"] == "inventory.movement.created" for event in events) == 2


def test_inventory_idempotency_replays_once_and_rejects_key_reuse(client, auth_headers):
    product = _create_product(client, auth_headers)
    url = f"/api/v1/products/{product['id']}/inventory/movements"
    payload = _movement("receipt", 8, "receipt-once-001")

    first = client.post(url, headers=auth_headers, json=payload)
    replay = client.post(url, headers=auth_headers, json=payload)
    assert first.status_code == 201, first.text
    assert replay.status_code == 200, replay.text
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json()["id"] == first.json()["id"]

    changed = client.post(
        url,
        headers=auth_headers,
        json=_movement("receipt", 9, "receipt-once-001"),
    )
    assert changed.status_code == 409
    balance = client.get(
        f"/api/v1/products/{product['id']}/inventory",
        headers=auth_headers,
    ).json()
    assert balance["quantity_on_hand"] == 8
    assert balance["movement_count"] == 1


def test_inventory_rejects_invalid_directions_zero_and_negative_stock(client, auth_headers):
    product = _create_product(client, auth_headers)
    url = f"/api/v1/products/{product['id']}/inventory/movements"

    zero = client.post(
        url,
        headers=auth_headers,
        json=_movement("adjustment", 0, "zero-stock-001"),
    )
    wrong_direction = client.post(
        url,
        headers=auth_headers,
        json=_movement("receipt", -1, "wrong-stock-001"),
    )
    insufficient = client.post(
        url,
        headers=auth_headers,
        json=_movement("sale", -2, "sale-stock-002"),
    )
    assert zero.status_code == 422
    assert wrong_direction.status_code == 422
    assert insufficient.status_code == 409

    balance = client.get(
        f"/api/v1/products/{product['id']}/inventory",
        headers=auth_headers,
    ).json()
    assert balance["quantity_on_hand"] == 0
    assert balance["movement_count"] == 0


def test_inventory_is_workspace_scoped_and_viewers_are_read_only(client, auth_headers):
    product = _create_product(client, auth_headers)
    balance_url = f"/api/v1/products/{product['id']}/inventory"
    movements_url = f"{balance_url}/movements"

    other = client.post(
        "/api/v1/auth/register",
        json={
            "email": "inventory-other@example.com",
            "password": "AnotherStrongPassword!2026",
            "display_name": "Other Inventory Owner",
            "workspace_name": "Other Inventory Workspace",
        },
    )
    assert other.status_code == 201
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert client.get(balance_url, headers=other_headers).status_code == 404
    assert client.get(movements_url, headers=other_headers).status_code == 404

    viewer = client.post(
        "/api/v1/auth/register",
        json={
            "email": "inventory-viewer@example.com",
            "password": "AnotherStrongPassword!2026",
            "display_name": "Inventory Viewer",
            "workspace_name": "Temporary Inventory Workspace",
        },
    )
    assert viewer.status_code == 201
    added = client.post(
        "/api/v1/workspaces/members",
        headers=auth_headers,
        json={"email": "inventory-viewer@example.com", "role": "viewer"},
    )
    assert added.status_code == 201, added.text
    workspace_id = client.get("/api/v1/auth/me", headers=auth_headers).json()["workspaces"][0]["id"]
    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "inventory-viewer@example.com",
            "password": "AnotherStrongPassword!2026",
            "workspace_id": workspace_id,
        },
    )
    assert login.status_code == 200, login.text
    viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert client.get(balance_url, headers=viewer_headers).status_code == 200
    denied = client.post(
        f"{balance_url}/movements",
        headers=viewer_headers,
        json=_movement("receipt", 4, "viewer-stock-001"),
    )
    assert denied.status_code == 403
