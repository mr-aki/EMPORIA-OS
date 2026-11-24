from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from emporia_api.config import settings


def _upgrade(database_url: str, revision: str = "head") -> None:
    settings.database_url = database_url
    command.upgrade(Config("alembic.ini"), revision)


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
            "products",
            "inventory_movements",
            "suppliers",
            "purchase_orders",
            "purchase_order_lines",
            "purchase_order_receipts",
            "purchase_order_receipt_lines",
            "inventory_cost_layers",
            "inventory_cost_allocations",
            "inventory_returns",
            "inventory_cost_return_allocations",
            "alembic_version",
        }.issubset(set(inspector.get_table_names()))
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == "0017_sale_linked_returns"
        assert "uq_login_attempt_rate_limit_subject" in {
            item["name"] for item in inspector.get_unique_constraints("login_attempt_rate_limits")
        }
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
        assert "background_jobs" in inspector.get_table_names()
        assert "login_attempt_rate_limits" in inspector.get_table_names()
        assert "workspace_model_prices" in inspector.get_table_names()
        assert "uq_products_workspace_sku" in {
            item["name"] for item in inspector.get_unique_constraints("products")
        }
        assert "uq_products_id_workspace" in {
            item["name"] for item in inspector.get_indexes("products")
        }
        inventory_foreign_keys = inspector.get_foreign_keys("inventory_movements")
        assert any(
            item["name"] == "fk_inventory_movements_product_workspace"
            and item["constrained_columns"] == ["product_id", "workspace_id"]
            and item["referred_columns"] == ["id", "workspace_id"]
            and item["referred_table"] == "products"
            for item in inventory_foreign_keys
        )
        assert "uq_inventory_movements_workspace_idempotency" in {
            item["name"]
            for item in inspector.get_unique_constraints("inventory_movements")
        }
        assert "ix_inventory_movements_workspace_product_created_at" in {
            item["name"] for item in inspector.get_indexes("inventory_movements")
        }
        assert "uq_inventory_movements_id_workspace_product" in {
            item["name"] for item in inspector.get_indexes("inventory_movements")
        }
        assert "uq_inventory_cost_layers_id_workspace_product" in {
            item["name"] for item in inspector.get_indexes("inventory_cost_layers")
        }
        assert "uq_inventory_cost_allocations_id_layer_workspace" in {
            item["name"] for item in inspector.get_indexes("inventory_cost_allocations")
        }
        assert "fk_inventory_returns_source_sale_workspace_product" in {
            item["name"] for item in inspector.get_foreign_keys("inventory_returns")
        }
        assert "fk_inventory_cost_return_allocations_source_layer_workspace" in {
            item["name"]
            for item in inspector.get_foreign_keys("inventory_cost_return_allocations")
        }
        assert "ix_products_workspace_created_at" in {
            item["name"] for item in inspector.get_indexes("products")
        }
        assert "uq_suppliers_workspace_code" in {
            item["name"] for item in inspector.get_unique_constraints("suppliers")
        }
        assert "uq_purchase_orders_workspace_number" in {
            item["name"] for item in inspector.get_unique_constraints("purchase_orders")
        }
        assert "uq_purchase_order_receipts_workspace_idempotency" in {
            item["name"]
            for item in inspector.get_unique_constraints("purchase_order_receipts")
        }
        assert "uq_purchase_order_lines_id_workspace" in {
            item["name"]
            for item in inspector.get_unique_constraints("purchase_order_lines")
        }
        assert "uq_inventory_movements_id_workspace" in {
            item["name"] for item in inspector.get_indexes("inventory_movements")
        }
        assert "fk_purchase_orders_supplier_workspace" in {
            item["name"] for item in inspector.get_foreign_keys("purchase_orders")
        }
        assert "fk_purchase_order_lines_product_workspace" in {
            item["name"] for item in inspector.get_foreign_keys("purchase_order_lines")
        }
        assert "fk_purchase_order_lines_order_workspace" in {
            item["name"] for item in inspector.get_foreign_keys("purchase_order_lines")
        }
        assert "fk_purchase_order_receipt_lines_receipt_workspace" in {
            item["name"]
            for item in inspector.get_foreign_keys("purchase_order_receipt_lines")
        }
        assert {"sku", "name", "unit_price", "currency", "status"}.issubset(
            {column["name"] for column in inspector.get_columns("products")}
        )
        assert "uq_workspace_model_price_provider_model" in {
            item["name"]
            for item in inspector.get_unique_constraints("workspace_model_prices")
        }
        assert "ix_workspace_model_prices_workspace_id" in {
            item["name"] for item in inspector.get_indexes("workspace_model_prices")
        }
        assert "business_action_requests" in inspector.get_table_names()
        assert {"action_type", "status", "requested_by", "approved_by", "inputs_json"}.issubset(
            {column["name"] for column in inspector.get_columns("business_action_requests")}
        )
        assert "uq_business_action_idempotency" in {
            item["name"] for item in inspector.get_unique_constraints("business_action_requests")
        }
        assert "uq_background_jobs_workspace_idempotency_key" in {
            item["name"] for item in inspector.get_unique_constraints("background_jobs")
        }
        assert {"workspace_id", "actor", "kind", "payload_json", "status", "attempts", "locked_by"}.issubset(
            {column["name"] for column in inspector.get_columns("background_jobs")}
        )
        assert "workspace_execution_rate_limits" in inspector.get_table_names()
        assert "evaluation_json" in {
            column["name"] for column in inspector.get_columns("skill_runs")
        }
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
            assert "execution_lease_expires_at" in {
                column["name"] for column in inspector.get_columns(table_name)
            }
            assert {
                "input_price_usd_per_million_tokens",
                "output_price_usd_per_million_tokens",
                "estimated_cost_usd",
            }.issubset(
                {column["name"] for column in inspector.get_columns(table_name)}
            )
            assert f"ix_{table_name}_execution_lease_expires_at" in {
                item["name"] for item in inspector.get_indexes(table_name)
            }
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
        assert "business_action_requests" in inspector.get_table_names()
        assert "products" in inspector.get_table_names()
        assert "inventory_movements" in inspector.get_table_names()
        assert "inventory_returns" in inspector.get_table_names()
        assert "inventory_cost_return_allocations" in inspector.get_table_names()
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



