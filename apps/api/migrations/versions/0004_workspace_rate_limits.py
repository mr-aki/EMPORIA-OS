"""Add fixed-window workspace execution rate-limit storage.

Revision ID: 0004_workspace_rate_limits
Revises: 0003_run_idempotency
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_workspace_rate_limits"
down_revision = "0003_run_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_execution_rate_limits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=120), nullable=False),
        sa.Column("execution_type", sa.String(length=20), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "execution_type",
            name="uq_workspace_execution_rate_limit",
        ),
    )


def downgrade() -> None:
    op.drop_table("workspace_execution_rate_limits")
