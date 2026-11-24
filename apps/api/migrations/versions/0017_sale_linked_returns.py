"""Add sale-linked returns and immutable FIFO cost reversals."""

from alembic import op
import sqlalchemy as sa


revision = "0017_sale_linked_returns"
down_revision = "0016_fifo_inventory_costs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_inventory_movements_id_workspace_product",
        "inventory_movements",
        ["id", "workspace_id", "product_id"],
        unique=True,
    )
    op.create_index(
        "uq_inventory_cost_layers_id_workspace_product",
        "inventory_cost_layers",
        ["id", "workspace_id", "product_id"],
        unique=True,
    )
    op.create_index(
        "uq_inventory_cost_allocations_id_layer_workspace",
        "inventory_cost_allocations",
        ["id", "cost_layer_id", "workspace_id"],
        unique=True,
    )

    op.create_table(
        "inventory_returns",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=120), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("source_sale_movement_id", sa.String(length=36), nullable=False),
        sa.Column("return_movement_id", sa.String(length=36), nullable=False),
        sa.Column("quantity_returned", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "quantity_returned > 0",
            name="ck_inventory_returns_quantity_positive",
        ),
        sa.ForeignKeyConstraint(
            ["source_sale_movement_id", "workspace_id", "product_id"],
            ["inventory_movements.id", "inventory_movements.workspace_id", "inventory_movements.product_id"],
            name="fk_inventory_returns_source_sale_workspace_product",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["return_movement_id", "workspace_id", "product_id"],
            ["inventory_movements.id", "inventory_movements.workspace_id", "inventory_movements.product_id"],
            name="fk_inventory_returns_movement_workspace_product",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "workspace_id", "product_id",
            name="uq_inventory_returns_id_workspace_product",
        ),
        sa.UniqueConstraint(
            "return_movement_id",
            name="uq_inventory_returns_return_movement",
        ),
    )
    op.create_index(
        "ix_inventory_returns_workspace_source_sale",
        "inventory_returns",
        ["workspace_id", "source_sale_movement_id"],
        unique=False,
    )

    op.create_table(
        "inventory_cost_return_allocations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=120), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("inventory_return_id", sa.String(length=36), nullable=False),
        sa.Column("source_cost_allocation_id", sa.String(length=36), nullable=True),
        sa.Column("cost_layer_id", sa.String(length=36), nullable=False),
        sa.Column("quantity_returned", sa.Integer(), nullable=False),
        sa.Column("unit_cost", sa.Numeric(20, 4), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("extended_cost", sa.Numeric(30, 8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "quantity_returned > 0",
            name="ck_inventory_cost_return_allocations_quantity_positive",
        ),
        sa.CheckConstraint(
            "((unit_cost IS NULL AND currency IS NULL AND extended_cost IS NULL) OR "
            "(unit_cost IS NOT NULL AND unit_cost >= 0 AND currency IS NOT NULL "
            "AND extended_cost IS NOT NULL AND extended_cost >= 0))",
            name="ck_inventory_cost_return_allocations_cost_currency_pair",
        ),
        sa.ForeignKeyConstraint(
            ["inventory_return_id", "workspace_id", "product_id"],
            ["inventory_returns.id", "inventory_returns.workspace_id", "inventory_returns.product_id"],
            name="fk_inventory_cost_return_allocations_return_workspace_product",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cost_layer_id", "workspace_id", "product_id"],
            ["inventory_cost_layers.id", "inventory_cost_layers.workspace_id", "inventory_cost_layers.product_id"],
            name="fk_inventory_cost_return_allocations_layer_workspace_product",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_cost_allocation_id", "cost_layer_id", "workspace_id"],
            ["inventory_cost_allocations.id", "inventory_cost_allocations.cost_layer_id", "inventory_cost_allocations.workspace_id"],
            name="fk_inventory_cost_return_allocations_source_layer_workspace",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "inventory_return_id", "source_cost_allocation_id",
            name="uq_inventory_cost_return_allocations_return_source",
        ),
    )
    op.create_index(
        "ix_inventory_cost_return_allocations_workspace_return",
        "inventory_cost_return_allocations",
        ["workspace_id", "inventory_return_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inventory_cost_return_allocations_workspace_return",
        table_name="inventory_cost_return_allocations",
    )
    op.drop_table("inventory_cost_return_allocations")
    op.drop_index(
        "ix_inventory_returns_workspace_source_sale",
        table_name="inventory_returns",
    )
    op.drop_table("inventory_returns")
    op.drop_index(
        "uq_inventory_cost_allocations_id_layer_workspace",
        table_name="inventory_cost_allocations",
    )
    op.drop_index(
        "uq_inventory_cost_layers_id_workspace_product",
        table_name="inventory_cost_layers",
    )
    op.drop_index(
        "uq_inventory_movements_id_workspace_product",
        table_name="inventory_movements",
    )
