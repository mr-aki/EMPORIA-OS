from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from emporia_api import models as _models  # noqa: F401
from emporia_api.database import Base

API_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG = API_ROOT / "alembic.ini"


def upgrade(connection) -> None:
    config = Config(str(ALEMBIC_CONFIG))
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


def test_migrations_create_fresh_schema_and_are_idempotent():
    engine = create_engine("sqlite://")
    try:
        with engine.connect() as connection:
            upgrade(connection)
            tables = set(inspect(connection).get_table_names())
            assert {"ventures", "audit_events", "agent_runs", "alembic_version"} <= tables
            columns = {column["name"] for column in inspect(connection).get_columns("agent_runs")}
            assert "research_sources_json" in columns
            upgrade(connection)
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert version == "20261112_0001"
    finally:
        engine.dispose()


def test_migration_preserves_legacy_agent_runs_and_adds_research_sources():
    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(bind=engine)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE agent_runs DROP COLUMN research_sources_json"
            )
            connection.execute(
                text("""
                    INSERT INTO agent_runs (
                        id, workspace_id, agent_id, agent_version, provider, model,
                        status, task, output, error_message, prompt_tokens,
                        completion_tokens, total_tokens, provider_request_id,
                        created_at, completed_at
                    ) VALUES (
                        'legacy-run', 'legacy-workspace', 'product-research-analyst',
                        '1.0.0', 'openai', 'test-model', 'completed', 'legacy task',
                        'legacy output', '', 10, 5, 15, NULL, '2026-11-12 00:00:00', NULL
                    )
                """)
            )
        with engine.connect() as connection:
            upgrade(connection)
            row = connection.execute(
                text("""
                    SELECT research_sources_json, output
                    FROM agent_runs WHERE id = 'legacy-run'
                """)
            ).one()
        assert row.research_sources_json == "[]"
        assert row.output == "legacy output"
    finally:
        engine.dispose()
