from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from emporia_api.config import settings


def _upgrade(database_url: str) -> None:
    settings.database_url = database_url
    command.upgrade(Config("alembic.ini"), "head")


def test_fresh_database_upgrades_to_head(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'fresh-migrations.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)

    _upgrade(database_url)
    _upgrade(database_url)

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert {
            "ventures",
            "audit_events",
            "agent_runs",
            "users",
            "workspaces",
            "workspace_memberships",
            "skill_runs",
            "alembic_version",
        }.issubset(set(inspector.get_table_names()))
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == "0005_workspace_output_budgets"
        assert {"idempotency_key", "request_fingerprint"}.issubset(
            {column["name"] for column in inspector.get_columns("agent_runs")}
        )
        assert {"idempotency_key", "request_fingerprint"}.issubset(
            {column["name"] for column in inspector.get_columns("skill_runs")}
        )
        assert "uq_agent_runs_workspace_idempotency" in {
            item["name"] for item in inspector.get_unique_constraints("agent_runs")
        }
        assert {"requested_max_tokens", "budget_charged_tokens"}.issubset(
            {column["name"] for column in inspector.get_columns("agent_runs")}
        )
        assert "workspace_output_token_budgets" in inspector.get_table_names()
        assert "workspace_execution_rate_limits" in inspector.get_table_names()
        assert "uq_skill_runs_workspace_idempotency" in {
            item["name"] for item in inspector.get_unique_constraints("skill_runs")
        }
        assert "workspace_execution_rate_limits" in inspector.get_table_names()
        assert "uq_workspace_execution_rate_limit" in {
            item["name"]
            for item in inspector.get_unique_constraints("workspace_execution_rate_limits")
        }
        assert "workspace_output_token_budgets" in inspector.get_table_names()
        assert "uq_workspace_output_token_budget" in {
            item["name"]
            for item in inspector.get_unique_constraints("workspace_output_token_budgets")
        }
        for table_name in ("agent_runs", "skill_runs"):
            assert {"requested_max_tokens", "budget_charged_tokens"}.issubset(
                {column["name"] for column in inspector.get_columns(table_name)}
            )
    finally:
        engine.dispose()


def test_migration_preserves_legacy_rows_and_adds_auth_tables(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'legacy-migrations.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)

    legacy_engine = create_engine(database_url)
    try:
        with legacy_engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE ventures (
                    id VARCHAR(36) PRIMARY KEY,
                    workspace_id VARCHAR(120) NOT NULL,
                    name VARCHAR(160) NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status VARCHAR(30) NOT NULL DEFAULT 'planning',
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
            """))
            connection.execute(text("""
                CREATE TABLE audit_events (
                    id VARCHAR(36) PRIMARY KEY,
                    workspace_id VARCHAR(120) NOT NULL,
                    actor VARCHAR(120) NOT NULL,
                    action VARCHAR(100) NOT NULL,
                    resource_type VARCHAR(80) NOT NULL,
                    resource_id VARCHAR(36) NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at DATETIME NOT NULL
                )
            """))
            connection.execute(text("""
                CREATE TABLE agent_runs (
                    id VARCHAR(36) PRIMARY KEY,
                    workspace_id VARCHAR(120) NOT NULL
                )
            """))
            connection.execute(text("""
                INSERT INTO ventures (
                    id, workspace_id, name, description, status, created_at, updated_at
                ) VALUES (
                    'venture-legacy', 'local-workspace', 'Legacy venture',
                    'Must survive migration', 'active', '2026-01-01', '2026-01-01'
                )
            """))
            connection.execute(text("""
                INSERT INTO agent_runs (id, workspace_id)
                VALUES ('run-legacy', 'local-workspace')
            """))

        _upgrade(database_url)

        with legacy_engine.connect() as connection:
            venture = connection.execute(
                text("SELECT name, description FROM ventures WHERE id = 'venture-legacy'")
            ).one()
            research_sources = connection.scalar(
                text("SELECT research_sources_json FROM agent_runs WHERE id = 'run-legacy'")
            )
        assert venture == ("Legacy venture", "Must survive migration")
        assert research_sources == "[]"

        inspector = inspect(legacy_engine)
        assert "users" in inspector.get_table_names()
        assert "workspaces" in inspector.get_table_names()
        assert "workspace_memberships" in inspector.get_table_names()
        assert "ix_ventures_workspace_id" in {
            item["name"] for item in inspector.get_indexes("ventures")
        }
        assert {"idempotency_key", "request_fingerprint"}.issubset(
            {column["name"] for column in inspector.get_columns("agent_runs")}
        )
        assert "uq_agent_runs_workspace_idempotency" in {
            item["name"] for item in inspector.get_unique_constraints("agent_runs")
        }
    finally:
        legacy_engine.dispose()
