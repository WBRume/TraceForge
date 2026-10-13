"""Read cloud results without joining collaboration or touching a local checkout."""

import json
import tempfile
from pathlib import Path

from app.core.subprocess_runner import run_git
from app.domains.task.models.session_turn import TaskSessionTurn, TaskSessionTurnStatus
from app.domains.task.services import task_git_snapshot_store as git_store

from . import content, manifest_store, service, session
from .models import CollaborationSnapshot, CollaborationState


def _ignored_at_checkpoint(names, entries, untracked):
    """Use the recorded ignore files, even if the Agent changed .gitignore.

    Only ignore rules are materialized, never a second checkout or a whole-tree
    content scan. The shadow Git object database is queried without its index.
    """
    if not untracked:
        return set()
    with tempfile.TemporaryDirectory(prefix="tf-review-ignore-") as temporary:
        rules = {name: item for name, item in names.items() if Path(name).name == ".gitignore"}
        for directory in {item["git_dir"] for item in rules.values()}:
            group = {name: item for name, item in rules.items() if item["git_dir"] == directory}
            blobs = dict(
                git_store.read_blobs(directory, list({(item["oid"], item["size"]) for item in group.values()}))
            )
            for name, item in group.items():
                content.validate_path(name)
                target = Path(temporary) / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blobs[item["oid"]])
        directory = next(iter(entries.values()))["git_dir"]
        result = run_git(
            ["--git-dir=" + directory, "--work-tree=" + temporary, "check-ignore", "--no-index", "--stdin", "-z"],
            cwd=temporary,
            input_data="\0".join(untracked).encode() + b"\0",
            decode_text=False,
        )
        if result.returncode not in {0, 1}:
            raise ValueError("Unable to filter checkpoint ignore rules")
        return {name.decode() for name in result.stdout.split(b"\0") if name}


def _checkpoint_inventory(path, task, repositories, store):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("version") != 4 or Path(payload["task_root"]).resolve() != Path(task.project_path).resolve():
        service._fail("REVIEW_BASELINE_UNAVAILABLE", "This task has no compatible Git baseline for comparison")
    entries = git_store.entries(payload)
    tracked = set(payload.get("tracked", []))
    exported, public = [], []
    for repo in repositories:
        prefix = repo["rel_path"] + "/"
        nested = [r["rel_path"][len(prefix) :] for r in repositories if r["rel_path"].startswith(prefix)]
        names = {name[len(prefix) :]: item for name, item in entries.items() if name.startswith(prefix)}
        repo_tracked = {name[len(prefix) :] for name in tracked if name.startswith(prefix)}
        untracked = sorted(names.keys() - repo_tracked)
        ignored = _ignored_at_checkpoint(names, entries, untracked)
        if untracked:
            result = run_git(
                ["check-ignore", "--no-index", "--stdin", "-z"],
                cwd=str(Path(task.project_path) / repo["rel_path"]),
                input_data="\0".join(untracked).encode() + b"\0",
                decode_text=False,
            )
            if result.returncode not in {0, 1}:
                raise ValueError("Unable to filter private snapshot files")
            ignored |= {name.decode() for name in result.stdout.split(b"\0") if name}
        scoped = []
        for name, item in sorted(names.items()):
            if name in ignored or content._excluded_export(name, repo_tracked, nested):
                continue
            content.validate_path(name)
            if item["size"] > content.MAX_OBJECT_BYTES:
                raise ValueError("Review file exceeds 64 MiB")
            scoped.append((name, item))
            public.append(item)
        exported.append((repo, scoped))
    if len(public) > 100000 or sum(item["size"] for item in public) > content.MAX_MANIFEST_BYTES:
        raise ValueError("Review snapshot exceeds limits")
    mapped, _ = store.git_objects.export(public)
    return [
        {
            **repo,
            "files": [
                {
                    "path": name,
                    "sha256": mapped[item["git_dir"], item["oid"]][0],
                    "size": item["size"],
                    "mode": item["mode"],
                }
                for name, item in scoped
            ],
        }
        for repo, scoped in exported
    ]


def changes(db, task, _user_id):
    service._check_task(task)
    state = service._state(db, task.id)
    if state and state.enabled:
        cloud = session.latest_snapshot(db, task, _user_id, None)
        baseline = service.get_snapshot(db, task.id, state.input_snapshot_id or state.snapshot_id)
        return {"input": baseline, "cloud": cloud, "running": state.sync_phase in service.ACTIVE_PHASES}

    repositories = service.repository_metadata(db, task)
    store = service._ensure_store(db, task)
    turn = (
        db.query(TaskSessionTurn)
        .filter_by(
            task_id=task.id,
            session_generation=task.session_generation,
            status=TaskSessionTurnStatus.ACTIVE,
        )
        .order_by(TaskSessionTurn.turn_index.desc())
        .first()
    )
    path = (
        turn.worktree_snapshot_path
        if turn
        else str(Path(task.task_meta_json["initial_workspace_checkpoint"]) / "worktree.json")
    )
    if not path:
        service._fail("REVIEW_BASELINE_UNAVAILABLE", "This turn has no recorded workspace baseline")
    key = content.digest([path, task.session_generation, task.session_revision])
    previous = db.query(CollaborationSnapshot).filter_by(task_id=task.id, source="REVIEW_INPUT").all()
    saved = next((row for row in previous if row.manifest_json.get("review_key") == key), None)
    if saved:
        baseline = manifest_store.read_manifest(db, saved)
    else:
        metadata = CollaborationState(
            workspace_revision=0,
            session_generation=task.session_generation or 0,
            session_revision=task.session_revision or 0,
            repository_set_digest=content.digest(repositories),
        )
        baseline = service._snapshot(
            db, task, metadata, "REVIEW_INPUT", _checkpoint_inventory(path, task, repositories, store)
        )
        row = db.get(CollaborationSnapshot, baseline["snapshot_id"])
        row.manifest_json = {**row.manifest_json, "review_key": key}
    try:
        # Never publish a final result cut while the Agent still owns the workspace.
        service._assert_no_writer(db, task.id)
    except service.CollaborationError as exc:
        if exc.code != "WRITER_ACTIVE":
            raise
        return {"input": baseline, "cloud": baseline, "running": True}
    return {"input": baseline, "cloud": session.latest_snapshot(db, task, _user_id, None), "running": False}
