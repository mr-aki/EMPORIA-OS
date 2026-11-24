from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from emporia_api.agents.registry import get_agent
from emporia_api.auth import Principal, get_current_principal, require_write_access
from emporia_api.config import settings
from emporia_api.database import get_session
from emporia_api.models import AuditEvent, BackgroundJob, WorkflowRun, utcnow
from emporia_api.providers import ProviderGateway
from emporia_api.rate_limits import RateLimitExceeded, consume_workspace_rate_limit
from emporia_api.schemas import (
    WorkflowAgentStep,
    WorkflowRunCreate,
    WorkflowRunRead,
    WorkflowSkillStep,
)
from emporia_api.skills.registry import get_skill, validate_skill_inputs

router = APIRouter(prefix="/api/v1/workflows", tags=["workflows"])
SessionDep = Annotated[Session, Depends(get_session)]
AuthDep = Annotated[Principal, Depends(get_current_principal)]
provider_gateway = ProviderGateway()


def _initial_steps(payload: WorkflowRunCreate) -> list[dict[str, object]]:
    steps: list[dict[str, object]] = []
    for index, step in enumerate(payload.steps):
        if isinstance(step, WorkflowAgentStep):
            steps.append({
                "sequence": index + 1,
                "kind": "agent",
                "target_id": step.agent_id,
                "status": "queued",
                "result_id": None,
                "error_message": "",
                "started_at": None,
                "completed_at": None,
            })
        else:
            steps.append({
                "sequence": index + 1,
                "kind": "skill",
                "target_id": step.skill_id,
                "status": "queued",
                "result_id": None,
                "error_message": "",
                "started_at": None,
                "completed_at": None,
            })
    return steps


def _stored_steps(payload: WorkflowRunCreate) -> list[dict[str, object]]:
    stored: list[dict[str, object]] = []
    for step in payload.steps:
        if isinstance(step, WorkflowAgentStep):
            stored.append({
                "kind": "agent",
                "target_id": step.agent_id,
                "payload": step.payload.model_dump(mode="json"),
                "include_previous_output": step.include_previous_output,
            })
        elif isinstance(step, WorkflowSkillStep):
            stored.append({
                "kind": "skill",
                "target_id": step.skill_id,
                "payload": step.payload.model_dump(mode="json"),
                "context_input_key": step.context_input_key,
            })
    return stored


def _validate_steps(payload: WorkflowRunCreate) -> list[dict[str, object]]:
    stored = _stored_steps(payload)
    for index, step in enumerate(payload.steps):
        if isinstance(step, WorkflowAgentStep):
            definition = get_agent(step.agent_id)
            if definition is None:
                raise HTTPException(status_code=404, detail=f"Agent not found at step {index + 1}")
            if step.payload.max_tokens > settings.agent_max_output_tokens:
                raise HTTPException(
                    status_code=422,
                    detail=f"Step {index + 1} exceeds the server agent output-token limit",
                )
            if not provider_gateway.configured(step.payload.provider):
                raise HTTPException(
                    status_code=503,
                    detail=f"Provider {step.payload.provider} is not configured on this server",
                )
        else:
            definition = get_skill(step.skill_id)
            if definition is None:
                raise HTTPException(status_code=404, detail=f"Skill not found at step {index + 1}")
            if step.payload.max_tokens > settings.skill_max_output_tokens:
                raise HTTPException(
                    status_code=422,
                    detail=f"Step {index + 1} exceeds the server skill output-token limit",
                )
            candidate = dict(step.payload.inputs)
            if step.context_input_key:
                if index == 0:
                    raise HTTPException(status_code=422, detail="The first step cannot consume previous output")
                field = next(
                    (item for item in definition.inputs if item.key == step.context_input_key),
                    None,
                )
                if field is None or field.value_type != "text":
                    raise HTTPException(
                        status_code=422,
                        detail=f"Step {index + 1} context_input_key must reference a declared text input",
                    )
                if step.context_input_key in candidate:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Step {index + 1} context input is populated automatically; omit it from inputs",
                    )
                if field.required:
                    candidate[step.context_input_key] = "x"
            errors = validate_skill_inputs(definition, candidate)
            if errors:
                raise HTTPException(
                    status_code=422,
                    detail={"message": f"Skill inputs are invalid at step {index + 1}", "errors": errors},
                )
            if not provider_gateway.configured(step.payload.provider):
                raise HTTPException(
                    status_code=503,
                    detail=f"Provider {step.payload.provider} is not configured on this server",
                )
    return stored


