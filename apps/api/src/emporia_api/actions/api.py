"""Workspace-scoped business-action proposals, approvals and fail-closed execution gate."""
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from emporia_api.actions.registry import (
    executor_available,
    get_action,
    list_actions,
    validate_action_inputs,
)
from emporia_api.auth import Principal, get_current_principal, require_write_access
from emporia_api.database import get_session
from emporia_api.models import (
    AuditEvent,
    BusinessActionRequest,
    User,
    WorkspaceMembership,
    utcnow,
)
from emporia_api.schemas import (
    ActionDecisionRequest,
    ActionDefinitionRead,
    ActionRequestCreate,
    ActionRequestRead,
    WorkspaceMemberCreate,
    WorkspaceMemberRead,
)

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]
AuthDep = Annotated[Principal, Depends(get_current_principal)]


def _require_persisted_user(actor: Principal) -> None:
    if actor.auth_type != "jwt":
        raise HTTPException(
            status_code=403,
            detail="This operation requires a registered workspace account",
        )


def _approval_authority(actor: Principal) -> None:
    if actor.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail="Only workspace owners and admins may approve or reject business actions",
        )
    _require_persisted_user(actor)


def _get_action_request(
    request_id: str,
    session: Session,
    actor: Principal,
) -> BusinessActionRequest:
    request = session.scalar(
        select(BusinessActionRequest).where(
            BusinessActionRequest.id == request_id,
            BusinessActionRequest.workspace_id == actor.workspace_id,
        )
    )
    if request is None:
        raise HTTPException(status_code=404, detail="Business action request not found")
    return request


def _audit(
    actor: Principal,
    action: str,
    request: BusinessActionRequest,
    detail: str = "",
) -> AuditEvent:
    return AuditEvent(
        workspace_id=actor.workspace_id,
        actor=actor.user_id,
        action=action,
        resource_type="business_action_request",
        resource_id=request.id,
        detail=detail or request.action_type,
    )


@router.get(
    "/api/v1/actions/catalog",
    response_model=list[ActionDefinitionRead],
    tags=["governance"],
)
def list_business_action_catalog(actor: AuthDep):
    """List safe proposal contracts; this release has no external executors."""
    return [definition.public_metadata() for definition in list_actions()]


@router.post(
    "/api/v1/actions/requests",
    response_model=ActionRequestRead,
    status_code=status.HTTP_201_CREATED,
    tags=["governance"],
)
def create_business_action_request(
    payload: ActionRequestCreate,
    session: SessionDep,
    actor: AuthDep,
    response: Response,
):
    require_write_access(actor)
    _require_persisted_user(actor)

    definition = get_action(payload.action_type)
    if definition is None:
        raise HTTPException(status_code=404, detail="Business action type is not allow-listed")
    errors = validate_action_inputs(payload.action_type, payload.inputs)
    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Action inputs are invalid", "errors": errors},
        )

    serialized_inputs = json.dumps(
        payload.inputs, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )
    if payload.idempotency_key:
        existing = session.scalar(
            select(BusinessActionRequest).where(
                BusinessActionRequest.workspace_id == actor.workspace_id,
                BusinessActionRequest.idempotency_key == payload.idempotency_key,
            )
        )
        if existing is not None:
            same_request = (
                existing.action_type == payload.action_type
                and existing.target_ref == payload.target_ref
                and existing.summary == payload.summary.strip()
                and existing.inputs_json == serialized_inputs
            )
            if same_request:
                response.status_code = status.HTTP_200_OK
                response.headers["Idempotency-Replayed"] = "true"
                return existing
            raise HTTPException(
                status_code=409,
                detail="Idempotency key was already used for a different action request",
            )

    request = BusinessActionRequest(
        workspace_id=actor.workspace_id,
        action_type=payload.action_type,
        target_ref=payload.target_ref,
        summary=payload.summary.strip(),
        inputs_json=serialized_inputs,
        status="pending_approval",
        requested_by=actor.user_id,
        idempotency_key=payload.idempotency_key,
    )
    session.add(request)
    try:
        session.flush()
        session.add(_audit(actor, "business_action.requested", request, f"{request.action_type}:{definition.risk_level}"))
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if payload.idempotency_key:
            existing = session.scalar(
                select(BusinessActionRequest).where(
                    BusinessActionRequest.workspace_id == actor.workspace_id,
                    BusinessActionRequest.idempotency_key == payload.idempotency_key,
                )
            )
            if existing is not None:
                same_request = (
                    existing.action_type == payload.action_type
                    and existing.target_ref == payload.target_ref
                    and existing.summary == payload.summary.strip()
                    and existing.inputs_json == serialized_inputs
                )
                if same_request:
                    response.status_code = status.HTTP_200_OK
                    response.headers["Idempotency-Replayed"] = "true"
                    return existing
        raise HTTPException(status_code=409, detail="Duplicate action request") from exc
    session.refresh(request)
    return request


