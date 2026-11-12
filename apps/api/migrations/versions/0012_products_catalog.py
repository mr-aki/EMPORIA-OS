"""Add workspace-scoped product catalog records."""

from alembic import op
import sqlalchemy as sa


revision = "0012_products_catalog"
down_revision = "0011_workspace_model_costs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("sku", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("vendor", sa.String(length=160), server_default="", nullable=False),
        sa.Column("product_type", sa.String(length=120), server_default="", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("price_amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("cost_amount", sa.Numeric(18, 4), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "sku", name="uq_products_workspace_sku"),
    )
    op.create_index("ix_products_workspace_id", "products", ["workspace_id"])
    op.create_index(
        "ix_products_workspace_status_created_at",
        "products",
        ["workspace_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_products_workspace_status_created_at", table_name="products")
    op.drop_index("ix_products_workspace_id", table_name="products")
    op.drop_table("products")
