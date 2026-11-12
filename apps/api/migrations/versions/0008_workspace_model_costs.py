"""Add explicit workspace model pricing and immutable run cost snapshots."""

from alembic import op
import sqlalchemy as sa


revision = "0008_workspace_model_costs"
down_revision = "0007_background_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_model_prices",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("input_usd_per_million_tokens", sa.Numeric(20, 10), nullable=False),
        sa.Column("output_usd_per_million_tokens", sa.Numeric(20, 10), nullable=False),
        sa.Column("updated_by", sa.String(length=120), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "provider",
            "model",
            name="uq_workspace_model_price_provider_model",
        ),
    )
    op.create_index(
        "ix_workspace_model_prices_workspace_id",
        "workspace_model_prices",
        ["workspace_id"],
    )

    for table_name in ("agent_runs", "skill_runs"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(
                sa.Column("input_price_usd_per_million_tokens", sa.Numeric(20, 10), nullable=True)
            )
            batch_op.add_column(
                sa.Column("output_price_usd_per_million_tokens", sa.Numeric(20, 10), nullable=True)
            )
            batch_op.add_column(
                sa.Column("estimated_cost_usd", sa.Numeric(30, 16), nullable=True)
            )


def downgrade() -> None:
    for table_name in ("skill_runs", "agent_runs"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_column("estimated_cost_usd")
            batch_op.drop_column("output_price_usd_per_million_tokens")
            batch_op.drop_column("input_price_usd_per_million_tokens")

    op.drop_index(
        "ix_workspace_model_prices_workspace_id",
        table_name="workspace_model_prices",
    )
    op.drop_table("workspace_model_prices")
