"""Add monthly workspace monetary budgets and per-run reservation accounting."""

from alembic import op
import sqlalchemy as sa


revision = "0012_workspace_monthly_cost_budgets"
down_revision = "0011_workspace_model_costs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_monthly_cost_budgets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=120), nullable=False),
        sa.Column("monthly_cost_budget_usd", sa.Numeric(20, 10), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", name="uq_workspace_monthly_cost_budget"),
    )
    for table_name in ("agent_runs", "skill_runs"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(sa.Column("reserved_output_cost_usd", sa.Numeric(30, 16), nullable=True))
            batch_op.add_column(sa.Column("budget_charged_cost_usd", sa.Numeric(30, 16), nullable=True))


def downgrade() -> None:
    for table_name in ("skill_runs", "agent_runs"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_column("budget_charged_cost_usd")
            batch_op.drop_column("reserved_output_cost_usd")
    op.drop_table("workspace_monthly_cost_budgets")
