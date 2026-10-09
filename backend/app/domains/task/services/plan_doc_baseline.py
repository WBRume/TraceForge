"""Compare documents against the immutable task creation snapshot."""

import hashlib
import json
from pathlib import Path

from app.domains.task.models.task import SddTask
from app.domains.task.services import task_git_snapshot_store, task_snapshot_store


def load_baseline(task: SddTask) -> dict | None:
    checkpoint = (task.task_meta_json or {}).get("initial_workspace_checkpoint")
    if not checkpoint:
        return None
    manifest_path = Path(checkpoint) / "worktree.json"
    if not manifest_path.is_file():
        return None
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if Path(payload.get("task_root", "")).resolve() != Path(task.project_path).resolve():
        raise ValueError("Plan document baseline belongs to a different task directory")
    if payload.get("version") == 4:
        if Path(payload["object_store"]).resolve() != Path(checkpoint).resolve().parent:
            raise ValueError("Plan document baseline store differs")
        payload["entries"] = task_git_snapshot_store.entries(payload)
    elif payload.get("version") == 2:
        payload["entries"] = payload["manifest"]
    else:
        return None
    return payload


def document_changed(baseline: dict, relative: str, file_path: Path) -> bool:
    entry = baseline["entries"].get(relative)
    if entry is None:
        return not task_snapshot_store.excluded(
            relative, baseline.get("policy") or {"excluded_dirs": [], "excluded_suffixes": []}
        )
    content = file_path.read_bytes()
    if baseline["version"] == 4:
        digest = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
        return digest != entry["oid"]
    return hashlib.sha256(content).hexdigest() != entry.get("sha256")