def test_fifo_cost_migration_backfills_existing_stock_as_uncosted(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    database_url = f"sqlite:///{tmp_path / 'fifo-backfill.db'}"
    monkeypatch.setattr(settings, "database_url", database_url)
    _upgrade(database_url, "0015_procurement")

    engine = create_engine(database_url)
    created_at = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO products (
                        id, workspace_id, sku, name, description, unit_price,
                        currency, status, created_at, updated_at
                    ) VALUES (
                        'legacy-product', 'legacy-workspace', 'LEGACY-001',
                        'Legacy stock', '', 10.0000, 'USD', 'active', :created_at, :created_at
                    )
                    """
                ),
                {"created_at": created_at},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO inventory_movements (
                        id, workspace_id, product_id, movement_type, quantity_delta,
                        quantity_after, reason, reference, idempotency_key, created_at
                    ) VALUES (
                        'legacy-receipt', 'legacy-workspace', 'legacy-product', 'receipt',
                        8, 8, 'legacy opening receipt', NULL, 'legacy-receipt-key', :created_at
                    )
                    """
                ),
                {"created_at": created_at},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO inventory_movements (
                        id, workspace_id, product_id, movement_type, quantity_delta,
                        quantity_after, reason, reference, idempotency_key, created_at
                    ) VALUES (
                        'legacy-sale', 'legacy-workspace', 'legacy-product', 'sale',
                        -3, 5, 'legacy sale', NULL, 'legacy-sale-key', :created_at
                    )
                    """
                ),
                {"created_at": created_at},
            )

        _upgrade(database_url)

        with engine.connect() as connection:
            layer = connection.execute(
                text(
                    """
                    SELECT source_type, quantity_received, quantity_remaining,
                           unit_cost, currency, source_inventory_movement_id
                    FROM inventory_cost_layers
                    WHERE workspace_id = 'legacy-workspace'
                      AND product_id = 'legacy-product'
                    """
                )
            ).one()
        assert layer == ("opening_balance", 5, 5, None, None, None)
    finally:
        engine.dispose()
