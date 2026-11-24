"""Add FIFO inventory cost layers and sale cost allocations."""

from datetime import UTC, datetime
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "0016_fifo_inventory_costs"
down_revision = "0015_procurement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_cost_layers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=120), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("source_inventory_movement_id", sa.String(length=36), nullable=True),
        sa.Column("source_type", sa.String(length=24), nullable=False),
        sa.Column("quantity_received", sa.Integer(), nullable=False),
        sa.Column("quantity_remaining", sa.Integer(), nullable=False),
        sa.Column("unit_cost", sa.Numeric(20, 4), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "quantity_received > 0",
            name="ck_inventory_cost_layers_received_positive",
        ),
        sa.CheckConstraint(
            "quantity_remaining >= 0 AND quantity_remaining <= quantity_received",
            name="ck_inventory_cost_layers_remaining_range",
        ),
        sa.CheckConstraint(
            "((unit_cost IS NULL AND currency IS NULL) OR "
            "(unit_cost IS NOT NULL AND unit_cost >= 0 AND currency IS NOT NULL))",
            name="ck_inventory_cost_layers_cost_currency_pair",
        ),
        sa.CheckConstraint(
            "((source_type = 'opening_balance' AND source_inventory_movement_id IS NULL) OR "
            "(source_type = 'inventory_movement' AND source_inventory_movement_id IS NOT NULL))",
            name="ck_inventory_cost_layers_source",
        ),
        sa.ForeignKeyConstraint(
            ["product_id", "workspace_id"],
            ["products.id", "products.workspace_id"],
            name="fk_inventory_cost_layers_product_workspace",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_inventory_movement_id", "workspace_id"],
            ["inventory_movements.id", "inventory_movements.workspace_id"],
            name="fk_inventory_cost_layers_source_movement_workspace",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "workspace_id",
            name="uq_inventory_cost_layers_id_workspace",
        ),
        sa.UniqueConstraint(
            "source_inventory_movement_id",
            name="uq_inventory_cost_layers_source_movement",
        ),
    )
    op.create_index(
        "ix_inventory_cost_layers_fifo",
        "inventory_cost_layers",
        ["workspace_id", "product_id", "created_at", "id"],
        unique=False,
    )

    op.create_table(
        "inventory_cost_allocations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=120), nullable=False),
        sa.Column("inventory_movement_id", sa.String(length=36), nullable=False),
        sa.Column("cost_layer_id", sa.String(length=36), nullable=False),
        sa.Column("quantity_allocated", sa.Integer(), nullable=False),
        sa.Column("unit_cost", sa.Numeric(20, 4), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("extended_cost", sa.Numeric(30, 8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "quantity_allocated > 0",
            name="ck_inventory_cost_allocations_quantity_positive",
        ),
        sa.CheckConstraint(
            "((unit_cost IS NULL AND currency IS NULL AND extended_cost IS NULL) OR "
            "(unit_cost IS NOT NULL AND unit_cost >= 0 AND currency IS NOT NULL "
            "AND extended_cost IS NOT NULL AND extended_cost >= 0))",
            name="ck_inventory_cost_allocations_cost_currency_pair",
        ),
        sa.ForeignKeyConstraint(
            ["inventory_movement_id", "workspace_id"],
            ["inventory_movements.id", "inventory_movements.workspace_id"],
            name="fk_inventory_cost_allocations_movement_workspace",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cost_layer_id", "workspace_id"],
            ["inventory_cost_layers.id", "inventory_cost_layers.workspace_id"],
            name="fk_inventory_cost_allocations_layer_workspace",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "inventory_movement_id", "cost_layer_id",
            name="uq_inventory_cost_allocations_movement_layer",
        ),
    )
    op.create_index(
        "ix_inventory_cost_allocations_workspace_movement",
        "inventory_cost_allocations",
        ["workspace_id", "inventory_movement_id"],
        unique=False,
    )

    # Existing stock predates cost layers. Preserve it as an explicit unknown-cost
    # opening layer so subsequent FIFO sales remain reconcilable without inventing cost.
    connection = op.get_bind()
    balances = connection.execute(
        sa.text(
            """
            SELECT workspace_id, product_id, SUM(quantity_delta) AS quantity
            FROM inventory_movements
            GROUP BY workspace_id, product_id
            HAVING SUM(quantity_delta) > 0
            """
        )
    ).mappings()
    created_at = datetime.now(UTC)
    insert_layer = sa.text(
        """
        INSERT INTO inventory_cost_layers (
            id, workspace_id, product_id, source_inventory_movement_id,
            source_type, quantity_received, quantity_remaining,
            unit_cost, currency, created_at
        ) VALUES (
            :id, :workspace_id, :product_id, NULL,
            'opening_balance', :quantity, :quantity,
            NULL, NULL, :created_at
        )
        """
    )
    for balance in balances:
        connection.execute(
            insert_layer,
            {
                "id": str(uuid4()),
                "workspace_id": balance["workspace_id"],
                "product_id": balance["product_id"],
                "quantity": int(balance["quantity"]),
                "created_at": created_at,
            },
        )


def downgrade() -> None:
    op.drop_index(
        "ix_inventory_cost_allocations_workspace_movement",
        table_name="inventory_cost_allocations",
    )
    op.drop_table("inventory_cost_allocations")
    op.drop_index(
        "ix_inventory_cost_layers_fifo",
        table_name="inventory_cost_layers",
    )
    op.drop_table("inventory_cost_layers")
