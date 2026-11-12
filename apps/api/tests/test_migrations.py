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
            "background_jobs",
            "alembic_version",
        }.issubset(set(inspector.get_table_names()))
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == "0003_background_jobs"
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
    finally:
        legacy_engine.dispose()


def test_background_job_migration_adds_queue_and_can_rollback_only_queue(
    tmp_path, monkeypatch
):
    database_url = f"sqlite:///{tmp_path / 'background-jobs.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)
    config = Config("alembic.ini")
    command.upgrade(config, "0002_skill_runs")

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO ventures "
                "(id, workspace_id, name, description, status, created_at, updated_at) "
                "VALUES ('queue-migration-venture', 'workspace-1', 'Existing store', '', "
                "'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))

        command.upgrade(config, "head")
        inspector = inspect(engine)
        assert "background_jobs" in inspector.get_table_names()
        assert "ix_background_jobs_status_available_at" in {
            item["name"] for item in inspector.get_indexes("background_jobs")
        }

        with engine.connect() as connection:
            name = connection.scalar(text(
                "SELECT name FROM ventures WHERE id = 'queue-migration-venture'"
            ))
        assert name == "Existing store"

        command.downgrade(config, "0002_skill_runs")
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert "background_jobs" not in tables
        assert {
            "ventures", "audit_events", "agent_runs", "skill_runs",
            "users", "workspaces", "workspace_memberships",
        }.issubset(tables)
    finally:
        engine.dispose()
