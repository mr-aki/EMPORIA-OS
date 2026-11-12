from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from emporia_api.agents.registry import get_agent, list_agents
from emporia_api.auth import require_api_token
from emporia_api.config import settings
from emporia_api.database import Base, engine, get_session
from emporia_api.models import AgentRun, AuditEvent, Venture, utcnow
from emporia_api.providers import ProviderGateway, ProviderNotConfigured, ProviderRequestError
from emporia_api.schemas import (
    AgentRead,
    AgentRunCreate,
    AgentRunRead,
    AuditRead,
    ChatCompletionRead,
    ChatCompletionRequest,
    ProviderRead,
    VentureCreate,
    VentureRead,
    VentureUpdate,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
SessionDep = Annotated[Session, Depends(get_session)]
AuthDep = Annotated[str, Depends(require_api_token)]


@app.get("/health/live", tags=["system"])
def liveness():
    return {"status": "alive", "service": "emporia-api"}


@app.get("/health/ready", tags=["system"])
def readiness(session: SessionDep):
    session.execute(select(1))
    return {"status": "ready", "database": "reachable"}


@app.post("/api/v1/ventures", response_model=VentureRead, status_code=status.HTTP_201_CREATED, tags=["ventures"])
def create_venture(payload: VentureCreate, session: SessionDep, actor: AuthDep):
    venture = Venture(workspace_id=settings.workspace_id, **payload.model_dump())
    session.add(venture)
    session.flush()
    session.add(AuditEvent(
        workspace_id=settings.workspace_id, actor=actor, action="venture.created",
        resource_type="venture", resource_id=venture.id, detail=venture.name,
    ))
    session.commit()
    session.refresh(venture)
    return venture


@app.get("/api/v1/ventures", response_model=list[VentureRead], tags=["ventures"])
def list_ventures(
    session: SessionDep,
    actor: AuthDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return list(session.scalars(
        select(Venture).where(Venture.workspace_id == settings.workspace_id)
        .order_by(Venture.created_at.desc()).limit(limit)
    ))


@app.get("/api/v1/ventures/{venture_id}", response_model=VentureRead, tags=["ventures"])
def get_venture(venture_id: str, session: SessionDep, actor: AuthDep):
    venture = session.scalar(select(Venture).where(
        Venture.id == venture_id, Venture.workspace_id == settings.workspace_id
    ))
    if venture is None:
        raise HTTPException(status_code=404, detail="Venture not found")
    return venture


@app.patch("/api/v1/ventures/{venture_id}", response_model=VentureRead, tags=["ventures"])
def update_venture(venture_id: str, payload: VentureUpdate, session: SessionDep, actor: AuthDep):
    venture = session.scalar(select(Venture).where(
        Venture.id == venture_id, Venture.workspace_id == settings.workspace_id
    ))
    if venture is None:
        raise HTTPException(status_code=404, detail="Venture not found")
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(venture, key, value)
    session.add(AuditEvent(
        workspace_id=settings.workspace_id, actor=actor, action="venture.updated",
        resource_type="venture", resource_id=venture.id, detail=",".join(sorted(changes)),
    ))
    session.commit()
    session.refresh(venture)
    return venture


@app.delete("/api/v1/ventures/{venture_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["ventures"])
def delete_venture(venture_id: str, session: SessionDep, actor: AuthDep):
    venture = session.scalar(select(Venture).where(
        Venture.id == venture_id, Venture.workspace_id == settings.workspace_id
    ))
    if venture is None:
        raise HTTPException(status_code=404, detail="Venture not found")
    session.add(AuditEvent(
        workspace_id=settings.workspace_id, actor=actor, action="venture.deleted",
        resource_type="venture", resource_id=venture.id, detail=venture.name,
    ))
    session.delete(venture)
    session.commit()


@app.get("/api/v1/audit-events", response_model=list[AuditRead], tags=["governance"])
def list_audit_events(
    session: SessionDep,
    actor: AuthDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    return list(session.scalars(
        select(AuditEvent).where(AuditEvent.workspace_id == settings.workspace_id)
        .order_by(AuditEvent.created_at.desc()).limit(limit)
    ))




provider_gateway = ProviderGateway()


@app.get("/api/v1/ai/providers", response_model=list[ProviderRead], tags=["ai"])
def list_ai_providers(actor: AuthDep):
    """Return provider availability without exposing credentials or secret metadata."""
    return provider_gateway.catalog()


@app.post(
    "/api/v1/ai/chat",
    response_model=ChatCompletionRead,
    tags=["ai"],
)
async def complete_ai_chat(
    payload: ChatCompletionRequest,
    session: SessionDep,
    actor: AuthDep,
):
    """Send a bounded, authenticated chat request to a configured server-side provider."""
    try:
        reply = await provider_gateway.complete(payload)
    except ProviderNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProviderRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    session.add(AuditEvent(
        workspace_id=settings.workspace_id,
        actor=actor,
        action="ai.chat.completed",
        resource_type="ai_provider",
        resource_id=payload.provider,
        detail=f"{payload.provider}:{payload.model}",
    ))
    session.commit()

    return ChatCompletionRead(
        provider=reply.provider,
        model=reply.model,
        content=reply.content,
        usage={
            "prompt_tokens": reply.prompt_tokens,
            "completion_tokens": reply.completion_tokens,
            "total_tokens": reply.total_tokens,
        },
        provider_request_id=reply.request_id,
    )


@app.get("/api/v1/agents", response_model=list[AgentRead], tags=["agents"])
def list_registered_agents(actor: AuthDep):
    """List installed specialist definitions without exposing private system prompts."""
    return [
        {**agent.public_metadata(), "tools_enabled": False}
        for agent in list_agents()
    ]


@app.post(
    "/api/v1/agents/{agent_id}/runs",
    response_model=AgentRunRead,
    status_code=status.HTTP_201_CREATED,
    tags=["agents"],
)
async def execute_agent(
    agent_id: str,
    payload: AgentRunCreate,
    session: SessionDep,
    actor: AuthDep,
):
    """Run a specialist against a configured model provider; no external action tools are enabled."""
    agent = get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    run = AgentRun(
        workspace_id=settings.workspace_id,
        agent_id=agent.id,
        agent_version=agent.version,
        provider=payload.provider,
        model=payload.model,
        status="running",
        task=payload.task,
    )
    session.add(run)
    session.flush()
    session.add(AuditEvent(
        workspace_id=settings.workspace_id,
        actor=actor,
        action="agent.run.started",
        resource_type="agent_run",
        resource_id=run.id,
        detail=f"{agent.id}:{payload.provider}:{payload.model}",
    ))
    session.commit()
    session.refresh(run)

    chat_request = ChatCompletionRequest(
        provider=payload.provider,
        model=payload.model,
        messages=[
            {"role": "system", "content": agent.system_prompt},
            {"role": "user", "content": payload.task},
        ],
        max_tokens=payload.max_tokens,
        temperature=payload.temperature,
    )
    try:
        reply = await provider_gateway.complete(chat_request)
    except ProviderNotConfigured as exc:
        run.status = "failed"
        run.error_message = str(exc)
        run.completed_at = utcnow()
        session.add(AuditEvent(
            workspace_id=settings.workspace_id,
            actor=actor,
            action="agent.run.failed",
            resource_type="agent_run",
            resource_id=run.id,
            detail="provider_not_configured",
        ))
        session.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProviderRequestError as exc:
        run.status = "failed"
        run.error_message = str(exc)
        run.completed_at = utcnow()
        session.add(AuditEvent(
            workspace_id=settings.workspace_id,
            actor=actor,
            action="agent.run.failed",
            resource_type="agent_run",
            resource_id=run.id,
            detail="provider_request_failed",
        ))
        session.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    run.status = "completed"
    run.output = reply.content
    run.prompt_tokens = reply.prompt_tokens or 0
    run.completion_tokens = reply.completion_tokens or 0
    run.total_tokens = reply.total_tokens or 0
    run.provider_request_id = reply.request_id
    run.completed_at = utcnow()
    session.add(AuditEvent(
        workspace_id=settings.workspace_id,
        actor=actor,
        action="agent.run.completed",
        resource_type="agent_run",
        resource_id=run.id,
        detail=f"{agent.id}:{run.total_tokens}_tokens",
    ))
    session.commit()
    session.refresh(run)
    return run


@app.get("/api/v1/agent-runs", response_model=list[AgentRunRead], tags=["agents"])
def list_agent_runs(
    session: SessionDep,
    actor: AuthDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
):
    return list(session.scalars(
        select(AgentRun)
        .where(AgentRun.workspace_id == settings.workspace_id)
        .order_by(AgentRun.created_at.desc())
        .limit(limit)
    ))


@app.get("/api/v1/agent-runs/{run_id}", response_model=AgentRunRead, tags=["agents"])
def get_agent_run(run_id: str, session: SessionDep, actor: AuthDep):
    run = session.scalar(select(AgentRun).where(
        AgentRun.id == run_id,
        AgentRun.workspace_id == settings.workspace_id,
    ))
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run
