"""Exercise the real file store and two independent Git repository baselines."""

import copy
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.subprocess_runner import run_git
from app.domains.auth.models.user import User, Workspace
from app.domains.task.models.chat_submission import TaskChatSubmission
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.models.task_repository import SddTaskRepository, TaskRepositoryState
from app.domains.workspace_collaboration import content, service
from app.domains.workspace_collaboration.models import CollaborationState
from app.domains.workspace_collaboration.schemas import (
    DeliveryReceipt,
    EnableRequest,
    Fence,
    HandoffRequest,
    LeaseRequest,
)


def git(path, *args):
    result = run_git(list(args), cwd=str(path), decode_text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture
def environment(db, tmp_path, monkeypatch):
    monkeypatch.setattr(content.settings, "TASK_SESSION_SNAPSHOT_ROOT", str(tmp_path / "private"))
    task_root = tmp_path / "task"
    task_root.mkdir()
    db.add(User(id="u", email="collaboration@test.local", display_name="Driver", hashed_password="x"))
    db.add(Workspace(id="w", name="Multi repo", owner_id="u"))
    task = SddTask(
        id="t",
        workspace_id="w",
        creator_id="u",
        name="Task",
        project_path=str(task_root),
        execution_location="SERVER",
        status=TaskStatus.CODING,
        session_generation=1,
        session_revision=0,
    )
    db.add(task)
    for name, branch in [("api", "release/2.x"), ("web", "feature/login")]:
        root = task_root / name
        root.mkdir()
        git(root, "init")
        git(root, "config", "user.name", "Test")
        git(root, "config", "user.email", "test@example.local")
        git(root, "config", "core.autocrlf", "false")
        (root / "same.txt").write_bytes((name + " baseline\r\n").encode())
        (root / "binary.bin").write_bytes(b"\x00\xff\xfe")
        git(root, "add", ".")
        git(root, "commit", "-m", "initial")
        sha = git(root, "rev-parse", "HEAD")
        db.add(
            SddTaskRepository(
                id=name,
                task_id="t",
                repository_id=None,
                repo_url="https://example.local/" + name,
                repo_name=name,
                repo_slug=name,
                branch_name=branch,
                base_commit_sha=sha,
                rel_path=name,
                state=TaskRepositoryState.READY,
            )
        )
    db.commit()
    return db, task, task_root


def enabled(environment):
    db, task, _ = environment
    state = service.enable(db, task, "u", EnableRequest(operation_id="enable", client_id="desktop", instance_id="boot"))
    db.commit()
    return state


def fence(state):
    return {
        "client_id": state["client_id"],
        "instance_id": state["instance_id"],
        "lease_epoch": state["lease_epoch"],
        "expected_state_version": state["state_version"],
        "expected_workspace_revision": state["workspace_revision"],
        "session_generation": state["session_generation"],
        "session_revision": state["session_revision"],
    }


def acknowledge(environment, state, **kwargs):
    db, task, _ = environment
    data = dict(
        **fence(state),
        operation_id=str(uuid4()),
        snapshot_id=state["snapshot_id"],
        local_scan_id="scan",
        repository_results=[
            {"task_repository_id": r["task_repository_id"], "status": "ALIGNED"} for r in state["repositories"]
        ],
    )
    data.update(kwargs)
    result = service.receipt(db, task, "u", DeliveryReceipt(**data))
    db.commit()
    return result


def preparing(environment):
    db, task, _ = environment
    state = acknowledge(environment, enabled(environment))
    receipt = TaskChatSubmission(
        id="submission",
        task_id="t",
        workspace_id="w",
        creator_id="u",
        client_message_id="message",
        content="edit",
        payload_hash="x",
        status="PREPARING",
        session_generation=1,
        session_revision=0,
        metadata_json={
            "collaboration": {key: state[key] for key in ["client_id", "instance_id", "binding_id", "lease_epoch"]}
        },
    )
    db.add(receipt)
    db.flush()
    state = service.request_input(db, task, receipt.id, "u")
    db.commit()
    return state


def input_request(environment, state, changes=None):
    db, _task, _ = environment
    manifest = copy.deepcopy(service.get_snapshot(db, "t", state["snapshot_id"]))
    store = content.ObjectStore("t")
    for repo in manifest["repositories"]:
        for name, raw in (changes or {}).get(repo["task_repository_id"], {}).items():
            repo["files"] = [entry for entry in repo["files"] if entry["path"] != name]
            if raw is not None:
                repo["files"].append({"path": name, "sha256": store.put(raw), "size": len(raw), "mode": "100644"})
    return HandoffRequest(
        **fence(state), operation_id="handoff", submission_id="submission", manifest=manifest, input_cut_seq=9
    )


def test_complete_round_keeps_each_repo_and_only_publishes_stable_output(environment):
    db, task, root = environment
    state = preparing(environment)
    assert not service.input_ready(db, "t", "submission")
    request = input_request(
        environment, state, {"api": {"same.txt": b"local input\r\n", "binary.bin": None, "new.bin": b"\xff\x00"}}
    )
    state = service.handoff(db, task, "u", request)
    db.commit()
    assert state["workspace_revision"] == 2
    assert (root / "api/same.txt").read_bytes() == b"local input\r\n"
    assert not (root / "api/binary.bin").exists()
    assert (root / "web/binary.bin").read_bytes() == b"\x00\xff\xfe"
    assert service.handoff(db, task, "u", request)["snapshot_id"] == state["snapshot_id"]
    task.session_revision += 1
    service.advance_session(db, task, "submission")
    authorized = service.authorize_execution(db, task, "submission", "job")
    db.commit()
    assert authorized["snapshot_id"] == state["snapshot_id"]
    (root / "api/same.txt").write_bytes(b"candidate\n")
    candidate = service.capture_progress(db, task, "job")
    db.commit()
    assert candidate["source"] == "PROGRESS"
    assert service.get_state(db, task)["workspace_revision"] == 2
    assert service.capture_progress(db, task, "job") is None
    (root / "api/same.txt").write_bytes(b"final\n")
    state = service.finish_execution(db, task, "job", confirmed_stopped=True)
    db.commit()
    assert state["workspace_revision"] == 3 and state["sync_phase"] == "DELIVERY_PENDING"
    final = service.get_snapshot(db, "t", state["snapshot_id"])
    assert {r["branch_name"] for r in final["repositories"]} == {"release/2.x", "feature/login"}
    assert len(final["repositories"]) == 2
    with pytest.raises(service.CollaborationError, match="Complete the current code delivery"):
        service.request_input(db, task, "next", "u")
    state = acknowledge(
        environment, state, conflicts=[{"task_repository_id": "api", "path": "same.txt", "local_sha256": "f" * 64}]
    )
    assert state["sync_phase"] == "CONFLICT_PENDING"
    state = acknowledge(environment, state, pending_local_changes=[{"task_repository_id": "web", "path": "theme.css"}])
    assert state["sync_phase"] == "READY"
    assert state["pending_local_changes"] == [{"task_repository_id": "web", "path": "theme.css"}]
    assert service.finish_execution(db, task, "old-job", confirmed_stopped=True) is None


def test_handoff_rejects_subset_missing_objects_and_stale_fences(environment):
    db, task, root = environment
    state = preparing(environment)
    request = input_request(environment, state)
    bad = request.model_copy(deep=True)
    bad.manifest.repositories.pop()
    with pytest.raises(service.CollaborationError, match="every task repository"):
        service.handoff(db, task, "u", bad)
    bad = request.model_copy(deep=True)
    bad.manifest.repositories[0].files[0].sha256 = "f" * 64
    with pytest.raises(service.CollaborationError, match="finished uploading"):
        service.handoff(db, task, "u", bad)
    bad = request.model_copy(update={"expected_workspace_revision": 99})
    with pytest.raises(service.CollaborationError, match="old code revision"):
        service.handoff(db, task, "u", bad)
    assert (root / "api/same.txt").read_bytes() == b"api baseline\r\n"


def test_partial_input_failure_is_recoverable_and_local_receipt_cannot_clear_it(environment, monkeypatch):
    db, task, root = environment
    state = preparing(environment)
    request = input_request(environment, state, {"api": {"same.txt": b"new api"}, "web": {"same.txt": b"new web"}})
    replace = content.os.replace

    def fail_second(source, target):
        if Path(target) == root / "web/same.txt":
            raise PermissionError("test locked second repository file")
        return replace(source, target)

    monkeypatch.setattr(content.os, "replace", fail_second)
    with pytest.raises(service.CollaborationError, match="test locked"):
        service.handoff(db, task, "u", request)
    db.commit()
    state = service.get_state(db, task)
    assert state["sync_phase"] == "RECOVERY_REQUIRED" and state["recovery_kind"] == "SERVER_INPUT"
    assert (root / "api/same.txt").read_bytes() == b"new api"
    assert (root / "web/same.txt").read_bytes() == b"web baseline\r\n"
    journal = content.ObjectStore("t").read_journal("handoff")
    assert journal["status"] == "APPLYING"
    assert all(item["status"] == "PENDING" for item in journal["files"])
    with pytest.raises(service.CollaborationError, match="Server workspace recovery"):
        acknowledge(environment, state)
    monkeypatch.setattr(content.os, "replace", replace)
    state = service.recover_input(db, task, "u", Fence(**fence(state)), "handoff")
    db.commit()
    assert state["sync_phase"] == "PREPARING" and service.input_ready(db, "t", "submission")
    assert (root / "web/same.txt").read_bytes() == b"new web"


def test_lease_session_and_repository_identity_are_fenced(environment):
    db, task, _ = environment
    state = preparing(environment)
    row = db.get(CollaborationState, "t")
    row.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
    with pytest.raises(service.CollaborationError, match="lease expired"):
        service.handoff(db, task, "u", input_request(environment, state))
    assert not service.input_ready(db, "t", "submission")
    with pytest.raises(service.CollaborationError, match="lease expired"):
        service.renew_lease(
            db, task, "u", LeaseRequest(client_id="desktop", instance_id="boot", lease_epoch=state["lease_epoch"])
        )
    row.lease_expires_at = datetime.utcnow() + timedelta(seconds=60)
    state = service.renew_lease(
        db, task, "u", LeaseRequest(client_id="desktop", instance_id="boot", lease_epoch=state["lease_epoch"])
    )
    db.get(SddTaskRepository, "web").branch_name = "other"
    db.flush()
    with pytest.raises(service.CollaborationError, match="bindings changed"):
        service.handoff(db, task, "u", input_request(environment, state))


def test_lease_lock_contention_returns_retryable_busy_without_faking_renewal(environment, monkeypatch):
    from sqlalchemy.exc import OperationalError

    db, task, _ = environment
    state = enabled(environment)
    deadline = db.get(CollaborationState, "t").lease_expires_at

    def busy(_db, _task_id, *, lock=True, nowait=False):
        assert nowait
        raise OperationalError("SELECT FOR UPDATE NOWAIT", {}, Exception(3572, "row lock busy"))

    monkeypatch.setattr(service, "_state", busy)
    with pytest.raises(service.CollaborationError) as failed:
        service.renew_lease(
            db, task, "u", LeaseRequest(**{k: state[k] for k in ("client_id", "instance_id", "lease_epoch")})
        )
    assert failed.value.code == "TASK_BUSY"
    assert db.get(CollaborationState, "t").lease_expires_at == deadline


def test_private_untracked_environment_and_ignored_files_never_enter_manifest(environment):
    db, task, root = environment
    (root / "api/.env").write_bytes(b"secret")
    (root / "api/.gitignore").write_text("ignored/\n")
    (root / "api/ignored").mkdir()
    (root / "api/ignored/cache").write_bytes(b"ignore")
    (root / "api/.sdd").mkdir()
    (root / "api/.sdd/internal").write_bytes(b"private")
    (root / "api/new.txt").write_bytes(b"include")
    state = enabled(environment)
    manifest = service.get_snapshot(db, "t", state["snapshot_id"])
    paths = {entry["path"] for entry in manifest["repositories"][0]["files"]}
    assert paths == {"same.txt", "binary.bin", ".gitignore", "new.txt"}


@pytest.mark.parametrize(
    "relative", ["../x", "/tmp/x", "C:/x", "a\\b", "a/.git/config", ".sdd/state", "CON.txt", "a//b", "x."]
)
def test_unsafe_paths_rejected(relative):
    with pytest.raises(ValueError):
        content.validate_path(relative)


def test_raw_object_hash_validation_and_task_isolation(environment):
    _db, _task, _root = environment
    store = content.ObjectStore("t")
    raw = b"\x00\xff\r\n"
    sha = store.put(raw)
    assert sha == hashlib.sha256(raw).hexdigest() and store.read(sha) == raw
    assert not content.ObjectStore("other").has(sha)
    with pytest.raises(ValueError, match="digest"):
        store.put(raw, "f" * 64)


def test_full_receipts_and_idempotent_enable(environment):
    db, task, _ = environment
    state = enabled(environment)
    again = service.enable(db, task, "u", EnableRequest(operation_id="enable", client_id="desktop", instance_id="boot"))
    assert again["snapshot_id"] == state["snapshot_id"]
    with pytest.raises(service.CollaborationError, match="exactly one"):
        acknowledge(environment, state, repository_results=[{"task_repository_id": "api", "status": "ALIGNED"}])


def test_cancelled_preparation_keeps_fixed_input_and_receipt_event(environment):
    db, task, _ = environment
    state = preparing(environment)
    state = service.handoff(db, task, "u", input_request(environment, state, {"api": {"same.txt": b"handoff"}}))
    db.commit()
    state = service.cancel_preparation(db, task, "u", Fence(**fence(state)), "submission")
    db.commit()
    assert state["sync_phase"] == "READY" and state["workspace_revision"] == 2
    assert db.get(TaskChatSubmission, "submission").status == "FAILED"


def test_takeover_expires_old_instance_and_requires_complete_reconciliation(environment):
    db, task, _ = environment
    state = acknowledge(environment, enabled(environment))
    request = EnableRequest(operation_id="claim", client_id="desktop", instance_id="new-boot")
    with pytest.raises(service.CollaborationError, match="active lease"):
        service.claim_driver(db, task, "u", request)
    db.get(CollaborationState, "t").lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
    new = service.claim_driver(db, task, "u", request)
    db.commit()
    assert new["lease_epoch"] == state["lease_epoch"] + 1
    assert new["sync_phase"] == "DELIVERY_PENDING" and new["reconciled_revision"] == 0
    with pytest.raises(service.CollaborationError, match="not the task driver"):
        service.renew_lease(
            db, task, "u", LeaseRequest(client_id="desktop", instance_id="boot", lease_epoch=state["lease_epoch"])
        )
    assert acknowledge(environment, new)["sync_phase"] == "READY"


def test_only_nonempty_handoff_records_human_provenance(environment):
    db, task, _ = environment
    state = preparing(environment)
    request = input_request(environment, state, {"web": {"same.txt": b"human"}})
    service.handoff(db, task, "u", request)
    db.commit()
    service.handoff(db, task, "u", request)
    history = service.handoff_history(db, "t")
    assert len(history) == 1
    assert history[0]["source"] == "ROUND_SNAPSHOT" and history[0]["actor_user_id"] == "u"
    assert [r["task_repository_id"] for r in history[0]["repository_deltas_json"]] == ["web"]
    assert history[0]["submission_id"] == "submission"


def test_unchanged_handoff_has_no_human_delta(environment):
    db, task, _ = environment
    state = preparing(environment)
    service.handoff(db, task, "u", input_request(environment, state))
    db.commit()
    assert service.handoff_history(db, "t") == []


def test_restore_recovery_requires_exact_completed_operation(environment):
    from app.domains.task.models.session_turn import TaskSessionOperation, TaskSessionOperationStatus

    db, task, root = environment
    state = acknowledge(environment, enabled(environment))
    service.begin_restore(db, task, "exact-undo")
    task.session_revision += 1
    (root / "api/same.txt").write_bytes(b"restored version")
    service.mark_recovery(db, "t", "capture failed")
    db.commit()
    state = service.get_state(db, task)
    with pytest.raises(service.CollaborationError, match="exact server history restore"):
        service.recover_output(db, task, "u", Fence(**fence(state)))
    db.add(
        TaskSessionOperation(
            id="undo",
            task_id="t",
            workspace_id="w",
            operation_id="exact-undo",
            actor_user_id="u",
            status=TaskSessionOperationStatus.REVERTED,
        )
    )
    db.commit()
    state = service.get_state(db, task)
    result = service.recover_output(db, task, "u", Fence(**fence(state)))
    db.commit()
    assert result["sync_phase"] == "DELIVERY_PENDING" and result["workspace_revision"] == 2
    assert result["session_revision"] == 1
    assert service.get_snapshot(db, "t", result["snapshot_id"])["source"] == "RESTORE"


def test_api_authentication_and_raw_transfer(environment):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app.dependencies import get_current_user, get_db
    from app.domains.auth.models.user import WorkspaceMember, WorkspaceRole
    from app.domains.workspace_collaboration.router import router

    db, _task, _ = environment
    db.add(WorkspaceMember(id="member", workspace_id="w", user_id="u", role=WorkspaceRole.OWNER))
    db.commit()
    bind = db.get_bind()
    app = FastAPI()
    app.include_router(router, prefix="/api")

    def database():
        with Session(bind=bind) as session:
            yield session

    user = db.get(User, "u")
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: user
    prefix = "/api/workspaces/w/tasks/t/collaboration"
    with TestClient(app) as client:
        response = client.post(
            prefix + "/enable", json={"operation_id": "api-enable", "client_id": "desktop", "instance_id": "boot"}
        )
        assert response.status_code == 200, response.text
        state = response.json()
        raw = b"\x00\xff\r\n"
        sha = hashlib.sha256(raw).hexdigest()
        params = {key: state[key] for key in ("client_id", "instance_id", "lease_epoch")}
        uploaded = client.put(prefix + "/objects/" + sha, params=params, content=raw)
        assert uploaded.status_code == 200, uploaded.text
        assert client.get(prefix + "/objects/" + sha).content == raw
        assert client.post(prefix + "/objects/missing", json={"hashes": [sha, "f" * 64]}).json() == {
            "missing": ["f" * 64]
        }
        rejected = client.put(prefix + "/objects/" + sha, params={**params, "instance_id": "forged"}, content=raw)
        assert rejected.status_code == 409 and rejected.json()["detail"]["code"] == "DRIVER_REQUIRED"
        assert client.get(prefix.replace("workspaces/w", "workspaces/not-member")).status_code == 403


def test_file_directory_transitions_and_interrupted_recovery(environment, monkeypatch):
    db, task, root = environment
    (root / "api/folder").mkdir()
    (root / "api/folder/child.txt").write_bytes(b"old child")
    state = preparing(environment)
    request = input_request(
        environment,
        state,
        {
            "api": {
                "same.txt": None,
                "same.txt/nested.bin": b"\x00\xff",
                "folder/child.txt": None,
                "folder": b"directory became file",
            }
        },
    )
    replace = content.os.replace

    def fail_nested(source, target):
        if Path(target) == root / "api/same.txt/nested.bin":
            raise PermissionError("interrupted structural change")
        return replace(source, target)

    monkeypatch.setattr(content.os, "replace", fail_nested)
    with pytest.raises(service.CollaborationError, match="interrupted structural"):
        service.handoff(db, task, "u", request)
    db.commit()
    monkeypatch.setattr(content.os, "replace", replace)
    state = service.get_state(db, task)
    state = service.recover_input(db, task, "u", Fence(**fence(state)), "handoff")
    db.commit()
    assert state["sync_phase"] == "PREPARING"
    assert (root / "api/folder").read_bytes() == b"directory became file"
    assert (root / "api/same.txt/nested.bin").read_bytes() == b"\x00\xff"


def test_windows_mode_change_is_rejected_before_install(environment):
    if content.os.name != "nt":
        pytest.skip("Windows capability boundary")
    db, task, root = environment
    state = preparing(environment)
    request = input_request(environment, state)
    request.manifest.repositories[0].files[0].mode = "100755"
    with pytest.raises(service.CollaborationError, match="filesystem that supports"):
        service.handoff(db, task, "u", request)
    assert service.get_state(db, task)["sync_phase"] == "PREPARING"
    assert (root / "api/binary.bin").read_bytes() == b"\x00\xff\xfe"


def _git_link_placeholder(environment, *, commit=True):
    if content.os.name != "nt":
        pytest.skip("Windows Git placeholder capability")
    db, _task, task_root = environment
    root = task_root / "api"
    git(root, "config", "core.symlinks", "false")
    (root / "linked.txt").write_bytes(b"same.txt")
    blob = git(root, "hash-object", "-w", "linked.txt")
    git(root, "update-index", "--add", "--cacheinfo", "120000", blob, "linked.txt")
    if commit:
        git(root, "commit", "-m", "tracked link placeholder")
        db.get(SddTaskRepository, "api").base_commit_sha = git(root, "rev-parse", "HEAD")
        db.commit()
    return root


def test_windows_git_link_placeholder_preserves_mode_and_raw_target(environment):
    db, task, _ = environment
    root = _git_link_placeholder(environment)
    state = preparing(environment)
    request = input_request(environment, state)
    link = next(entry for entry in request.manifest.repositories[0].files if entry.path == "linked.txt")
    assert link.mode == "120000"
    assert content.ObjectStore("t").read(link.sha256) == b"same.txt"
    link.sha256 = content.ObjectStore("t").put(b"binary.bin")
    link.size = len(b"binary.bin")
    state = service.handoff(db, task, "u", request)
    db.commit()
    assert (root / "linked.txt").read_bytes() == b"binary.bin"
    assert not (root / "linked.txt").is_symlink()
    snapshot = service.get_snapshot(db, "t", state["snapshot_id"])
    assert (
        next(entry for entry in snapshot["repositories"][0]["files"] if entry["path"] == "linked.txt")["mode"]
        == "120000"
    )


@pytest.mark.parametrize("path,mode", [("linked.txt", "100644"), ("same.txt", "120000"), ("new.txt", "120000")])
def test_link_placeholder_creation_and_type_conversion_are_rejected(environment, path, mode):
    from app.domains.workspace_collaboration.schemas import FileEntry

    db, task, _ = environment
    root = _git_link_placeholder(environment)
    state = preparing(environment)
    request = input_request(environment, state)
    files = request.manifest.repositories[0].files
    entry = next((item for item in files if item.path == path), None)
    if entry:
        entry.mode = mode
    else:
        files.append(FileEntry(path=path, sha256=content.ObjectStore("t").put(b"same.txt"), size=8, mode=mode))
    with pytest.raises(service.CollaborationError, match="cannot be created or converted"):
        service.handoff(db, task, "u", request)
    assert (root / "linked.txt").read_bytes() == b"same.txt"
    assert not (root / "new.txt").exists()


def test_git_link_placeholder_requires_explicit_false_and_committed_type(environment):
    root = _git_link_placeholder(environment, commit=False)
    with pytest.raises(ValueError, match="placeholder required"):
        enabled(environment)
    environment[0].rollback()
    git(root, "commit", "-m", "anchor link")
    git(root, "config", "core.symlinks", "true")
    with pytest.raises(ValueError, match="placeholder required"):
        enabled(environment)


def test_slow_capture_renews_reserved_driver_without_accepting_expired_replay(environment, monkeypatch):
    db, task, _ = environment
    original_capture = service._capture

    class CaptureClock:
        now = datetime.utcnow()

        @classmethod
        def utcnow(cls):
            return cls.now

    def slow_capture(*args, **kwargs):
        captured = original_capture(*args, **kwargs)
        CaptureClock.now += timedelta(seconds=120)
        return captured

    monkeypatch.setattr(service, "datetime", CaptureClock)
    monkeypatch.setattr(service, "_capture", slow_capture)
    state = preparing(environment)
    assert datetime.fromisoformat(state["lease_expires_at"].removesuffix("Z")) > CaptureClock.now
    request = input_request(environment, state, {"api": {"same.txt": b"slow input"}})
    state = service.handoff(db, task, "u", request)
    db.commit()
    assert state["sync_phase"] == "PREPARING"
    assert service.input_ready(db, "t", "submission")
    CaptureClock.now += timedelta(seconds=61)
    with pytest.raises(service.CollaborationError, match="lease expired"):
        service.handoff(db, task, "u", request)


@pytest.mark.parametrize("expired_at_start", [False, True])
def test_final_capture_only_renews_the_driver_lease_reserved_at_start(environment, monkeypatch, expired_at_start):
    db, task, _ = environment
    state = preparing(environment)
    service.handoff(db, task, "u", input_request(environment, state))
    task.session_revision += 1
    service.advance_session(db, task, "submission")
    service.authorize_execution(db, task, "submission", "job")
    db.commit()

    class CaptureClock:
        now = datetime.utcnow()

        @classmethod
        def utcnow(cls):
            return cls.now

    if expired_at_start:
        db.get(CollaborationState, "t").lease_expires_at = CaptureClock.now - timedelta(seconds=1)
    original_capture = service._capture

    def slow_capture(*args, **kwargs):
        captured = original_capture(*args, **kwargs)
        CaptureClock.now += timedelta(seconds=120)
        return captured

    monkeypatch.setattr(service, "datetime", CaptureClock)
    monkeypatch.setattr(service, "_capture", slow_capture)
    state = service.finish_execution(db, task, "job", confirmed_stopped=True)
    db.commit()
    assert state["sync_phase"] == "DELIVERY_PENDING"
    assert state["driver_connected"] is not expired_at_start


def test_journal_writes_complete_plan_once_then_completion_and_replay_is_idempotent(environment, monkeypatch):
    db, _task, root = environment
    state = preparing(environment)
    request = input_request(environment, state, {"api": {"same.txt": b"a"}, "web": {"same.txt": b"b"}})
    store = content.ObjectStore("t")
    baseline = service.get_snapshot(db, "t", state["snapshot_id"])
    calls = []
    original_journal = store.journal

    def persist(operation_id, journal):
        if journal["status"] == "APPLYING":
            assert (root / "api/same.txt").read_bytes() == b"api baseline\r\n"
            assert (root / "web/same.txt").read_bytes() == b"web baseline\r\n"
        calls.append(journal["status"])
        original_journal(operation_id, journal)

    monkeypatch.setattr(store, "journal", persist)
    content.apply_manifest(root, baseline, request.manifest.model_dump(), store, "apply")
    assert calls == ["APPLYING", "COMPLETED"]
    assert (root / "api/same.txt").read_bytes() == b"a"
    assert (root / "web/same.txt").read_bytes() == b"b"

    def unexpected_write(*args, **kwargs):
        pytest.fail("Completed replay must not install files again")

    monkeypatch.setattr(content, "_install_item", unexpected_write)
    content.apply_manifest(root, baseline, request.manifest.model_dump(), store, "apply", recover=True)
    assert calls == ["APPLYING", "COMPLETED"]


def test_input_recovers_when_all_files_written_but_completion_journal_fails(environment, monkeypatch):
    db, task, root = environment
    state = preparing(environment)
    request = input_request(environment, state, {"api": {"same.txt": b"a"}, "web": {"same.txt": b"b"}})
    original_journal = content.ObjectStore.journal

    def interrupted_completion(store, operation_id, journal):
        if journal["status"] == "COMPLETED":
            raise OSError("completion journal interrupted")
        original_journal(store, operation_id, journal)

    monkeypatch.setattr(content.ObjectStore, "journal", interrupted_completion)
    with pytest.raises(service.CollaborationError, match="completion journal interrupted"):
        service.handoff(db, task, "u", request)
    db.commit()
    assert (root / "api/same.txt").read_bytes() == b"a"
    assert (root / "web/same.txt").read_bytes() == b"b"
    journal = content.ObjectStore("t").read_journal("handoff")
    assert all(item["status"] == "PENDING" for item in journal["files"])
    monkeypatch.setattr(content.ObjectStore, "journal", original_journal)
    recovered = service.recover_input(db, task, "u", Fence(**fence(service.get_state(db, task))), "handoff")
    db.commit()
    assert recovered["sync_phase"] == "PREPARING"
    assert content.ObjectStore("t").read_journal("handoff")["status"] == "COMPLETED"


def test_shared_git_capture_rejects_replacement_during_raw_import(environment, monkeypatch):
    import builtins

    from app.domains.task.services import task_git_snapshot_store as snapshots

    _db, _task, root = environment
    path = root / "api/same.txt"
    shadow = snapshots.Shadow(str(root), str(root.parent / "private-test"), "api", str(root / "api"))
    shadow.initialize()
    original_open = builtins.open

    def replace_before_open(filename, mode="r", *args, **kwargs):
        if str(filename) == str(path) and mode == "rb":
            path.rename(root / "api/old.txt")
            path.write_bytes(b"replacement")
        return original_open(filename, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", replace_before_open)
    with pytest.raises(ValueError, match="File changed during snapshot"):
        shadow.import_blobs(["same.txt"])


def test_windows_cmd_capture_accepts_extension_mode_but_keeps_git_mode(environment):
    if content.os.name != "nt":
        pytest.skip("Windows filename-derived executable bits")
    db, _task, root = environment
    path = root / "api/launcher.cmd"
    path.write_bytes(b"@echo off\r\necho validation\r\n")
    git(root / "api", "add", "launcher.cmd")
    state = enabled(environment)
    manifest = service.get_snapshot(db, "t", state["snapshot_id"])
    entry = next(item for item in manifest["repositories"][0]["files"] if item["path"] == "launcher.cmd")
    assert entry["mode"] == "100644"
    assert content.ObjectStore("t").read(entry["sha256"]) == path.read_bytes()


def test_migration_roundtrip_matches_registered_models(db, monkeypatch):
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    from app.database import Base

    path = Path(__file__).resolve().parents[2] / "alembic/versions/d0b6a2e94f31_workspace_collaboration.py"
    spec = importlib.util.spec_from_file_location("collaboration_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with db.get_bind().begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.downgrade()
        migration.upgrade()
        inspector = inspect(connection)
        for name, table in Base.metadata.tables.items():
            if name.startswith("task_collaboration_"):
                assert {column["name"] for column in inspector.get_columns(name)} == set(table.columns.keys())


def test_browser_driver_request_waits_for_native_handoff(environment):
    db, task, _ = environment
    state = acknowledge(environment, enabled(environment))
    row = TaskChatSubmission(
        id="web-submit",
        task_id="t",
        workspace_id="w",
        creator_id="u",
        client_message_id="browser",
        content="edit",
        payload_hash="x",
        status="PREPARING",
        session_generation=1,
        session_revision=0,
        metadata_json={
            "collaboration": {"request_driver_input": True, "binding_id": "wrong", "lease_epoch": state["lease_epoch"]}
        },
    )
    db.add(row)
    db.flush()
    with pytest.raises(service.CollaborationError, match="bound desktop instance"):
        service.request_input(db, task, row.id, "u")
    row.metadata_json = {
        "collaboration": {
            "request_driver_input": True,
            "binding_id": state["binding_id"],
            "lease_epoch": state["lease_epoch"],
        }
    }
    state = service.request_input(db, task, row.id, "u")
    db.commit()
    assert state["sync_phase"] == "PREPARING" and not service.input_ready(db, "t", row.id)


def test_git_preview_and_final_reuse_blobs_without_forcing_full_contents(environment, monkeypatch):
    from app.domains.task.services import task_git_snapshot_store as snapshots

    db, task, root = environment
    state = preparing(environment)
    service.handoff(db, task, "u", input_request(environment, state))
    task.session_revision += 1
    service.advance_session(db, task, "submission")
    service.authorize_execution(db, task, "submission", "job")
    db.commit()
    (root / "api/same.txt").write_bytes(b"cloud result")
    staged = service.stage_progress(db, task, "job")
    db.commit()
    captured = service.collect_progress(staged)
    service.publish_progress(db, task, "job", staged, captured)
    db.commit()
    reads, forced = [], []
    original_read, original_run = snapshots.read_blobs, snapshots.Shadow.run

    def observe_read(directory, objects):
        reads.extend(objects)
        return original_read(directory, objects)

    def observe_run(shadow, args, data=None):
        if "--renormalize" in args:
            forced.append(args)
        return original_run(shadow, args, data)

    monkeypatch.setattr(snapshots, "read_blobs", observe_read)
    monkeypatch.setattr(snapshots.Shadow, "run", observe_run)
    assert service.capture_progress(db, task, "job") is None
    assert reads == [] and forced == []
    result = service.finish_execution(db, task, "job", confirmed_stopped=True)
    db.commit()
    assert reads == []
    assert forced == []
    assert result["sync_phase"] == "DELIVERY_PENDING"


def test_cancel_after_lost_handoff_commit_requires_server_reconciliation(environment):
    db, task, root = environment
    state = preparing(environment)
    request = input_request(environment, state, {"api": {"same.txt": b"installed before lost commit"}})
    service.handoff(db, task, "u", request)
    db.rollback()
    state = service.get_state(db, task)
    assert state["workspace_revision"] == 1 and (root / "api/same.txt").read_bytes() == b"installed before lost commit"
    state = service.cancel_preparation(db, task, "u", Fence(**fence(state)), "submission")
    db.commit()
    assert state["sync_phase"] == "RECOVERY_REQUIRED" and state["recovery_operation_id"] == "handoff"
    state = service.recover_input(db, task, "u", Fence(**fence(state)), "handoff")
    db.commit()
    assert state["sync_phase"] == "READY" and state["workspace_revision"] == 2
    assert state["pending_submission_id"] is None and state["input_cut_seq"] == 9
    assert (root / "api/same.txt").read_bytes() == b"installed before lost commit"


def test_new_preparation_fences_late_old_output(environment):
    db, task, _ = environment
    state = preparing(environment)
    service.handoff(db, task, "u", input_request(environment, state))
    task.session_revision += 1
    service.advance_session(db, task, "submission")
    service.authorize_execution(db, task, "submission", "old-job")
    db.commit()
    state = service.finish_execution(db, task, "old-job", confirmed_stopped=True)
    db.commit()
    state = acknowledge(environment, state)
    old = db.get(TaskChatSubmission, "submission")
    old.status = "SUCCEEDED"
    new = TaskChatSubmission(
        id="new-submission",
        task_id="t",
        workspace_id="w",
        creator_id="u",
        client_message_id="new-message",
        content="next",
        payload_hash="x",
        status="PREPARING",
        session_generation=task.session_generation,
        session_revision=task.session_revision,
        metadata_json=old.metadata_json,
    )
    db.add(new)
    db.flush()
    state = service.request_input(db, task, new.id, "u")
    db.commit()
    assert service.finish_execution(db, task, "old-job", confirmed_stopped=True) is None
    assert service.get_state(db, task)["sync_phase"] == "PREPARING"


def test_git_store_reuses_initial_index_batches_mappings_and_retains_old_bytes(environment, monkeypatch):
    from app.domains.task.services import task_git_snapshot_store as snapshots

    db, task, root = environment
    state = enabled(environment)
    first = service.get_snapshot(db, task.id, state["snapshot_id"])
    store = content.ObjectStore(task.id)
    assert store.git_objects.shared_root() == Path(task.task_meta_json["initial_workspace_checkpoint"]).parent
    entries = [entry for repo in first["repositories"] for entry in repo["files"]]
    assert store.has_many([entry["sha256"] for entry in entries]) == {entry["sha256"] for entry in entries}
    assert not (store.root / "objects").exists()
    reads = []
    original = snapshots.read_blobs

    def observe(directory, objects):
        reads.extend(objects)
        return original(directory, objects)

    monkeypatch.setattr(snapshots, "read_blobs", observe)
    service._inventory(task.id, task.project_path, service.repository_metadata(db, task), stable=True)
    assert reads == []
    (root / "api/same.txt").write_bytes(b"new version")
    service._inventory(task.id, task.project_path, service.repository_metadata(db, task), stable=True)
    assert len(reads) == 1
    old = next(entry for entry in first["repositories"][0]["files"] if entry["path"] == "same.txt")
    snapshots.collect(str(store.git_objects.shared_root()))
    assert store.read(old["sha256"]) == b"api baseline\r\n"


def test_exact_h_checkpoint_keeps_private_scope_out_of_wire_manifest(environment):
    import json

    db, task, root = environment
    (root / "api/.env").write_bytes(b"first secret")
    state = preparing(environment)
    service.handoff(db, task, "u", input_request(environment, state))
    db.commit()
    original = service.input_worktree_checkpoint(db, task, "submission")
    (root / "api/.env").write_bytes(b"second secret")
    service._inventory(task.id, task.project_path, service.repository_metadata(db, task), stable=True)
    assert service.input_worktree_checkpoint(db, task, "submission") == original
    snapshot = service.get_snapshot(db, task.id, service.get_state(db, task)["input_snapshot_id"])
    serialized = json.dumps(snapshot)
    assert ".env" not in serialized and "git_dir" not in serialized and "object_store" not in serialized
    secret_sha = hashlib.sha256(b"first secret").hexdigest()
    assert not content.ObjectStore(task.id).has(secret_sha)


def test_legacy_raw_object_migrates_to_git_without_losing_journal(environment):
    _db, task, _root = environment
    store = content.ObjectStore(task.id)
    raw = b"legacy\x00\xff\r\n"
    sha = hashlib.sha256(raw).hexdigest()
    path = store.path(sha)
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    store.journal("old-input", {"status": "APPLYING", "target": {"submission_id": "old"}})
    assert store.read(sha) == raw
    path.unlink()
    assert content.ObjectStore(task.id).read(sha) == raw
    assert content.ObjectStore(task.id).input_journals("old")[0]["status"] == "APPLYING"


def test_legacy_input_batch_migrates_once_without_per_file_git_processes(environment, monkeypatch):
    from app.domains.task.services import task_git_snapshot_store as snapshots

    store = content.ObjectStore(environment[1].id)
    entries = []
    for number in range(32):
        raw = f"legacy-{number}".encode() + b"\x00\xff"
        sha = hashlib.sha256(raw).hexdigest()
        path = store.path(sha)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        entries.append({"sha256": sha, "size": len(raw)})
    commands = []
    original = snapshots.shadow_git

    def observe(directory, args, data=None, **kwargs):
        commands.append(args)
        return original(directory, args, data, **kwargs)

    monkeypatch.setattr(snapshots, "shadow_git", observe)
    store.validate_objects(entries)
    assert sum("fast-import" in args for args in commands) == 1
    assert sum("update-ref" in args for args in commands) == 1
    assert len(commands) <= 4
    assert len(store.git_objects.known([entry["sha256"] for entry in entries])) == 32
    for entry in entries:
        assert store.path(entry["sha256"]).exists()


def test_finalization_refreshes_stale_identity_map_before_publishing(environment):
    from sqlalchemy import update

    db, task, _root = environment
    state = preparing(environment)
    service.handoff(db, task, "u", input_request(environment, state))
    task.session_revision += 1
    service.advance_session(db, task, "submission")
    service.authorize_execution(db, task, "submission", "job")
    db.commit()
    stale = db.get(CollaborationState, task.id)
    assert stale.sync_phase == "RUNNING"
    # Simulate a committed final publisher without refreshing this worker's ORM identity.
    db.execute(
        update(CollaborationState).where(CollaborationState.task_id == task.id).values(sync_phase="DELIVERY_PENDING"),
        execution_options={"synchronize_session": False},
    )
    db.commit()
    old_id = stale.snapshot_id
    assert service.finish_execution(db, task, "job", confirmed_stopped=True)["snapshot_id"] == old_id
    assert db.get(CollaborationState, task.id).sync_phase == "DELIVERY_PENDING"


def test_stable_publication_updates_changed_paths_without_full_inventory(environment, monkeypatch):
    from app.domains.task.services import task_git_snapshot_store as git_store

    db, task, _root = environment
    state = preparing(environment)
    request = input_request(environment, state, {"api": {"same.txt": b"incremental"}})
    calls = []
    original = git_store.capture

    def capture(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(git_store, "capture", capture)
    accepted = service.handoff(db, task, "u", request)
    assert accepted["input_snapshot_id"]
    assert calls == []


def test_delta_handoff_replay_multirepo_and_private_rollback_without_inventory(environment, monkeypatch):
    import json

    from app.domains.task.services import task_git_snapshot_store as git_store
    from app.domains.workspace_collaboration.delta import between

    db, task, root = environment
    state = preparing(environment)
    base = service.get_snapshot(db, task.id, state["snapshot_id"])
    full = input_request(
        environment, state, {"api": {"same.txt": b"delta", "new.bin": b"\x00\xff"}, "web": {"binary.bin": None}}
    )
    wire = between(base, full.manifest.model_dump())
    request = HandoffRequest(**{**full.model_dump(), "manifest": wire})
    assert sum(len(repo["files"]) for repo in wire["repositories"]) == 2
    assert wire["repositories"][1]["deleted"] == ["binary.bin"]
    (root / "private-notes.txt").write_bytes(b"rollback only")
    monkeypatch.setattr(git_store, "scan", lambda *_args: pytest.fail("warm cut traversed the worktree"))
    accepted = service.handoff(db, task, "u", request)
    db.commit()
    assert service.handoff(db, task, "u", request)["snapshot_id"] == accepted["snapshot_id"]
    checkpoint = json.loads(
        (content.ObjectStore(task.id).root / "snapshots" / (accepted["snapshot_id"] + ".json")).read_text()
    )
    assert "private-notes.txt" in git_store.entries(checkpoint["worktree"])
    assert (root / "api/same.txt").read_bytes() == b"delta"
    assert not (root / "web/binary.bin").exists()


def test_delta_rejects_wrong_base_and_repo_branch_before_writing(environment):
    from app.domains.workspace_collaboration.delta import between

    db, task, root = environment
    state = preparing(environment)
    base = service.get_snapshot(db, task.id, state["snapshot_id"])
    full = input_request(environment, state, {"api": {"same.txt": b"delta"}})
    wire = between(base, full.manifest.model_dump())
    bad = copy.deepcopy(wire)
    bad["delta"]["base_snapshot_id"] = "wrong"
    with pytest.raises(ValueError, match="DELTA_BASE_MISMATCH"):
        service.handoff(db, task, "u", HandoffRequest(**{**full.model_dump(), "manifest": bad}))
    wire["repositories"][0]["branch_name"] = "wrong"
    with pytest.raises(ValueError, match="DELTA_REPOSITORY_MISMATCH"):
        service.handoff(db, task, "u", HandoffRequest(**{**full.model_dump(), "manifest": wire}))
    assert (root / "api/same.txt").read_bytes() == b"api baseline\r\n"


def test_runtime_skill_directory_replacement_stays_scoped_and_preserves_git_stat_cache(environment, monkeypatch):
    from app.domains.task.services import task_git_snapshot_store as git_store
    from app.domains.workspace_collaboration import change_journal

    db, task, root = environment
    state = enabled(environment)
    repositories = service.repository_metadata(db, task)
    store = content.ObjectStore(task.id)
    original_scan = git_store.scan
    scanned = []

    def scoped_scan(directory, policy):
        assert Path(directory) != root, "directory changes must not walk the entire task"
        scanned.append(Path(directory))
        return original_scan(directory, policy)

    monkeypatch.setattr(git_store, "scan", scoped_scan)
    skills = root / ".agents" / "skills"
    skills.mkdir(parents=True)
    (skills / "runtime.json").write_bytes(b"first")
    first = content.capture_task(root, store, repositories, stable=False)
    skills.rename(root / ".agents" / "old-skills")
    skills.mkdir()
    (skills / "runtime.json").write_bytes(b"second")
    second = content.capture_task(root, store, repositories, stable=True)
    assert first == second == service.get_snapshot(db, task.id, state["snapshot_id"])["repositories"]
    assert scanned and all(path.is_relative_to(root / ".agents") for path in scanned)
    # A recovery inventory may stat every path, but must not import all unchanged contents.
    monkeypatch.setattr(git_store, "scan", original_scan)
    original_import = git_store.Shadow.import_blobs
    imported = []

    def importing(shadow, names):
        imported.extend((shadow.relative, name) for name in names)
        return original_import(shadow, names)

    monkeypatch.setattr(git_store.Shadow, "import_blobs", importing)
    change_journal.close_all()
    content.capture_task(root, store, repositories, stable=True)
    assert not any(part in {"api", "web"} for part, _ in imported)


def test_hot_publication_keeps_refs_and_reads_only_requested_object_mappings(environment, monkeypatch):
    from app.domains.task.services import task_git_snapshot_store as git_store
    from app.domains.workspace_collaboration.git_objects import GitObjects

    db, task, root = environment
    state = preparing(environment)
    request = input_request(environment, state, {"api": {"same.txt": b"only api changed"}})
    queries = []
    connect = GitObjects.connect

    def traced_connect(self):
        connection = connect(self)
        connection.set_trace_callback(queries.append)
        return connection

    monkeypatch.setattr(GitObjects, "connect", traced_connect)
    accepted = service.handoff(db, task, "u", request)
    lookups = [q for q in queries if q.startswith("SELECT oid,sha256,size")]
    assert lookups and all(" WHERE oid IN (" in q for q in lookups)
    store = content.ObjectStore(task.id)
    import json

    checkpoint = json.loads((store.root / "snapshots" / (accepted["snapshot_id"] + ".json")).read_text())
    for part in checkpoint["worktree"]["partitions"]:
        assert git_store.shadow_git(part["git_dir"], ["rev-parse", part["ref"]]).decode().strip() == part["tree"]
    assert (root / "web/same.txt").read_bytes() == b"web baseline\r\n"


def test_handoff_validates_small_object_batch_once_and_reuses_bytes_for_both_repos(environment, monkeypatch):
    from app.domains.task.services import task_git_snapshot_store as git_store

    db, task, root = environment
    state = preparing(environment)
    request = input_request(
        environment, state, {"api": {"same.txt": b"api changed"}, "web": {"same.txt": b"web changed"}}
    )
    calls = []
    original = git_store.read_blobs

    def read(directory, objects):
        calls.append(len(objects))
        yield from original(directory, objects)

    monkeypatch.setattr(git_store, "read_blobs", read)
    service.handoff(db, task, "u", request)
    assert calls == [2]
    assert (root / "api/same.txt").read_bytes() == b"api changed"
    assert (root / "web/same.txt").read_bytes() == b"web changed"


def test_verified_input_batch_rejects_wrong_mapping_before_any_install(environment):
    db, task, root = environment
    state = preparing(environment)
    request = input_request(environment, state, {"api": {"same.txt": b"good input!"}})
    store = content.ObjectStore(task.id)
    expected = hashlib.sha256(b"good input!").hexdigest()
    wrong = store.put(b"wrong input")
    with store.git_objects.connect() as connection:
        connection.execute("DELETE FROM objects WHERE sha256=?", (expected,))
        connection.execute("UPDATE objects SET sha256=? WHERE sha256=?", (expected, wrong))
    with pytest.raises(service.CollaborationError, match="checksum"):
        service.handoff(db, task, "u", request)
    assert (root / "api/same.txt").read_bytes() == b"api baseline\r\n"
