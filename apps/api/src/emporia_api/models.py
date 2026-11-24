import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from emporia_api.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)




class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class WorkspaceMembership(Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_membership"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), default="viewer", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

class Venture(Base):
    __tablename__ = "ventures"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="planning", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Product(Base):
    """Workspace-owned catalogue product with a normalized, workspace-unique SKU."""

    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("workspace_id", "sku", name="uq_products_workspace_sku"),
        Index("uq_products_id_workspace", "id", "workspace_id", unique=True),
        Index("ix_products_workspace_created_at", "workspace_id", "created_at"),
        CheckConstraint("unit_price > 0", name="ck_products_unit_price_positive"),
        CheckConstraint("status IN ('draft', 'active', 'archived')", name="ck_products_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), nullable=False)
    sku: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="draft", server_default="draft", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )



class InventoryMovement(Base):
    """Immutable workspace-scoped stock movement; current stock is the sum of deltas."""

    __tablename__ = "inventory_movements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["product_id", "workspace_id"],
            ["products.id", "products.workspace_id"],
            name="fk_inventory_movements_product_workspace",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "workspace_id", "idempotency_key",
            name="uq_inventory_movements_workspace_idempotency",
        ),
        Index("uq_inventory_movements_id_workspace", "id", "workspace_id", unique=True),
        Index("uq_inventory_movements_id_workspace_product", "id", "workspace_id", "product_id", unique=True),
        Index(
            "ix_inventory_movements_workspace_product_created_at",
            "workspace_id", "product_id", "created_at",
        ),
        CheckConstraint("quantity_delta <> 0", name="ck_inventory_movements_nonzero_delta"),
        CheckConstraint("quantity_after >= 0", name="ck_inventory_movements_nonnegative_balance"),
        CheckConstraint(
            "movement_type IN ('receipt', 'sale', 'return', 'damage', 'adjustment')",
            name="ck_inventory_movements_type",
        ),
        CheckConstraint(
            "((movement_type IN ('receipt', 'return') AND quantity_delta > 0) "
            "OR (movement_type IN ('sale', 'damage') AND quantity_delta < 0) "
            "OR (movement_type = 'adjustment' AND quantity_delta <> 0))",
            name="ck_inventory_movements_direction",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), nullable=False)
    product_id: Mapped[str] = mapped_column(String(36), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)




