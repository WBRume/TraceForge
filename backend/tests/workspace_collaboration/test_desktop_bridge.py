"""Exercise the Python coordinator and actual TypeScript desktop through their wire DTOs."""

import base64
import json
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import pytest
from workspace_collaboration import test_service as shared
from workspace_collaboration.test_service import enabled, fence, git

from app.domains.task.models.chat_submission import TaskChatSubmission
from app.domains.task.services import task_git_snapshot_store, task_session_snapshot_service
from app.domains.workspace_collaboration import content, service
from app.domains.workspace_collaboration.schemas import DeliveryReceipt, HandoffRequest, LeaseRequest

environment = shared.environment


@pytest.fixture
def desktop(tmp_path, environment):
    repository_root = Path(__file__).resolve().parents[3]
    frontend = repository_root / "frontend"
    executable = frontend / "node_modules" / "bun" / "bin" / ("bun.exe" if os.name == "nt" else "bun")
    if not executable.is_file():
        pytest.skip("Installed frontend Bun runtime is required for native collaboration integration")
    runtime_url = (frontend / "desktop/local-resource/collaboration.ts").as_uri()
    bridge = tmp_path / "desktop-bridge.ts"
    bridge.write_text(
        f"import {{ CollaborationRuntime }} from {json.dumps(runtime_url)};\n"
        "import fs from 'node:fs';\n"
        "const input = JSON.parse(fs.readFileSync(0, 'utf8'));\n"
        "const runtime = new CollaborationRuntime(input.state, () => input.roots);\n"
        "try { process.stdout.write(JSON.stringify(runtime.execute(input.kind, input.payload))); }\n"
        "finally { runtime.close(); }\n",
        encoding="utf-8",
    )

    def execute(kind, payload):
        # Each request starts a new runtime to prove binding, input and recovery persistence.
        process = subprocess.Popen(
            [str(executable), str(bridge)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        request = json.dumps(
            {"state": str(tmp_path / "desktop-state"), "roots": [str(tmp_path)], "kind": kind, "payload": payload}
        )
        deadline = time.monotonic() + 120
        try:
            while True:
                try:
                    output, error = process.communicate(request, timeout=min(10, max(0.1, deadline - time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    request = None
                    if time.monotonic() >= deadline:
                        raise
                    # Desktop heartbeat continues independently while its file worker is busy.
                    db, task, _root = environment
                    renew(environment, service.get_state(db, task))
            assert process.returncode == 0, error
            return json.loads(output)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)

    return execute


def transfer_to_desktop(desktop, manifest):
    store = content.ObjectStore(manifest["task_id"])
    hashes = {entry["sha256"] for repo in manifest["repositories"] for entry in repo["files"]}
    missing = desktop("missing_objects", {"sha256": sorted(hashes)})["missing"]
    desktop(
        "cache_objects",
        {"objects": [{"sha256": sha, "content": base64.b64encode(store.read(sha)).decode()} for sha in missing]},
    )


def renew(environment, state):
    db, task, _ = environment
    state = service.renew_lease(
        db,
        task,
        "u",
        LeaseRequest(client_id=state["client_id"], instance_id=state["instance_id"], lease_epoch=state["lease_epoch"]),
    )
    db.commit()
    return state


def acknowledge_native(environment, state, local):
    db, task, _ = environment
    state = renew(environment, state)
    conflicted = {entry["task_repository_id"] for entry in local["conflicts"]}
    changed = {entry["task_repository_id"] for entry in local["local_changes"]}
    state = service.receipt(
        db,
        task,
        "u",
        DeliveryReceipt(
            **fence(state),
            operation_id=str(uuid4()),
            snapshot_id=state["snapshot_id"],
            local_scan_id=str(uuid4()),
            repository_results=[
                {
                    "task_repository_id": repo["task_repository_id"],
                    "status": "CONFLICTS"
                    if repo["task_repository_id"] in conflicted
                    else "LOCAL_CHANGES"
                    if repo["task_repository_id"] in changed
                    else "ALIGNED",
                }
                for repo in state["repositories"]
            ],
            conflicts=local["conflicts"],
            pending_local_changes=local["local_changes"],
        ),
    )
    db.commit()
    return state


def test_real_desktop_multi_repository_round_trip_preserves_parallel_edits(environment, desktop, tmp_path, monkeypatch):
    db, task, cloud_root = environment
    (cloud_root / "api/.env").write_bytes(b"rollback-only-private-value")
    checkpoint = task_session_snapshot_service._create_checkpoint_sync(
        str(cloud_root), ["api", "web"], "opencode", None, "w", "Workspace", task.id, "Task"
    )
    task.task_meta_json = {"initial_workspace_checkpoint": checkpoint["root"]}
    db.commit()
    capture = task_git_snapshot_store.capture
    used_stores = []

    def record_store(root, repo_rels, destination, object_store, *args, **kwargs):
        used_stores.append(object_store)
        return capture(root, repo_rels, destination, object_store, *args, **kwargs)

    monkeypatch.setattr(task_git_snapshot_store, "capture", record_store)
    state = enabled(environment)
    initial = service.get_snapshot(db, task.id, state["snapshot_id"])
    assert used_stores and set(used_stores) == {checkpoint["worktree"]["object_store"]}
    assert all(entry["path"] != ".env" for repo in initial["repositories"] for entry in repo["files"])
    local_repositories = []
    source_indexes = {}
    for repo in initial["repositories"]:
        mapped = tmp_path / ("mapped-" + repo["repo_slug"])
        git(tmp_path, "clone", "--no-hardlinks", str(cloud_root / repo["rel_path"]), str(mapped))
        fork_url = "https://personal.example/" + repo["repo_slug"]
        git(mapped, "remote", "set-url", "origin", fork_url)
        git(mapped, "config", "core.autocrlf", "false")
        (mapped / "same.txt").write_bytes(b"original mapped checkout remains dirty")
        git(mapped, "add", "same.txt")
        source_indexes[str(mapped)] = git(mapped, "diff", "--cached", "--binary", "--full-index")
        local_repositories.append({**repo, "local_path": str(mapped), "configured_git_url": fork_url})
    prepared = desktop(
        "prepare",
        {
            **initial,
            "binding_id": state["binding_id"],
            "workspace_root": str(tmp_path / "desktop-worktrees"),
            "repositories": local_repositories,
        },
    )
    paths = {repo["task_repository_id"]: Path(repo["local_worktree_path"]) for repo in prepared["repositories"]}
    assert {repo["branch_name"] for repo in prepared["repositories"]} == {"release/2.x", "feature/login"}
    transfer_to_desktop(desktop, initial)
    received = desktop("reconcile", {"task_id": task.id, "operation_id": "initial", "target": initial})
    assert received["state"] == "READY", received["errors"]
    state = acknowledge_native(environment, state, received)
    assert state["sync_phase"] == "READY"

    (paths["api"] / "same.txt").write_bytes(b"human input\r\n")
    (paths["api"] / "binary.bin").unlink()
    binary_input = b"\x00\xff\r\n\xfe\x80\x00"
    (paths["api"] / "new-binary.dat").write_bytes(binary_input)
    (paths["api"] / ".env").write_bytes(b"local-private-value")
    db.add(
        TaskChatSubmission(
            id="desktop-submission",
            task_id=task.id,
            workspace_id="w",
            creator_id="u",
            client_message_id="desktop-message",
            content="edit both repositories",
            payload_hash="fixture",
            status="PREPARING",
            session_generation=task.session_generation,
            session_revision=task.session_revision,
            metadata_json={
                "collaboration": {key: state[key] for key in ["client_id", "instance_id", "binding_id", "lease_epoch"]}
            },
        )
    )
    db.flush()
    state = service.request_input(db, task, "desktop-submission", "u")
    db.commit()
    frozen = desktop("capture", {"task_id": task.id, "operation_id": "handoff:desktop-submission"})
    for entry in frozen["objects"]:
        content.ObjectStore(task.id).put(base64.b64decode(entry["content"]), entry["sha256"])
    state = renew(environment, state)
    state = service.handoff(
        db,
        task,
        "u",
        HandoffRequest(
            **fence(state),
            operation_id="desktop-handoff",
            submission_id="desktop-submission",
            manifest=frozen["manifest"],
            input_cut_seq=frozen["input_cut_seq"],
        ),
    )
    db.commit()
    accepted = service.get_snapshot(db, task.id, state["snapshot_id"])
    assert (cloud_root / "api/same.txt").read_bytes() == b"human input\r\n"
    assert not (cloud_root / "api/binary.bin").exists()
    assert (cloud_root / "api/new-binary.dat").read_bytes() == binary_input
    assert (cloud_root / "api/.env").read_bytes() == b"rollback-only-private-value"
    pinned = service.input_worktree_checkpoint(db, task, "desktop-submission")
    assert pinned is not None
    before_turn = task_session_snapshot_service._create_checkpoint_sync(
        str(cloud_root),
        ["api", "web"],
        "opencode",
        None,
        "w",
        "Workspace",
        task.id,
        "Task",
        initial_checkpoint=checkpoint["root"],
        pinned_worktree=pinned,
    )
    undo_entries = task_git_snapshot_store.entries(before_turn["worktree"])
    assert "api/.env" in undo_entries
    assert "api/new-binary.dat" in undo_entries
    assert "api/binary.bin" not in undo_entries
    assert before_turn["worktree"]["object_store"] == checkpoint["worktree"]["object_store"]
    (paths["api"] / "same.txt").write_bytes(b"human after input cut")
    desktop(
        "accept_input",
        {"task_id": task.id, "operation_id": "handoff:desktop-submission", "target": accepted},
    )
    assert (paths["api"] / "same.txt").read_bytes() == b"human after input cut"
    task.session_revision += 1
    service.advance_session(db, task, "desktop-submission")
    service.authorize_execution(db, task, "desktop-submission", "desktop-job")
    db.commit()
    (cloud_root / "api/same.txt").write_bytes(b"cloud candidate")
    (cloud_root / "web/same.txt").write_bytes(b"cloud independent file")
    (paths["web"] / "theme.css").write_bytes(b"local independent file")
    progress = service.capture_progress(db, task, "desktop-job")
    db.commit()
    transfer_to_desktop(desktop, progress)
    preview = desktop("reconcile", {"task_id": task.id, "operation_id": "preview", "target": progress, "preview": True})
    assert len(preview["preview_conflicts"]) == 1
    assert (paths["web"] / "same.txt").read_bytes() == b"web baseline\r\n"
    (cloud_root / "api/same.txt").write_bytes(b"cloud final")
    state = service.finish_execution(db, task, "desktop-job", confirmed_stopped=True)
    db.commit()
    final = service.get_snapshot(db, task.id, state["snapshot_id"])
    transfer_to_desktop(desktop, final)
    delivered = desktop("reconcile", {"task_id": task.id, "operation_id": "final", "target": final})
    assert delivered["state"] == "CONFLICT_PENDING", delivered["errors"]
    assert (paths["web"] / "same.txt").read_bytes() == b"cloud independent file"
    assert (paths["web"] / "theme.css").read_bytes() == b"local independent file"
    state = acknowledge_native(environment, state, delivered)
    assert state["sync_phase"] == "CONFLICT_PENDING"
    conflict = delivered["conflicts"][0]
    restored = desktop(
        "restore",
        {
            "task_id": task.id,
            "operation_id": "restore-selected",
            "conflict_set_id": delivered["conflict_set_id"],
            "selected": [{key: conflict[key] for key in ["task_repository_id", "path", "expected_sha256"]}],
        },
    )
    assert restored["state"] == "READY", restored["errors"]
    backup = desktop("read_object", {"sha256": conflict["expected_sha256"]})
    assert base64.b64decode(backup["content"]) == b"human after input cut"
    backups = desktop("backups", {"task_id": task.id})
    assert any(entry["sha256"] == conflict["expected_sha256"] for entry in backups["backups"])
    assert all(Path(entry["backup_path"]).parent.name == ".traceforge-sync" for entry in backups["backups"])
    state = acknowledge_native(environment, state, restored)
    assert state["sync_phase"] == "READY"
    next_input = desktop("capture", {"task_id": task.id, "operation_id": "next-input"})
    assert {entry["path"] for entry in next_input["status"]["local_changes"]} == {"theme.css"}
    assert (paths["api"] / "same.txt").read_bytes() == b"cloud final"
    assert (paths["api"] / ".env").read_bytes() == b"local-private-value"
    assert set(used_stores) == {checkpoint["worktree"]["object_store"]}
    for repo in local_repositories:
        assert (Path(repo["local_path"]) / "same.txt").read_bytes() == b"original mapped checkout remains dirty"
        assert (
            git(Path(repo["local_path"]), "diff", "--cached", "--binary", "--full-index")
            == source_indexes[repo["local_path"]]
        )
