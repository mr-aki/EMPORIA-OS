from decimal import Decimal

from emporia_api.auth import create_access_token, hash_password
from emporia_api.database import SessionLocal
from emporia_api.models import User, WorkspaceMembership


def _workspace_id(client, headers):
    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["workspaces"][0]["id"]


def _member_headers(workspace_id, role, email):
    with SessionLocal() as session:
        user = User(
            email=email,
            display_name=f"Catalog {role}",
            password_hash=hash_password("AnotherStrongPassword!2026"),
        )
        session.add(user)
        session.flush()
        session.add(
            WorkspaceMembership(
                workspace_id=workspace_id,
                user_id=user.id,
                role=role,
            )
        )
        session.commit()
        user_id = user.id
    return {"Authorization": f"Bearer {create_access_token(user_id, workspace_id)}"}


def _payload(**overrides):
    payload = {
        "sku": "SKU-001",
        "name": "Everyday Water Bottle",
        "description": "Reusable stainless steel bottle",
        "vendor": "Northwind Supply",
        "product_type": "Drinkware",
        "status": "active",
        "price_amount": "24.9900",
        "cost_amount": "8.5000",
        "currency": "usd",
    }
    payload.update(overrides)
    return payload


def test_product_catalog_create_search_update_delete_and_audit(client, auth_headers):
    assert client.get("/api/v1/products").status_code == 401

    created = client.post(
        "/api/v1/products",
        headers=auth_headers,
        json=_payload(sku=" sku-001 ", name="  Everyday Water Bottle  "),
    )
    assert created.status_code == 201, created.text
    product = created.json()
    assert product["sku"] == "SKU-001"
    assert product["name"] == "Everyday Water Bottle"
    assert product["currency"] == "USD"
    assert Decimal(product["price_amount"]) == Decimal("24.9900")
    assert Decimal(product["cost_amount"]) == Decimal("8.5000")
    product_id = product["id"]

    listed = client.get(
        "/api/v1/products?status=active&search=sku-001",
        headers=auth_headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [product_id]

    fetched = client.get(f"/api/v1/products/{product_id}", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json()["sku"] == "SKU-001"

    updated = client.patch(
        f"/api/v1/products/{product_id}",
        headers=auth_headers,
        json={
            "name": "Everyday Insulated Bottle",
            "price_amount": "29.5000",
            "cost_amount": None,
            "status": "draft",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Everyday Insulated Bottle"
    assert Decimal(updated.json()["price_amount"]) == Decimal("29.5000")
    assert updated.json()["cost_amount"] is None
    assert updated.json()["status"] == "draft"

    events = client.get("/api/v1/audit-events", headers=auth_headers)
    assert events.status_code == 200
    actions = [event["action"] for event in events.json()]
    assert "product.created" in actions
    assert "product.updated" in actions

    deleted = client.delete(f"/api/v1/products/{product_id}", headers=auth_headers)
    assert deleted.status_code == 204
    missing = client.get(f"/api/v1/products/{product_id}", headers=auth_headers)
    assert missing.status_code == 404

    after_delete = client.get("/api/v1/audit-events", headers=auth_headers)
    assert "product.deleted" in [event["action"] for event in after_delete.json()]


def test_product_sku_is_normalized_and_unique_per_workspace(client, auth_headers):
    first = client.post(
        "/api/v1/products",
        headers=auth_headers,
        json=_payload(sku="ab-100"),
    )
    assert first.status_code == 201, first.text
    conflict = client.post(
        "/api/v1/products",
        headers=auth_headers,
        json=_payload(sku="AB-100", name="Duplicate SKU"),
    )
    assert conflict.status_code == 409
    assert "SKU already exists" in conflict.json()["detail"]


def test_product_catalog_is_workspace_isolated(client, auth_headers):
    created = client.post(
        "/api/v1/products",
        headers=auth_headers,
        json=_payload(),
    )
    assert created.status_code == 201, created.text
    product_id = created.json()["id"]

    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": "catalog-other-workspace@example.com",
            "password": "AnotherStrongPassword!2026",
            "display_name": "Other Workspace Owner",
            "workspace_name": "Separate Catalog Workspace",
        },
    )
    assert registration.status_code == 201, registration.text
    other_headers = {
        "Authorization": f"Bearer {registration.json()['access_token']}"
    }

    assert client.get("/api/v1/products", headers=other_headers).json() == []
    assert client.get(
        f"/api/v1/products/{product_id}", headers=other_headers
    ).status_code == 404
    assert client.patch(
        f"/api/v1/products/{product_id}",
        headers=other_headers,
        json={"name": "Unauthorized edit"},
    ).status_code == 404
    assert client.delete(
        f"/api/v1/products/{product_id}", headers=other_headers
    ).status_code == 404


def test_viewers_can_read_but_cannot_change_products(client, auth_headers):
    created = client.post(
        "/api/v1/products",
        headers=auth_headers,
        json=_payload(),
    )
    assert created.status_code == 201, created.text
    product_id = created.json()["id"]
    viewer_headers = _member_headers(
        _workspace_id(client, auth_headers),
        "viewer",
        "catalog-viewer@example.com",
    )

    listed = client.get("/api/v1/products", headers=viewer_headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    denied_create = client.post(
        "/api/v1/products",
        headers=viewer_headers,
        json=_payload(sku="SKU-002"),
    )
    assert denied_create.status_code == 403
    denied_update = client.patch(
        f"/api/v1/products/{product_id}",
        headers=viewer_headers,
        json={"name": "Viewer cannot edit"},
    )
    assert denied_update.status_code == 403
    denied_delete = client.delete(
        f"/api/v1/products/{product_id}",
        headers=viewer_headers,
    )
    assert denied_delete.status_code == 403


def test_product_validation_rejects_bad_sku_money_and_empty_patch(client, auth_headers):
    invalid_sku = client.post(
        "/api/v1/products",
        headers=auth_headers,
        json=_payload(sku="SKU 001"),
    )
    assert invalid_sku.status_code == 422

    negative_price = client.post(
        "/api/v1/products",
        headers=auth_headers,
        json=_payload(sku="SKU-NEG", price_amount="-1"),
    )
    assert negative_price.status_code == 422

    invalid_currency = client.post(
        "/api/v1/products",
        headers=auth_headers,
        json=_payload(sku="SKU-CUR", currency="US"),
    )
    assert invalid_currency.status_code == 422

    invalid_precision = client.post(
        "/api/v1/products",
        headers=auth_headers,
        json=_payload(sku="SKU-PREC", price_amount="1.12345"),
    )
    assert invalid_precision.status_code == 422

    created = client.post(
        "/api/v1/products",
        headers=auth_headers,
        json=_payload(sku="SKU-PATCH"),
    )
    assert created.status_code == 201
    empty_patch = client.patch(
        f"/api/v1/products/{created.json()['id']}",
        headers=auth_headers,
        json={},
    )
    assert empty_patch.status_code == 422


def test_product_list_pagination_and_status_filter(client, auth_headers):
    for sku, status_value in [
        ("PAGE-001", "draft"),
        ("PAGE-002", "active"),
        ("PAGE-003", "archived"),
    ]:
        response = client.post(
            "/api/v1/products",
            headers=auth_headers,
            json=_payload(sku=sku, status=status_value),
        )
        assert response.status_code == 201, response.text

    active = client.get(
        "/api/v1/products?status=active&limit=1&offset=0",
        headers=auth_headers,
    )
    assert active.status_code == 200
    assert len(active.json()) == 1
    assert active.json()[0]["sku"] == "PAGE-002"

    second_page = client.get(
        "/api/v1/products?limit=1&offset=1",
        headers=auth_headers,
    )
    assert second_page.status_code == 200
    assert len(second_page.json()) == 1
