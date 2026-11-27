"""Task 会话生命周期编排：start（建立）/ initialize（重置）/ interrupt（打断）/ resume（恢复）。

四个转换共享同一套编排纪律：
- 路由层负责鉴权、参数解析与任务分布式锁（锁冲突映射为 HTTP 409/429）；
- 服务层在锁内把同步 DB 段拆成单事务、在 DB 线程执行（run_db_txn_with_bind），
  引擎检查、attempt 恢复、turn 创建与广播保持在事件循环；
- 业务守卫失败抛 TaskSessionControlError（携带 HTTP 状态码），路由统一映射。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from datetime import datetime
from functools import partial
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.offload import run_db_txn, run_db_txn_with_bind
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.schemas.websocket import WSMessage
from app.domains.ai.services.ai_job_convergence_service import (
    AttemptTerminationRequest,
    TerminationRequestResult,
    persisted_stop_mode,
    request_attempt_termination_in_txn,
)
from app.domains.ai.services.jobs import attempts as ai_job_attempts
from app.domains.ai.services.jobs import publishing as ai_job_publishing
from app.domains.ai.services.jobs.registry import WORKER_BOOT_ID
from app.domains.ai.services.jobs.registry import runtime as ai_runtime
from app.domains.ai.services.jobs.store import (
    create_task_chat_job,
    find_active_summary_job,
    has_blocking_chat_job,
    serialize_job,
)
from app.domains.skill.services.runtime import configuration as skill_runtime_configuration
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.services import context_token_service, task_event_publisher
from app.domains.task.services import status_machine as sm
from app.domains.task.services.chat_images import CHAT_IMAGES_KEY
from app.domains.task.services.conversation import messages as task_conversation_messages
from app.domains.task.services.task_records import queries as task_task_records_queries
from app.domains.websocket.ws.manager import manager as task_ws_manager
from app.engine.session import TaskAgentEngine, get_engine

logger = get_logger(__name__, category="task_execution")

# ── 会话状态守卫文案（业务规则归属服务层，HTTP 层引用同一来源）──
BASELINED_LOCKED_MSG = "Task is BASELINED and locked for changes"
TASK_RUNNING_MSG = "Task is currently running. Please wait or cancel it first."
TASK_INTERRUPTED_MSG = "Task is interrupted. Resume it or initialize a fresh session."
TASK_PROVISIONING_MSG = "Task is still being provisioned. Please wait until the workspace is ready."


class TaskSessionControlError(Exception):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _as_text(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def _merge_json(original: Any, patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(original) if isinstance(original, dict) else {}
    merged.update(patch)
    return merged


def _require_local_actor(db: Session, task_id: str, actor_id: str) -> None:
    from app.domains.local_resource.client import ResourceError
    from app.domains.local_resource.service import require_operation

    try:
        require_operation(db, db.get(SddTask, task_id), actor_id)
    except ResourceError as exc:
        raise TaskSessionControlError(str(exc), status_code=exc.status_code) from exc


def _current_task_job(db: Session, task: SddTask) -> SddAiJob | None:
    if not task.status_run_id:
        return None
    return db.query(SddAiJob).filter_by(id=task.status_run_id, task_id=task.id, channel=AiJobChannel.TASK_CHAT).first()


def _find_latest_interrupted_job(db: Session, task: SddTask) -> SddAiJob | None:
    return (
        db.query(SddAiJob)
        .filter(
            SddAiJob.task_id == task.id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
            SddAiJob.status == AiJobStatus.INTERRUPTED,
            SddAiJob.session_generation == task.session_generation,
            SddAiJob.context_json["superseded_by_resume_job_id"].as_string().is_(None),
        )
        .order_by(SddAiJob.interrupted_at.desc().nulls_last(), SddAiJob.created_at.desc(), SddAiJob.id.desc())
        .first()
    )


def find_resume_source_job(db: Session, task: SddTask) -> SddAiJob | None:
    # A queued stop or a finished turn-mode question can be the source of a
    # resume. Its current revision takes precedence over historical pauses.
    job = (
        db.query(SddAiJob)
        .filter(
            SddAiJob.task_id == task.id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
            SddAiJob.session_generation == task.session_generation,
            SddAiJob.session_revision == task.session_revision,
            SddAiJob.status.in_(
                [AiJobStatus.INTERRUPTED, AiJobStatus.SUCCESS, AiJobStatus.CANCELLED, AiJobStatus.FAILED]
            ),
        )
        .order_by(SddAiJob.created_at.desc(), SddAiJob.id.desc())
        .first()
    )
    return job or _find_latest_interrupted_job(db, task)


def _remote_attempt_starting(db: Session, task_id: str) -> bool:
    task = db.get(SddTask, task_id)
    job = _current_task_job(db, task) if task else None
    return bool(
        job
        and job.status == AiJobStatus.RUNNING
        and job.process_execution_kind == "REMOTE_SESSION"
        and not job.session_id
    )


async def _wait_for_remote_attempt_start(run_txn, task_id: str) -> None:
    deadline = asyncio.get_running_loop().time() + 10
    while await run_txn(lambda session: _remote_attempt_starting(session, task_id)):
        if asyncio.get_running_loop().time() >= deadline:
            return
        await asyncio.sleep(0.05)


def _task_payload(task: SddTask, job_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        **sm.snapshot(task),
        "session_id": task.session_id,
        "interrupt_reason": task.interrupt_reason,
        "interrupted_by_id": task.interrupted_by_id,
        "interrupted_at": task.interrupted_at.isoformat() if task.interrupted_at else None,
        "job": job_payload,
    }


def _load_interrupt_state_sync(db: Session, *, task_id: str, job_id: str | None) -> dict[str, Any]:
    task = db.query(SddTask).filter(SddTask.id == task_id).first()
    if not task:
        raise TaskSessionControlError("Task not found", status_code=404)
    job = db.get(SddAiJob, job_id) if job_id else None
    job_payload = serialize_job(job) if job else None
    return _task_payload(task, job_payload)


def _interrupt_preparing_submission(db: Session, task_id: str, message: str) -> dict[str, Any] | None:
    from app.domains.task.models.chat_submission import TaskChatSubmission
    from app.domains.task.services import chat_submission_service
    from app.domains.workspace_collaboration.service import abandon_input

    row = db.query(TaskChatSubmission).filter_by(task_id=task_id, status="PREPARING").with_for_update().one_or_none()
    if not row:
        return None
    abandon_input(db, task_id, row.id)
    chat_submission_service._transition(db, row, "FAILED", error_message=message)
    return chat_submission_service.serialize(row)


def _accept_interrupt_command(
    db: Session,
    task_id: str,
    actor_id: str,
    command_id: str | None,
    sequence: int | None,
    reason: str | None,
    *,
    workspace_id: str | None = None,
    user_requested: bool = False,
) -> tuple[dict[str, Any], TerminationRequestResult | None]:
    task_query = db.query(SddTask).filter_by(id=task_id)
    if workspace_id is not None:
        task_query = task_query.filter_by(workspace_id=workspace_id)
    task = task_query.populate_existing().with_for_update().one_or_none()
    if task is None:
        raise TaskSessionControlError("Task not found", status_code=404)
    _require_local_actor(db, task_id, actor_id)
    if command_id is None and task.status == TaskStatus.INTERRUPTED:
        return {**_task_payload(task), "duplicate": True}, None

    event_key = f"interrupt-command:{command_id or uuid4()}"
    # The transition clears status_run_id. Capture its exact job while holding
    # the task lock, then commit the two writes together.
    job = _current_task_job(db, task)
    if (
        job is not None
        and job.status in {AiJobStatus.TERMINATING, AiJobStatus.ORPHANED}
        and persisted_stop_mode(job) == "CANCEL"
    ):
        if user_requested:
            raise TaskSessionControlError("当前执行已请求终止，请等待回收完成", status_code=409)
        return {**_task_payload(task), "duplicate": True}, None
    result = sm.dispatch(
        db,
        task,
        sm.Trigger.INTERRUPT if user_requested else sm.Trigger.SYSTEM_INTERRUPT,
        event_key=event_key,
        actor_id=actor_id,
        expected_seq=sequence,
        reason=reason,
    )
    if result.get("duplicate"):
        return {**sm.receipt(db, task_id, event_key), "duplicate": True}, None

    default_reason = "User temporarily interrupted the AI session" if user_requested else "AI session stopped by system"
    reason_text = str(reason or default_reason).strip()
    stopped = None
    if job is not None:
        stopped = request_attempt_termination_in_txn(
            db,
            AttemptTerminationRequest(
                job_id=job.id,
                task_id=task.id,
                actor_user_id=actor_id,
                reason=reason_text,
                mode="INTERRUPT",
                message="AI session interrupted by user"
                if user_requested and job.status != AiJobStatus.PENDING
                else reason_text,
                failure_code="USER_INTERRUPT" if user_requested else "SYSTEM_INTERRUPT",
                interrupt_context_patch={"interrupt_kind": task.interrupt_kind},
            ),
        )
        task.session_id = stopped.session_id or task.session_id
    submission = _interrupt_preparing_submission(db, task_id, reason_text)
    if user_requested:
        task.error_message = None
    task.interrupt_reason = reason_text
    task.interrupted_by_id = actor_id
    task.interrupted_at = datetime.utcnow()
    db.flush()
    receipt = _task_payload(task)
    if job is not None:
        receipt["job"] = {"id": job.id, "status": _as_text(job.status)}
    if submission is not None:
        receipt["submission"] = submission
    sm.remember_command_result(db, task_id, event_key, receipt)
    db.commit()
    return receipt, stopped


def _engine_owns_stop(engine: TaskAgentEngine, target: TerminationRequestResult) -> bool:
    if not engine.running or engine.current_job_id != target.job_id:
        return False
    attempt = engine.attempt
    return (attempt.run_token if attempt else None) == target.run_token and (
        attempt.worker_boot_id if attempt else None
    ) == target.worker_boot_id


async def interrupt_task(
    db: Session,
    *,
    task: SddTask | None = None,
    task_id: str | None = None,
    workspace_id: str | None = None,
    actor_user_id: str,
    reason: str | None = None,
    command_id: str | None = None,
    expected_status_seq: int | None = None,
    user_requested: bool = False,
) -> dict[str, Any]:
    """Stop an execution, preserving the source of the interrupt for task and job."""
    db_bind = db.get_bind()
    if task is None:
        db.close()
    resolved_task_id = str(task_id or (task.id if task is not None else ""))
    if not resolved_task_id:
        raise TaskSessionControlError("Task not found", status_code=404)
    run_interrupt_txn = _bind_txn_runner(db, db_bind)

    # Give a provider that is creating a session time to persist its locator.
    # Recovery needs that locator if this worker goes away during the stop.
    await _wait_for_remote_attempt_start(run_interrupt_txn, resolved_task_id)
    receipt, target = await run_interrupt_txn(
        lambda session: _accept_interrupt_command(
            session,
            resolved_task_id,
            actor_user_id,
            command_id,
            expected_status_seq,
            reason,
            workspace_id=workspace_id,
            user_requested=user_requested,
        )
    )
    if receipt.get("duplicate"):
        return receipt

    if target and target.changed and target.status == AiJobStatus.TERMINATING.value:
        engine = get_engine(resolved_task_id)
        if engine and _engine_owns_stop(engine, target):
            await _stop_interrupt_engine(run_interrupt_txn, engine, target, receipt["interrupt_reason"])
        elif target.worker_boot_id == WORKER_BOOT_ID:
            # The local runner may be starting or exiting without an engine.
            # The durable request also lets the reaper stop an abandoned owner.
            ai_runtime.request_cancel(target.job_id)

    state = await run_interrupt_txn(
        lambda session: _load_interrupt_state_sync(
            session, task_id=resolved_task_id, job_id=target.job_id if target else None
        )
    )
    if "submission" in receipt:
        state["submission"] = receipt["submission"]
    if target and target.changed:
        await ai_job_publishing.publish_job(target.job_id)
    task_event_publisher.wake()
    await _publish_interruption(resolved_task_id, state)
    return state


async def _stop_interrupt_engine(run_txn, engine, target: TerminationRequestResult, reason: str) -> None:
    try:
        stop_result = await engine.interrupt()
    except Exception as exc:
        stop_result = None
        reason = str(exc) or exc.__class__.__name__
    await run_txn(
        lambda session: ai_job_attempts.finalize_interruption_in_txn(
            session, target, stop_result=stop_result, reason=reason
        )
    )


async def _publish_interruption(task_id: str, state: dict[str, Any]) -> None:
    await task_ws_manager.send_message_to_room(task_id, WSMessage(type="task_interrupted", payload=state))


def _prepare_interrupted_resume(
    db: Session,
    *,
    task_id,
    actor_user_id,
    idempotency_key,
    prompt,
    confirm_continue,
    new_agent_session=False,
    agent_model=None,
    images=None,
) -> dict[str, Any]:
    _require_local_actor(db, task_id, actor_user_id)
    if idempotency_key:
        from app.domains.workspace_collaboration.control import existing_resume

        existing_receipt = existing_resume(
            db,
            task_id,
            actor_user_id,
            idempotency_key,
            prompt,
            confirm_continue,
            new_agent_session=new_agent_session,
            agent_model=agent_model,
            images=images,
        )
        if existing_receipt:
            return {"duplicate_payload": existing_receipt}

    task = db.query(SddTask).filter(SddTask.id == task_id).first()
    if task is None:
        raise TaskSessionControlError("Task not found", status_code=404)
    if task.status != TaskStatus.INTERRUPTED:
        raise TaskSessionControlError("Only interrupted tasks can be resumed", status_code=409)

    # 会话/总结互斥：总结进行中禁止恢复会话
    if find_active_summary_job(db, task_id) is not None:
        raise TaskSessionControlError(
            "一键总结问题案例进行中，请等待完成或停止后再恢复会话",
            status_code=409,
        )

    prompt_text = str(prompt or "").strip()
    if not prompt_text and confirm_continue:
        prompt_text = "Please continue the interrupted task from the current session context."
    if not prompt_text and not images:
        raise TaskSessionControlError("Prompt is required to resume an interrupted task", status_code=400)

    job = find_resume_source_job(db, task)
    job_session = job.session_id if job and job.session_revision == task.session_revision else None
    session_id = str(task.session_id or job_session or "").strip()
    return {
        "duplicate_payload": None,
        "task_status": _as_text(task.status),
        "interrupt_reason": task.interrupt_reason,
        "interrupted_by_id": task.interrupted_by_id,
        "interrupted_at": task.interrupted_at.isoformat() if task.interrupted_at else None,
        "old_job_id": str(job.id) if job else None,
        "session_id": session_id or None,
        "status_seq": task.status_seq,
        "session_generation": task.session_generation,
        "session_revision": task.session_revision,
        "prompt_text": prompt_text,
    }


async def resume_interrupted_task(
    *,
    task_id: str,
    actor_user_id: str,
    prompt: str | None = None,
    confirm_continue: bool = False,
    metadata_json: dict[str, Any] | None = None,
    client_message_id: str | None = None,
    new_agent_session: bool = False,
) -> dict[str, Any]:
    """Accept a durable resume receipt before preparing the successor turn."""
    idempotency_key = str(client_message_id or "").strip()
    from app.domains.task.services import chat_submission_service

    if len(idempotency_key) > chat_submission_service.MAX_CLIENT_MESSAGE_ID_LENGTH:
        raise TaskSessionControlError("消息标识过长", status_code=400)
    if idempotency_key.lower().startswith(chat_submission_service.PRE_INPUT_CLIENT_ID_PREFIX):
        raise TaskSessionControlError("该消息标识由协作预输入保留", status_code=400)

    message_metadata = dict(metadata_json) if isinstance(metadata_json, dict) else {}
    _prepare_resume_sync = partial(
        _prepare_interrupted_resume,
        task_id=task_id,
        actor_user_id=actor_user_id,
        idempotency_key=idempotency_key,
        prompt=prompt,
        confirm_continue=confirm_continue,
        new_agent_session=new_agent_session,
        agent_model=message_metadata.get("agent_model"),
        images=message_metadata.get(CHAT_IMAGES_KEY),
    )

    prepared = await run_db_txn(_prepare_resume_sync)
    if prepared.get("duplicate_payload") is not None:
        return prepared["duplicate_payload"]

    from app.domains.task.services.task_attempt_recovery_service import recover_task_attempts

    await recover_task_attempts(task_id, run_txn=run_db_txn, wait_for_running=True, wait_for_interrupt_lease=True)
    await run_db_txn(lambda db: chat_submission_service._reconcile_sync(db, task_id=task_id))
    await chat_submission_service.wake_event_publisher()

    engine = get_engine(task_id)
    if engine and engine.running:
        raise TaskSessionControlError("Task is already running", status_code=409)

    from app.domains.task.services.agent_session_switch import check_task_session

    key, status = await check_task_session(task_id, new_session=new_agent_session)
    failed_check = key if status is None else None
    if new_agent_session:
        prepared["replace_agent_session"] = True
        prepared["agent_session_replacement_check"] = key

    from app.domains.workspace_collaboration.control import resume_submission, schedule_control

    receipt = await run_db_txn(
        lambda db: resume_submission(
            db, task_id, actor_user_id, prepared, idempotency_key or None, message_metadata, failed_check=failed_check
        )
    )
    await schedule_control(receipt)
    return {"task_id": task_id, "job": None, "submission": receipt}


# ──────────────────────── 会话建立：start / initialize ────────────────────────


def _session_bind(db: Session) -> Any:
    """Resolve the bind of a possibly closed request dependency session."""
    return db.get_bind()


def _bind_txn_runner(db: Session, db_bind: Any) -> Callable[[Callable[[Session], Any]], Awaitable[Any]]:
    """Run each body in its own worker-thread transaction on the dependency's bind."""

    async def run(body: Callable[[Session], Any]) -> Any:
        return await run_db_txn_with_bind(db_bind, body)

    return run


