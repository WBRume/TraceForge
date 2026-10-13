from pathlib import Path

import pytest

from app.domains.task.models.session_turn import TaskSessionTurn
from app.domains.task.models.task import TaskType
from app.domains.task.services import task_session_snapshot_service as snapshots
from app.domains.workspace_collaboration import content, review, service
from app.domains.workspace_collaboration.models import CollaborationState
from tests.workspace_collaboration.test_service import enabled, git
from tests.workspace_collaboration.test_service import environment as repository_environment

environment = repository_environment


def test_readonly_latest_turn_multi_repo_uses_recorded_input_without_connecting(environment, monkeypatch):
    db, task, root = environment
    service._ensure_store(db, task)
    (root / "api/same.txt").write_bytes(b"human input\n")
    (root / "api/.gitignore").write_text("private.log\n")
    (root / "api/private.log").write_text("private")
    (root / "api/.env").write_text("secret")
    checkpoint = snapshots._create_checkpoint_sync(
        task.project_path,
        ["api", "web"],
        "none",
        None,
        task.workspace_id,
        "Multi repo",
        task.id,
        task.name,
        initial_checkpoint=task.task_meta_json["initial_workspace_checkpoint"],
    )
    db.add(
        TaskSessionTurn(
            id="turn",
            task_id=task.id,
            workspace_id=task.workspace_id,
            session_generation=1,
            session_revision=0,
            turn_index=1,
            provider="test",
            worktree_snapshot_path=str(Path(checkpoint["root"]) / "worktree.json"),
        )
    )
    db.commit()
    # Changing ignore rules must not expose private files from the old snapshot.
    (root / "api/.gitignore").write_text("")
    (root / "api/private.log").unlink()
    (root / "api/same.txt").write_bytes(b"agent result\n")
    (root / "api/new.txt").write_text("created\n")
    (root / "web/same.txt").unlink()
    before = {repo: git(root / repo, "status", "--porcelain") for repo in ["api", "web"]}
    result = review.changes(db, task, "viewer")
    db.commit()

    def by_path(manifest):
        return {
            (repo["repo_slug"], file["path"]): file["sha256"]
            for repo in manifest["repositories"]
            for file in repo["files"]
        }

    old, new = by_path(result["input"]), by_path(result["cloud"])
    store = content.ObjectStore(task)
    assert store.read(old["api", "same.txt"]) == b"human input\n"
    assert store.read(new["api", "same.txt"]) == b"agent result\n"
    assert ("api", "new.txt") not in old and ("api", "new.txt") in new
    assert ("web", "same.txt") in old and ("web", "same.txt") not in new
    assert all(path not in {".env", "private.log"} for _, path in old.keys() | new.keys())
    assert db.get(CollaborationState, task.id) is None
    assert before == {repo: git(root / repo, "status", "--porcelain") for repo in before}
    monkeypatch.setattr(review, "_checkpoint_inventory", lambda *args: pytest.fail("Baseline must be reused"))
    assert review.changes(db, task, "viewer")["input"]["snapshot_id"] == result["input"]["snapshot_id"]


def test_active_collaboration_review_reuses_published_snapshots_without_changing_driver(environment, monkeypatch):
    db, task, _ = environment
    state = enabled(environment)
    monkeypatch.setattr(service, "_inventory", lambda *args, **kwargs: pytest.fail("No rescan for published results"))
    assert review.changes(db, task, "viewer")["cloud"]["snapshot_id"] == state["snapshot_id"]
    assert service.get_state(db, task) == state


def test_running_cloud_review_waits_for_final_cut_and_never_acquires_lease(environment, monkeypatch):
    db, task, _ = environment

    def writer(*_):
        raise service.CollaborationError("WRITER_ACTIVE", "running")

    monkeypatch.setattr(service, "_assert_no_writer", writer)
    monkeypatch.setattr(service, "_inventory", lambda *args, **kwargs: pytest.fail("No final scan while executing"))
    assert review.changes(db, task, "viewer")["running"] is True
    assert db.get(CollaborationState, task.id) is None


def test_storage_root_is_configurable_and_pinned_across_configuration_changes(environment, tmp_path, monkeypatch):
    db, task, _ = environment
    configured = tmp_path / "collaboration-data"
    monkeypatch.setattr(content.settings, "COLLABORATION_SNAPSHOT_ROOT", str(configured))
    store = service._ensure_store(db, task)
    sha = store.put(b"durable input")
    db.commit()
    assert store.root == configured / task.id
    monkeypatch.setattr(content.settings, "COLLABORATION_SNAPSHOT_ROOT", str(tmp_path / "next-root"))
    assert service._ensure_store(db, task).read(sha) == b"durable input"
    assert content.ObjectStore(task).root == configured / task.id


def test_legacy_storage_is_not_orphaned_when_configuration_changes(environment, tmp_path, monkeypatch):
    db, task, _ = environment
    original = service._ensure_store(db, task)
    sha = original.put(b"legacy data")
    task.task_meta_json = {
        key: value for key, value in task.task_meta_json.items() if key != "collaboration_store_path"
    }
    db.commit()
    monkeypatch.setattr(content.settings, "COLLABORATION_SNAPSHOT_ROOT", str(tmp_path / "next-root"))
    assert service._ensure_store(db, task).read(sha) == b"legacy data"
    assert Path(task.task_meta_json["collaboration_store_path"]) == original.root


def test_diagnosis_remains_excluded(environment):
    db, task, _ = environment
    task.task_type = TaskType.DIAGNOSIS
    with pytest.raises(service.CollaborationError) as error:
        review.changes(db, task, "viewer")
    assert error.value.code == "TASK_TYPE_UNSUPPORTED"
