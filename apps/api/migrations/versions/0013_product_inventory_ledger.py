"""Add an append-only inventory movement ledger for products."""

from alembic import op
import sqlalchemy as sa


revision = "0013_product_inventory_ledger"
down_revision = "0012_workspace_product_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_movements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=120), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("movement_type", sa.String(length=20), nullable=False),
        sa.Column("quantity_delta", sa.Integer(), nullable=False),
        sa.Column("quantity_after", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "quantity_delta <> 0",
            name="ck_inventory_movements_nonzero_delta",
        ),
        sa.CheckConstraint(
            "quantity_after >= 0",
            name="ck_inventory_movements_nonnegative_balance",
        ),
        sa.CheckConstraint(
            "movement_type IN ('receipt', 'sale', 'return', 'damage', 'adjustment')",
            name="ck_inventory_movements_type",
        ),
        sa.CheckConstraint(
            "((movement_type IN ('receipt', 'return') AND quantity_delta > 0) "
            "OR (movement_type IN ('sale', 'damage') AND quantity_delta < 0) "
            "OR (movement_type = 'adjustment' AND quantity_delta <> 0))",
            name="ck_inventory_movements_direction",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_inventory_movements_product_id_products",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_inventory_movements_workspace_idempotency",
        ),
    )
    op.create_index(
        "ix_inventory_movements_workspace_product_created_at",
        "inventory_movements",
        ["workspace_id", "product_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inventory_movements_workspace_product_created_at",
        table_name="inventory_movements",
    )
    op.drop_table("inventory_movements")