def _ensure_task_not_baselined(task: SddTask) -> None:
    if task.baselined_at is not None:
        raise TaskSessionControlError(BASELINED_LOCKED_MSG, status_code=403)
    if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
        raise TaskSessionControlError("Terminal tasks cannot resume or start a new session.", status_code=409)


def _assert_no_preparing_submission(db: Session, task_id: str) -> None:
    from app.domains.task.services.chat_submission_service import (
        SubmissionError,
        assert_no_preparing_submission,
    )

    try:
        assert_no_preparing_submission(db, task_id)
    except SubmissionError as exc:
        raise TaskSessionControlError(str(exc), status_code=409) from exc


def build_session_prompt(task: SddTask, requested_prompt: str | None) -> dict[str, str]:
    """组装会话首条 prompt（start 与 initialize 共用）。

    会话窗口只展示用户输入部分（``user_display``）；规格文件指引与诊断
    后缀等内置提示词只随作业发给 agent（``prompt``）。
    """
    from app.domains.task.services.diagnosis_result_service import build_diagnosis_prompt_suffix

    requested = str(requested_prompt or "").strip()
    user_display = requested or (task.description or "").strip() or f"Please start task '{task.name}'."
    prompt = user_display
    if task.spec_doc_path:
        abs_path = os.path.abspath(task.spec_doc_path)
        prompt += (
            "\n\nPlease read and strictly implement all requirements in the specification file. "
            f"Absolute path: {abs_path}"
        )
    prompt += build_diagnosis_prompt_suffix(task)
    return {"user_display": user_display, "prompt": prompt}


