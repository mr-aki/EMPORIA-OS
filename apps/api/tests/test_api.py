def test_health_is_public(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


def test_venture_crud_and_audit(client, auth_headers):
    created = client.post("/api/v1/ventures", headers=auth_headers, json={
        "name": "Northstar Store", "description": "First commerce venture"
    })
    assert created.status_code == 201
    venture = created.json()
    assert venture["status"] == "planning"

    listed = client.get("/api/v1/ventures", headers=auth_headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    updated = client.patch(f"/api/v1/ventures/{venture['id']}", headers=auth_headers, json={
        "status": "active"
    })
    assert updated.status_code == 200
    assert updated.json()["status"] == "active"

    events = client.get("/api/v1/audit-events", headers=auth_headers)
    assert events.status_code == 200
    assert [event["action"] for event in events.json()] == ["venture.updated", "venture.created"]

    deleted = client.delete(f"/api/v1/ventures/{venture['id']}", headers=auth_headers)
    assert deleted.status_code == 204
    assert client.get("/api/v1/ventures", headers=auth_headers).json() == []


def test_api_requires_auth(client):
    assert client.get("/api/v1/ventures").status_code == 401
    assert client.post("/api/v1/ventures", json={"name": "No auth"}).status_code == 401


def test_validation_rejects_empty_name(client, auth_headers):
    response = client.post("/api/v1/ventures", headers=auth_headers, json={"name": ""})
    assert response.status_code == 422


def test_missing_venture_is_not_found(client, auth_headers):
    response = client.get("/api/v1/ventures/does-not-exist", headers=auth_headers)
    assert response.status_code == 404



def test_ai_provider_catalog_requires_auth_and_never_exposes_secrets(client):
    assert client.get("/api/v1/ai/providers").status_code == 401
    response = client.get("/api/v1/ai/providers", headers={"Authorization": "Bearer test-secret"})
    assert response.status_code == 200
    providers = response.json()
    assert {item["id"] for item in providers} == {
        "openai", "anthropic", "gemini", "openai-compatible"
    }
    assert all(item["configured"] is False for item in providers)
    assert all("api_key" not in item and "secret" not in item for item in providers)


def test_ai_chat_returns_clear_setup_error_when_provider_is_not_configured(client, auth_headers):
    response = client.post(
        "/api/v1/ai/chat",
        headers=auth_headers,
        json={
            "provider": "openai",
            "model": "gpt-5",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_ai_chat_validates_model_and_requires_a_user_message(client, auth_headers):
    invalid_model = client.post(
        "/api/v1/ai/chat",
        headers=auth_headers,
        json={
            "provider": "gemini",
            "model": "../unsafe",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )
    assert invalid_model.status_code == 422

    system_only = client.post(
        "/api/v1/ai/chat",
        headers=auth_headers,
        json={
            "provider": "anthropic",
            "model": "claude-sonnet",
            "messages": [{"role": "system", "content": "Only system"}],
        },
    )
    assert system_only.status_code == 422
