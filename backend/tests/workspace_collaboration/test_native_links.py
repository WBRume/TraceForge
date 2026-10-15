"""Linux links and Windows placeholder manifests share the same opaque Git bytes."""

import os

import pytest
from workspace_collaboration import test_service as collaboration_fixtures
from workspace_collaboration.test_service import (
    acknowledge,
    enabled,
    git,
    input_request,
    preparing,
)

from app.domains.task.models.task_repository import SddTaskRepository
from app.domains.workspace_collaboration import content, service

environment = collaboration_fixtures.environment

pytestmark = pytest.mark.skipif(os.name == "nt", reason="Requires native POSIX symlinks")


def test_native_journal_close_stops_watcher_before_returning(tmp_path):
    from app.domains.workspace_collaboration.change_journal import Journal

    journal = Journal(tmp_path)
    assert journal.thread.is_alive()
    journal.close()
    assert not journal.thread.is_alive()


def seed_links(environment):
    db, _task, task_root = environment
    for repo in ("api", "web"):
        root = task_root / repo
        (root / "linked.txt").symlink_to("same.txt")
        (root / "dangling").symlink_to("missing")
        (root / "directory").mkdir()
        (root / "directory/keep").write_bytes(b"untouched")
        (root / "directory-link").symlink_to("directory", target_is_directory=True)
        git(root, "add", ".")
        git(root, "commit", "-m", "links")
        db.get(SddTaskRepository, repo).base_commit_sha = git(root, "rev-parse", "HEAD")
    db.commit()


def test_dual_repo_link_roundtrip_delete_and_incremental_regular_edit(environment):
    db, task, root = environment
    seed_links(environment)
    state = preparing(environment)
    request = input_request(environment, state)
    store = content.ObjectStore(task)
    for repo in request.manifest.repositories:
        link = next(f for f in repo.files if f.path == "linked.txt")
        assert link.mode == "120000" and store.read(link.sha256) == b"same.txt"
        link.sha256, link.size = store.put(b"binary.bin"), len(b"binary.bin")
        repo.files = [f for f in repo.files if f.path != "dangling"]
    state = service.handoff(db, task, "u", request)
    db.commit()
    for repo in ("api", "web"):
        assert os.readlink(root / repo / "linked.txt") == "binary.bin"
        assert not os.path.lexists(root / repo / "dangling")
        assert (root / repo / "same.txt").read_bytes() == (repo + " baseline\r\n").encode()
        assert (root / repo / "directory/keep").read_bytes() == b"untouched"
    task.session_revision += 1
    service.advance_session(db, task, "submission")
    service.authorize_execution(db, task, "submission", "job")
    db.commit()
    for repo in ("api", "web"):
        link = root / repo / "linked.txt"
        link.unlink()
        link.symlink_to("missing-agent-output")
        (root / repo / "same.txt").write_bytes(b"agent output")
    service.capture_progress(db, task, "job")
    db.commit()
    (root / "web/same.txt").write_bytes(b"incremental edit")
    state = service.finish_execution(db, task, "job", confirmed_stopped=True)
    db.commit()
    snapshot = service.get_snapshot(db, task.id, state["snapshot_id"])
    for repo in snapshot["repositories"]:
        link = next(f for f in repo["files"] if f["path"] == "linked.txt")
        assert link["mode"] == "120000" and store.read(link["sha256"]) == b"missing-agent-output"
    assert acknowledge(environment, state)["sync_phase"] == "READY"


def test_link_install_recovery_never_follows_target_or_changes_target_mode(environment, monkeypatch, tmp_path):
    _db, _task, root = environment
    seed_links(environment)
    state = preparing(environment)
    request = input_request(environment, state)
    outside = tmp_path / "outside"
    outside.write_bytes(b"keep outside")
    outside.chmod(0o600)
    store = content.ObjectStore("t")
    link = next(f for f in request.manifest.repositories[0].files if f.path == "linked.txt")
    raw = os.fsencode(outside)
    link.sha256, link.size = store.put(raw), len(raw)
    baseline = service.get_snapshot(environment[0], "t", state["snapshot_id"])
    journal = store.journal

    def interrupt(operation, value):
        if value["status"] == "COMPLETED":
            raise OSError("interrupted")
        journal(operation, value)

    monkeypatch.setattr(store, "journal", interrupt)
    with pytest.raises(OSError, match="interrupted"):
        content.apply_manifest(root, baseline, request.manifest.model_dump(), store, "recover-link")
    monkeypatch.setattr(store, "journal", journal)
    content.apply_manifest(root, baseline, request.manifest.model_dump(), store, "recover-link", recover=True)
    assert os.readlink(root / "api/linked.txt") == str(outside)
    assert outside.read_bytes() == b"keep outside"
    assert outside.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="Linked collaboration path"):
        content.safe_path(root / "api", "directory-link/keep", leaf_link=True)
    with pytest.raises(ValueError, match="Linked collaboration path"):
        content.safe_path(root / "api", "linked.txt")


@pytest.mark.parametrize("path,mode", [("linked.txt", "100644"), ("same.txt", "120000")])
def test_native_link_type_conversion_rejected_before_writes(environment, path, mode):
    db, task, root = environment
    seed_links(environment)
    state = preparing(environment)
    request = input_request(environment, state)
    next(f for f in request.manifest.repositories[0].files if f.path == path).mode = mode
    with pytest.raises(service.CollaborationError, match="cannot be created or converted"):
        service.handoff(db, task, "u", request)
    assert os.readlink(root / "api/linked.txt") == "same.txt"


def test_replaced_git_link_cannot_export_target_contents(environment):
    seed_links(environment)
    _db, _task, root = environment
    (root / "api/linked.txt").unlink()
    (root / "api/linked.txt").write_bytes(b"unexpected regular file")
    with pytest.raises(ValueError, match="Unsupported Git link"):
        enabled(environment)