def load_start_task_context_sync(
    db: Session,
    *,
    ws_id: str,
    task_id: str,
    requested_prompt: str | None = None,
) -> dict[str, Any]:
    """启动前守卫 + 首条 prompt 组装（单事务，调用方已持有任务锁）。"""
    task = task_task_records_queries.get_task(db, task_id, ws_id)
    if not task:
        raise TaskSessionControlError("Task not found", status_code=404)
    _assert_no_preparing_submission(db, task_id)
    _ensure_task_not_baselined(task)
    if task.status == TaskStatus.PROVISIONING:
        raise TaskSessionControlError(TASK_PROVISIONING_MSG, status_code=409)
    if task.status == TaskStatus.RUNNING:
        raise TaskSessionControlError(TASK_RUNNING_MSG, status_code=409)
    if task.status == TaskStatus.INTERRUPTED:
        raise TaskSessionControlError(TASK_INTERRUPTED_MSG, status_code=409)
    if task.status != TaskStatus.INITIALIZED:
        raise TaskSessionControlError("Only initialized tasks can be started.", status_code=409)
    if find_active_summary_job(db, task.id) is not None:
        raise TaskSessionControlError("一键总结问题案例进行中，请等待完成或停止后再启动会话", status_code=409)
    prompts = build_session_prompt(task, requested_prompt)
    return {
        "task_id": task.id,
        "task_name": task.name,
        "task_description": task.description,
        "task_spec_doc_path": task.spec_doc_path,
        **prompts,
    }


