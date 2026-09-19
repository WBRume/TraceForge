"""Scoped checkpoint round trips, retention, and failure safety."""

import json
import os
from pathlib import Path
import subprocess
import threading
from unittest.mock import patch

import pytest

from app.domains.task.services import task_session_snapshot_service as snapshots
from app.domains.task.services import task_snapshot_store as store


def write(root, rel, value=b"before\r\n\x00\xff"):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return path


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout


def init_repo(root):
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init")
    git(root, "config", "user.name", "Snapshot Test")
    git(root, "config", "user.email", "snapshot@example.test")


def checkpoint(root, destination, repos=None):
    return snapshots._create_worktree_checkpoint_sync(str(root), repos or [], str(destination))


def objects(root):
    return {p for p in (root / "objects").glob("*/*") if p.is_file()}


def test_deduplicates_raw_bytes_and_only_restores_changes(tmp_path):
    task = tmp_path / "task"
    path = write(task, "src/main.py")
    stable = write(task, "README.md", b"unchanged")
    first = checkpoint(task, tmp_path / "turn-1")
    initial = {p: p.stat().st_mtime_ns for p in objects(tmp_path)}
    checkpoint(task, tmp_path / "turn-2")
    assert {p: p.stat().st_mtime_ns for p in objects(tmp_path)} == initial
    assert not (tmp_path / "turn-1/worktree").exists()
    path.write_bytes(b"after")
    write(task, "new.txt")
    stable_time = stable.stat().st_mtime_ns
    snapshots._restore_worktree_sync(str(tmp_path / "turn-1"), str(task), str(tmp_path / "turn-1/current-worktree"))
    assert path.read_bytes() == b"before\r\n\x00\xff"
    assert stable.stat().st_mtime_ns == stable_time
    assert not (task / "new.txt").exists()
    assert first["manifest"]["src/main.py"]["sha256"] == store.capture_file(str(path), None)["sha256"]


@pytest.mark.parametrize("directory", ["node_modules", "dist", ".next", "target", ".gradle", ".venv", "__pycache__"])
def test_excluded_directories_are_not_read_or_removed(tmp_path, directory):
    task = tmp_path / "task"
    write(task, "src/main.txt")
    excluded = write(task, f"nested/{directory}/data.bin")
    original = store.capture_file

    def checked_capture(path, object_store):
        assert directory not in Path(path).parts
        return original(path, object_store)

    with patch.object(store, "capture_file", side_effect=checked_capture):
        checkpoint(task, tmp_path / "turn-1")
        excluded.write_bytes(b"keep current cache")
        snapshots._restore_worktree_sync(str(tmp_path / "turn-1"), str(task), str(tmp_path / "turn-1/current-worktree"))
    assert excluded.read_bytes() == b"keep current cache"


def test_tracked_generated_files_override_exclusion_and_env_is_protected(tmp_path):
    task = tmp_path / "task"
    init_repo(task)
    tracked = write(task, "dist/tracked.js")
    write(task, ".gitignore", b".env\ndist/\n")
    env = write(task, ".env", b"LOCAL=value")
    git(task, "add", "-f", "dist/tracked.js", ".gitignore")
    git(task, "commit", "-m", "seed")
    write(task, "dist/cache.bin")
    checkpoint(task, tmp_path / "turn-1")
    tracked.write_bytes(b"changed")
    env.unlink()
    write(task, "dist/cache.bin", b"current")
    snapshots._restore_worktree_sync(str(tmp_path / "turn-1"), str(task), str(tmp_path / "turn-1/current-worktree"))
    assert tracked.read_bytes() == b"before\r\n\x00\xff"
    assert env.read_bytes() == b"LOCAL=value"
    assert (task / "dist/cache.bin").read_bytes() == b"current"
    assert git(task, "status", "--porcelain") == b""