@router.post(
    "/runs",
    response_model=WorkflowRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_workflow(
    payload: WorkflowRunCreate,
    response: Response,
    session: SessionDep,
    actor: AuthDep,
) -> WorkflowRun:
    """Queue a bounded sequential workflow composed only of registered advisory agents and skills."""
    require_write_access(actor)
    if actor.auth_type != "jwt":
        raise HTTPException(status_code=403, detail="Workflows require a registered JWT user account")

    stored_steps = _validate_steps(payload)
    payload_json = json.dumps(
        {"name": payload.name.strip(), "steps": stored_steps},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )

    if payload.idempotency_key:
        existing_job = session.scalar(
            select(BackgroundJob).where(
                BackgroundJob.workspace_id == actor.workspace_id,
                BackgroundJob.idempotency_key == payload.idempotency_key,
            )
        )
        if existing_job is not None:
            if (
                existing_job.kind != "workflow"
                or existing_job.actor != actor.user_id
                or existing_job.payload_json != payload_json
            ):
                raise HTTPException(status_code=409, detail="Idempotency key was used for a different request")
            existing_run = session.scalar(
                select(WorkflowRun).where(
                    WorkflowRun.workspace_id == actor.workspace_id,
                    WorkflowRun.background_job_id == existing_job.id,
                )
            )
            if existing_run is None:
                raise HTTPException(status_code=409, detail="Existing workflow record is unavailable")
            response.status_code = status.HTTP_200_OK
            response.headers["Idempotency-Replayed"] = "true"
            return existing_run

    try:
        consume_workspace_rate_limit(
            session,
            actor.workspace_id,
            "job",
            settings.job_submissions_per_minute,
        )
    except RateLimitExceeded as exc:
        session.rollback()
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc

    workflow = WorkflowRun(
        workspace_id=actor.workspace_id,
        actor=actor.user_id,
        name=payload.name.strip(),
        status="queued",
        steps_json=json.dumps(_initial_steps(payload), ensure_ascii=False, separators=(",", ":")),
        total_steps=len(stored_steps),
        completed_steps=0,
        background_job_id="pending",
        idempotency_key=payload.idempotency_key,
    )
    session.add(workflow)
    session.flush()

    job = BackgroundJob(
        workspace_id=actor.workspace_id,
        actor=actor.user_id,
        kind="workflow",
        target_id="sequential-workflow",
        payload_json=payload_json,
        status="queued",
        attempts=0,
        max_attempts=3,
        idempotency_key=payload.idempotency_key,
        result_id=workflow.id,
    )
    session.add(job)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        if payload.idempotency_key:
            existing_job = session.scalar(
                select(BackgroundJob).where(
                    BackgroundJob.workspace_id == actor.workspace_id,
                    BackgroundJob.idempotency_key == payload.idempotency_key,
                )
            )
            if existing_job is not None:
                existing_run = session.scalar(
                    select(WorkflowRun).where(
                        WorkflowRun.workspace_id == actor.workspace_id,
                        WorkflowRun.background_job_id == existing_job.id,
                    )
                )
                if existing_job.kind == "workflow" and existing_run is not None:
                    response.status_code = status.HTTP_200_OK
                    response.headers["Idempotency-Replayed"] = "true"
                    return existing_run
        raise HTTPException(status_code=409, detail="Duplicate workflow submission") from exc

    workflow.background_job_id = job.id
    session.add(AuditEvent(
        workspace_id=actor.workspace_id,
        actor=actor.user_id,
        action="workflow.queued",
        resource_type="workflow_run",
        resource_id=workflow.id,
        detail=f"{workflow.total_steps}_steps",
    ))
    session.add(AuditEvent(
        workspace_id=actor.workspace_id,
        actor=actor.user_id,
        action="job.queued",
        resource_type="background_job",
        resource_id=job.id,
        detail=f"workflow:{workflow.id}",
    ))
    session.commit()
    session.refresh(workflow)
    response.status_code = status.HTTP_202_ACCEPTED
    return workflow


@router.get("/runs", response_model=list[WorkflowRunRead])
def list_workflows(
    session: SessionDep,
    actor: AuthDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
):
    return list(session.scalars(
        select(WorkflowRun)
        .where(WorkflowRun.workspace_id == actor.workspace_id)
        .order_by(WorkflowRun.created_at.desc())
        .limit(limit)
    ))


@router.get("/runs/{workflow_id}", response_model=WorkflowRunRead)
def get_workflow(workflow_id: str, session: SessionDep, actor: AuthDep):
    workflow = session.scalar(select(WorkflowRun).where(
        WorkflowRun.id == workflow_id,
        WorkflowRun.workspace_id == actor.workspace_id,
    ))
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.post("/runs/{workflow_id}/cancel", response_model=WorkflowRunRead)
def cancel_workflow(workflow_id: str, session: SessionDep, actor: AuthDep):
    """Cancel only before the worker claims the workflow; running model calls are not interrupted."""
    require_write_access(actor)
    workflow = session.scalar(select(WorkflowRun).where(
        WorkflowRun.id == workflow_id,
        WorkflowRun.workspace_id == actor.workspace_id,
    ))
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    result = session.execute(
        update(BackgroundJob)
        .where(
            BackgroundJob.id == workflow.background_job_id,
            BackgroundJob.workspace_id == actor.workspace_id,
            BackgroundJob.status.in_(("queued", "retry_wait")),
        )
        .values(
            status="cancelled",
            completed_at=utcnow(),
            updated_at=utcnow(),
            locked_at=None,
            locked_by=None,
        )
    )
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Workflow cannot be cancelled while status is {workflow.status}",
        )
    workflow.status = "cancelled"
    workflow.completed_at = utcnow()
    session.add(AuditEvent(
        workspace_id=actor.workspace_id,
        actor=actor.user_id,
        action="workflow.cancelled",
        resource_type="workflow_run",
        resource_id=workflow.id,
        detail="cancelled_before_worker_claim",
    ))
    session.commit()
    session.refresh(workflow)
    return workflow
