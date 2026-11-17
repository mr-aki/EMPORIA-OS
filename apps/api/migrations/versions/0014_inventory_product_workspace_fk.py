"""Enforce workspace-consistent product references in inventory movements."""

from alembic import op


revision = "0014_inventory_product_workspace_fk"
down_revision = "0013_product_inventory_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite requires a unique parent key for the composite foreign key. The
    # product id is already globally unique, but the composite key makes the
    # workspace boundary explicit and enforceable by every database writer.
    op.create_index(
        "uq_products_id_workspace",
        "products",
        ["id", "workspace_id"],
        unique=True,
    )
    with op.batch_alter_table("inventory_movements") as batch_op:
        batch_op.drop_constraint(
            "fk_inventory_movements_product_id_products",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_inventory_movements_product_workspace",
            "products",
            ["product_id", "workspace_id"],
            ["id", "workspace_id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("inventory_movements") as batch_op:
        batch_op.drop_constraint(
            "fk_inventory_movements_product_workspace",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_inventory_movements_product_id_products",
            "products",
            ["product_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.drop_index("uq_products_id_workspace", table_name="products")
