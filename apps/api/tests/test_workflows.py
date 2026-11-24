import asyncio
from datetime import timedelta
from types import SimpleNamespace

from fastapi import HTTPException

from emporia_api.config import settings
from emporia_api.database import SessionLocal
from emporia_api.job_queue import claim_next_job
from emporia_api.models import BackgroundJob, WorkflowRun, utcnow


class FakeGateway:
    def configured(self, provider):
        return provider == "openai"


def workflow_payload(**overrides):
    value = {
        "name": "Smart-watch opportunity workflow",
        "idempotency_key": "smartwatch-flow-001",
        "steps": [
            {
                "kind": "agent",
                "agent_id": "commerce-strategist",
                "payload": {
                    "provider": "openai",
                    "model": "gpt-5",
                    "task": "Build a launch thesis for smart watches.",
                    "max_tokens": 128,
                },
            },
            {
                "kind": "agent",
                "agent_id": "product-research-analyst",
                "include_previous_output": True,
                "payload": {
                    "provider": "openai",
                    "model": "gpt-5",
                    "task": "Review the previous strategy and identify evidence gaps.",
                    "max_tokens": 128,
                },
            },
        ],
    }
    value.update(overrides)
    return value


def test_workflow_enqueue_is_persisted_and_idempotent(client, auth_headers, monkeypatch):
    monkeypatch.setattr("emporia_api.workflows.api.provider_gateway", FakeGateway())
    first = client.post("/api/v1/workflows/runs", headers=auth_headers, json=workflow_payload())
    assert first.status_code == 202, first.text
    body = first.json()
    assert body["status"] == "queued"
    assert body["total_steps"] == 2
    assert body["completed_steps"] == 0
    assert [item["status"] for item in body["steps"]] == ["queued", "queued"]

    replay = client.post("/api/v1/workflows/runs", headers=auth_headers, json=workflow_payload())
    assert replay.status_code == 200
    assert replay.headers["idempotency-replayed"] == "true"
    assert replay.json()["id"] == body["id"]

    changed = workflow_payload()
    changed["name"] = "Different logical workflow"
    conflict = client.post("/api/v1/workflows/runs", headers=auth_headers, json=changed)
    assert conflict.status_code == 409

    listed = client.get("/api/v1/workflows/runs", headers=auth_headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [body["id"]]
    queue_listing = client.get("/api/v1/jobs", headers=auth_headers)
    assert queue_listing.status_code == 200, queue_listing.text
    assert any(item["kind"] == "workflow" for item in queue_listing.json())
    with SessionLocal() as session:
        job = session.get(BackgroundJob, body["background_job_id"])
        stored = session.get(WorkflowRun, body["id"])
        assert job is not None and job.kind == "workflow" and job.max_attempts == 3
        assert stored is not None and stored.workspace_id
        assert len(stored.steps) == 2


def test_worker_executes_steps_in_order_and_hands_off_prior_output(
    client, auth_headers, monkeypatch
):
    monkeypatch.setattr("emporia_api.workflows.api.provider_gateway", FakeGateway())
    queued = client.post("/api/v1/workflows/runs", headers=auth_headers, json=workflow_payload())
    assert queued.status_code == 202, queued.text
    workflow_id = queued.json()["id"]
    seen_tasks = []

    async def fake_agent(agent_id, payload, response, session, actor, idempotency_key=None):
        seen_tasks.append((agent_id, payload.task, idempotency_key))
        index = len(seen_tasks)
        return SimpleNamespace(
            id=f"simulated-run-{index}",
            status="completed",
            output=f"previous specialist output {index}",
        )

    monkeypatch.setattr("emporia_api.main.execute_agent", fake_agent)
    from emporia_api.worker import run_one_job

    assert asyncio.run(run_one_job("workflow-test-worker")) is True
    assert [item[0] for item in seen_tasks] == [
        "commerce-strategist",
        "product-research-analyst",
    ]
    assert "previous specialist output 1" in seen_tasks[1][1]
    assert "untrusted analysis data" in seen_tasks[1][1]
    assert seen_tasks[0][2] != seen_tasks[1][2]

    completed = client.get(f"/api/v1/workflows/runs/{workflow_id}", headers=auth_headers)
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["completed_steps"] == 2
    assert [item["status"] for item in completed.json()["steps"]] == ["completed", "completed"]


def test_workflow_validates_registered_skills_and_previous_output_mapping(
    client, auth_headers, monkeypatch
):
    monkeypatch.setattr("emporia_api.workflows.api.provider_gateway", FakeGateway())
    payload = workflow_payload()
    payload["steps"][1] = {
        "kind": "skill",
        "skill_id": "market-opportunity-scan",
        "context_input_key": "not-a-declared-field",
        "payload": {"provider": "openai", "model": "gpt-5", "inputs": {}, "max_tokens": 128},
    }
    response = client.post("/api/v1/workflows/runs", headers=auth_headers, json=payload)
    assert response.status_code == 422
    assert "context_input_key" in response.text

    payload["steps"][1] = {
        "kind": "skill",
        "skill_id": "skill-that-does-not-exist",
        "payload": {"provider": "openai", "model": "gpt-5", "inputs": {}, "max_tokens": 128},
    }
    missing = client.post("/api/v1/workflows/runs", headers=auth_headers, json=payload)
    assert missing.status_code == 404


def test_workflows_are_tenant_scoped_and_cancellable_before_claim(
    client, auth_headers, monkeypatch
):
    monkeypatch.setattr("emporia_api.workflows.api.provider_gateway", FakeGateway())
    created = client.post("/api/v1/workflows/runs", headers=auth_headers, json=workflow_payload())
    assert created.status_code == 202
    workflow_id = created.json()["id"]

    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": "workflow-other@example.com",
            "password": "AnotherStrongPassword!2026",
            "display_name": "Other Workspace",
            "workspace_name": "Different Workspace",
        },
    )
    other_headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}
    hidden = client.get(f"/api/v1/workflows/runs/{workflow_id}", headers=other_headers)
    assert hidden.status_code == 404

    cancelled = client.post(
        f"/api/v1/workflows/runs/{workflow_id}/cancel",
        headers=auth_headers,
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    conflict = client.post(
        f"/api/v1/workflows/runs/{workflow_id}/cancel",
        headers=auth_headers,
    )
    assert conflict.status_code == 409


def test_terminal_step_failure_is_saved_on_workflow_and_job(
    client, auth_headers, monkeypatch
):
    monkeypatch.setattr("emporia_api.workflows.api.provider_gateway", FakeGateway())
    queued = client.post("/api/v1/workflows/runs", headers=auth_headers, json=workflow_payload())
    workflow_id = queued.json()["id"]

    async def fail_agent(agent_id, payload, response, session, actor, idempotency_key=None):
        raise HTTPException(status_code=400, detail="Step input rejected")

    monkeypatch.setattr("emporia_api.main.execute_agent", fail_agent)
    from emporia_api.worker import run_one_job

    assert asyncio.run(run_one_job("workflow-failure-worker")) is True
    failed = client.get(f"/api/v1/workflows/runs/{workflow_id}", headers=auth_headers)
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    assert failed.json()["failed_step"] == 1
    assert failed.json()["steps"][0]["status"] == "failed"
    with SessionLocal() as session:
        job = session.get(BackgroundJob, queued.json()["background_job_id"])
        assert job is not None and job.status == "failed"



def test_exhausted_worker_lease_marks_parent_workflow_failed(
    client, auth_headers, monkeypatch
):
    monkeypatch.setattr("emporia_api.workflows.api.provider_gateway", FakeGateway())
    queued = client.post("/api/v1/workflows/runs", headers=auth_headers, json=workflow_payload())
    assert queued.status_code == 202
    workflow_id = queued.json()["id"]
    with SessionLocal() as session:
        job = session.get(BackgroundJob, queued.json()["background_job_id"])
        job.status = "running"
        job.attempts = job.max_attempts
        job.locked_by = "dead-worker"
        job.locked_at = utcnow() - timedelta(seconds=settings.worker_lease_seconds + 10)
        session.commit()

    with SessionLocal() as session:
        assert claim_next_job(session, "replacement-worker") is None
        workflow = session.get(WorkflowRun, workflow_id)
        assert workflow.status == "failed"
        assert workflow.steps[0]["status"] == "failed"
        job = session.get(BackgroundJob, queued.json()["background_job_id"])
        assert job.status == "failed"
