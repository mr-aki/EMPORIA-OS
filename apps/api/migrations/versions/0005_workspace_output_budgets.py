"""Add workspace monthly output-token budgets and run reservations.

Revision ID: 0005_workspace_output_budgets
Revises: 0004_workspace_rate_limits
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_workspace_output_budgets"
down_revision = "0004_workspace_rate_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.add_column(
            sa.Column("requested_max_tokens", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("budget_charged_tokens", sa.Integer(), nullable=False, server_default="0")
        )

    with op.batch_alter_table("skill_runs") as batch_op:
        batch_op.add_column(
            sa.Column("requested_max_tokens", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("budget_charged_tokens", sa.Integer(), nullable=False, server_default="0")
        )

    op.create_table(
        "workspace_output_token_budgets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=120), nullable=False),
        sa.Column("monthly_output_token_limit", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", name="uq_workspace_output_token_budget"),
    )


def downgrade() -> None:
    op.drop_table("workspace_output_token_budgets")

    with op.batch_alter_table("skill_runs") as batch_op:
        batch_op.drop_column("budget_charged_tokens")
        batch_op.drop_column("requested_max_tokens")

    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_column("budget_charged_tokens")
        batch_op.drop_column("requested_max_tokens")
