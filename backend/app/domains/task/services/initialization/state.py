"""Durable forward-only initialization journal and write fence."""

from copy import deepcopy
from datetime import datetime

from app.domains.task.models.task import SddTask


class InitializationError(ValueError):
    status_code = 409
    code = "TASK_INITIALIZATION_PENDING"


def current(task):
    return deepcopy((getattr(task, "task_meta_json", None) or {}).get("initialization") or {})


def require_available(task, allowed_id=None):
    operation = current(task)
    if operation and operation["state"] != "COMPLETED" and operation["id"] != allowed_id:
        raise InitializationError("任务初始化尚未完成，请点击初始化继续；完成前不能写入或接收任务代码。")


def save(db, task, operation):
    operation = {**operation, "updated_at": datetime.utcnow().isoformat()}
    task.task_meta_json = {**(task.task_meta_json or {}), "initialization": operation}
    db.commit()
    return deepcopy(operation)


def update(db, task_id, operation_id, **patch):
    task = db.query(SddTask).filter_by(id=task_id).with_for_update().one()
    operation = current(task)
    if operation.get("id") != operation_id:
        raise InitializationError("初始化操作已变化，请刷新后重试。")
    return save(db, task, {**operation, **patch})


def complete_with_turn(task, operation_id, job_id, checkpoint):
    operation = current(task)
    if operation.get("id") != operation_id or operation.get("state") != "STARTING":
        raise InitializationError("初始化操作已变化，不能发布旧会话。")
    if not checkpoint:
        raise InitializationError("初始化后的代码基线尚未就绪。")
    task.task_meta_json = {
        **(task.task_meta_json or {}),
        "initial_workspace_checkpoint": checkpoint,
        "workspace_snapshot_checkpoint": checkpoint,
        "initialization_receipts": {
            **(task.task_meta_json or {}).get("initialization_receipts", {}),
            operation_id: {"job_id": job_id, "actor_id": operation["actor_id"]},
        },
        "initialization": {
            **operation,
            "state": "COMPLETED",
            "job_id": job_id,
            "error": None,
            "finished_at": datetime.utcnow().isoformat(),
        },
    }


def public(task):
    operation = current(task)
    if not operation:
        return {"operation": None}
    operation["repositories"] = [
        {key: value for key, value in repo.items() if key != "url"} for repo in operation.get("repositories", [])
    ]
    return {
        "operation": {key: value for key, value in operation.items() if key not in {"roots", "resource", "protected"}}
    }
