from emporia_api.auth import create_access_token, hash_password
from emporia_api.database import SessionLocal
from emporia_api.models import User, WorkspaceMembership


def _member_headers(workspace_id: str, role: str, email: str) -> tuple[dict[str, str], str]:
    with SessionLocal() as session:
        user = User(
            email=email,
            display_name=f"Action {role}",
            password_hash=hash_password("AnotherStrongPassword!2026"),
        )
        session.add(user)
        session.flush()
        session.add(WorkspaceMembership(
            workspace_id=workspace_id,
            user_id=user.id,
            role=role,
        ))
        session.commit()
        user_id = user.id
    token = create_access_token(user_id, workspace_id)
    return {"Authorization": f"Bearer {token}"}, user_id


def _workspace_id(client, headers: dict[str, str]) -> str:
    profile = client.get("/api/v1/auth/me", headers=headers)
    assert profile.status_code == 200
    return profile.json()["workspaces"][0]["id"]


def _inventory_payload(**overrides):
    inputs = {
        "sku": "SKU-001",
        "location_id": "warehouse-main",
        "quantity_delta": -3,
        "reason": "Damaged units confirmed during cycle count",
    }
    inputs.update(overrides)
    return {
        "action_type": "inventory.stock.adjust",
        "target_ref": "SKU-001",
        "summary": "Reduce three damaged units from available stock",
        "inputs": inputs,
    }


def test_action_catalog_is_allow_listed_and_has_no_live_executors(client, auth_headers):
    response = client.get("/api/v1/actions/catalog", headers=auth_headers)
    assert response.status_code == 200
    catalog = response.json()
    assert {item["id"] for item in catalog} == {
        "catalog.product.update",
        "inventory.stock.adjust",
        "marketing.campaign.publish",
        "orders.refund.issue",
    }
    assert all(item["executor_available"] is False for item in catalog)
    assert all(item["mode"] == "proposal_and_approval_only" for item in catalog)


def test_action_request_is_persisted_and_idempotent(client, auth_headers):
    payload = _inventory_payload()
    payload["idempotency_key"] = "inventory-cycle-count-2026-01"
    first = client.post("/api/v1/actions/requests", json=payload, headers=auth_headers)
    second = client.post("/api/v1/actions/requests", json=payload, headers=auth_headers)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["status"] == "pending_approval"
    assert first.json()["executor_available"] is False

    events = client.get("/api/v1/audit-events", headers=auth_headers)
    assert events.status_code == 200
    assert sum(event["action"] == "business_action.requested" for event in events.json()) == 1


def test_action_input_validation_and_secret_hygiene(client, auth_headers):
    unknown = client.post(
        "/api/v1/actions/requests",
        json={
            "action_type": "payments.capture",
            "target_ref": "payment-1",
            "summary": "Capture payment",
            "inputs": {"payment_id": "payment-1"},
        },
        headers=auth_headers,
    )
    assert unknown.status_code == 404

    invalid_type = client.post(
        "/api/v1/actions/requests",
        json=_inventory_payload(quantity_delta=1.25),
        headers=auth_headers,
    )
    assert invalid_type.status_code == 422

    secret = _inventory_payload()
    secret["inputs"]["password"] = "must-never-be-stored"
    rejected = client.post(
        "/api/v1/actions/requests",
        json=secret,
        headers=auth_headers,
    )
    assert rejected.status_code == 422


def test_idempotency_key_cannot_be_reused_for_a_different_request(client, auth_headers):
    payload = _inventory_payload()
    payload["idempotency_key"] = "same-operation-key"
    first = client.post("/api/v1/actions/requests", json=payload, headers=auth_headers)
    changed = {**payload, "summary": "Different requested stock adjustment"}

    assert first.status_code == 201
    conflict = client.post(
        "/api/v1/actions/requests",
        json=changed,
        headers=auth_headers,
    )
    assert conflict.status_code == 409


