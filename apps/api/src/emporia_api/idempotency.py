import hashlib
import json
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from emporia_api.models import AgentRun, AuditEvent, SkillRun

RunModel = type[AgentRun] | type[SkillRun]


def fingerprint_request(
    execution_type: str,
    resource_id: str,
    resource_version: str,
    actor_id: str,
    payload: BaseModel,
) -> str:
    """Create a stable fingerprint from the normalized, validated request."""
    canonical = json.dumps(
        {
            "execution_type": execution_type,
            "resource_id": resource_id,
            "resource_version": resource_version,
            "actor_id": actor_id,
            "payload": payload.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def find_replay(
    session: Session,
    run_model: RunModel,
    workspace_id: str,
    idempotency_key: str | None,
    fingerprint: str,
) -> AgentRun | SkillRun | None:
    """Return a prior run, rejecting reuse of a key for a different request."""
    if idempotency_key is None:
        return None

    existing = session.scalar(
        select(run_model).where(
            run_model.workspace_id == workspace_id,
            run_model.idempotency_key == idempotency_key,
        )
    )
    if existing is not None and existing.request_fingerprint != fingerprint:
        raise HTTPException(
            status_code=409,
            detail="Idempotency-Key was already used with a different request",
        )
    return existing


def create_run_once(
    session: Session,
    run_model: RunModel,
    run: AgentRun | SkillRun,
    workspace_id: str,
    idempotency_key: str | None,
    fingerprint: str,
    audit_event_factory: Callable[[str], AuditEvent],
) -> tuple[AgentRun | SkillRun, bool]:
    """Persist a run and audit event; resolve concurrent duplicate inserts safely."""
    session.add(run)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = find_replay(
            session,
            run_model,
            workspace_id,
            idempotency_key,
            fingerprint,
        )
        if existing is not None:
            return existing, True
        raise

    session.add(audit_event_factory(run.id))
    session.commit()
    session.refresh(run)
    return run, False
