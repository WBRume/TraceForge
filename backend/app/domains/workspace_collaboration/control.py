"""Keep start/resume commands on the same durable input path as ordinary chat."""

from uuid import uuid4

from app.domains.task.services import status_machine as sm
from app.domains.workspace_collaboration.models import CollaborationState


def enabled(db, task_id: str) -> bool:
    state = db.get(CollaborationState, task_id)
    return bool(state and state.enabled)


def accept_control(
    db,
    task,
    actor_id,
    *,
    content,
    prompt=None,
    fresh_session=False,
    source,
    client_id=None,
    metadata=None,
    failed_check=None,
    replacement_check=None,
):
    from app.domains.task.services import chat_submission_service
    from app.domains.workspace_collaboration.session import uses_local_input

    state = db.get(CollaborationState, task.id)
    metadata = {
        **(metadata or {}),
        "source": source,
        "_collaboration_control": {"prompt": prompt or content, "fresh_session": fresh_session},
    }
    # Historical bindings are not an input dependency. Match ordinary chat:
    # only the connected driver's own command requests a local handoff.
    metadata.pop("collaboration", None)
    if uses_local_input(state, actor_id):
        metadata["collaboration"] = {
            "client_id": state.client_id,
            "instance_id": state.instance_id,
            "binding_id": state.binding_id,
            "lease_epoch": state.lease_epoch,
        }
    return chat_submission_service._accept_sync(
        db,
        task.id,
        actor_id,
        client_id or str(uuid4()),
        content,
        metadata,
        failed_check=failed_check,
        replacement_check=replacement_check,
    )


async def schedule_control(receipt):
    from app.domains.task.services import chat_submission_service

    chat_submission_service.schedule(receipt["id"])
    await chat_submission_service.wake_event_publisher()


def accept_pre_input(db, task_id, actor_id, text, metadata):
    from app.domains.task.models.task import SddTask, TaskStatus
    from app.domains.task.services.chat_submission_service import PRE_INPUT_CLIENT_ID_PREFIX

    task = db.get(SddTask, task_id)
    client_id = f"{PRE_INPUT_CLIENT_ID_PREFIX}{metadata['pre_input_id']}"
    if task.status == TaskStatus.INTERRUPTED:
        from app.domains.task.services.task_session_control_service import (
            TaskSessionControlError,
            _prepare_interrupted_resume,
        )
        from app.engine.session import get_engine

        engine = get_engine(task_id)
        if engine and engine.running:
            raise TaskSessionControlError("Task is already running", status_code=409)
        prepared = _prepare_interrupted_resume(
            db, task_id=task_id, actor_user_id=actor_id, idempotency_key=None, prompt=text, confirm_continue=False
        )
        return _accept_resumed_control(
            db, task, actor_id, prepared, client_id, metadata, content=text, source="pre_input_collaboration"
        )
    return accept_control(
        db,
        task,
        actor_id,
        content=text,
        source="pre_input_collaboration",
        client_id=client_id,
        metadata=metadata,
    )


def require_ready(db, task_id, *, actor_id=None):
    from app.domains.task.models.task import SddTask
    from app.domains.task.services.repository_updates.storage import require_available
    from app.domains.task.services.task_session_control_service import TaskSessionControlError
    from app.domains.workspace_collaboration.session import cloud_input_available, uses_local_input

    try:
        require_available(db.get(SddTask, task_id))
    except ValueError as exc:
        raise TaskSessionControlError(str(exc), status_code=409) from exc
    state = db.get(CollaborationState, task_id)
    if state and state.enabled and state.sync_phase != "READY":
        if actor_id and not uses_local_input(state, actor_id) and cloud_input_available(state):
            return
        raise TaskSessionControlError("请先完成当前本地代码交付及冲突恢复", status_code=409)


def resume_submission(db, task_id, actor_id, prepared, client_id, metadata=None, *, failed_check=None):
    from app.domains.task.models.task import SddTask

    if not enabled(db, task_id):
        return None
    return _accept_resumed_control(
        db,
        db.get(SddTask, task_id),
        actor_id,
        prepared,
        client_id,
        metadata,
        content=prepared["prompt_text"],
        source="task_resume",
        failed_check=failed_check,
    )


def _accept_resumed_control(db, task, actor_id, prepared, client_id, metadata, *, content, source, failed_check=None):
    from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob

    require_ready(db, task.id, actor_id=actor_id)
    sm.dispatch(
        db, task, sm.Trigger.RESUME, event_key=f"resume:{client_id or prepared['old_job_id']}", actor_id=actor_id
    )
    task.session_id = prepared.get("session_id", task.session_id)
    task.error_message = None
    task.interrupt_reason = None
    task.interrupted_by_id = None
    task.interrupted_at = None
    if prepared.get("replace_agent_session"):
        metadata = {**(metadata or {}), "_new_agent_session": True}
    receipt = accept_control(
        db,
        task,
        actor_id,
        content=content,
        prompt=prepared["prompt_text"],
        source=source,
        client_id=client_id,
        metadata=metadata,
        failed_check=failed_check,
        replacement_check=prepared.get("agent_session_replacement_check"),
    )
    old_job_id = prepared["old_job_id"]
    old_job = db.get(SddAiJob, old_job_id) if old_job_id else None
    if old_job is not None and old_job.status == AiJobStatus.INTERRUPTED:
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
