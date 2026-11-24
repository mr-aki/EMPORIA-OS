"""Add durable workspace-scoped workflow runs."""

from alembic import op
import sqlalchemy as sa


revision = "0012_workflow_runs"
down_revision = "0011_workspace_model_costs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=120), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("steps_json", sa.Text(), nullable=False),
        sa.Column("total_steps", sa.Integer(), nullable=False),
        sa.Column("completed_steps", sa.Integer(), nullable=False),
        sa.Column("failed_step", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("background_job_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_workflow_runs_workspace_idempotency",
        ),
    )
    op.create_index("ix_workflow_runs_workspace_id", "workflow_runs", ["workspace_id"])
    op.create_index("ix_workflow_runs_background_job_id", "workflow_runs", ["background_job_id"])
    op.create_index(
        "ix_workflow_runs_workspace_created",
        "workflow_runs",
        ["workspace_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_workspace_created", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_background_job_id", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_workspace_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")