@router.get(
    "/api/v1/actions/requests",
    response_model=list[ActionRequestRead],
    tags=["governance"],
)
def list_business_action_requests(
    session: SessionDep,
    actor: AuthDep,
    request_status: Annotated[
        Literal["pending_approval", "approved", "rejected", "cancelled"] | None,
        Query(alias="status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    query = select(BusinessActionRequest).where(
        BusinessActionRequest.workspace_id == actor.workspace_id
    )
    if request_status:
        query = query.where(BusinessActionRequest.status == request_status)
    query = query.order_by(BusinessActionRequest.requested_at.desc()).limit(limit)
    return list(session.scalars(query))


@router.get(
    "/api/v1/actions/requests/{request_id}",
    response_model=ActionRequestRead,
    tags=["governance"],
)
def get_business_action_request(
    request_id: str,
    session: SessionDep,
    actor: AuthDep,
):
    return _get_action_request(request_id, session, actor)


def _decide_request(
    request_id: str,
    note: str,
    session: Session,
    actor: Principal,
    decision: Literal["approved", "rejected"],
) -> BusinessActionRequest:
    _approval_authority(actor)
    current = _get_action_request(request_id, session, actor)
    if current.requested_by == actor.user_id:
        raise HTTPException(
            status_code=409,
            detail="The requester cannot approve or reject their own action",
        )
    if current.status != "pending_approval":
        raise HTTPException(status_code=409, detail="Only pending requests may be decided")

    now = utcnow()
    values = {
        "status": decision,
        "decision_note": note.strip(),
        "decided_at": now,
    }
    values["approved_by" if decision == "approved" else "rejected_by"] = actor.user_id
    result = session.execute(
        update(BusinessActionRequest)
        .where(
            BusinessActionRequest.id == request_id,
            BusinessActionRequest.workspace_id == actor.workspace_id,
            BusinessActionRequest.status == "pending_approval",
            BusinessActionRequest.requested_by != actor.user_id,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(status_code=409, detail="This request was already changed by another actor")

    request = _get_action_request(request_id, session, actor)
    session.add(_audit(actor, f"business_action.{decision}", request))
    session.commit()
    session.refresh(request)
    return request


@router.post(
    "/api/v1/actions/requests/{request_id}/approve",
    response_model=ActionRequestRead,
    tags=["governance"],
)
def approve_business_action_request(
    request_id: str,
    payload: ActionDecisionRequest,
    session: SessionDep,
    actor: AuthDep,
):
    return _decide_request(request_id, payload.note, session, actor, "approved")


@router.post(
    "/api/v1/actions/requests/{request_id}/reject",
    response_model=ActionRequestRead,
    tags=["governance"],
)
def reject_business_action_request(
    request_id: str,
    payload: ActionDecisionRequest,
    session: SessionDep,
    actor: AuthDep,
):
    if not payload.note.strip():
        raise HTTPException(status_code=422, detail="A rejection reason is required")
    return _decide_request(request_id, payload.note, session, actor, "rejected")


@router.post(
    "/api/v1/actions/requests/{request_id}/cancel",
    response_model=ActionRequestRead,
    tags=["governance"],
)
def cancel_business_action_request(
    request_id: str,
    payload: ActionDecisionRequest,
    session: SessionDep,
    actor: AuthDep,
):
    require_write_access(actor)
    _require_persisted_user(actor)
    current = _get_action_request(request_id, session, actor)
    is_requester = current.requested_by == actor.user_id
    is_workspace_admin = actor.role in {"owner", "admin"}
    if not is_requester and not is_workspace_admin:
        raise HTTPException(status_code=403, detail="Only the requester or a workspace admin may cancel")
    if current.status not in {"pending_approval", "approved"}:
        raise HTTPException(status_code=409, detail="This action request can no longer be cancelled")

    result = session.execute(
        update(BusinessActionRequest)
        .where(
            BusinessActionRequest.id == request_id,
            BusinessActionRequest.workspace_id == actor.workspace_id,
            BusinessActionRequest.status.in_(("pending_approval", "approved")),
            *(
                ()
                if is_workspace_admin
                else (BusinessActionRequest.requested_by == actor.user_id,)
            ),
        )
        .values(
            status="cancelled",
            decision_note=payload.note.strip(),
            cancelled_at=utcnow(),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(status_code=409, detail="This action request was already changed")
    request = _get_action_request(request_id, session, actor)
    session.add(_audit(actor, "business_action.cancelled", request))
    session.commit()
    session.refresh(request)
    return request


@router.post(
    "/api/v1/actions/requests/{request_id}/execute",
    response_model=ActionRequestRead,
    tags=["governance"],
)
def execute_approved_business_action(
    request_id: str,
    session: SessionDep,
    actor: AuthDep,
):
    """Fail closed until a reviewed action adapter is registered for this action type."""
    _approval_authority(actor)
    request = _get_action_request(request_id, session, actor)
    if request.status != "approved":
        raise HTTPException(status_code=409, detail="Only approved requests may be executed")

    reason = "No reviewed execution adapter is registered; external side effects are disabled."
    if not executor_available(request.action_type):
        if request.execution_block_reason != reason:
            result = session.execute(
                update(BusinessActionRequest)
                .where(
                    BusinessActionRequest.id == request_id,
                    BusinessActionRequest.workspace_id == actor.workspace_id,
                    BusinessActionRequest.status == "approved",
                )
                .values(execution_block_reason=reason)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                session.rollback()
                raise HTTPException(status_code=409, detail="The approved request changed before execution")
            session.add(_audit(actor, "business_action.execution_blocked", request))
            session.commit()
            session.refresh(request)
        raise HTTPException(
            status_code=409,
            detail={"message": reason, "request_id": request.id, "status": request.status},
        )
    raise HTTPException(status_code=503, detail="Action executor unavailable")


@router.get(
    "/api/v1/workspaces/members",
    response_model=list[WorkspaceMemberRead],
    tags=["workspaces"],
)
def list_workspace_members(session: SessionDep, actor: AuthDep):
    rows = session.execute(
        select(User, WorkspaceMembership)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .where(
            WorkspaceMembership.workspace_id == actor.workspace_id,
            User.is_active.is_(True),
        )
        .order_by(WorkspaceMembership.created_at.asc())
    ).all()
    return [
        WorkspaceMemberRead(
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=membership.role,
            created_at=membership.created_at,
        )
        for user, membership in rows
    ]


@router.post(
    "/api/v1/workspaces/members",
    response_model=WorkspaceMemberRead,
    status_code=status.HTTP_201_CREATED,
    tags=["workspaces"],
)
def add_workspace_member(
    payload: WorkspaceMemberCreate,
    session: SessionDep,
    actor: AuthDep,
):
    _require_persisted_user(actor)
    if actor.role != "owner":
        raise HTTPException(status_code=403, detail="Only the workspace owner may add members")
    user = session.scalar(
        select(User).where(User.email == str(payload.email).lower(), User.is_active.is_(True))
    )
    if user is None:
        raise HTTPException(status_code=404, detail="An active account with that email was not found")
    existing = session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == actor.workspace_id,
            WorkspaceMembership.user_id == user.id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="This user is already a workspace member")

    membership = WorkspaceMembership(
        workspace_id=actor.workspace_id,
        user_id=user.id,
        role=payload.role,
    )
    session.add(membership)
    try:
        session.flush()
        session.add(AuditEvent(
            workspace_id=actor.workspace_id,
            actor=actor.user_id,
            action="workspace.member_added",
            resource_type="workspace_membership",
            resource_id=membership.id,
            detail=f"{user.id}:{payload.role}",
        ))
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="This user is already a workspace member") from exc
    session.refresh(membership)
    return WorkspaceMemberRead(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=membership.role,
        created_at=membership.created_at,
    )
