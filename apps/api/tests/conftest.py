import os
import tempfile

os.environ["EMPORIA_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
os.environ["EMPORIA_API_TOKEN"] = "test-secret"
os.environ["EMPORIA_WORKSPACE_ID"] = "test-workspace"
os.environ["EMPORIA_ENVIRONMENT"] = "test"

import pytest
from fastapi.testclient import TestClient

from emporia_api.main import app
from emporia_api.database import Base, engine


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def auth_headers():
    return {"Authorization": "Bearer test-secret"}
