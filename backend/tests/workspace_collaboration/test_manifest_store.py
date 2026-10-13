import hashlib
import json

import pytest
import zstandard
from sqlalchemy import event

from app.domains.workspace_collaboration import manifest_store, service
from app.domains.workspace_collaboration.models import CollaborationManifest, CollaborationSnapshot
from tests.task.test_task_chat_history_ordering import _seed_task


def test_inventories_are_deduplicated_without_losing_snapshot_headers(db):
    task = _seed_task(db)
    repositories = [
        {
            "task_repository_id": "repo",
            "files": [
                {"path": f"src/file-{i}.py", "hash": hashlib.sha256(str(i).encode()).hexdigest(), "size": i}
                for i in range(1000)
            ],
        }
    ]
    digest = manifest_store.store_repositories(db, task.id, repositories)
    assert manifest_store.store_repositories(db, task.id, repositories) == digest
    for i, source in enumerate(("HUMAN_HANDOFF", "PROGRESS", "AGENT_OUTPUT")):
        db.add(
            CollaborationSnapshot(
                id=f"snapshot-{i}",
                task_id=task.id,
                content_digest=digest,
                source=source,
                manifest_json={"snapshot_id": f"snapshot-{i}", "source": source, "progress_seq": i},
            )
        )
    db.commit()
    db.expunge_all()
    assert db.query(CollaborationManifest).count() == 1
    assert db.query(CollaborationSnapshot).count() == 3
    for i in range(3):
        result = service.get_snapshot(db, "task-1", f"snapshot-{i}")
        assert result["repositories"] == repositories
        assert result["progress_seq"] == i
        assert "repositories" not in db.get(CollaborationSnapshot, f"snapshot-{i}").manifest_json
    payload = db.get(CollaborationManifest, ("task-1", digest)).repositories_zstd
    assert len(payload) < len(json.dumps(repositories).encode()) / 2
    with pytest.raises(service.CollaborationError, match="not found"):
        service.get_snapshot(db, "other-task", "snapshot-0")


def test_reusing_inventory_only_reads_the_digest_and_rollback_keeps_no_content(db):
    task = _seed_task(db)
    repositories = [{"files": []}]
    digest = manifest_store.store_repositories(db, task.id, repositories)
    db.commit()
    statements = []
    engine = db.get_bind()

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        manifest_store.store_repositories(db, "task-1", repositories)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    assert "repositories_zstd" not in statements[0]
    new_digest = manifest_store.store_repositories(db, "task-1", [{"files": [{"path": "changed"}]}])
    db.rollback()
    assert db.get(CollaborationManifest, ("task-1", digest)) is not None
    assert db.get(CollaborationManifest, ("task-1", new_digest)) is None


def test_corrupted_inventory_fails_instead_of_delivering_wrong_files(db):
    task = _seed_task(db)
    digest = manifest_store.store_repositories(db, task.id, [{"files": []}])
    snapshot = CollaborationSnapshot(
        id="snapshot",
        task_id=task.id,
        content_digest=digest,
        source="INITIAL",
        manifest_json={},
    )
    db.add(snapshot)
    db.flush()
    row = db.get(CollaborationManifest, (task.id, digest))
    row.repositories_zstd = zstandard.ZstdCompressor().compress(b"[]")
    with pytest.raises(ValueError, match="digest differs"):
        manifest_store.read_manifest(db, snapshot)
