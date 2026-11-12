from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from emporia_api.database import Base
from emporia_api import models as _models  # noqa: F401 — register all ORM tables


API_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG = API_ROOT / "alembic.ini"


def upgrade(connection) -> None:
    config = Config(str(ALEMBIC_CONFIG))
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


def test_migrations_create_a_fresh_schema_and_are_idempotent():
    engine = create_engine("sqlite://")
    try:
        with engine.connect() as connection:
            upgrade(connection)
            tables = set(inspect(connection).get_table_names())
            assert {"ventures", "audit_events", "agent_runs", "alembic_version"} <= tables

            agent_columns = {
                column["name"] for column in inspect(connection).get_columns("agent_runs")
            }
            assert "research_sources_json" in agent_columns

            # A second upgrade at head must be a no-op.
            upgrade(connection)
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert version == "20261112_0001"
    finally:
        engine.dispose()


def test_migration_adds_research_sources_to_an_existing_agent_runs_table():
    engine = create_engine("sqlite://")
    try:
        # Recreate the schema produced by the pre-research ORM, then remove only
        # the column introduced by the research connector.
        Base.metadata.create_all(bind=engine)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE agent_runs DROP COLUMN research_sources_json"
            )
            connection.execute(
                text(
                    """
                    INSERT INTO agent_runs (
                        id, workspace_id, agent_id, agent_version, provider, model,
                        status, task, output, error_message, prompt_tokens,
                        completion_tokens, total_tokens, provider_request_id,
                        created_at, completed_at
                    ) VALUES (
                        :id, :workspace_id, :agent_id, :agent_version, :provider, :model,
                        :status, :task, :output, :error_message, :prompt_tokens,
                        :completion_tokens, :total_tokens, :provider_request_id,
                        :created_at, :completed_at
                    )
                    """
                ),
                {
                    "id": "legacy-run",
                    "workspace_id": "legacy-workspace",
                    "agent_id": "product-research-analyst",
                    "agent_version": "1.0.0",
                    "provider": "openai",
                    "model": "gpt-test",
                    "status": "completed",
                    "task": "legacy task",
                    "output": "legacy output",
                    "error_message": "",
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "provider_request_id": None,
                    "created_at": "2026-11-12 00:00:00",
                    "completed_at": None,
                },
            )

        with engine.connect() as connection:
            upgrade(connection)
            stored_sources = connection.execute(
                text(
                    "SELECT research_sources_json FROM agent_runs WHERE id = :run_id"
                ),
                {"run_id": "legacy-run"},
            ).scalar_one()
            stored_output = connection.execute(
                text("SELECT output FROM agent_runs WHERE id = :run_id"),
                {"run_id": "legacy-run"},
            ).scalar_one()

        assert stored_sources == "[]"
        assert stored_output == "legacy output"
    finally:
        engine.dispose()
