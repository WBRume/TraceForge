"""Task 会话生命周期编排：start（建立）/ initialize（重置）/ interrupt（打断）/ resume（恢复）。

四个转换共享同一套编排纪律：
- 路由层负责鉴权、参数解析与任务分布式锁（锁冲突映射为 HTTP 409/429）；
- 服务层在锁内把同步 DB 段拆成单事务、在 DB 线程执行（run_db_txn_with_bind），
  引擎检查、attempt 恢复、turn 创建与广播保持在事件循环；
- 业务守卫失败抛 TaskSessionControlError（携带 HTTP 状态码），路由统一映射。
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.engine.session import TaskAgentEngine, get_engine
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.task.models.chat import ChatMessage, MessageRole, MessageType
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.ai.schemas.websocket import WSMessage
from app.domains.ai.services.jobs import attempts as ai_job_attempts
from app.domains.ai.services.jobs import publishing as ai_job_publishing
from app.domains.ai.services.jobs.store import (
    create_task_chat_job,
    find_active_summary_job,
    serialize_job,
)
from app.domains.task.services import context_token_service, task_service, task_session_service
from app.core.offload import run_db_txn, run_db_txn_with_bind
from app.domains.websocket.ws.manager import manager as task_ws_manager

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


def _merge_json(original: Any, patch: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(original) if isinstance(original, dict) else {}
    merged.update(patch)
    return merged


def _find_running_task_job(db: Session, task_id: str, engine: TaskAgentEngine) -> Optional[SddAiJob]:
    query = db.query(SddAiJob).filter(
        SddAiJob.task_id == task_id,
        SddAiJob.channel == AiJobChannel.TASK_CHAT,
        SddAiJob.status == AiJobStatus.RUNNING,
    )
    if engine.current_job_id:
        current = query.filter(SddAiJob.id == engine.current_job_id).first()
        if current:
            return current
    return query.order_by(SddAiJob.created_at.desc()).first()


def _find_active_task_job(db: Session, task_id: str) -> Optional[SddAiJob]:
    """查找尚未结束的 TASK_CHAT 作业（PENDING/RUNNING/WAITING_HITL）。"""
    return (
        db.query(SddAiJob)
        .filter(
            SddAiJob.task_id == task_id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
            SddAiJob.status.in_([
                AiJobStatus.PENDING,
                AiJobStatus.RUNNING,
                AiJobStatus.WAITING_HITL,
                AiJobStatus.TERMINATING,
                AiJobStatus.ORPHANED,
            ]),
        )
        .order_by(SddAiJob.created_at.desc())
        .first()
    )


def _find_latest_interrupted_job(db: Session, task_id: str) -> Optional[SddAiJob]:
    return (
        db.query(SddAiJob)
        .filter(
            SddAiJob.task_id == task_id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
            SddAiJob.status == AiJobStatus.INTERRUPTED,
        )
        .order_by(SddAiJob.interrupted_at.desc(), SddAiJob.created_at.desc())
        .first()
    )


def _task_payload(task: SddTask, job_payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "task_id": task.id,
        "workspace_id": task.workspace_id,
        "status": _as_text(task.status),
        "session_id": task.session_id,
        "interrupt_reason": task.interrupt_reason,
        "interrupted_by_id": task.interrupted_by_id,
        "interrupted_at": task.interrupted_at.isoformat() if task.interrupted_at else None,
        "job": job_payload,
    }


async def _broadcast_task_event(event_type: str, task: SddTask, job_payload: Optional[Dict[str, Any]]) -> None:
    await task_ws_manager.send_message_to_room(
        task.id,
        WSMessage(type=event_type, payload=_task_payload(task, job_payload)),
    )


def _prepare_interrupt_sync(
    db: Session,
    *,
    task_id: str,
    actor_user_id: str,
    reason: Optional[str],
    engine_job_id: Optional[str],
) -> Dict[str, Any]:
    """中断准备段（单事务）：job/task 加锁 + 唯一 termination request（doc §4.5.1）。

    不再直接把 job 写成 TERMINATING：行锁与写路径全部由
    ``request_attempt_termination_in_txn`` 提供，与业务 finalizer 共享同一
    锁协议，杜绝“普通 SELECT 读到 RUNNING 后覆盖已提交终态”的交错。
    """
    from app.domains.ai.services.ai_job_convergence_service import (
        AttemptTerminationRequest,
        request_attempt_termination_in_txn,
    )

    task = db.query(SddTask).filter(SddTask.id == task_id).first()
    if not task:
        raise TaskSessionControlError("Task not found", status_code=404)
    query = db.query(SddAiJob.id).filter(
        SddAiJob.task_id == task_id,
        SddAiJob.channel == AiJobChannel.TASK_CHAT,
        SddAiJob.status == AiJobStatus.RUNNING,
    )
    if engine_job_id:
        query = query.filter(SddAiJob.id == engine_job_id)
    candidate = query.order_by(SddAiJob.created_at.desc()).first()
    if not candidate:
        raise TaskSessionControlError("No running AI job to interrupt", status_code=409)
    job_id = str(candidate[0])

    now = datetime.utcnow()
    reason_text = str(reason or "User temporarily interrupted the AI session").strip()
    result = request_attempt_termination_in_txn(
        db,
        AttemptTerminationRequest(
            job_id=job_id,
            task_id=task_id,
            actor_user_id=actor_user_id,
            reason=reason_text,
            mode="INTERRUPT",
            message="AI session interrupted by user",
            failure_code="USER_INTERRUPT",
            interrupt_context_patch={
                "interrupted": True,
                "interrupted_at": now.isoformat() + "Z",
                "interrupted_by_id": actor_user_id,
            },
            mark_task_interrupted=True,
        ),
    )
    if not result.changed:
        # 行锁内重读发现已被 finalizer/取消收敛：幂等退出，不得覆盖。
        raise TaskSessionControlError("AI job is no longer interruptible", status_code=409)
    db.commit()
    return {
        "task_id": task_id,
        "job_id": job_id,
        "run_token": result.run_token,
        "session_id": result.session_id,
    }


def _load_interrupt_state_sync(
    db: Session, *, task_id: str, job_id: Optional[str]
) -> Dict[str, Any]:
    task = db.query(SddTask).filter(SddTask.id == task_id).first()
    if not task:
        raise TaskSessionControlError("Task not found", status_code=404)
    job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first() if job_id else None
    return {
        "task": _task_payload(task, serialize_job(job) if job else None),
        "job": serialize_job(job) if job else None,
    }


def _cancel_active_jobs_sync(
    db: Session, *, task_id: str, workspace_id: str, message: str
) -> Dict[str, Any]:
    active = _find_active_task_job(db, task_id)
    if not active:
        raise TaskSessionControlError(
            "No running Claude CLI session or active AI job to interrupt",
            status_code=409,
        )
    cancelled_ids = ai_job_attempts.mark_task_chat_jobs_cancelled(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        message=message,
    )
    if not cancelled_ids:
        raise TaskSessionControlError("No active AI job to interrupt", status_code=409)
    task = db.query(SddTask).filter(SddTask.id == task_id).first()
    job = db.query(SddAiJob).filter(SddAiJob.id == active.id).first()
    return {
        "cancelled_ids": cancelled_ids,
        "task": _task_payload(task, serialize_job(job) if job else None),
        "job": serialize_job(job) if job else None,
    }


def _finalize_legacy_interrupt_sync(
    db: Session,
    *,
    task_id: str,
    job_id: str,
    confirmed_dead: bool,
    reason: str,
) -> None:
    job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
    if not job or job.status not in {AiJobStatus.TERMINATING, AiJobStatus.ORPHANED}:
        return
    if confirmed_dead:
        job.status = AiJobStatus.INTERRUPTED
        job.progress = 100
        job.message = "AI session interrupted by user"
        job.finished_at = datetime.utcnow()
        job.error_message = None
        job.run_token = None
        job.worker_id = None
        job.worker_boot_id = None
        job.process_pid = None
        job.process_started_at = None
        job.process_group_id = None
        job.heartbeat_at = None
        job.lease_expires_at = None
    else:
        job.status = AiJobStatus.ORPHANED
        job.message = "Agent process could not be confirmed dead"
        job.error_message = reason
        job.failure_code = "PROCESS_TREE_UNKNOWN"
        job.terminal_reason = reason
    db.commit()


async def interrupt_task(
    db: Session,
    *,
    task: Optional[SddTask] = None,
    task_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    actor_user_id: str,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    # The dependency Session is only useful for the caller's initial route
    # lookup.  All DB work below is isolated into short worker-thread txns.
    db_bind = db.get_bind()

    async def run_interrupt_txn(body):
        return await run_db_txn_with_bind(db_bind, body)

    # Direct service callers may intentionally retain a persistent ORM object
    # for their own transaction assertions.  Production routes pass ids only
    # and close the dependency session before awaiting locks.
    if task is None:
        db.close()
    resolved_task_id = str(task_id or (task.id if task is not None else ""))
    resolved_workspace_id = str(
        workspace_id or (task.workspace_id if task is not None else "")
    )
    if not resolved_task_id:
        raise TaskSessionControlError("Task not found", status_code=404)
    engine = get_engine(resolved_task_id)
    if engine and engine.running:
        prepared = await run_interrupt_txn(
            lambda session: _prepare_interrupt_sync(
                session,
                task_id=resolved_task_id,
                actor_user_id=actor_user_id,
                reason=reason,
                engine_job_id=engine.current_job_id,
            )
        )
        reason_text = str(reason or "User temporarily interrupted the AI session").strip()
        run_token = prepared["run_token"]
        termination_error: Optional[str] = None
        try:
            termination = await engine.interrupt()
        except Exception as exc:
            # The process state is unknown when the engine stop path itself
            # fails.  Preserve the durable blocker as ORPHANED instead of
            # claiming an INTERRUPTED terminal state.
            termination = None
            termination_error = str(exc) or exc.__class__.__name__

        termination_reason = termination_error or str(
            getattr(termination, "error_message", "") or reason_text
        )
        # 统一停止结果协议（doc §5）：REMOTE_SESSION 以 stop_acknowledged 为
        # 准；LOCAL_PROCESS 以 local_process_confirmed_dead 为准。旧 bridge 的
        # TerminationResult 仍兼容（confirmed_dead 字段）。
        from app.agents.contract import AgentStopResult
        from app.domains.ai.services.ai_job_convergence_service import (
            evidence_from_stop_result,
        )

        if isinstance(termination, AgentStopResult):
            if termination.execution_kind == "REMOTE_SESSION":
                evidence = evidence_from_stop_result(
                    termination,
                    remote_session_started=bool(engine.session_id),
                    execution_kind="REMOTE_SESSION",
                )
            else:
                evidence = evidence_from_stop_result(termination, execution_kind="LOCAL_PROCESS")
            confirmed_dead = termination_error is None and (
                (
                    termination.execution_kind == "REMOTE_SESSION"
                    and termination.stop_acknowledged is True
                )
                or (
                    termination.execution_kind == "LOCAL_PROCESS"
                    and bool(termination.local_process_confirmed_dead)
                )
            )
        else:
            confirmed_dead = termination_error is None and (
                (termination is None and not run_token)
                or bool(termination is not None and getattr(termination, "confirmed_dead", False))
            )
            evidence = None
        if run_token:
            await ai_job_attempts.finalize_attempt_termination(
                prepared["job_id"],
                run_token,
                confirmed_dead=confirmed_dead,
                reason=termination_reason,
                failure_code=str(
                    getattr(termination, "error_code", "") or (
                        "USER_INTERRUPT" if confirmed_dead else "PROCESS_TREE_UNKNOWN"
                    )
                ),
                evidence=evidence,
                termination_mode="INTERRUPT",
            )
        else:
            await run_interrupt_txn(
                lambda session: _finalize_legacy_interrupt_sync(
                    session,
                    task_id=resolved_task_id,
                    job_id=prepared["job_id"],
                    confirmed_dead=confirmed_dead,
                    reason=termination_reason,
                )
            )
        state = await run_interrupt_txn(
            lambda session: _load_interrupt_state_sync(
                session, task_id=resolved_task_id, job_id=prepared["job_id"]
            )
        )

        await ai_job_publishing.publish_job(prepared["job_id"])
        if task is not None:
            await _broadcast_task_event("task_interrupted", task, state["job"])
        else:
            await task_ws_manager.send_message_to_room(
                resolved_task_id,
                WSMessage(type="task_interrupted", payload=state["task"]),
            )
        return state["task"]

    # 没有 running engine：可能是任务还在排队/刚结束，前端把停止按钮置为可点。
    # 此时不再报“No running Claude CLI session”，而是取消尚未真正启动的 AI job，
    # 让前端可以正确回刷运行状态。
    state = await run_interrupt_txn(
        lambda session: _cancel_active_jobs_sync(
            session,
            task_id=resolved_task_id,
            workspace_id=resolved_workspace_id,
            message=str(reason or "Task execution stopped before Claude session started").strip(),
        )
    )
    for job_id in state["cancelled_ids"]:
        # final 判定由 publish_job 依据 payload 状态计算（doc §9.2）。
        await ai_job_publishing.publish_job(job_id)
    if task is not None:
        await _broadcast_task_event("task_interrupted", task, state["job"])
    else:
        await task_ws_manager.send_message_to_room(
            resolved_task_id,
            WSMessage(type="task_interrupted", payload=state["task"]),
        )
    return state["task"]


async def resume_interrupted_task(
    *,
    task_id: str,
    actor_user_id: str,
    prompt: Optional[str] = None,
    confirm_continue: bool = False,
    metadata_json: Optional[Dict[str, Any]] = None,
    client_message_id: Optional[str] = None,
) -> Dict[str, Any]:
    """恢复被打断的任务（上行/REST 共用入口）。

    同步 DB 段拆分到 DB 线程执行（准备/收尾各自单事务、线程内自建 session）；
    引擎检查、checkpoint、turn 创建与广播保持在事件循环。
    """
    idempotency_key = str(client_message_id or "").strip()

    def _prepare_resume_sync(db: Session) -> Dict[str, Any]:
        if idempotency_key:
            existing_jobs = (
                db.query(SddAiJob)
                .filter(
                    SddAiJob.task_id == task_id,
                    SddAiJob.channel == AiJobChannel.TASK_CHAT,
                )
                .order_by(SddAiJob.created_at.desc())
                .limit(30)
                .all()
            )
            for existing in existing_jobs:
                context = existing.context_json if isinstance(existing.context_json, dict) else {}
                if context.get("client_message_id") == idempotency_key:
                    task = db.query(SddTask).filter(SddTask.id == task_id).first()
                    if task is not None:
                        return {"duplicate_payload": _task_payload(task, serialize_job(existing))}

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
        if not prompt_text:
            raise TaskSessionControlError("Prompt is required to resume an interrupted task", status_code=400)

        job = _find_latest_interrupted_job(db, task_id)
        if not job:
            raise TaskSessionControlError("No interrupted AI job found for this task", status_code=409)

        session_id = str(task.session_id or job.session_id or "").strip()
        return {
            "duplicate_payload": None,
            "task_status": _as_text(task.status),
            "interrupt_reason": task.interrupt_reason,
            "interrupted_by_id": task.interrupted_by_id,
            "interrupted_at": task.interrupted_at.isoformat() if task.interrupted_at else None,
            "old_job_id": str(job.id),
            "session_id": session_id or None,
            "prompt_text": prompt_text,
        }

    prepared = await run_db_txn(_prepare_resume_sync)
    if prepared.get("duplicate_payload") is not None:
        return prepared["duplicate_payload"]

    from app.domains.task.services import chat_submission_service
    from app.domains.task.services.task_attempt_recovery_service import recover_task_attempts

    await recover_task_attempts(task_id, run_txn=run_db_txn)
    await run_db_txn(lambda db: chat_submission_service._reconcile_sync(db, task_id=task_id))
    await chat_submission_service.wake_event_publisher()

    engine = get_engine(task_id)
    if engine and engine.running:
        raise TaskSessionControlError("Task is already running", status_code=409)

    now = datetime.utcnow()

    from app.domains.task.services import task_session_service

    message_metadata = dict(metadata_json) if isinstance(metadata_json, dict) else {}
    created = await task_session_service.create_task_chat_turn(
        task_id=task_id,
        actor_user_id=actor_user_id,
        content=prepared["prompt_text"],
        context_json={
            "source": "task_resume",
            "resume_interrupted": True,
            "resumed_from_job_id": prepared["old_job_id"],
            "resumed_at": now.isoformat() + "Z",
            "resumed_by_id": actor_user_id,
            "client_message_id": idempotency_key or None,
            **message_metadata,
        },
        session_id=prepared["session_id"],
        client_message_id=idempotency_key or None,
    )

    def _finalize_resume_sync(db: Session) -> Dict[str, Any]:
        """收尾段（单事务）：task 状态清理 + 旧 job 终态 + snapshot 种子 + payload 组装。"""
        task = db.query(SddTask).filter(SddTask.id == task_id).first()
        if task is None:
            raise TaskSessionControlError("Task not found", status_code=404)
        task.status = TaskStatus.CODING
        task.session_id = prepared["session_id"]
        task.error_message = None
        task.interrupt_reason = None
        task.interrupted_by_id = None
        task.interrupted_at = None

        # The interrupted attempt remains immutable history.  Making it terminal
        # removes the queue blocker; the new attempt is claimed as RUNNING only by
        # the normal queue worker, so scheduling failures cannot strand it RUNNING.
        old_job = db.query(SddAiJob).filter(SddAiJob.id == prepared["old_job_id"]).first()
        if old_job is not None:
            old_job.status = AiJobStatus.CANCELLED
            old_job.progress = 100
            old_job.message = "Interrupted attempt superseded by resume"
            old_job.finished_at = now
            old_job.context_json = _merge_json(
                old_job.context_json,
                {
                    "superseded_by_resume_job_id": created.job_id,
                    "superseded_at": now.isoformat() + "Z",
                },
            )

        resume_job = db.query(SddAiJob).filter(SddAiJob.id == created.job_id).first()
        try:
            if resume_job is not None:
                snapshot = context_token_service.ensure_snapshot_for_job(db, resume_job, status="PENDING")
                context_token_service.record_task_prompt(
                    db,
                    snapshot=snapshot,
                    prompt_text=prepared["prompt_text"],
                    chat_message_id=created.message_id,
                )
        except Exception:
            pass

        db.commit()
        job_payload = serialize_job(resume_job) if resume_job is not None else {}
        task_payload = _task_payload(task, job_payload)
        return {"task_payload": task_payload, "job_payload": job_payload}

    finalized = await run_db_txn(_finalize_resume_sync)

    await ai_job_publishing.publish_job(prepared["old_job_id"])
    await task_ws_manager.send_message_to_room(
        task_id,
        WSMessage(type="task_resumed", payload=finalized["task_payload"]),
    )
    await ai_job_publishing.enqueue_task_chat_job(created.job_id)
    return finalized["task_payload"]


# ──────────────────────── 会话建立：start / initialize ────────────────────────


def _session_bind(db: Session) -> Any:
    """Resolve the bind of a (possibly closed) request dependency session.

    轻量测试替身可能没有 get_bind：返回 None 时编排退化为直接同步执行。
    """
    getter = getattr(db, "get_bind", None)
    return getter() if callable(getter) else None


def _bind_txn_runner(
    db: Session, db_bind: Any
) -> Callable[[Callable[[Session], Any]], Awaitable[Any]]:
    """锁内短事务执行器：有 bind 走 DB 线程，无 bind（测试替身）同步执行。"""
    if db_bind is None:
        async def run(body: Callable[[Session], Any]) -> Any:
            return body(db)
    else:
        async def run(body: Callable[[Session], Any]) -> Any:
            return await run_db_txn_with_bind(db_bind, body)
    return run


def _ensure_task_not_baselined(task: SddTask) -> None:
    if task.status == TaskStatus.BASELINED:
        raise TaskSessionControlError(BASELINED_LOCKED_MSG, status_code=403)


def _assert_no_preparing_submission(db: Session, task_id: str) -> None:
    from app.domains.task.services.chat_submission_service import (
        SubmissionError,
        assert_no_preparing_submission,
    )

    try:
        assert_no_preparing_submission(db, task_id)
    except SubmissionError as exc:
        raise TaskSessionControlError(str(exc), status_code=409) from exc


def build_session_prompt(task: SddTask, requested_prompt: Optional[str]) -> Dict[str, str]:
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
    requested_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """启动前守卫 + 首条 prompt 组装（单事务，调用方已持有任务锁）。"""
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise TaskSessionControlError("Task not found", status_code=404)
    _assert_no_preparing_submission(db, task_id)
    _ensure_task_not_baselined(task)
    if task.status == TaskStatus.PROVISIONING:
        raise TaskSessionControlError(TASK_PROVISIONING_MSG, status_code=409)
    if task.status == TaskStatus.CODING:
        raise TaskSessionControlError(TASK_RUNNING_MSG, status_code=409)
    if task.status == TaskStatus.INTERRUPTED:
        raise TaskSessionControlError(TASK_INTERRUPTED_MSG, status_code=409)
    if find_active_summary_job(db, task.id) is not None:
        raise TaskSessionControlError(
            "一键总结问题案例进行中，请等待完成或停止后再启动会话", status_code=409
        )
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
) -> Dict[str, Any]:
    """任务状态重置为 CODING，并创建首条消息 + 聊天作业（单事务，锁内调用）。"""
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise TaskSessionControlError("Task not found", status_code=404)
    _ensure_task_not_baselined(task)
    task.status = TaskStatus.CODING
    task.error_message = None
    task.session_id = None
    task.interrupt_reason = None
    task.interrupted_by_id = None
    task.interrupted_at = None

    initial_message = task_service.save_chat_message(
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
    )
    job = create_task_chat_job(
        db,
        workspace_id=ws_id,
        task_id=task.id,
        creator_id=creator_id,
        prompt_text=prompt,
        context_json={"source": "task_start", "fresh_session": True},
        chat_message_id=initial_message.id,
    )
    return {
        "task_id": task.id,
        "job_id": job.id,
        "job": serialize_job(job),
    }


async def start_task_session(
    db: Session,
    *,
    ws_id: str,
    task_id: str,
    actor_user_id: str,
    requested_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """启动全新任务会话（POST /start 业务编排；调用方已持有任务锁）。

    守卫检查 → 旧引擎收尾 → 状态重置 + 首条消息 + 聊天作业 → 入队执行。
    依赖 Session 只用于解析 bind（路由层已在等待锁前关闭它）。
    """
    run_txn = _bind_txn_runner(db, _session_bind(db))
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
        )
    )
    await ai_job_publishing.enqueue_task_chat_job(result["job_id"])
    return {"msg": "Task started", "task_id": result["task_id"], "job": result["job"]}


def _initialize_has_active_jobs_sync(db: Session, *, task_id: str) -> bool:
    """Cancellation is a request, not proof that the old attempt has exited."""
    from app.domains.task.services.chat_submission_service import BLOCKING

    return db.query(SddAiJob.id).filter(
        SddAiJob.task_id == task_id,
        SddAiJob.channel == AiJobChannel.TASK_CHAT,
        SddAiJob.status.in_(BLOCKING),
    ).first() is not None


def prepare_initialize_sync(db: Session, *, ws_id: str, task_id: str) -> Dict[str, Any]:
    """重新初始化前置守卫 + 取消在途聊天作业（单事务，锁内调用）。"""
    task = task_service.get_task(db, task_id, ws_id)
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
    cancelled_job_ids = ai_job_attempts.mark_task_chat_jobs_cancelled(
        db,
        workspace_id=ws_id,
        task_id=task_id,
        message="Task initialized with a fresh session",
    )
    return {"task_id": task.id, "cancelled_job_ids": cancelled_job_ids}


def apply_initialize_sync(
    db: Session,
    *,
    ws_id: str,
    task_id: str,
    skill_ids: Optional[list[str]],
    keep_deleted_runtime_skills: bool,
    requested_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """替换 Skills、推进 session_generation、重置状态并组装首条 prompt（单事务，锁内调用）。"""
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise TaskSessionControlError("Task not found", status_code=404)
    _ensure_task_not_baselined(task)
    # Cancellation is a request, not proof that the old attempt has exited.
    # Check before clearing the session or advancing its generation.
    if _initialize_has_active_jobs_sync(db, task_id=task_id):
        raise TaskSessionControlError(
            "旧任务执行尚未清理完成，请稍后重试初始化；无需删除任务。", status_code=409
        )
    if skill_ids is not None:
        task_service.replace_task_skills_for_initialize(
            db,
            task,
            workspace_id=ws_id,
            skill_ids=skill_ids,
            keep_deleted_runtime_skills=keep_deleted_runtime_skills,
        )
    task.retry_count = int(task.retry_count or 0) + 1
    task.session_generation = int(getattr(task, "session_generation", 0) or 0) + 1
    task.status = TaskStatus.CODING
    task.error_message = None
    task.session_id = None
    task.interrupt_reason = None
    task.interrupted_by_id = None
    task.interrupted_at = None
    db.commit()
    prompts = build_session_prompt(task, requested_prompt)
    return {"task_id": task.id, **prompts}


def _serialize_job_by_id_sync(db: Session, job_id: str) -> Optional[Dict[str, Any]]:
    job = db.get(SddAiJob, job_id)
    return serialize_job(job) if job else None


async def initialize_task_session(
    db: Session,
    *,
    ws_id: str,
    task_id: str,
    actor_user_id: str,
    skill_ids: Optional[list[str]] = None,
    keep_deleted_runtime_skills: bool = True,
    requested_prompt: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """重新初始化任务会话（POST /initialize 业务编排；调用方已持有任务锁）。

    取消在途作业并广播 → 停旧引擎 → 恢复 attempt → 换装 Skills / 推进代际
    → 落 init_reason 消息 → 创建新会话 turn → 入队执行。
    """
    run_txn = _bind_txn_runner(db, _session_bind(db))
    prepared = await run_txn(
        lambda session: prepare_initialize_sync(session, ws_id=ws_id, task_id=task_id)
    )
    engine = get_engine(task_id)
    if engine:
        try:
            await engine.stop()
        except Exception as exc:
            logger.exception("Failed to stop old engine before initialization: task_id={}", task_id)
            raise TaskSessionControlError(
                "旧引擎尚未停止，请稍后重试初始化；原会话已保留。", status_code=409
            ) from exc
    for old_job_id in prepared["cancelled_job_ids"]:
        await ai_job_publishing.publish_job(old_job_id)

    from app.domains.task.services.task_attempt_recovery_service import recover_task_attempts

    await recover_task_attempts(task_id, run_txn=run_txn, wait_for_running=True)

    try:
        state = await run_txn(
            lambda session: apply_initialize_sync(
                session,
                ws_id=ws_id,
                task_id=task_id,
                skill_ids=skill_ids,
                keep_deleted_runtime_skills=keep_deleted_runtime_skills,
                requested_prompt=requested_prompt,
            )
        )
    except ValueError as exc:
        raise TaskSessionControlError(str(exc), status_code=int(getattr(exc, "status_code", 400))) from exc

    init_reason_text = str(reason or "").strip()
    # 同步落库 off-loop（线程内自建 session，含通知生成）
    await run_txn(
        lambda session: task_service.save_chat_message(
            session,
            task_id,
            ws_id,
            actor_user_id,
            role="system",
            content=init_reason_text,
            message_type="init_reason",
        )
    )
    created = await task_session_service.create_task_chat_turn(
        task_id=task_id,
        actor_user_id=actor_user_id,
        content=state["user_display"],
        prompt_text=state["prompt"],
        context_json={
            "source": "task_initialize",
            "fresh_session": True,
            "initialize_reason": init_reason_text,
        },
        fresh_session=True,
        skip_checkpoint=True,
    )
    await ai_job_publishing.enqueue_task_chat_job(created.job_id)
    job_payload = await run_txn(
        lambda session: _serialize_job_by_id_sync(session, created.job_id)
    )
    return {"msg": "Task initialized", "job": job_payload}
