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



def test_login_failed_attempts_are_limited_per_normalized_email(
    client, auth_headers, monkeypatch
):
    from emporia_api.config import settings

    monkeypatch.setattr(settings, "login_attempts_per_email_window", 2)
    monkeypatch.setattr(settings, "login_attempts_per_ip_window", 100)

    bad_password = {
        "email": "TEST@EXAMPLE.COM",
        "password": "incorrect-password",
    }
    for _ in range(2):
        response = client.post("/api/v1/auth/login", json=bad_password)
        assert response.status_code == 401

    blocked = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "VeryStrongTestPassword!2026",
        },
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1


def test_login_failed_attempts_are_limited_across_accounts_per_client_ip(
    client, monkeypatch
):
    from emporia_api.config import settings

    monkeypatch.setattr(settings, "login_attempts_per_email_window", 100)
    monkeypatch.setattr(settings, "login_attempts_per_ip_window", 2)

    for email in ("one@example.com", "two@example.com"):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong-password"},
        )
        assert response.status_code == 401

    blocked = client.post(
        "/api/v1/auth/login",
        json={"email": "three@example.com", "password": "wrong-password"},
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1


def test_successful_login_clears_email_counter_but_keeps_ip_counter(
    client, auth_headers
):
    from sqlalchemy import select

    from emporia_api.database import SessionLocal
    from emporia_api.models import LoginAttemptRateLimit

    failed = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "incorrect-password"},
    )
    assert failed.status_code == 401

    success = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "VeryStrongTestPassword!2026",
        },
    )
    assert success.status_code == 200

    with SessionLocal() as session:
        email_counter = session.scalar(
            select(LoginAttemptRateLimit).where(
                LoginAttemptRateLimit.subject_type == "email"
            )
        )
        ip_counter = session.scalar(
            select(LoginAttemptRateLimit).where(LoginAttemptRateLimit.subject_type == "ip")
        )
    assert email_counter is None
    assert ip_counter is not None
    assert "test@example.com" not in ip_counter.subject_hash
