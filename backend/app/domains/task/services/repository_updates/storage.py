"""Durable update journals stored alongside the configurable snapshot store."""

import json
from pathlib import Path
from uuid import UUID, uuid4

from app.config import settings
from app.domains.task.models.task_event_outbox import TaskEventOutbox
from app.domains.task.services.task_snapshot_store import write_json

from .git import UpdateError

BLOCKED = {"PREPARING", "APPLYING", "RECOVERY_REQUIRED", "ADAPTING"}


def directory(task, operation_id: str) -> Path:
    try:
        operation_id = str(UUID(operation_id))
        task_id = str(UUID(task.id))
    except ValueError as exc:
        raise UpdateError("无效的代码更新记录") from exc
    root = Path(settings.TASK_SESSION_SNAPSHOT_ROOT).resolve()
    if root.is_relative_to(Path(task.project_path).resolve()):
        raise UpdateError("快照存储目录不能位于任务工作目录中")
    return root / "repository-updates" / task_id / operation_id


def load(task, operation_id: str | None = None) -> dict | None:
    pointer = (task.task_meta_json or {}).get("repository_update") or {}
    if not pointer:
        return None
    if operation_id and pointer["id"] != operation_id:
        raise UpdateError("代码更新记录已变化，请刷新后重试。", "UPDATE_CHANGED")
    path = directory(task, pointer["id"]) / "update.json"
    if not path.is_file():
        raise UpdateError("代码更新预览已丢失；若尚未应用，可放弃预览后重新检查。", "UPDATE_STORAGE_MISSING")
    result = json.loads(path.read_text(encoding="utf-8"))
    if result["task_id"] != task.id or result["id"] != pointer["id"]:
        raise UpdateError("代码更新记录与任务不匹配")
    # APPLYING is committed before the first filesystem write. If publication
    # failed, never infer success from a newer filesystem manifest alone.
    if pointer["state"] in {"APPLYING", "RECOVERY_REQUIRED"}:
        result["state"] = pointer["state"]
    return result


def save(db, task, plan: dict):
    plan["version"] = int(plan.get("version", 0)) + 1
    root = directory(task, plan["id"])
    root.mkdir(parents=True, exist_ok=True)
    write_json(str(root / "update.json"), plan)
    pointer = {key: plan.get(key) for key in ("id", "state", "version", "job_id", "error")}
    task.task_meta_json = {**(task.task_meta_json or {}), "repository_update": pointer}
    publish(db, task, pointer)


def publish(db, task, pointer):
    db.add(
        TaskEventOutbox(
            event_id=str(uuid4()),
            task_id=task.id,
            payload_json={
                "event_type": "task_repository_update",
                "task_id": task.id,
                **pointer,
                "session_generation": task.session_generation,
                "session_revision": task.session_revision,
                "session_id": task.session_id,
                "undo_before_revision": (task.task_meta_json or {}).get("repository_update_revision"),
            },
        )
    )


def require_available(task, *, initialization_id=None):
    from app.domains.task.services.initialization.state import require_available as require_initialized

    require_initialized(task, initialization_id)
    state = ((getattr(task, "task_meta_json", None) or {}).get("repository_update") or {}).get("state")
    if state in BLOCKED:
        raise UpdateError(
            "任务代码正在更新或等待恢复，请先在「任务代码 → 仓库与版本」中完成处理。", "REPOSITORY_UPDATE_BUSY"
        )


def require_version(plan: dict, version: int):
    if plan["version"] != version:
        raise UpdateError("其他用户已更新此预览，请刷新后重试。", "UPDATE_CHANGED")


def baseline(task, repo) -> str:
    return str((task.task_meta_json or {}).get("repository_baselines", {}).get(repo.id) or repo.base_commit_sha or "")