def test_gc_preserves_other_turns_and_compensation_then_reclaims(tmp_path):
    task = tmp_path / "task"
    path = write(task, "main.py", b"one")
    checkpoint(task, tmp_path / "turn-1")
    checkpoint(task, tmp_path / "turn-2")
    snapshots._cleanup_checkpoint_sync(str(tmp_path / "turn-1"))
    assert len(objects(tmp_path)) == 1
    path.write_bytes(b"two")
    snapshots._restore_worktree_sync(str(tmp_path / "turn-2"), str(task), str(tmp_path / "turn-2/current-worktree"))
    with store.store_lock(str(tmp_path)):
        store.collect(str(tmp_path))
    assert len(objects(tmp_path)) == 2
    # A later orchestration failure can restore the live pre-undo state.
    snapshots._restore_worktree_sync(str(tmp_path / "turn-2/current-worktree"), str(task), str(tmp_path / "turn-2/current-recovery-worktree"))
    assert path.read_bytes() == b"two"
    snapshots._cleanup_checkpoint_sync(str(tmp_path / "turn-2"))
    assert not objects(tmp_path)


def test_corrupt_object_fails_before_modifying_live_files(tmp_path):
    task = tmp_path / "task"
    path = write(task, "main.py")
    checkpoint(task, tmp_path / "turn-1")
    next(iter(objects(tmp_path))).write_bytes(b"corrupt")
    path.write_bytes(b"live")
    with pytest.raises(ValueError, match="corrupt"):
        snapshots._restore_worktree_sync(str(tmp_path / "turn-1"), str(task), str(tmp_path / "turn-1/current-worktree"))
    assert path.read_bytes() == b"live"
    assert not (tmp_path / "turn-1/current-worktree/worktree.json").exists()


def test_multi_repo_branch_index_and_excluded_data(tmp_path):
    task = tmp_path / "task"
    heads = {}
    for name in ["frontend", "backend"]:
        repo = task / name
        init_repo(repo)
        write(repo, "main.txt", b"seed")
        git(repo, "add", ".")
        git(repo, "commit", "-m", "seed")
        heads[name] = git(repo, "rev-parse", "HEAD")
        write(repo, "main.txt", b"staged")
        git(repo, "add", ".")
        write(repo, "main.txt", b"unstaged")
    checkpoint(task, tmp_path / "turn-1", ["frontend", "backend"])
    for name in heads:
        repo = task / name
        git(repo, "checkout", "-b", "other")
        git(repo, "commit", "-am", "later")
        write(repo, "node_modules/local", b"preserve")
    snapshots._restore_worktree_sync(str(tmp_path / "turn-1"), str(task), str(tmp_path / "turn-1/current-worktree"))
    for name, head in heads.items():
        repo = task / name
        assert git(repo, "rev-parse", "HEAD") == head
        assert git(repo, "status", "--porcelain", "--", "main.txt").startswith(b"MM ")
        assert (repo / "node_modules/local").read_bytes() == b"preserve"


def test_configurable_hierarchy_and_name_sanitization(tmp_path, monkeypatch):
    task = tmp_path / "task"
    write(task, "main.txt")
    monkeypatch.setattr(snapshots.settings, "TASK_SESSION_SNAPSHOT_ROOT", str(tmp_path / "configured"))
    result = snapshots._create_checkpoint_sync(str(task), [], "none", None, "ws-1", "工作区/测试", "task-2", "任务:*?")
    root = Path(result["root"])
    assert root.parent == tmp_path / "configured/ws-1_工作区_测试/task-2_任务___"
    assert root.name.startswith("turn-")
    assert (root / "worktree.json").is_file()
    assert (root.parent / "objects").is_dir()
    snapshots._cleanup_checkpoint_sync(str(root))
    assert not objects(root.parent)


def test_policy_is_frozen_and_untracked_files_survive_roundtrip(tmp_path, monkeypatch):
    task = tmp_path / "task"
    write(task, "notes/local.txt")
    write(task, "generated/data")
    monkeypatch.setattr(snapshots.settings, "TASK_SESSION_SNAPSHOT_EXCLUDED_DIRS", ["generated"])
    checkpoint(task, tmp_path / "turn-1")
    monkeypatch.setattr(snapshots.settings, "TASK_SESSION_SNAPSHOT_EXCLUDED_DIRS", ["notes"])
    write(task, "notes/local.txt", b"changed")
    write(task, "generated/data", b"current")
    snapshots._restore_worktree_sync(str(tmp_path / "turn-1"), str(task), str(tmp_path / "turn-1/current-worktree"))
    assert (task / "notes/local.txt").read_bytes() == b"before\r\n\x00\xff"
    assert (task / "generated/data").read_bytes() == b"current"


