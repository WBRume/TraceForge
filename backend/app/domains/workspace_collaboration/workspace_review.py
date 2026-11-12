"""Review task-root files that are outside prepared repository worktrees."""

import json
import os
import stat
from pathlib import Path

from app.domains.skill.services.runtime.layout import SKILL_LAYOUT_ROOTS
from app.domains.task.models.session_turn import TaskSessionTurn, TaskSessionTurnStatus
from app.domains.task.services import task_git_snapshot_store as git_store
from app.domains.task.services import task_snapshot_store as snapshot_files
from app.domains.task.services.task_session_snapshot_service import _snapshot_policy

from . import content, identity, service

WORKSPACE_ID = "workspace"
GENERATED_DEMO_DIRS = {"dist", "build", ".output"}


def _visible(path: str, policy: dict, repository_paths: list[str]) -> bool:
    if snapshot_files.excluded(path, policy) or content._excluded_export(path, {}, repository_paths):
        return False
    try:
        content.validate_path(path)
    except ValueError:
        return False
    return True


def _workspace_paths(root: Path, policy: dict, repository_paths: list[str]) -> list[str]:
    paths = []
    size = 0

    def visit(directory: Path, prefix: str) -> None:
        nonlocal size
        with os.scandir(directory) as entries:
            for entry in entries:
                path = prefix + entry.name
                if not _visible(path, policy, repository_paths):
                    continue
                info = entry.stat(follow_symlinks=False)
                if getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    continue
                if stat.S_ISDIR(info.st_mode):
                    visit(Path(entry.path), path + "/")
                elif stat.S_ISREG(info.st_mode) and info.st_size <= content.MAX_OBJECT_BYTES:
                    size += info.st_size
                    paths.append(path)
                    if size > content.MAX_MANIFEST_BYTES or len(paths) > 100_000:
                        raise ValueError("Task workspace results exceed review limits")

    visit(root, "")
    return sorted(paths)


def _files(store: content.ObjectStore, entries: dict) -> dict:
    objects, _ = store.git_objects.export(list(entries.values()))
    return {
        path: {
            "path": path,
            "sha256": objects[item["git_dir"], item["oid"]][0],
            "content_sha256": objects[item["git_dir"], item["oid"]][1],
            "size": item["size"],
            "mode": item["mode"],
        }
        for path, item in entries.items()
    }


def _baseline(db, task, root, store, policy, repository_paths, scope) -> dict:
    checkpoint = (task.task_meta_json or {}).get("initial_workspace_checkpoint")
    path = Path(checkpoint, "worktree.json") if checkpoint else None
    if scope == "round":
        turn = (
            db.query(TaskSessionTurn)
            .filter_by(task_id=task.id, session_generation=task.session_generation, status=TaskSessionTurnStatus.ACTIVE)
            .order_by(TaskSessionTurn.turn_index.desc())
            .first()
        )
        if turn and turn.worktree_snapshot_path:
            path = Path(turn.worktree_snapshot_path)
    if not path or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != git_store.VERSION or Path(payload["task_root"]).resolve() != root:
        return {}
    # Other partitions belong to repository worktrees. Skip them before Git reads.
    payload["partitions"] = [part for part in payload["partitions"] if part["relative"] == "."]
    return _files(
        store,
        {
            name: item
            for name, item in git_store.entries(payload, paths=snapshot_files.validate_relative_path).items()
            if item["mode"] in {"100644", "100755"}
            and item["size"] <= content.MAX_OBJECT_BYTES
            and _visible(name, policy, repository_paths)
        },
    )


def diff(db, task, repository_paths: list[str], scope: str) -> tuple[list[dict], bool]:
    """Use the initial task cut and the last stable workspace tree."""
    if not task.project_path or not Path(task.project_path).is_dir():
        return [], False
    root = Path(task.project_path).resolve(strict=True)
    store = content.ObjectStore(task)
    if store.root.resolve().is_relative_to(root):
        raise ValueError("Review storage must be outside the task workspace")
    policy = _snapshot_policy()
    policy["excluded_dirs"] = [name for name in policy["excluded_dirs"] if name not in GENERATED_DEMO_DIRS]
    excluded_roots = sorted({*repository_paths, *SKILL_LAYOUT_ROOTS.values()})
    cache = store.root / "workspace-review"
    key = content.digest([str(root), task.session_generation, task.session_revision, excluded_roots, policy])
    pointer = cache / "latest.json"
    try:
        service._assert_no_writer(db, task.id, read_only=True)
    except service.CollaborationError as exc:
        if exc.code != "WRITER_ACTIVE":
            raise
        running = True
        saved = json.loads(pointer.read_text(encoding="utf-8")) if pointer.is_file() else {}
        part = saved.get("partition") if saved.get("key") == key else None
    else:
        running = False
        with snapshot_files.store_lock(str(cache)):
            shadow = git_store.Shadow(str(root), str(cache), ".", None)
            part = shadow.capture(_workspace_paths(root, policy, excluded_roots), "refs/traceforge/workspace-review")
            # Exports issued from older drawer views still refer to this immutable cut.
            git_store.shadow_git(
                part["git_dir"], ["update-ref", "refs/traceforge-review/" + part["tree"], part["tree"]]
            )
            snapshot_files.write_json(str(pointer), {"key": key, "partition": part})
    if part is None:
        return [], running
    old = _baseline(db, task, root, store, policy, excluded_roots, scope)
    new = _files(store, git_store.tree_entries(part, str(root), snapshot_files.validate_relative_path))
    return [
        {
            "task_repository_id": WORKSPACE_ID,
            "repo_slug": "",
            "path": name,
            "change": "D" if name not in new else "M" if name in old else "A",
            "left": old.get(name),
            "right": new.get(name),
        }
        for name in sorted(old.keys() | new.keys())
        if not identity.same_file(old.get(name), new.get(name))
    ], running
