"""Create initial Emporia tables and add research evidence persistence.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _indexes(table_name: str) -> set[str]:
    return {item["name"] for item in inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    tables = _tables()

    if "ventures" not in tables:
        op.create_table(
            "ventures",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("workspace_id", sa.String(120), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(30), nullable=False, server_default="planning"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        tables.add("ventures")

    if "audit_events" not in tables:
        op.create_table(
            "audit_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("workspace_id", sa.String(120), nullable=False),
            sa.Column("actor", sa.String(120), nullable=False),
            sa.Column("action", sa.String(100), nullable=False),
            sa.Column("resource_type", sa.String(80), nullable=False),
            sa.Column("resource_id", sa.String(36), nullable=False),
            sa.Column("detail", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        tables.add("audit_events")

    if "agent_runs" not in tables:
        op.create_table(
            "agent_runs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("workspace_id", sa.String(120), nullable=False),
            sa.Column("agent_id", sa.String(100), nullable=False),
            sa.Column("agent_version", sa.String(30), nullable=False),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("model", sa.String(128), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="running"),
            sa.Column("task", sa.Text(), nullable=False),
            sa.Column("output", sa.Text(), nullable=False, server_default=""),
            sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
            sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("provider_request_id", sa.String(160), nullable=True),
            sa.Column("research_sources_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
        tables.add("agent_runs")
    else:
        columns = {column["name"] for column in inspect(op.get_bind()).get_columns("agent_runs")}
        if "research_sources_json" not in columns:
            op.add_column(
                "agent_runs",
                sa.Column(
                    "research_sources_json",
                    sa.Text(),
                    nullable=False,
                    server_default=sa.text("'[]'"),
                ),
            )

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("email", sa.String(320), nullable=False),
            sa.Column("display_name", sa.String(120), nullable=False),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("email", name="uq_users_email"),
        )
        tables.add("users")

    if "workspaces" not in tables:
        op.create_table(
            "workspaces",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column(
                "owner_user_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        tables.add("workspaces")

    if "workspace_memberships" not in tables:
        op.create_table(
            "workspace_memberships",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "workspace_id",
                sa.String(36),
                sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_membership"),
        )
        tables.add("workspace_memberships")

    for table_name in ("ventures", "audit_events", "agent_runs"):
        index_name = f"ix_{table_name}_workspace_id"
        if index_name not in _indexes(table_name):
            op.create_index(index_name, table_name, ["workspace_id"], unique=False)

    for table_name, column_name in (
        ("workspace_memberships", "workspace_id"),
        ("workspace_memberships", "user_id"),
    ):
        index_name = f"ix_{table_name}_{column_name}"
        if index_name not in _indexes(table_name):
            op.create_index(index_name, table_name, [column_name], unique=False)


def downgrade() -> None:
    # Preserve existing commerce and agent data during rollback.
    op.drop_table("workspace_memberships")
    op.drop_table("workspaces")
    op.drop_table("users")
