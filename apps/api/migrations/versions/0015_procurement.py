"""Add workspace-scoped suppliers, purchase orders, and idempotent receipts."""

from alembic import op
import sqlalchemy as sa


revision = "0015_procurement"
down_revision = "0014_inventory_ws_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_inventory_movements_id_workspace",
        "inventory_movements",
        ["id", "workspace_id"],
        unique=True,
    )
    op.create_table(
        "suppliers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=120), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("contact_email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=60), nullable=True),
        sa.Column("website", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_suppliers_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workspace_id", name="uq_suppliers_id_workspace"),
        sa.UniqueConstraint("workspace_id", "code", name="uq_suppliers_workspace_code"),
    )
    op.create_index(
        "ix_suppliers_workspace_created_at",
        "suppliers",
        ["workspace_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=120), nullable=False),
        sa.Column("supplier_id", sa.String(length=36), nullable=False),
        sa.Column("order_number", sa.String(length=80), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="draft", nullable=False),
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'ordered', 'partially_received', 'received', 'cancelled')",
            name="ck_purchase_orders_status",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id", "workspace_id"],
            ["suppliers.id", "suppliers.workspace_id"],
            name="fk_purchase_orders_supplier_workspace",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workspace_id", name="uq_purchase_orders_id_workspace"),
        sa.UniqueConstraint(
            "workspace_id", "order_number", name="uq_purchase_orders_workspace_number"
        ),
    )
    op.create_index(
        "ix_purchase_orders_workspace_created_at",
        "purchase_orders",
        ["workspace_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=120), nullable=False),
        sa.Column("purchase_order_id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("quantity_ordered", sa.Integer(), nullable=False),
        sa.Column("quantity_received", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unit_cost", sa.Numeric(20, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "quantity_ordered > 0", name="ck_purchase_order_lines_ordered_positive"
        ),
        sa.CheckConstraint(
            "quantity_received >= 0 AND quantity_received <= quantity_ordered",
            name="ck_purchase_order_lines_received_range",
        ),
        sa.CheckConstraint(
            "unit_cost >= 0", name="ck_purchase_order_lines_unit_cost_nonnegative"
        ),
        sa.ForeignKeyConstraint(
            ["purchase_order_id", "workspace_id"],
            ["purchase_orders.id", "purchase_orders.workspace_id"],
            name="fk_purchase_order_lines_order_workspace",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id", "workspace_id"],
            ["products.id", "products.workspace_id"],
            name="fk_purchase_order_lines_product_workspace",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "purchase_order_id", "product_id",
            name="uq_purchase_order_lines_order_product",
        ),
    )
    op.create_index(
        "ix_purchase_order_lines_workspace_order",
        "purchase_order_lines",
        ["workspace_id", "purchase_order_id"],
        unique=False,
    )
    op.create_table(
        "purchase_order_receipts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=120), nullable=False),
        sa.Column("purchase_order_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["purchase_order_id", "workspace_id"],
            ["purchase_orders.id", "purchase_orders.workspace_id"],
            name="fk_purchase_order_receipts_order_workspace",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workspace_id", name="uq_purchase_order_receipts_id_workspace"),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key",
            name="uq_purchase_order_receipts_workspace_idempotency",
        ),
    )
    op.create_index(
        "ix_purchase_order_receipts_workspace_order_created",
        "purchase_order_receipts",
        ["workspace_id", "purchase_order_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "purchase_order_receipt_lines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=120), nullable=False),
        sa.Column("receipt_id", sa.String(length=36), nullable=False),
        sa.Column("purchase_order_line_id", sa.String(length=36), nullable=False),
        sa.Column("inventory_movement_id", sa.String(length=36), nullable=False),
        sa.Column("quantity_received", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "quantity_received > 0", name="ck_purchase_order_receipt_lines_positive"
        ),
        sa.ForeignKeyConstraint(
            ["receipt_id", "workspace_id"],
            ["purchase_order_receipts.id", "purchase_order_receipts.workspace_id"],
            name="fk_purchase_order_receipt_lines_receipt_workspace",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_order_line_id", "workspace_id"],
            ["purchase_order_lines.id", "purchase_order_lines.workspace_id"],
            name="fk_purchase_order_receipt_lines_order_line_workspace",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["inventory_movement_id"],
            ["inventory_movements.id"],
            name="fk_purchase_order_receipt_lines_inventory_movement",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "receipt_id", "purchase_order_line_id",
            name="uq_purchase_order_receipt_lines_receipt_line",
        ),
        sa.UniqueConstraint(
            "inventory_movement_id",
            name="uq_purchase_order_receipt_lines_inventory_movement",
        ),
    )


def downgrade() -> None:
    op.drop_table("purchase_order_receipt_lines")
    op.drop_index(
        "ix_purchase_order_receipts_workspace_order_created",
        table_name="purchase_order_receipts",
    )
    op.drop_table("purchase_order_receipts")
    op.drop_index("ix_purchase_order_lines_workspace_order", table_name="purchase_order_lines")
    op.drop_table("purchase_order_lines")
    op.drop_index("ix_purchase_orders_workspace_created_at", table_name="purchase_orders")
    op.drop_table("purchase_orders")
    op.drop_index("ix_suppliers_workspace_created_at", table_name="suppliers")
    op.drop_table("suppliers")
    op.drop_index(
        "uq_inventory_movements_id_workspace",
        table_name="inventory_movements",
    )
