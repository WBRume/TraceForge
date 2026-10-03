"""Exercise the incremental migration against retained development rows."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_upgrade_and_downgrade_preserve_existing_rows(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/d063b42e98a1_task_awareness_webhooks.py"
    spec = importlib.util.spec_from_file_location("awareness_migration", path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            for sql in ["CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)", "CREATE TABLE workspaces (id VARCHAR(36) PRIMARY KEY)",
                        "CREATE TABLE sdd_tasks (id VARCHAR(36) PRIMARY KEY, name TEXT)",
                        "CREATE TABLE sdd_ai_jobs (id VARCHAR(36) PRIMARY KEY, status TEXT)",
                        "INSERT INTO sdd_tasks VALUES ('task-old', 'historical task')",
                        "INSERT INTO sdd_ai_jobs VALUES ('job-old', 'FAILED')"]:
                connection.execute(text(sql))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            assert connection.execute(text("SELECT name, business_state FROM sdd_tasks")).one() == ("historical task", "TASK_IN_PROGRESS")
            assert connection.execute(text("SELECT status, awareness_state, awareness_version FROM sdd_ai_jobs")).one() == ("FAILED", None, 0)
            assert connection.execute(text("SELECT count(*) FROM task_awareness_events")).scalar() == 0
            assert {"task_webhook_deliveries", "task_webhook_endpoints", "task_awareness_events"} <= set(inspect(connection).get_table_names())
            migration.downgrade()
            assert connection.execute(text("SELECT name FROM sdd_tasks")).scalar() == "historical task"
            assert connection.execute(text("SELECT status FROM sdd_ai_jobs")).scalar() == "FAILED"
            assert "task_awareness_events" not in inspect(connection).get_table_names()
            migration.upgrade()
            assert connection.execute(text("SELECT count(*) FROM sdd_tasks")).scalar() == 1
    finally:
        engine.dispose()


def test_standard_webhook_migration_retains_urls_subscriptions_and_delivery_history(monkeypatch):
    directory = Path(__file__).resolve().parents[2] / "alembic/versions"
    migrations = []
    for filename in ["d063b42e98a1_task_awareness_webhooks.py", "e184ac70f9d2_standard_webhooks_only.py"]:
        spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), directory / filename)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); migrations.append(module)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            for statement in ["CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)", "CREATE TABLE workspaces (id VARCHAR(36) PRIMARY KEY)",
                              "CREATE TABLE sdd_tasks (id VARCHAR(36) PRIMARY KEY)", "CREATE TABLE sdd_ai_jobs (id VARCHAR(36) PRIMARY KEY)"]:
                connection.execute(text(statement))
            for module in migrations:
                monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
            migrations[0].upgrade()
            connection.execute(text("INSERT INTO task_webhook_endpoints (id, scope_key, enabled, url, format, delivery_location, events_json) VALUES ('ep', 'user:u1', 1, 'https://receiver.example/hook', 'generic', 'server', '[\"TASK_COMPLETED\"]')"))
            connection.execute(text("INSERT INTO task_awareness_events (id, event_key, creator_id, workspace_id, task_id, event_type, payload_json, available_at) VALUES ('ev', 'business:t1:ev', 'u1', 'ws', 't1', 'TASK_COMPLETED', '{}', CURRENT_TIMESTAMP)"))
            connection.execute(text("INSERT INTO task_webhook_deliveries (id, event_id, endpoint_id, status, attempts, available_at) VALUES ('del', 'ev', 'ep', 'SENT', 1, CURRENT_TIMESTAMP)"))
            for action in [migrations[1].upgrade, migrations[1].downgrade, migrations[1].upgrade]:
                action()
                assert connection.execute(text("SELECT url, events_json FROM task_webhook_endpoints")).one() == ("https://receiver.example/hook", '["TASK_COMPLETED"]')
                assert connection.execute(text("SELECT status, attempts FROM task_webhook_deliveries")).one() == ("SENT", 1)
            assert "format" not in {column["name"] for column in inspect(connection).get_columns("task_webhook_endpoints")}
    finally:
        engine.dispose()
