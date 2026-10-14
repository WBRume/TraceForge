"""Recover operational snapshot storage without replacing historical baselines."""

import json
from pathlib import Path

from app.config import settings
from app.domains.local_resource.snapshots import PREFIX
from app.domains.task.services import task_session_snapshot_service as snapshots


def current_anchor(task, repo_paths: list[str], workspace_name: str) -> str | None:
    metadata = dict(task.task_meta_json or {})
    anchor = metadata.get("workspace_snapshot_checkpoint") or metadata.get("initial_workspace_checkpoint")
    if not anchor or str(anchor).startswith(PREFIX):
        return anchor
    path = Path(anchor).resolve()
    if not path.is_relative_to(Path(settings.TASK_SESSION_SNAPSHOT_ROOT).resolve()):
        raise snapshots.TaskSessionSnapshotError("Snapshot is outside configured storage", code="SNAPSHOT_PATH_INVALID")
    manifest = path / "worktree.json"
    if manifest.is_file():
        # Existing but damaged/foreign stores still fail validation in capture.
        # Only missing manifests are recoverable from the current workspace.
        return anchor
    created = snapshots._create_checkpoint_sync(
        task.project_path,
        repo_paths,
        "none",
        None,
        task.workspace_id,
        workspace_name,
        task.id,
        task.name,
    )
    metadata["workspace_snapshot_checkpoint"] = created["root"]
    task.task_meta_json = metadata
    return created["root"]


def bind_recovered_store(store, anchor: str, task_root: str) -> None:
    """A deleted store may have belonged to the task before a name change."""
    binding = store.root / "git-store.json"
    if binding.is_file():
        previous = json.loads(binding.read_text(encoding="utf-8"))
        old_root = Path(previous["object_store"])
        if old_root.resolve() != Path(anchor).resolve().parent and not old_root.exists():
            if Path(previous["task_root"]).resolve() != Path(task_root).resolve():
                raise ValueError("Collaboration Git store ownership changed")
            binding.unlink()
    store.bind(anchor, task_root)
