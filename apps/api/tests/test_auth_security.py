from sqlalchemy import select

from emporia_api.database import SessionLocal
from emporia_api.models import WorkspaceMembership


def test_registration_and_login_normalize_email_case(client):
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "email": "Mixed.Case@Example.com",
            "password": "StrongMixedCasePassword!2026",
            "display_name": "Mixed Case",
            "workspace_name": "Case Test Workspace",
        },
    )
    assert registered.status_code == 201

    token = registered.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    profile = client.get("/api/v1/auth/me", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["email"] == "mixed.case@example.com"

    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "MIXED.CASE@EXAMPLE.COM",
            "password": "StrongMixedCasePassword!2026",
        },
    )
    assert login.status_code == 200


def test_revoked_workspace_membership_invalidates_existing_token(client, auth_headers):
    profile = client.get("/api/v1/auth/me", headers=auth_headers)
    assert profile.status_code == 200
    workspace_id = profile.json()["workspaces"][0]["id"]

    with SessionLocal() as session:
        membership = session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id
            )
        )
        assert membership is not None
        session.delete(membership)
        session.commit()

    response = client.get("/api/v1/ventures", headers=auth_headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "Workspace membership is not active"


def test_login_cannot_select_another_users_workspace(client, auth_headers):
    other_registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": "other-owner@example.com",
            "password": "AnotherStrongPassword!2026",
            "display_name": "Other Owner",
            "workspace_name": "Other Workspace",
        },
    )
    assert other_registration.status_code == 201
    other_workspace_id = other_registration.json()["workspace_id"]

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "VeryStrongTestPassword!2026",
            "workspace_id": other_workspace_id,
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "No membership exists for the selected workspace"
