"""Workspace-scoped product catalogue API."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from emporia_api.auth import Principal, get_current_principal, require_write_access
from emporia_api.database import get_session
from emporia_api.models import AuditEvent, Product
from emporia_api.schemas import ProductCreate, ProductRead, ProductUpdate

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]
AuthDep = Annotated[Principal, Depends(get_current_principal)]
ProductStatus = Literal["draft", "active", "archived"]


@router.post("/api/v1/products", response_model=ProductRead, status_code=status.HTTP_201_CREATED, tags=["catalog"])
def create_product(payload: ProductCreate, session: SessionDep, actor: AuthDep):
    """Create a catalogue product and its audit event in one transaction."""
    require_write_access(actor)
    product = Product(workspace_id=actor.workspace_id, **payload.model_dump())
    session.add(product)
    try:
        session.flush()
        session.add(AuditEvent(
            workspace_id=actor.workspace_id, actor=actor.user_id,
            action="product.created", resource_type="product",
            resource_id=product.id, detail=product.sku,
        ))
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A product with this SKU already exists in this workspace",
        ) from exc
    session.refresh(product)
    return product


@router.get("/api/v1/products", response_model=list[ProductRead], tags=["catalog"])
def list_products(
    session: SessionDep,
    actor: AuthDep,
    product_status: Annotated[ProductStatus | None, Query(alias="status")] = None,
    query: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    """List only the current workspace's products, with bounded filters."""
    statement = select(Product).where(Product.workspace_id == actor.workspace_id)
    if product_status is not None:
        statement = statement.where(Product.status == product_status)
    if query and query.strip():
        pattern = f"%{query.strip()}%"
        statement = statement.where(or_(Product.sku.ilike(pattern), Product.name.ilike(pattern)))
    statement = statement.order_by(Product.created_at.desc(), Product.sku.asc()).limit(limit)
    return list(session.scalars(statement))


@router.get("/api/v1/products/{product_id}", response_model=ProductRead, tags=["catalog"])
def get_product(product_id: str, session: SessionDep, actor: AuthDep):
    product = session.scalar(select(Product).where(
        Product.id == product_id, Product.workspace_id == actor.workspace_id,
    ))
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.patch("/api/v1/products/{product_id}", response_model=ProductRead, tags=["catalog"])
def update_product(product_id: str, payload: ProductUpdate, session: SessionDep, actor: AuthDep):
    require_write_access(actor)
    product = session.scalar(select(Product).where(
        Product.id == product_id, Product.workspace_id == actor.workspace_id,
    ))
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(product, field, value)
    session.add(AuditEvent(
        workspace_id=actor.workspace_id, actor=actor.user_id,
        action="product.updated", resource_type="product",
        resource_id=product.id, detail=",".join(sorted(changes)),
    ))
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A product with this SKU already exists in this workspace",
        ) from exc
    session.refresh(product)
    return product
