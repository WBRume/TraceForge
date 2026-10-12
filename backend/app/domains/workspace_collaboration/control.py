"""Keep start/resume commands on the same durable input path as ordinary chat."""

from uuid import uuid4

from app.domains.workspace_collaboration.models import CollaborationState


def enabled(db, task_id: str) -> bool:
    state = db.get(CollaborationState, task_id)
    return bool(state and state.enabled)


def accept_control(
    db, task, actor_id, *, content, prompt=None, fresh_session=False, source, client_id=None, metadata=None
):
    from app.domains.task.services import chat_submission_service
    from app.domains.workspace_collaboration.service import CollaborationError

    state = db.get(CollaborationState, task.id)
    if state.driver_user_id != actor_id:
        raise CollaborationError("COLLABORATION_DRIVER_REQUIRED", "请由主控桌面客户端发起下一轮")
    metadata = {
        **(metadata or {}),
        "source": source,
        "collaboration": {
            "client_id": state.client_id,
            "instance_id": state.instance_id,
            "binding_id": state.binding_id,
            "lease_epoch": state.lease_epoch,
        },
        "_collaboration_control": {"prompt": prompt or content, "fresh_session": fresh_session},
    }
    return chat_submission_service._accept_sync(db, task.id, actor_id, client_id or str(uuid4()), content, metadata)


async def schedule_control(receipt):
    from app.domains.task.services import chat_submission_service

    chat_submission_service.schedule(receipt["id"])
    await chat_submission_service.wake_event_publisher()


def accept_pre_input(db, task_id, actor_id, text, metadata):
    from app.domains.task.models.task import SddTask

    if not enabled(db, task_id):
        return None
    return accept_control(
        db,
        db.get(SddTask, task_id),
        actor_id,
        content=text,
        source="pre_input_collaboration",
        client_id=f"pre-input:{metadata['pre_input_id']}",
        metadata=metadata,
    )


def require_ready(db, task_id):
    from app.domains.task.services.task_session_control_service import TaskSessionControlError

    state = db.get(CollaborationState, task_id)
    if state and state.enabled and state.sync_phase != "READY":
        raise TaskSessionControlError("请先完成当前本地代码交付及冲突恢复", status_code=409)


def closeout_snapshot(db, task, confirmed_snapshot_id):
    """Closeout deliberately references confirmed server code, never unseen disk edits."""
    from app.domains.task.services.task_closeout_service import TaskCloseoutError
    from app.domains.workspace_collaboration import service

    state = db.query(CollaborationState).filter_by(task_id=task.id).with_for_update().first()
    if not state or not state.enabled:
        return None
    if state.sync_phase != "READY" or not confirmed_snapshot_id or confirmed_snapshot_id != state.snapshot_id:
        raise TaskCloseoutError(
            "请先完成代码交付，并确认本次收尾使用的云端代码版本；尚未交接的本地修改不会包含在内", status_code=409
        )
    try:
        service._check_session(state, task)
        service._check_repositories(db, state, task)
    except service.CollaborationError as exc:
        raise TaskCloseoutError(str(exc), status_code=exc.status_code) from exc
    return {
        "snapshot_id": state.snapshot_id,
        "workspace_revision": state.workspace_revision,
        "repository_set_digest": state.repository_set_digest,
        "scope": "CONFIRMED_SERVER_SNAPSHOT",
        "unhanded_local_changes_excluded": True,
    }


def resume_submission(db, task_id, actor_id, prepared, client_id, metadata=None):
    from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
    from app.domains.task.models.task import SddTask, TaskStatus

    task = db.get(SddTask, task_id)
    if not enabled(db, task_id):
        return None
    require_ready(db, task_id)
    task.status = TaskStatus.CODING
    task.session_id = prepared.get("session_id", task.session_id)
    task.error_message = None
    task.interrupt_reason = None
    task.interrupted_by_id = None
    task.interrupted_at = None
    receipt = accept_control(
        db,
        task,
        actor_id,
        content=prepared["prompt_text"],
        source="task_resume",
        client_id=client_id,
        metadata=metadata,
    )
    old_job = db.get(SddAiJob, prepared["old_job_id"])
    if old_job is not None:
        old_job.status = AiJobStatus.CANCELLED
        old_job.message = "Interrupted attempt superseded by resume preparation"
    return receipt


def existing_resume(db, task_id, actor_id, client_id, prompt, confirm_continue):
    from app.domains.task.models.chat_submission import TaskChatSubmission
    from app.domains.task.services import chat_submission_service
    from app.domains.task.services.task_session_control_service import TaskSessionControlError

    row = (
        db.query(TaskChatSubmission)
        .filter_by(task_id=task_id, creator_id=actor_id, client_message_id=client_id)
        .first()
    )
    if row is None:
        return None
    expected = str(prompt or "").strip()
    if not expected and confirm_continue:
        expected = "Please continue the interrupted task from the current session context."
    if row.content != expected or (row.metadata_json or {}).get("source") != "task_resume":
        raise TaskSessionControlError("相同消息标识不能用于不同内容", status_code=409)
    return {"task_id": task_id, "submission": chat_submission_service.serialize(row), "job": None}
