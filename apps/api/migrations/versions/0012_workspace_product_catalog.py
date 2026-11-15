"""Add workspace-scoped product catalogue records."""

from alembic import op
import sqlalchemy as sa


revision = "0012_workspace_product_catalog"
down_revision = "0011_workspace_model_costs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=120), nullable=False),
        sa.Column("sku", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("unit_price", sa.Numeric(20, 4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("unit_price > 0", name="ck_products_unit_price_positive"),
        sa.CheckConstraint("status IN ('draft', 'active', 'archived')", name="ck_products_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "sku", name="uq_products_workspace_sku"),
    )
    op.create_index(
        "ix_products_workspace_created_at", "products",
        ["workspace_id", "created_at"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_products_workspace_created_at", table_name="products")
    op.drop_table("products")