def start_task_session_sync(
    db: Session,
    *,
    ws_id: str,
    task_id: str,
    creator_id: str,
    prompt: str,
    user_display: str,
    sop_auto_run: bool | None = None,
    command_id: str = "start",
    command_reason: str | None = None,
) -> dict[str, Any]:
    """任务状态重置为 RUNNING，并创建首条消息 + 聊天作业（单事务，锁内调用）。"""
    task = task_task_records_queries.get_task(db, task_id, ws_id)
    if not task:
        raise TaskSessionControlError("Task not found", status_code=404)
    _ensure_task_not_baselined(task)
    if task.status != TaskStatus.INITIALIZED:
        raise TaskSessionControlError("Only initialized tasks can be started.", status_code=409)
    event_key = f"start:{command_id}"
    sm.dispatch(db, task, sm.Trigger.START, event_key=event_key, actor_id=creator_id, reason=command_reason)
    task.error_message = None
    task.business_state = "TASK_IN_PROGRESS"
    task.session_id = None
    previous_generation = int(task.session_generation or 0)
    task.session_generation = max(1, int(task.session_generation or 0))
    task.interrupt_reason = None
    task.interrupted_by_id = None
    task.interrupted_at = None
    # 主开关：启动引擎时可更新“自动执行全流程”任务级偏好
    if sop_auto_run is not None:
        task.task_meta_json = {**(task.task_meta_json or {}), "sop_auto_run": bool(sop_auto_run)}

    from app.domains.workspace_collaboration import control as collaboration_control

    if collaboration_control.enabled(db, task.id):
        if previous_generation != task.session_generation:
            from app.domains.workspace_collaboration.service import reset_session

            reset_session(db, task, actor_id=creator_id)
        receipt = collaboration_control.accept_control(
            db, task, creator_id, content=user_display, prompt=prompt, fresh_session=True, source="task_start"
        )
        result = {**sm.snapshot(task), "job_id": None, "job": None, "submission": receipt}
        sm.remember_command_result(db, task.id, event_key, result)
        return result

    initial_message = task_conversation_messages.save_chat_message(
        db,
        task_id=task.id,
        workspace_id=ws_id,
        creator_id=creator_id,
        role="user",
        content=user_display,
        message_type="text",
        metadata_json={
            "source": "task_start",
            "fresh_session": True,
            "initial_prompt": True,
        },
        session_generation=task.session_generation,
        commit=False,
    )
    job = create_task_chat_job(
        db,
        workspace_id=ws_id,
        task_id=task.id,
        creator_id=creator_id,
        prompt_text=prompt,
        context_json={"source": "task_start", "fresh_session": True, "chat_message_id": initial_message.id},
        chat_message_id=initial_message.id,
        session_generation=task.session_generation,
        session_revision=task.session_revision,
        commit=False,
    )
    result = {
        "task_id": task.id,
        "job_id": job.id,
        "job": serialize_job(job),
        **sm.snapshot(task),
    }
    sm.remember_command_result(db, task.id, event_key, result)
    return result


