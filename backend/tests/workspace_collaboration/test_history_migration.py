import importlib.util
import json
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_migration_backfills_existing_handoffs_without_code_access(monkeypatch):
    path = Path(__file__).parents[2] / "alembic/versions/e16c8a43d920_link_collaboration_human_deltas.py"
    spec = importlib.util.spec_from_file_location("history_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE sdd_tasks (id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(36))")
        connection.exec_driver_sql(
            "CREATE TABLE task_collaboration_handoffs (id VARCHAR(36) PRIMARY KEY, task_id VARCHAR(36), actor_user_id VARCHAR(36), created_at DATETIME, repository_deltas_json JSON)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE sdd_human_deltas (id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(36), task_id VARCHAR(36), created_by_id VARCHAR(36), status VARCHAR(20), changed_files_count INTEGER, change_category VARCHAR(100), promote_candidate BOOLEAN, created_at DATETIME, updated_at DATETIME)"
        )
        connection.exec_driver_sql("INSERT INTO users VALUES ('u')")
        connection.exec_driver_sql("INSERT INTO sdd_tasks VALUES ('t', 'w')")
        changes = json.dumps(
            [
                {"task_repository_id": "a", "files": [{"path": "same.txt"}]},
                {"task_repository_id": "b", "files": [{"path": "same.txt"}]},
            ]
        )
        connection.execute(
            sa.text("INSERT INTO task_collaboration_handoffs VALUES ('h', 't', 'u', '2026-10-12 17:48:49', :changes)"),
            {"changes": changes},
        )
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        result = connection.execute(sa.text("SELECT * FROM sdd_human_deltas")).mappings().one()
        assert result["collaboration_handoff_id"] == "h"
        assert result["created_by_id"] == "u"
        assert result["changed_files_count"] == 2
        assert result["created_at"] == "2026-10-12 17:48:49"
        assert result["status"] == "READY"