def test_requester_cannot_approve_own_action_but_another_admin_can(client, auth_headers):
    payload = _inventory_payload()
    created = client.post("/api/v1/actions/requests", json=payload, headers=auth_headers)
    assert created.status_code == 201
    request_id = created.json()["id"]

    self_approval = client.post(
        f"/api/v1/actions/requests/{request_id}/approve",
        json={"note": "I approve my own request"},
        headers=auth_headers,
    )
    assert self_approval.status_code == 409

    workspace_id = _workspace_id(client, auth_headers)
    admin_headers, admin_id = _member_headers(
        workspace_id, "admin", "action-admin@example.com"
    )
    approved = client.post(
        f"/api/v1/actions/requests/{request_id}/approve",
        json={"note": "Reviewed against the cycle-count evidence"},
        headers=admin_headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_by"] == admin_id
    assert approved.json()["decision_note"] == "Reviewed against the cycle-count evidence"


def test_approved_action_stays_blocked_without_a_reviewed_executor(client, auth_headers):
    created = client.post(
        "/api/v1/actions/requests",
        json=_inventory_payload(),
        headers=auth_headers,
    )
    assert created.status_code == 201
    request_id = created.json()["id"]

    admin_headers, _ = _member_headers(
        _workspace_id(client, auth_headers), "admin", "executor-admin@example.com"
    )
    approved = client.post(
        f"/api/v1/actions/requests/{request_id}/approve",
        json={"note": "Approved for execution once a connector is reviewed"},
        headers=admin_headers,
    )
    assert approved.status_code == 200

    attempt = client.post(
        f"/api/v1/actions/requests/{request_id}/execute",
        headers=auth_headers,
    )
    assert attempt.status_code == 409
    assert "No reviewed execution adapter" in attempt.json()["detail"]["message"]

    stored = client.get(
        f"/api/v1/actions/requests/{request_id}",
        headers=auth_headers,
    )
    assert stored.status_code == 200
    assert stored.json()["status"] == "approved"
    assert stored.json()["execution_block_reason"].startswith("No reviewed execution adapter")

    events = client.get("/api/v1/audit-events", headers=auth_headers)
    assert any(event["action"] == "business_action.execution_blocked" for event in events.json())


def test_workspace_viewer_can_read_catalog_but_cannot_propose_actions(client, auth_headers):
    viewer_headers, _ = _member_headers(
        _workspace_id(client, auth_headers), "viewer", "action-viewer@example.com"
    )
    assert client.get("/api/v1/actions/catalog", headers=viewer_headers).status_code == 200
    denied = client.post(
        "/api/v1/actions/requests",
        json=_inventory_payload(),
        headers=viewer_headers,
    )
    assert denied.status_code == 403


def test_action_requests_are_isolated_between_workspaces(client, auth_headers):
    created = client.post(
        "/api/v1/actions/requests",
        json=_inventory_payload(),
        headers=auth_headers,
    )
    assert created.status_code == 201

    other = client.post(
        "/api/v1/auth/register",
        json={
            "email": "different-workspace-owner@example.com",
            "password": "AnotherStrongPassword!2026",
            "display_name": "Other Workspace Owner",
            "workspace_name": "Separate Workspace",
        },
    )
    assert other.status_code == 201
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    hidden = client.get(
        f"/api/v1/actions/requests/{created.json()['id']}",
        headers=other_headers,
    )
    assert hidden.status_code == 404


def test_requester_can_cancel_pending_action_but_cannot_cancel_rejected_state(
    client, auth_headers
):
    created = client.post(
        "/api/v1/actions/requests",
        json=_inventory_payload(),
        headers=auth_headers,
    )
    request_id = created.json()["id"]
    cancelled = client.post(
        f"/api/v1/actions/requests/{request_id}/cancel",
        json={"note": "The stock count was corrected"},
        headers=auth_headers,
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    workspace_id = _workspace_id(client, auth_headers)
    second_admin, _ = _member_headers(
        workspace_id, "admin", "rejecting-admin@example.com"
    )
    another = client.post(
        "/api/v1/actions/requests",
        json={**_inventory_payload(), "summary": "Another stock correction"},
        headers=auth_headers,
    )
    rejected = client.post(
        f"/api/v1/actions/requests/{another.json()['id']}/reject",
        json={"note": "Evidence does not support this adjustment"},
        headers=second_admin,
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    cannot_cancel = client.post(
        f"/api/v1/actions/requests/{another.json()['id']}/cancel",
        json={"note": "Too late"},
        headers=auth_headers,
    )
    assert cannot_cancel.status_code == 409



def test_owner_can_add_existing_workspace_co_approver_and_admin_cannot_grant_roles(
    client, auth_headers
):
    workspace_id = _workspace_id(client, auth_headers)
    account = client.post(
        "/api/v1/auth/register",
        json={
            "email": "new-approver@example.com",
            "password": "AnotherStrongPassword!2026",
            "display_name": "New Approver",
            "workspace_name": "New Approver Workspace",
        },
    )
    assert account.status_code == 201

    added = client.post(
        "/api/v1/workspaces/members",
        json={"email": "NEW-APPROVER@example.com", "role": "admin"},
        headers=auth_headers,
    )
    assert added.status_code == 201, added.text
    assert added.json()["role"] == "admin"
    assert added.json()["email"] == "new-approver@example.com"

    members = client.get("/api/v1/workspaces/members", headers=auth_headers)
    assert members.status_code == 200
    assert any(member["email"] == "new-approver@example.com" for member in members.json())

    admin_login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "new-approver@example.com",
            "password": "AnotherStrongPassword!2026",
            "workspace_id": workspace_id,
        },
    )
    assert admin_login.status_code == 200
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    another = client.post(
        "/api/v1/auth/register",
        json={
            "email": "third-member@example.com",
            "password": "AnotherStrongPassword!2026",
            "display_name": "Third Member",
            "workspace_name": "Third Member Workspace",
        },
    )
    assert another.status_code == 201

    denied = client.post(
        "/api/v1/workspaces/members",
        json={"email": "third-member@example.com", "role": "viewer"},
        headers=admin_headers,
    )
    assert denied.status_code == 403

    duplicate = client.post(
        "/api/v1/workspaces/members",
        json={"email": "new-approver@example.com", "role": "admin"},
        headers=auth_headers,
    )
    assert duplicate.status_code == 409