def _replay_start(db, task_id, command_id, actor_id, reason):
    key = f"start:{command_id}"
    result = sm.receipt(db, task_id, key)
    if result:
        sm.dispatch(db, db.get(SddTask, task_id), sm.Trigger.START, event_key=key, actor_id=actor_id, reason=reason)
    return result


def _finish_start_side_effects(db: Session, job_id: str) -> None:
    from app.domains.task.models.chat import ChatMessage
    from app.domains.task.services.conversation.notifications import notify_followers

    job = db.get(SddAiJob, job_id)
    if not job:
        return
    message_id = (job.context_json or {}).get("chat_message_id")
    if message_id and (message := db.get(ChatMessage, message_id)):
        notify_followers(db, message)
    try:
        context_token_service.seed_snapshot_for_job(
            db, job=job, prompt_text=job.prompt_text, chat_message_id=message_id
        )
    except Exception:
        logger.exception("Start context snapshot deferred: job_id={}", job_id)
        db.rollback()


async def start_task_session(
    db: Session,
    *,
    ws_id: str,
    task_id: str,
    actor_user_id: str,
    requested_prompt: str | None = None,
    sop_auto_run: bool | None = None,
    command_id: str = "start",
) -> dict[str, Any]:
    """启动全新任务会话（POST /start 业务编排；调用方已持有任务锁）。

    守卫检查 → 旧引擎收尾 → 状态重置 + 首条消息 + 聊天作业 → 入队执行。
    依赖 Session 只用于解析 bind（路由层已在等待锁前关闭它）。
    """
    run_txn = _bind_txn_runner(db, _session_bind(db))
    await run_txn(lambda session: _require_local_actor(session, task_id, actor_user_id))
    import json

    command_reason = json.dumps([requested_prompt, sop_auto_run], ensure_ascii=False)
    previous = await run_txn(lambda session: _replay_start(session, task_id, command_id, actor_user_id, command_reason))
    if previous:
        return previous
    state = await run_txn(
        lambda session: load_start_task_context_sync(
            session, ws_id=ws_id, task_id=task_id, requested_prompt=requested_prompt
        )
    )
    existing_engine = get_engine(state["task_id"])
    if existing_engine and existing_engine.running:
        raise TaskSessionControlError(TASK_RUNNING_MSG, status_code=409)
    if existing_engine and not existing_engine.running:
        await existing_engine.stop()

    result = await run_txn(
        lambda session: start_task_session_sync(
            session,
            ws_id=ws_id,
            task_id=task_id,
            creator_id=actor_user_id,
            prompt=state["prompt"],
            user_display=state["user_display"],
            sop_auto_run=sop_auto_run,
            command_id=command_id,
            command_reason=command_reason,
        )
    )
    if result.get("submission"):
        from app.domains.workspace_collaboration.control import schedule_control

        await schedule_control(result["submission"])
        return {**result, "msg": "正在准备本轮本地代码"}
    await run_txn(lambda session: _finish_start_side_effects(session, result["job_id"]))
    await ai_job_publishing.enqueue_task_chat_job(result["job_id"])
    return {**result, "msg": "Task started"}


