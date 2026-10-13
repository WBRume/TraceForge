"""Exercise populated upgrade/downgrade on SQLite and opt-in isolated MySQL."""

import importlib.util
import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
import zstandard
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.config import settings
from app.domains.workspace_collaboration.content import digest


def load_migration(name):
    path = Path(__file__).parents[2] / "alembic" / "versions" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def create_legacy_schema(connection):
    metadata = sa.MetaData()
    sa.Table(
        "sdd_tasks",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), index=True),
        sa.Column("created_at", sa.DateTime),
    )
    sa.Table(
        "task_collaboration_snapshots",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("manifest_json", sa.JSON, nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime),
    )
    sa.Table(
        "sdd_task_pre_inputs",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("mentioned_user_ids", sa.JSON, nullable=False),
    )
    sa.Table(
        "sdd_user_notifications",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("recipient_user_id", sa.String(36), index=True),
        sa.Column("read_at", sa.DateTime, index=True),
        sa.Column("created_at", sa.DateTime),
    )
    sa.Table(
        "task_collaboration_handoffs",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime),
    )
    metadata.create_all(connection)
    return metadata


@pytest.fixture(params=["sqlite", "mysql"])
def migration_connection(request):
    if request.param == "sqlite":
        engine = sa.create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                yield connection
        finally:
            engine.dispose()
        return
    if os.getenv("DB_MODEL_MYSQL_TESTS") != "1":
        pytest.skip("set DB_MODEL_MYSQL_TESTS=1 for a disposable MySQL schema")
    name = "traceforge_model_test_" + uuid4().hex[:12]
    admin = sa.create_engine(settings.DATABASE_URL)
    with admin.begin() as connection:
        connection.exec_driver_sql(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    engine = sa.create_engine(admin.url.set(database=name))
    try:
        with engine.begin() as connection:
            yield connection
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f"DROP DATABASE `{name}`")
        admin.dispose()


def test_storage_migrations_preserve_history_and_mentions(migration_connection):
    connection = migration_connection
    metadata = create_legacy_schema(connection)
    connection.execute(metadata.tables["sdd_tasks"].insert(), [{"id": "t1"}, {"id": "t2"}])
    originals = {}
    rows = []
    for i in range(105):
        identity = f"snapshot-{i:03}"
        task_id = "t1" if i % 2 else "t2"
        repositories = [{"files": [{"path": "src/中文.py", "hash": str(i % 3), "executable": False}]}]
        manifest = {"snapshot_id": identity, "task_id": task_id, "progress_seq": i, "repositories": repositories}
        originals[identity] = manifest
        rows.append(
            {
                "id": identity,
                "task_id": task_id,
                "manifest_json": manifest,
                "content_digest": digest(repositories),
                "source": "PROGRESS",
                "created_at": datetime(2026, 10, 13),
            }
        )
    connection.execute(metadata.tables["task_collaboration_snapshots"].insert(), rows)
    expected_users = {"pre-1": ["user-b", "user-a", "historical-user"], "pre-2": []}
    expected_users.update({f"batch-{i:04}": ["user-a"] if i % 250 == 0 else [] for i in range(503)})
    connection.execute(
        metadata.tables["sdd_task_pre_inputs"].insert(),
        [{"id": identity, "mentioned_user_ids": users} for identity, users in expected_users.items()],
    )
    snapshots = load_migration("f42a81d9c630_deduplicate_collaboration_manifests.py")
    mentions = load_migration("a63d27b8e104_normalize_mentions_and_list_indexes.py")
    with Operations.context(MigrationContext.configure(connection)):
        for _attempt in range(2):
            snapshots.upgrade()
            mentions.upgrade()
            assert connection.execute(sa.text("SELECT COUNT(*) FROM task_collaboration_manifests")).scalar() == 6
            assert connection.execute(sa.text("SELECT COUNT(*) FROM sdd_task_pre_input_mentions")).scalar() == 6
            for row in connection.execute(
                sa.text(
                    "SELECT s.id, s.manifest_json, m.repositories_zstd FROM task_collaboration_snapshots s "
                    "JOIN task_collaboration_manifests m ON m.task_id=s.task_id AND m.content_digest=s.content_digest"
                )
            ).mappings():
                header = json.loads(row["manifest_json"])
                assert "repositories" not in header
                header["repositories"] = json.loads(zstandard.ZstdDecompressor().decompress(row["repositories_zstd"]))
                assert header == originals[row["id"]]
            assert "mentioned_user_ids" not in {
                c["name"] for c in sa.inspect(connection).get_columns("sdd_task_pre_inputs")
            }
            mentions.downgrade()
            snapshots.downgrade()
            restored = connection.execute(sa.select(metadata.tables["task_collaboration_snapshots"])).mappings()
            assert {row["id"]: row["manifest_json"] for row in restored} == originals
            restored_users = dict(connection.execute(sa.select(metadata.tables["sdd_task_pre_inputs"])).all())
            assert restored_users == expected_users