class InventoryCostLayer(Base):
    """FIFO receipt layer; unknown-cost stock remains explicitly uncosted."""

    __tablename__ = "inventory_cost_layers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["product_id", "workspace_id"],
            ["products.id", "products.workspace_id"],
            name="fk_inventory_cost_layers_product_workspace",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_inventory_movement_id", "workspace_id"],
            ["inventory_movements.id", "inventory_movements.workspace_id"],
            name="fk_inventory_cost_layers_source_movement_workspace",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "workspace_id", name="uq_inventory_cost_layers_id_workspace"),
        Index("uq_inventory_cost_layers_id_workspace_product", "id", "workspace_id", "product_id", unique=True),
        UniqueConstraint("source_inventory_movement_id", name="uq_inventory_cost_layers_source_movement"),
        Index("ix_inventory_cost_layers_fifo", "workspace_id", "product_id", "created_at", "id"),
        CheckConstraint("quantity_received > 0", name="ck_inventory_cost_layers_received_positive"),
        CheckConstraint(
            "quantity_remaining >= 0 AND quantity_remaining <= quantity_received",
            name="ck_inventory_cost_layers_remaining_range",
        ),
        CheckConstraint(
            "((unit_cost IS NULL AND currency IS NULL) OR "
            "(unit_cost IS NOT NULL AND unit_cost >= 0 AND currency IS NOT NULL))",
            name="ck_inventory_cost_layers_cost_currency_pair",
        ),
        CheckConstraint(
            "((source_type = 'opening_balance' AND source_inventory_movement_id IS NULL) OR "
            "(source_type = 'inventory_movement' AND source_inventory_movement_id IS NOT NULL))",
            name="ck_inventory_cost_layers_source",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), nullable=False)
    product_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_inventory_movement_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False)
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_remaining: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class InventoryCostAllocation(Base):
    """Immutable FIFO cost allocation from a layer to an outbound inventory movement."""

    __tablename__ = "inventory_cost_allocations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["inventory_movement_id", "workspace_id"],
            ["inventory_movements.id", "inventory_movements.workspace_id"],
            name="fk_inventory_cost_allocations_movement_workspace",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["cost_layer_id", "workspace_id"],
            ["inventory_cost_layers.id", "inventory_cost_layers.workspace_id"],
            name="fk_inventory_cost_allocations_layer_workspace",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "inventory_movement_id", "cost_layer_id",
            name="uq_inventory_cost_allocations_movement_layer",
        ),
        Index("uq_inventory_cost_allocations_id_layer_workspace", "id", "cost_layer_id", "workspace_id", unique=True),
        Index(
            "ix_inventory_cost_allocations_workspace_movement",
            "workspace_id", "inventory_movement_id",
        ),
        CheckConstraint("quantity_allocated > 0", name="ck_inventory_cost_allocations_quantity_positive"),
        CheckConstraint(
            "((unit_cost IS NULL AND currency IS NULL AND extended_cost IS NULL) OR "
            "(unit_cost IS NOT NULL AND unit_cost >= 0 AND currency IS NOT NULL "
            "AND extended_cost IS NOT NULL AND extended_cost >= 0))",
            name="ck_inventory_cost_allocations_cost_currency_pair",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), nullable=False)
    inventory_movement_id: Mapped[str] = mapped_column(String(36), nullable=False)
    cost_layer_id: Mapped[str] = mapped_column(String(36), nullable=False)
    quantity_allocated: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    extended_cost: Mapped[Decimal | None] = mapped_column(Numeric(30, 8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)



class InventoryReturn(Base):
    """A product return linked to exactly one original sale movement."""

    __tablename__ = "inventory_returns"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_sale_movement_id", "workspace_id", "product_id"],
            ["inventory_movements.id", "inventory_movements.workspace_id", "inventory_movements.product_id"],
            name="fk_inventory_returns_source_sale_workspace_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["return_movement_id", "workspace_id", "product_id"],
            ["inventory_movements.id", "inventory_movements.workspace_id", "inventory_movements.product_id"],
            name="fk_inventory_returns_movement_workspace_product",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "workspace_id", "product_id", name="uq_inventory_returns_id_workspace_product"),
        UniqueConstraint("return_movement_id", name="uq_inventory_returns_return_movement"),
        Index("ix_inventory_returns_workspace_source_sale", "workspace_id", "source_sale_movement_id"),
        CheckConstraint("quantity_returned > 0", name="ck_inventory_returns_quantity_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), nullable=False)
    product_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_sale_movement_id: Mapped[str] = mapped_column(String(36), nullable=False)
    return_movement_id: Mapped[str] = mapped_column(String(36), nullable=False)
    quantity_returned: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class InventoryCostReturnAllocation(Base):
    """Immutable cost reversal linking a return to the original sale allocation."""

    __tablename__ = "inventory_cost_return_allocations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["inventory_return_id", "workspace_id", "product_id"],
            ["inventory_returns.id", "inventory_returns.workspace_id", "inventory_returns.product_id"],
            name="fk_inventory_cost_return_allocations_return_workspace_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["cost_layer_id", "workspace_id", "product_id"],
            ["inventory_cost_layers.id", "inventory_cost_layers.workspace_id", "inventory_cost_layers.product_id"],
            name="fk_inventory_cost_return_allocations_layer_workspace_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_cost_allocation_id", "cost_layer_id", "workspace_id"],
            ["inventory_cost_allocations.id", "inventory_cost_allocations.cost_layer_id", "inventory_cost_allocations.workspace_id"],
            name="fk_inventory_cost_return_allocations_source_layer_workspace",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "inventory_return_id", "source_cost_allocation_id",
            name="uq_inventory_cost_return_allocations_return_source",
        ),
        Index(
            "ix_inventory_cost_return_allocations_workspace_return",
            "workspace_id", "inventory_return_id",
        ),
        CheckConstraint(
            "quantity_returned > 0",
            name="ck_inventory_cost_return_allocations_quantity_positive",
        ),
        CheckConstraint(
            "((unit_cost IS NULL AND currency IS NULL AND extended_cost IS NULL) OR "
            "(unit_cost IS NOT NULL AND unit_cost >= 0 AND currency IS NOT NULL "
            "AND extended_cost IS NOT NULL AND extended_cost >= 0))",
            name="ck_inventory_cost_return_allocations_cost_currency_pair",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), nullable=False)
    product_id: Mapped[str] = mapped_column(String(36), nullable=False)
    inventory_return_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_cost_allocation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cost_layer_id: Mapped[str] = mapped_column(String(36), nullable=False)
    quantity_returned: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    extended_cost: Mapped[Decimal | None] = mapped_column(Numeric(30, 8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Supplier(Base):
    """Workspace-owned supplier contact and lifecycle record."""

    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id", name="uq_suppliers_id_workspace"),
        UniqueConstraint("workspace_id", "code", name="uq_suppliers_workspace_code"),
        Index("ix_suppliers_workspace_created_at", "workspace_id", "created_at"),
        CheckConstraint("status IN ('active', 'archived')", name="ck_suppliers_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class PurchaseOrder(Base):
    """Workspace-scoped supplier order with an explicit receiving lifecycle."""

    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id", name="uq_purchase_orders_id_workspace"),
        UniqueConstraint("workspace_id", "order_number", name="uq_purchase_orders_workspace_number"),
        ForeignKeyConstraint(
            ["supplier_id", "workspace_id"],
            ["suppliers.id", "suppliers.workspace_id"],
            name="fk_purchase_orders_supplier_workspace",
            ondelete="RESTRICT",
        ),
        Index("ix_purchase_orders_workspace_created_at", "workspace_id", "created_at"),
        CheckConstraint(
            "status IN ('draft', 'ordered', 'partially_received', 'received', 'cancelled')",
            name="ck_purchase_orders_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), nullable=False)
    supplier_id: Mapped[str] = mapped_column(String(36), nullable=False)
    order_number: Mapped[str] = mapped_column(String(80), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="draft", server_default="draft", nullable=False
    )
    notes: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class PurchaseOrderLine(Base):
    """Ordered quantity and cost with a mutable received counter."""

    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id", name="uq_purchase_order_lines_id_workspace"),
        ForeignKeyConstraint(
            ["purchase_order_id", "workspace_id"],
            ["purchase_orders.id", "purchase_orders.workspace_id"],
            name="fk_purchase_order_lines_order_workspace",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["product_id", "workspace_id"],
            ["products.id", "products.workspace_id"],
            name="fk_purchase_order_lines_product_workspace",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "purchase_order_id", "product_id",
            name="uq_purchase_order_lines_order_product",
        ),
        Index(
            "ix_purchase_order_lines_workspace_order",
            "workspace_id", "purchase_order_id",
        ),
        CheckConstraint("quantity_ordered > 0", name="ck_purchase_order_lines_ordered_positive"),
        CheckConstraint(
            "quantity_received >= 0 AND quantity_received <= quantity_ordered",
            name="ck_purchase_order_lines_received_range",
        ),
        CheckConstraint("unit_cost >= 0", name="ck_purchase_order_lines_unit_cost_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), nullable=False)
    purchase_order_id: Mapped[str] = mapped_column(String(36), nullable=False)
    product_id: Mapped[str] = mapped_column(String(36), nullable=False)
    quantity_ordered: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_received: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PurchaseOrderReceipt(Base):
    """Idempotent receipt envelope for one purchase-order receiving operation."""

    __tablename__ = "purchase_order_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["purchase_order_id", "workspace_id"],
            ["purchase_orders.id", "purchase_orders.workspace_id"],
            name="fk_purchase_order_receipts_order_workspace",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "workspace_id", "idempotency_key",
            name="uq_purchase_order_receipts_workspace_idempotency",
        ),
        UniqueConstraint("id", "workspace_id", name="uq_purchase_order_receipts_id_workspace"),
        Index(
            "ix_purchase_order_receipts_workspace_order_created",
            "workspace_id", "purchase_order_id", "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), nullable=False)
    purchase_order_id: Mapped[str] = mapped_column(String(36), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PurchaseOrderReceiptLine(Base):
    """Received order line linked to its immutable inventory movement."""

    __tablename__ = "purchase_order_receipt_lines"
    __table_args__ = (
        ForeignKeyConstraint(
            ["receipt_id", "workspace_id"],
            ["purchase_order_receipts.id", "purchase_order_receipts.workspace_id"],
            name="fk_purchase_order_receipt_lines_receipt_workspace",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["purchase_order_line_id", "workspace_id"],
            ["purchase_order_lines.id", "purchase_order_lines.workspace_id"],
            name="fk_purchase_order_receipt_lines_order_line_workspace",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["inventory_movement_id", "workspace_id"],
            ["inventory_movements.id", "inventory_movements.workspace_id"],
            name="fk_purchase_order_receipt_lines_inventory_movement_workspace",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "receipt_id", "purchase_order_line_id",
            name="uq_purchase_order_receipt_lines_receipt_line",
        ),
        UniqueConstraint(
            "inventory_movement_id",
            name="uq_purchase_order_receipt_lines_inventory_movement",
        ),
        CheckConstraint("quantity_received > 0", name="ck_purchase_order_receipt_lines_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), nullable=False)
    receipt_id: Mapped[str] = mapped_column(String(36), nullable=False)
    purchase_order_line_id: Mapped[str] = mapped_column(String(36), nullable=False)
    inventory_movement_id: Mapped[str] = mapped_column(String(36), nullable=False)
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_agent_runs_workspace_idempotency"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    output: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_price_usd_per_million_tokens: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    output_price_usd_per_million_tokens: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(30, 16), nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    requested_max_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    budget_charged_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    execution_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    research_sources_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def research_sources(self) -> list[dict[str, object]]:
        try:
            value = json.loads(self.research_sources_json or "[]")
        except (TypeError, ValueError):
            return []
        return value if isinstance(value, list) else []

    @research_sources.setter
    def research_sources(self, value: list[dict[str, object]]) -> None:
        self.research_sources_json = json.dumps(value, ensure_ascii=False)



class WorkspaceExecutionRateLimit(Base):
    __tablename__ = "workspace_execution_rate_limits"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "execution_type",
            name="uq_workspace_execution_rate_limit",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), nullable=False)
    execution_type: Mapped[str] = mapped_column(String(20), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class LoginAttemptRateLimit(Base):
    __tablename__ = "login_attempt_rate_limits"
    __table_args__ = (
        UniqueConstraint(
            "subject_type",
            "subject_hash",
            name="uq_login_attempt_rate_limit_subject",
        ),
        Index("ix_login_attempt_rate_limits_window_start", "window_start"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class WorkspaceOutputTokenBudget(Base):
    __tablename__ = "workspace_output_token_budgets"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_workspace_output_token_budget"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), nullable=False)
    monthly_output_token_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class WorkspaceModelPrice(Base):
    """Workspace-configured provider rates, expressed in USD per one million tokens."""

    __tablename__ = "workspace_model_prices"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "provider",
            "model",
            name="uq_workspace_model_price_provider_model",
        ),
        Index("ix_workspace_model_prices_workspace_id", "workspace_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    input_usd_per_million_tokens: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    output_usd_per_million_tokens: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(120), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class SkillRun(Base):
    __tablename__ = "skill_runs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_skill_runs_workspace_idempotency"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    skill_id: Mapped[str] = mapped_column(String(120), nullable=False)
    skill_version: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    inputs_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    output: Mapped[str] = mapped_column(Text, default="", nullable=False)
    evaluation_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_price_usd_per_million_tokens: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    output_price_usd_per_million_tokens: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(30, 16), nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    requested_max_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    budget_charged_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    execution_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def evaluation(self) -> dict[str, Any] | None:
        if self.status != "completed":
            return None
        try:
            value = json.loads(self.evaluation_json or "{}")
        except (TypeError, ValueError):
            value = {}
        if isinstance(value, dict) and value:
            return value

        # Backfill-compatible fallback for completed runs created before snapshots existed.
        from emporia_api.skills.evaluation import evaluate_skill_output
        from emporia_api.skills.registry import get_skill

        skill = get_skill(self.skill_id)
        if skill is None or skill.version != self.skill_version:
            return None
        return evaluate_skill_output(skill, self.output)

    @property
    def inputs(self) -> dict[str, Any]:
        try:
            value = json.loads(self.inputs_json or "{}")
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    @property
    def calculations(self) -> dict[str, Any]:
        from emporia_api.skills.calculations import calculate_skill
        from emporia_api.skills.registry import get_skill

        skill = get_skill(self.skill_id)
        if skill is None or skill.version != self.skill_version:
            return {}
        return calculate_skill(self.skill_id, self.inputs)



class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_background_jobs_workspace_idempotency_key",
        ),
        Index("ix_background_jobs_status_available_at", "status", "available_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[str] = mapped_column(String(120), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    result_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def payload(self) -> dict[str, Any]:
        try:
            value = json.loads(self.payload_json or "{}")
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}



class BusinessActionRequest(Base):
    __tablename__ = "business_action_requests"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_business_action_idempotency",
        ),
        Index("ix_business_action_requests_status_requested_at", "status", "requested_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(120), nullable=False)
    target_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    inputs_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="pending_approval", server_default="pending_approval", nullable=False
    )
    requested_by: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    rejected_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    decision_note: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    execution_block_reason: Mapped[str] = mapped_column(
        Text, default="", server_default="", nullable=False
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def inputs(self) -> dict[str, Any]:
        try:
            value = json.loads(self.inputs_json or "{}")
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}