def prepare_initialize_sync(
    db: Session, *, ws_id: str, task_id: str, actor_user_id: str | None = None, cancel_jobs: bool = True
) -> dict[str, Any]:
    """重新初始化前置守卫 + 取消在途聊天作业（单事务，锁内调用）。"""
    task = task_task_records_queries.get_task(db, task_id, ws_id)
    if not task:
        raise TaskSessionControlError("Task not found", status_code=404)
    _assert_no_preparing_submission(db, task_id)
    _ensure_task_not_baselined(task)
    if task.status == TaskStatus.PROVISIONING:
        raise TaskSessionControlError(TASK_PROVISIONING_MSG, status_code=409)
    if str(task.current_phase or "").strip().upper() == "PREPARE_FAILED":
        raise TaskSessionControlError(
            "Task preparation failed and cannot be initialized. Please create a new task.",
            status_code=409,
        )
    cancelled_job_ids = (
        ai_job_attempts.mark_task_chat_jobs_cancelled(
            db,
            workspace_id=ws_id,
            task_id=task_id,
            message="Task initialized with a fresh session",
        )
        if cancel_jobs
        else []
    )
    return {"task_id": task.id, "cancelled_job_ids": cancelled_job_ids}


def apply_initialize_sync(
    db: Session,
    *,
    ws_id: str,
    task_id: str,
    skill_ids: list[str] | None,
    keep_deleted_runtime_skills: bool,
    requested_prompt: str | None = None,
    actor_user_id: str | None = None,
    reason: str | None = None,
    initialization_id: str | None = None,
) -> dict[str, Any]:
    """替换 Skills、推进 session_generation、重置状态并组装首条 prompt（单事务，锁内调用）。"""
    task = task_task_records_queries.get_task(db, task_id, ws_id)
    if not task:
        raise TaskSessionControlError("Task not found", status_code=404)
    _ensure_task_not_baselined(task)
    # Cancellation is a request, not proof that the old attempt has exited.
    # Check before clearing the session or advancing its generation.
    if has_blocking_chat_job(db, task_id):
        raise TaskSessionControlError("旧任务执行尚未清理完成，请稍后重试初始化；无需删除任务。", status_code=409)
    if skill_ids is not None:
        skill_runtime_configuration.replace_task_skills_for_initialize(
            db,
            task,
            workspace_id=ws_id,
            skill_ids=skill_ids,
            keep_deleted_runtime_skills=keep_deleted_runtime_skills,
        )
    task.retry_count = int(task.retry_count or 0) + 1
    task.session_generation = int(getattr(task, "session_generation", 0) or 0) + 1
    sm.dispatch(
        db,
        task,
        sm.Trigger.RESET,
        event_key=f"reset:{initialization_id or task.session_generation}",
        actor_id=actor_user_id,
    )
    task.business_state = "TASK_IN_PROGRESS"
    task.error_message = None
    task.session_id = None
    task.interrupt_reason = None
    task.interrupted_by_id = None
    task.interrupted_at = None
    if initialization_id:
        from app.domains.task.services.initialization import state as initialization

        operation = initialization.current(task)
        if operation.get("id") != initialization_id:
            raise initialization.InitializationError("初始化操作已变化。")
        task.session_generation = operation["generation"]
        task.task_meta_json = {
            **(task.task_meta_json or {}),
            "repository_update": None,
            "repository_baselines": {repo["id"]: repo["target"] for repo in operation["repositories"]},
            "repository_update_revision": int(task.session_revision or 0) + 1,
            "initialization": {**operation, "state": "STARTING", "error": None},
        }
    prompts = build_session_prompt(task, requested_prompt)
    from app.domains.workspace_collaboration import control as collaboration_control
    from app.domains.workspace_collaboration import service as collaboration

    collaboration.reset_session(db, task, actor_id=actor_user_id)
    receipt = None
    if actor_user_id and collaboration_control.enabled(db, task_id):
        # Accept before committing the reset. A rejected input must preserve
        # the previous session, generation and collaboration state together.
        receipt = collaboration_control.accept_control(
            db,
            task,
            actor_user_id,
            content=prompts["user_display"],
            prompt=prompts["prompt"],
            fresh_session=True,
            source="task_initialize",
            metadata={"initialize_reason": str(reason or "").strip()},
        )
    if actor_user_id:
        from app.domains.notification.services.task_awareness import capture_business

        capture_business(db, task, actor_user_id, "TASK_INITIALIZED", str(reason or "任务已人工初始化"))
    db.commit()
    return {"task_id": task.id, **prompts, "submission": receipt}


def _serialize_job_by_id_sync(db: Session, job_id: str) -> dict[str, Any] | None:
    job = db.get(SddAiJob, job_id)
    return serialize_job(job) if job else None


async def initialize_task_session(
    db: Session,
    *,
    ws_id: str,
    task_id: str,
    actor_user_id: str,
    skill_ids: list[str] | None = None,
    keep_deleted_runtime_skills: bool = True,
    requested_prompt: str | None = None,
    reason: str | None = None,
    operation_id: str | None = None,
    collaboration: dict | None = None,
    local_reset_receipt: dict | None = None,
) -> dict[str, Any]:
    """Restart code and provider context as one recoverable initialization."""
    from app.domains.task.services.initialization.service import initialize
    from app.domains.task.services.initialization.state import InitializationError

    try:
        return await initialize(
            db,
            ws_id=ws_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
            operation_id=operation_id,
            collaboration=collaboration,
            local_reset_receipt=local_reset_receipt,
            skill_ids=skill_ids,
            keep_deleted_runtime_skills=keep_deleted_runtime_skills,
            requested_prompt=requested_prompt,
            reason=reason,
        )
    except InitializationError as exc:
        raise TaskSessionControlError(str(exc), status_code=exc.status_code) from exc
