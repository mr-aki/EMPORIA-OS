from decimal import Decimal

from emporia_api.database import SessionLocal
from emporia_api.models import InventoryCostAllocation, InventoryCostLayer


def _create_product(client, auth_headers, sku="FIFO-001"):
    response = client.post(
        "/api/v1/products",
        headers=auth_headers,
        json={
            "sku": sku,
            "name": "FIFO Test Product",
            "unit_price": "20.0000",
            "currency": "USD",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_supplier(client, auth_headers):
    response = client.post(
        "/api/v1/suppliers",
        headers=auth_headers,
        json={"code": "FIFO-SUP", "name": "FIFO Supplier"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _receive_purchase_order(
    client,
    auth_headers,
    supplier_id,
    product_id,
    *,
    order_number,
    quantity,
    unit_cost,
    currency="USD",
):
    order_response = client.post(
        "/api/v1/purchase-orders",
        headers=auth_headers,
        json={
            "order_number": order_number,
            "supplier_id": supplier_id,
            "currency": currency,
            "lines": [
                {
                    "product_id": product_id,
                    "quantity_ordered": quantity,
                    "unit_cost": unit_cost,
                }
            ],
        },
    )
    assert order_response.status_code == 201, order_response.text
    order = order_response.json()
    placed = client.post(
        f"/api/v1/purchase-orders/{order['id']}/order",
        headers=auth_headers,
    )
    assert placed.status_code == 200, placed.text
    receipt = client.post(
        f"/api/v1/purchase-orders/{order['id']}/receipts",
        headers=auth_headers,
        json={
            "idempotency_key": f"fifo-receipt-{order_number}",
            "lines": [
                {
                    "purchase_order_line_id": order["lines"][0]["id"],
                    "quantity_received": quantity,
                }
            ],
        },
    )
    assert receipt.status_code == 201, receipt.text
    return order, receipt.json()


def _post_movement(client, auth_headers, product_id, movement_type, delta, key):
    return client.post(
        f"/api/v1/products/{product_id}/inventory/movements",
        headers=auth_headers,
        json={
            "movement_type": movement_type,
            "quantity_delta": delta,
            "reason": "FIFO costing regression",
            "idempotency_key": key,
        },
    )


def test_fifo_sale_consumes_oldest_purchase_receipt_layers_and_replays_once(
    client, auth_headers
):
    supplier = _create_supplier(client, auth_headers)
    product = _create_product(client, auth_headers)
    _receive_purchase_order(
        client, auth_headers, supplier["id"], product["id"],
        order_number="FIFO-PO-001", quantity=5, unit_cost="2.0000",
    )
    _receive_purchase_order(
        client, auth_headers, supplier["id"], product["id"],
        order_number="FIFO-PO-002", quantity=5, unit_cost="3.0000",
    )

    sale = _post_movement(client, auth_headers, product["id"], "sale", -6, "fifo-sale-001")
    assert sale.status_code == 201, sale.text
    replay = _post_movement(client, auth_headers, product["id"], "sale", -6, "fifo-sale-001")
    assert replay.status_code == 200, replay.text
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json()["id"] == sale.json()["id"]

    cogs = client.get(
        f"/api/v1/products/{product['id']}/inventory/cost-of-goods-sold",
        headers=auth_headers,
    )
    assert cogs.status_code == 200, cogs.text
    cogs_data = cogs.json()
    assert cogs_data["allocated_quantity_sold"] == 6
    assert cogs_data["costed_quantity_sold"] == 6
    assert cogs_data["uncosted_quantity_sold"] == 0
    assert cogs_data["costing_method"] == "fifo"
    assert len(cogs_data["by_currency"]) == 1
    assert cogs_data["by_currency"][0]["currency"] == "USD"
    assert cogs_data["by_currency"][0]["quantity"] == 6
    assert Decimal(str(cogs_data["by_currency"][0]["total_cost"])) == Decimal("13.00000000")

    valuation = client.get(
        f"/api/v1/products/{product['id']}/inventory/valuation",
        headers=auth_headers,
    )
    assert valuation.status_code == 200, valuation.text
    valuation_data = valuation.json()
    assert valuation_data["quantity_on_hand"] == 4
    assert valuation_data["costed_quantity"] == 4
    assert valuation_data["uncosted_quantity"] == 0
    assert valuation_data["by_currency"][0]["currency"] == "USD"
    assert valuation_data["by_currency"][0]["quantity"] == 4
    assert Decimal(str(valuation_data["by_currency"][0]["total_cost"])) == Decimal("12.00000000")

    with SessionLocal() as session:
        allocations = sorted(
            session.query(InventoryCostAllocation)
            .filter(InventoryCostAllocation.inventory_movement_id == sale.json()["id"]),
            key=lambda row: row.unit_cost,
        )
        layers = list(
            session.query(InventoryCostLayer)
            .filter(InventoryCostLayer.product_id == product["id"])
            .order_by(InventoryCostLayer.created_at.asc(), InventoryCostLayer.id.asc())
        )
    assert [(row.quantity_allocated, row.unit_cost) for row in allocations] == [
        (5, Decimal("2.0000")),
        (1, Decimal("3.0000")),
    ]
    assert [row.quantity_remaining for row in layers] == [0, 4]


def test_unknown_opening_and_manual_receipts_are_reported_as_uncosted(client, auth_headers):
    supplier = _create_supplier(client, auth_headers)
    product = _create_product(client, auth_headers, sku="FIFO-UNCOSTED-001")

    manual_receipt = _post_movement(
        client, auth_headers, product["id"], "receipt", 2, "fifo-manual-receipt-001"
    )
    assert manual_receipt.status_code == 201, manual_receipt.text

    _receive_purchase_order(
        client, auth_headers, supplier["id"], product["id"],
        order_number="FIFO-PO-003", quantity=3, unit_cost="4.5000",
    )
    sale = _post_movement(
        client, auth_headers, product["id"], "sale", -3, "fifo-sale-uncosted-001"
    )
    assert sale.status_code == 201, sale.text

    cogs = client.get(
        f"/api/v1/products/{product['id']}/inventory/cost-of-goods-sold",
        headers=auth_headers,
    ).json()
    assert cogs["allocated_quantity_sold"] == 3
    assert cogs["costed_quantity_sold"] == 1
    assert cogs["uncosted_quantity_sold"] == 2
    assert cogs["by_currency"][0]["currency"] == "USD"
    assert cogs["by_currency"][0]["quantity"] == 1
    assert Decimal(str(cogs["by_currency"][0]["total_cost"])) == Decimal("4.50000000")

    valuation = client.get(
        f"/api/v1/products/{product['id']}/inventory/valuation",
        headers=auth_headers,
    ).json()
    assert valuation["quantity_on_hand"] == 2
    assert valuation["costed_quantity"] == 2
    assert valuation["uncosted_quantity"] == 0
    assert Decimal(str(valuation["by_currency"][0]["total_cost"])) == Decimal("9.00000000")


def test_fifo_valuation_and_cogs_are_workspace_scoped(client, auth_headers):
    product = _create_product(client, auth_headers, sku="FIFO-PRIVATE-001")
    for endpoint in ("valuation", "cost-of-goods-sold"):
        url = f"/api/v1/products/{product['id']}/inventory/{endpoint}"
        own = client.get(url, headers=auth_headers)
        assert own.status_code == 200

    other = client.post(
        "/api/v1/auth/register",
        json={
            "email": "fifo-other@example.com",
            "password": "AnotherStrongPassword!2026",
            "display_name": "Other FIFO Owner",
            "workspace_name": "Other FIFO Workspace",
        },
    )
    assert other.status_code == 201
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    for endpoint in ("valuation", "cost-of-goods-sold"):
        url = f"/api/v1/products/{product['id']}/inventory/{endpoint}"
        assert client.get(url, headers=other_headers).status_code == 404


def _post_return(client, auth_headers, product_id, sale_id, quantity, key):
    return client.post(
        f"/api/v1/products/{product_id}/inventory/sales/{sale_id}/returns",
        headers=auth_headers,
        json={
            "quantity_returned": quantity,
            "reason": "Customer return",
            "idempotency_key": key,
        },
    )


def test_partial_linked_returns_restore_original_fifo_cost_and_reverse_cogs(
    client, auth_headers
):
    supplier = _create_supplier(client, auth_headers)
    product = _create_product(client, auth_headers, sku="FIFO-RETURN-001")
    _receive_purchase_order(
        client, auth_headers, supplier["id"], product["id"],
        order_number="FIFO-RETURN-PO-001", quantity=5, unit_cost="2.0000",
    )
    _receive_purchase_order(
        client, auth_headers, supplier["id"], product["id"],
        order_number="FIFO-RETURN-PO-002", quantity=5, unit_cost="3.0000",
    )
    sale = _post_movement(
        client, auth_headers, product["id"], "sale", -6, "fifo-return-sale-001"
    )
    assert sale.status_code == 201, sale.text

    first_return = _post_return(
        client, auth_headers, product["id"], sale.json()["id"], 3, "fifo-return-001"
    )
    assert first_return.status_code == 201, first_return.text
    assert first_return.json()["source_sale_movement_id"] == sale.json()["id"]
    replay = _post_return(
        client, auth_headers, product["id"], sale.json()["id"], 3, "fifo-return-001"
    )
    assert replay.status_code == 200, replay.text
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json()["return_movement"]["id"] == first_return.json()["return_movement"]["id"]

    valuation = client.get(
        f"/api/v1/products/{product['id']}/inventory/valuation",
        headers=auth_headers,
    ).json()
    assert valuation["quantity_on_hand"] == 7
    assert valuation["costed_quantity"] == 7
    assert valuation["uncosted_quantity"] == 0
    assert Decimal(str(valuation["by_currency"][0]["total_cost"])) == Decimal("18.00000000")

    cogs = client.get(
        f"/api/v1/products/{product['id']}/inventory/cost-of-goods-sold",
        headers=auth_headers,
    ).json()
    assert cogs["allocated_quantity_sold"] == 6
    assert cogs["allocated_quantity_returned"] == 3
    assert cogs["costed_quantity_returned"] == 3
    assert cogs["uncosted_quantity_returned"] == 0
    assert cogs["net_quantity_sold"] == 3
    assert Decimal(str(cogs["by_currency_returns"][0]["total_cost"])) == Decimal("6.00000000")
    assert Decimal(str(cogs["by_currency_net"][0]["total_cost"])) == Decimal("7.00000000")

    second_return = _post_return(
        client, auth_headers, product["id"], sale.json()["id"], 3, "fifo-return-002"
    )
    assert second_return.status_code == 201, second_return.text
    over_return = _post_return(
        client, auth_headers, product["id"], sale.json()["id"], 1, "fifo-return-over-001"
    )
    assert over_return.status_code == 409

    changed_replay = client.post(
        f"/api/v1/products/{product['id']}/inventory/sales/{sale.json()['id']}/returns",
        headers=auth_headers,
        json={
            "quantity_returned": 2,
            "reason": "Different quantity",
            "idempotency_key": "fifo-return-001",
        },
    )
    assert changed_replay.status_code == 409

    valuation = client.get(
        f"/api/v1/products/{product['id']}/inventory/valuation",
        headers=auth_headers,
    ).json()
    assert valuation["quantity_on_hand"] == 10
    assert valuation["costed_quantity"] == 10
    assert Decimal(str(valuation["by_currency"][0]["total_cost"])) == Decimal("25.00000000")

    cogs = client.get(
        f"/api/v1/products/{product['id']}/inventory/cost-of-goods-sold",
        headers=auth_headers,
    ).json()
    assert cogs["allocated_quantity_returned"] == 6
    assert cogs["net_quantity_sold"] == 0
    assert Decimal(str(cogs["by_currency_returns"][0]["total_cost"])) == Decimal("13.00000000")
    assert Decimal(str(cogs["by_currency_net"][0]["total_cost"])) == Decimal(0)


def test_uncosted_sale_return_restores_the_original_uncosted_layer(client, auth_headers):
    product = _create_product(client, auth_headers, sku="FIFO-RETURN-UNCOSTED-001")
    receipt = _post_movement(
        client, auth_headers, product["id"], "receipt", 2, "fifo-return-uncosted-receipt"
    )
    assert receipt.status_code == 201, receipt.text
    sale = _post_movement(
        client, auth_headers, product["id"], "sale", -1, "fifo-return-uncosted-sale"
    )
    assert sale.status_code == 201, sale.text

    unlinked = client.post(
        f"/api/v1/products/{product['id']}/inventory/movements",
        headers=auth_headers,
        json={
            "movement_type": "return",
            "quantity_delta": 1,
            "reason": "Must link to a sale",
            "idempotency_key": "fifo-return-unlinked-001",
        },
    )
    assert unlinked.status_code == 422

    returned = _post_return(
        client, auth_headers, product["id"], sale.json()["id"], 1, "fifo-return-uncosted-001"
    )
    assert returned.status_code == 201, returned.text

    valuation = client.get(
        f"/api/v1/products/{product['id']}/inventory/valuation",
        headers=auth_headers,
    ).json()
    assert valuation["quantity_on_hand"] == 2
    assert valuation["costed_quantity"] == 0
    assert valuation["uncosted_quantity"] == 2

    cogs = client.get(
        f"/api/v1/products/{product['id']}/inventory/cost-of-goods-sold",
        headers=auth_headers,
    ).json()
    assert cogs["allocated_quantity_sold"] == 1
    assert cogs["uncosted_quantity_sold"] == 1
    assert cogs["allocated_quantity_returned"] == 1
    assert cogs["costed_quantity_returned"] == 0
    assert cogs["uncosted_quantity_returned"] == 1
    assert cogs["net_quantity_sold"] == 0
    assert cogs["by_currency_returns"] == []
    assert cogs["by_currency_net"] == []


def test_linked_return_rejects_sales_from_another_workspace(client, auth_headers):
    product = _create_product(client, auth_headers, sku="FIFO-RETURN-PRIVATE-001")
    _post_movement(client, auth_headers, product["id"], "receipt", 2, "fifo-private-receipt")
    sale = _post_movement(
        client, auth_headers, product["id"], "sale", -1, "fifo-private-sale"
    )
    other = client.post(
        "/api/v1/auth/register",
        json={
            "email": "fifo-return-other@example.com",
            "password": "AnotherStrongPassword!2026",
            "display_name": "Other Return Owner",
            "workspace_name": "Other Return Workspace",
        },
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    denied = _post_return(
        client, other_headers, product["id"], sale.json()["id"], 1, "fifo-return-other-001"
    )
    assert denied.status_code == 404
