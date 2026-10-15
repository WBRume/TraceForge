"""A desktop receipt gates the new writer after both mapped repositories reset."""

from datetime import datetime, timedelta

from app.domains.workspace_collaboration.models import CollaborationState

from .state import InitializationError, current


def require_driver(db, task, actor_id, identity):
    state = db.get(CollaborationState, task.id)
    if not state or not state.enabled:
        return None
    identity = identity or {}
    if actor_id != state.driver_user_id or any(
        identity.get(key) != getattr(state, field)
        for key, field in (
            ("client_id", "client_id"),
            ("instance_id", "instance_id"),
            ("binding_id", "binding_id"),
        )
    ):
        raise InitializationError("本地协同已开启，请在当前连接代码的桌面端初始化，以同时清理本地仓库。")
    return {key: identity[key] for key in ("client_id", "instance_id", "binding_id")} | {
        "previous_binding_id": state.binding_id
    }


def command(task_id, operation):
    return {
        "task_id": task_id,
        "operation_id": operation["id"],
        **operation["collaboration"],
        "session_generation": operation["generation"],
        "session_revision": operation["revision"],
        "repositories": [
            {"task_repository_id": repo["id"], "target": repo["target"], "url": repo["url"]}
            for repo in operation["repositories"]
        ],
    }


def verify_receipt(task_id, operation, identity, receipt):
    expected = command(task_id, operation)
    if not identity or identity.get("client_id") != expected["client_id"] or not identity.get("instance_id"):
        raise InitializationError("请使用发起初始化的桌面端继续清理本地仓库。")
    if not receipt:
        return False
    if any(receipt.get(key) != expected[key] for key in ("task_id", "operation_id", "binding_id")):
        raise InitializationError("本地初始化回执已失效。")
    targets = {repo["task_repository_id"]: repo["target"] for repo in expected["repositories"]}
    rows = receipt.get("repositories", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise InitializationError("本地初始化回执无效。")
    if (
        len(rows) != len(targets)
        or {row.get("task_repository_id"): row.get("head") for row in rows} != targets
        or any(row.get("clean") is not True for row in rows)
    ):
        raise InitializationError("请完成全部本地仓库的清理后再启动新会话。")
    return True


def resume_with_turn(db, task, job):
    """Commit the clean collaboration input and its authorized job together."""
    operation = current(task)
    if not operation.get("collaboration"):
        return
    if not operation.get("local_reset_receipt"):
        raise InitializationError("尚未收到本地仓库清理回执。")
    from app.domains.workspace_collaboration import service
    from app.domains.workspace_collaboration.hooks import authorize_job

    state = db.get(CollaborationState, task.id)
    state.instance_id = operation["collaboration"]["instance_id"]
    state.session_generation = task.session_generation
    state.session_revision = task.session_revision
    state.repository_set_digest = service.content.digest(service.repository_metadata(db, task))
    state.conflicts_json = state.pending_local_changes_json = []
    state.run_id = None
    state.progress_seq = 0
    state.final_progress_seq = None
    state.recovery_kind = state.recovery_message = state.recovery_operation_id = None
    # Reuses the warm Git index; captures only the clean new baseline, never discarded output.
    manifest = service._capture(db, task, state, "INITIAL", stable=True)
    service._publish(state, manifest)
    state.input_snapshot_id = manifest["snapshot_id"]
    state.pending_submission_id = state.input_submission_id = None
    state.input_cut_seq = None
    state.sync_phase = "PREPARING"
    state.enabled = True
    state.lease_expires_at = datetime.utcnow() + timedelta(seconds=service.LEASE_SECONDS)
    authorize_job(db, job)
