class FakeGateway:
    def configured(self, provider):
        return provider == "openai"


def payload(**overrides):
    value = {
        "kind": "agent",
        "agent_id": "commerce-strategist",
        "payload": {
            "provider": "openai",
            "model": "gpt-5",
            "task": "Prepare a launch plan.",
            "max_tokens": 128,
        },
        "max_attempts": 3,
        "idempotency_key": "launch-job-001",
    }
    value.update(overrides)
    return value


def test_enqueue_job_is_workspace_scoped_and_idempotent(client, auth_headers, monkeypatch):
    monkeypatch.setattr("emporia_api.main.provider_gateway", FakeGateway())
    first = client.post("/api/v1/jobs", headers=auth_headers, json=payload())
    assert first.status_code == 201, first.text
    first_job = first.json()
    assert first_job["status"] == "queued"
    assert first_job["attempts"] == 0
    assert "payload" not in first_job

    replay = client.post("/api/v1/jobs", headers=auth_headers, json=payload())
    assert replay.status_code == 200
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json()["id"] == first_job["id"]

    conflict = payload()
    conflict["payload"]["task"] = "Different task"
    response = client.post("/api/v1/jobs", headers=auth_headers, json=conflict)
    assert response.status_code == 409


def test_job_list_and_get_are_workspace_scoped(client, auth_headers, monkeypatch):
    monkeypatch.setattr("emporia_api.main.provider_gateway", FakeGateway())
    created = client.post("/api/v1/jobs", headers=auth_headers, json=payload())
    assert created.status_code == 201
    job_id = created.json()["id"]

    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": "different-workspace@example.com",
            "password": "DifferentStrongPassword!2026",
            "display_name": "Other Owner",
            "workspace_name": "Other Workspace",
        },
    )
    assert registration.status_code == 201
    other_headers = {
        "Authorization": f"Bearer {registration.json()['access_token']}"
    }
    assert client.get("/api/v1/jobs", headers=other_headers).json() == []
    assert client.get(f"/api/v1/jobs/{job_id}", headers=other_headers).status_code == 404


def test_queued_job_can_be_cancelled_and_is_audited(client, auth_headers, monkeypatch):
    monkeypatch.setattr("emporia_api.main.provider_gateway", FakeGateway())
    created = client.post("/api/v1/jobs", headers=auth_headers, json=payload())
    job_id = created.json()["id"]

    cancelled = client.post(
        f"/api/v1/jobs/{job_id}/cancel",
        headers=auth_headers,
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["completed_at"] is not None


def test_enqueue_requires_a_registered_jwt_user(client, monkeypatch):
    monkeypatch.setattr("emporia_api.main.provider_gateway", FakeGateway())
    response = client.post(
        "/api/v1/jobs",
        headers={"Authorization": "Bearer test-secret"},
        json=payload(),
    )
    assert response.status_code in {401, 403}


def test_enqueue_rejects_unconfigured_provider(client, auth_headers, monkeypatch):
    class UnconfiguredGateway:
        def configured(self, provider):
            return False

    monkeypatch.setattr("emporia_api.main.provider_gateway", UnconfiguredGateway())
    response = client.post("/api/v1/jobs", headers=auth_headers, json=payload())
    assert response.status_code == 503
