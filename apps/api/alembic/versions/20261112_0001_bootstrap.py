"""Bootstrap the Emporia API schema and add research source persistence.

Revision ID: 20261112_0001
Revises:
Create Date: 2026-11-12
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261112_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _ensure_index(table_name: str, index_name: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {item["name"] for item in inspector.get_indexes(table_name)}
    if index_name not in existing:
        op.create_index(index_name, table_name, columns, unique=False)


def upgrade() -> None:
    """Create missing application tables and patch older agent_runs schemas safely."""
    tables = _table_names()

    if "ventures" not in tables:
        op.create_table(
            "ventures",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("workspace_id", sa.String(length=120), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("description", sa.Text(), server_default="", nullable=False),
            sa.Column("status", sa.String(length=30), server_default="planning", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    _ensure_index("ventures", "ix_ventures_workspace_id", ["workspace_id"])

    if "audit_events" not in tables:
        op.create_table(
            "audit_events",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("workspace_id", sa.String(length=120), nullable=False),
            sa.Column("actor", sa.String(length=120), nullable=False),
            sa.Column("action", sa.String(length=100), nullable=False),
            sa.Column("resource_type", sa.String(length=80), nullable=False),
            sa.Column("resource_id", sa.String(length=36), nullable=False),
            sa.Column("detail", sa.Text(), server_default="", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    _ensure_index("audit_events", "ix_audit_events_workspace_id", ["workspace_id"])

    if "agent_runs" not in tables:
        op.create_table(
            "agent_runs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("workspace_id", sa.String(length=120), nullable=False),
            sa.Column("agent_id", sa.String(length=100), nullable=False),
            sa.Column("agent_version", sa.String(length=30), nullable=False),
            sa.Column("provider", sa.String(length=40), nullable=False),
            sa.Column("model", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=20), server_default="running", nullable=False),
            sa.Column("task", sa.Text(), nullable=False),
            sa.Column("output", sa.Text(), server_default="", nullable=False),
            sa.Column("error_message", sa.Text(), server_default="", nullable=False),
            sa.Column("prompt_tokens", sa.Integer(), server_default="0", nullable=False),
            sa.Column("completion_tokens", sa.Integer(), server_default="0", nullable=False),
            sa.Column("total_tokens", sa.Integer(), server_default="0", nullable=False),
            sa.Column("provider_request_id", sa.String(length=160), nullable=True),
            sa.Column(
                "research_sources_json",
                sa.Text(),
                server_default=sa.text("'[]'"),
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
    else:
        columns = {
            column["name"] for column in sa.inspect(op.get_bind()).get_columns("agent_runs")
        }
        if "research_sources_json" not in columns:
            # A constant server default backfills existing rows on SQLite and PostgreSQL.
            op.add_column(
                "agent_runs",
                sa.Column(
                    "research_sources_json",
                    sa.Text(),
                    server_default=sa.text("'[]'"),
                    nullable=False,
                ),
            )
    _ensure_index("agent_runs", "ix_agent_runs_workspace_id", ["workspace_id"])


def downgrade() -> None:
    """Remove the bootstrap schema.

    This is the initial schema revision. Downgrading it drops application data;
    take and verify a database backup before running `alembic downgrade base`.
    """
    tables = _table_names()
    for table_name in ("agent_runs", "audit_events", "ventures"):
        if table_name in tables:
            op.drop_table(table_name)
