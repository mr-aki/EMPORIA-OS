from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from emporia_api.auth import require_api_token
from emporia_api.config import settings
from emporia_api.database import Base, engine, get_session
from emporia_api.models import AuditEvent, Venture
from emporia_api.schemas import AuditRead, VentureCreate, VentureRead, VentureUpdate


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
