import os
import tempfile

os.environ["EMPORIA_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
os.environ["EMPORIA_API_TOKEN"] = "test-secret"
os.environ["EMPORIA_JWT_SECRET"] = "unit-test-jwt-secret-with-at-least-32-chars"
os.environ["EMPORIA_ALLOW_REGISTRATION"] = "true"
os.environ["EMPORIA_WORKSPACE_ID"] = "test-workspace"
os.environ["EMPORIA_ENVIRONMENT"] = "test"

import pytest
from fastapi.testclient import TestClient

from emporia_api.database import Base, engine
from emporia_api.main import app


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def auth_headers(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "test@example.local",
            "password": "VeryStrongTestPassword!2026",
            "display_name": "Test User",
            "workspace_name": "Test Workspace",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
