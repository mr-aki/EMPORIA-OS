"""Add workspace-scoped inventory reorder policies."""

from alembic import op
import sqlalchemy as sa


revision = "0018_inventory_reorder_policies"
down_revision = "0017_sale_linked_returns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_reorder_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=120), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("reorder_point", sa.Integer(), server_default="0", nullable=False),
        sa.Column("target_stock", sa.Integer(), nullable=False),
        sa.Column("lead_time_days", sa.Integer(), server_default="14", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "reorder_point >= 0",
            name="ck_inventory_reorder_policies_reorder_point_nonnegative",
        ),
        sa.CheckConstraint(
            "target_stock > reorder_point",
            name="ck_inventory_reorder_policies_target_above_reorder_point",
        ),
        sa.CheckConstraint(
            "lead_time_days >= 0 AND lead_time_days <= 365",
            name="ck_inventory_reorder_policies_lead_time_range",
        ),
        sa.ForeignKeyConstraint(
            ["product_id", "workspace_id"],
            ["products.id", "products.workspace_id"],
            name="fk_inventory_reorder_policies_product_workspace",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "product_id",
            name="uq_inventory_reorder_policies_workspace_product",
        ),
    )
    op.create_index(
        "ix_inventory_reorder_policies_workspace_product",
        "inventory_reorder_policies",
        ["workspace_id", "product_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inventory_reorder_policies_workspace_product",
        table_name="inventory_reorder_policies",
    )
    op.drop_table("inventory_reorder_policies")
