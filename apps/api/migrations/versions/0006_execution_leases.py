"""Add expiring execution leases for workspace concurrency limits.

Revision ID: 0006_execution_leases
Revises: 0005_workspace_output_budgets
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_execution_leases"
down_revision = "0005_workspace_output_budgets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.add_column(
            sa.Column("execution_lease_expires_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_index(
            "ix_agent_runs_execution_lease_expires_at",
            ["execution_lease_expires_at"],
        )

    with op.batch_alter_table("skill_runs") as batch_op:
        batch_op.add_column(
            sa.Column("execution_lease_expires_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_index(
            "ix_skill_runs_execution_lease_expires_at",
            ["execution_lease_expires_at"],
        )


def downgrade() -> None:
    with op.batch_alter_table("skill_runs") as batch_op:
        batch_op.drop_index("ix_skill_runs_execution_lease_expires_at")
        batch_op.drop_column("execution_lease_expires_at")

    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_index("ix_agent_runs_execution_lease_expires_at")
        batch_op.drop_column("execution_lease_expires_at")
