"""Persist idempotency keys for agent and skill executions.

Revision ID: 0003_run_idempotency
Revises: 0002_skill_runs
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_run_idempotency"
down_revision = "0002_skill_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.add_column(sa.Column("idempotency_key", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("request_fingerprint", sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint(
            "uq_agent_runs_workspace_idempotency",
            ["workspace_id", "idempotency_key"],
        )

    with op.batch_alter_table("skill_runs") as batch_op:
        batch_op.add_column(sa.Column("idempotency_key", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("request_fingerprint", sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint(
            "uq_skill_runs_workspace_idempotency",
            ["workspace_id", "idempotency_key"],
        )


def downgrade() -> None:
    with op.batch_alter_table("skill_runs") as batch_op:
        batch_op.drop_constraint("uq_skill_runs_workspace_idempotency", type_="unique")
        batch_op.drop_column("request_fingerprint")
        batch_op.drop_column("idempotency_key")

    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_constraint("uq_agent_runs_workspace_idempotency", type_="unique")
        batch_op.drop_column("request_fingerprint")
        batch_op.drop_column("idempotency_key")
