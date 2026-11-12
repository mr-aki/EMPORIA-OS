"""Add the durable background job queue.

Revision ID: 0003_background_jobs
Revises: 0002_skill_runs
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_background_jobs"
down_revision = "0002_skill_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=120), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.String(length=120), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=120), nullable=True),
        sa.Column("idempotency_key", sa.String(length=120), nullable=True),
        sa.Column("result_id", sa.String(length=36), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_background_jobs_workspace_idempotency_key",
        ),
    )
    op.create_index(
        "ix_background_jobs_workspace_id",
        "background_jobs",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_background_jobs_status_available_at",
        "background_jobs",
        ["status", "available_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_background_jobs_status_available_at",
        table_name="background_jobs",
    )
    op.drop_index(
        "ix_background_jobs_workspace_id",
        table_name="background_jobs",
    )
    op.drop_table("background_jobs")