def test_gc_aborts_on_invalid_manifest(tmp_path):
    task = tmp_path / "task"
    write(task, "main.txt")
    checkpoint(task, tmp_path / "turn-1")
    (tmp_path / "turn-1/worktree.json").write_text("invalid", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        store.collect(str(tmp_path))
    assert objects(tmp_path)


def test_file_directory_transitions(tmp_path):
    task = tmp_path / "task"
    write(task, "old-dir/file")
    write(task, "old-file")
    checkpoint(task, tmp_path / "turn-1")
    (task / "old-dir/file").unlink()
    (task / "old-dir").rmdir()
    write(task, "old-dir")
    (task / "old-file").unlink()
    write(task, "old-file/child")
    snapshots._restore_worktree_sync(str(tmp_path / "turn-1"), str(task), str(tmp_path / "turn-1/current-worktree"))
    assert (task / "old-dir/file").is_file()
    assert (task / "old-file").is_file()


def test_nested_git_worktree_control_file_survives(tmp_path):
    origin = tmp_path / "origin"
    init_repo(origin)
    write(origin, "main.py")
    git(origin, "add", ".")
    git(origin, "commit", "-m", "seed")
    task = tmp_path / "task"
    task.mkdir()
    git(origin, "worktree", "add", "--detach", str(task / "repo"))
    control = (task / "repo/.git").read_bytes()
    checkpoint(task, tmp_path / "turn-1", ["repo"])
    write(task, "repo/main.py", b"changed")
    write(task, "repo/new.py")
    snapshots._restore_worktree_sync(str(tmp_path / "turn-1"), str(task), str(tmp_path / "turn-1/current-worktree"))
    assert (task / "repo/.git").read_bytes() == control
    assert git(task / "repo", "status", "--porcelain") == b""


def test_failed_creation_reclaims_unpublished_objects(tmp_path, monkeypatch):
    task = tmp_path / "task"
    write(task, "main.py")
    monkeypatch.setattr(snapshots.settings, "TASK_SESSION_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))
    with patch.object(snapshots, "_provider_checkpoint_sync", side_effect=RuntimeError("provider failure")):
        with pytest.raises(RuntimeError, match="provider failure"):
            snapshots._create_checkpoint_sync(str(task), [], "none", None, "ws", "workspace", "task", "task")
    assert not list((tmp_path / "snapshots").rglob("worktree.json"))
    assert not list((tmp_path / "snapshots").glob("*/*/objects/*/*"))


def test_rejects_missing_worktree_and_snapshot_inside_worktree(tmp_path, monkeypatch):
    with pytest.raises(FileNotFoundError):
        checkpoint(tmp_path / "missing", tmp_path / "turn-1")
    task = tmp_path / "task"
    write(task, "main.py")
    monkeypatch.setattr(snapshots.settings, "TASK_SESSION_SNAPSHOT_ROOT", str(task / "snapshots"))
    with pytest.raises(snapshots.TaskSessionSnapshotError) as error:
        snapshots._create_checkpoint_sync(str(task), [], "none", None, "ws", "workspace", "task", "task")
    assert error.value.code == "SNAPSHOT_ROOT_INSIDE_WORKTREE"


def test_store_lock_serializes_publication_and_gc(tmp_path):
    task = tmp_path / "task"
    write(task, "main.py")
    entered = threading.Event()
    completed = threading.Event()
    failures = []

    def create():
        entered.set()
        try:
            checkpoint(task, tmp_path / "turn-1")
        except Exception as error:
            failures.append(error)
        finally:
            completed.set()

    with store.store_lock(str(tmp_path)):
        worker = threading.Thread(target=create)
        worker.start()
        assert entered.wait(2)
        assert not completed.wait(0.1)
        store.collect(str(tmp_path))
    worker.join(5)
    assert completed.is_set()
    assert not failures
    assert (tmp_path / "turn-1/worktree.json").exists()
    assert len(objects(tmp_path)) == 1


def test_task_below_repository_does_not_capture_ancestor_git_state(tmp_path):
    init_repo(tmp_path)
    write(tmp_path, "outside.txt")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "seed")
    task = tmp_path / "task"
    write(task, "main.txt")
    metadata = checkpoint(task, tmp_path / "turn-1")
    assert metadata["repositories"] == []
    assert set(metadata["manifest"]) == {"main.txt"}
