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
