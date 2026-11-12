from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from emporia_api.database import Base
from emporia_api import models as _models  # noqa: F401


API_ROOT = Path(__file__).resolve().parents[1]


def migration_config() -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    return config


def schema_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'migration-test.db'}"


def test_alembic_upgrade_creates_all_current_tables_and_workspace_indexes(
    tmp_path, monkeypatch
):
    url = schema_url(tmp_path)
    monkeypatch.setenv("EMPORIA_DATABASE_URL", url)

    command.upgrade(migration_config(), "head")

    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert {
            "alembic_version",
            "ventures",
            "audit_events",
            "agent_runs",
            "skill_runs",
        }.issubset(tables)

        expected_indexes = {
            "ventures": "ix_ventures_workspace_id",
            "audit_events": "ix_audit_events_workspace_id",
            "agent_runs": "ix_agent_runs_workspace_id",
            "skill_runs": "ix_skill_runs_workspace_id",
        }
        for table, index_name in expected_indexes.items():
            names = {item["name"] for item in inspector.get_indexes(table)}
            assert index_name in names

        with engine.connect() as connection:
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert version == "0001_initial_schema"
    finally:
        engine.dispose()


def test_alembic_downgrade_removes_baseline_tables(tmp_path, monkeypatch):
    url = schema_url(tmp_path)
    monkeypatch.setenv("EMPORIA_DATABASE_URL", url)
    config = migration_config()

    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert not {
            "ventures",
            "audit_events",
            "agent_runs",
            "skill_runs",
            "alembic_version",
        }.intersection(tables)
    finally:
        engine.dispose()


def test_existing_create_all_database_can_be_stamped_without_data_loss(
    tmp_path, monkeypatch
):
    url = schema_url(tmp_path)
    monkeypatch.setenv("EMPORIA_DATABASE_URL", url)
    engine = create_engine(url)
    try:
        Base.metadata.create_all(bind=engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO ventures "
                    "(id, workspace_id, name, description, status, created_at, updated_at) "
                    "VALUES ('venture-1', 'workspace-1', 'Existing Store', '', "
                    "'planning', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )

        command.stamp(migration_config(), "head")
        command.upgrade(migration_config(), "head")

        with engine.connect() as connection:
            name = connection.execute(
                text("SELECT name FROM ventures WHERE id = 'venture-1'")
            ).scalar_one()
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert name == "Existing Store"
        assert version == "0001_initial_schema"
    finally:
        engine.dispose()


def test_production_startup_rejects_schema_auto_creation(monkeypatch):
    import asyncio

    from emporia_api.main import app, lifespan
    from emporia_api.config import settings

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "auto_create_schema", True)

    async def run_lifespan():
        with pytest.raises(RuntimeError, match="restricted to development and test"):
            async with lifespan(app):
                pass

    asyncio.run(run_lifespan())
