"""Add workspace-scoped business action approvals.

Revision ID: 0008_business_action_requests
Revises: 0007_background_jobs
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_business_action_requests"
down_revision = "0007_background_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business_action_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("action_type", sa.String(length=120), nullable=False),
        sa.Column("target_ref", sa.String(length=160), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("inputs_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="pending_approval", nullable=False),
        sa.Column("requested_by", sa.String(length=36), nullable=False),
        sa.Column("approved_by", sa.String(length=36), nullable=True),
        sa.Column("rejected_by", sa.String(length=36), nullable=True),
        sa.Column("decision_note", sa.Text(), server_default="", nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=True),
        sa.Column("execution_block_reason", sa.Text(), server_default="", nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rejected_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_business_action_idempotency"
        ),
    )
    op.create_index(
        "ix_business_action_requests_workspace_id",
        "business_action_requests",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_business_action_requests_status_requested_at",
        "business_action_requests",
        ["status", "requested_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_business_action_requests_status_requested_at",
        table_name="business_action_requests",
    )
    op.drop_index(
        "ix_business_action_requests_workspace_id",
        table_name="business_action_requests",
    )
    op.drop_table("business_action_requests")
