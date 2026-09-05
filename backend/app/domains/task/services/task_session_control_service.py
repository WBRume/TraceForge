"""Task AI session interrupt/resume orchestration."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.engine.workflow_engine import WorkflowEngine, get_engine
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.task.models.chat import ChatMessage, MessageRole, MessageType
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.ai.schemas.websocket import WSMessage
from app.domains.ai.services import ai_job_service
from app.domains.task.services import context_token_service
from app.core.offload import run_db_txn
from app.domains.websocket.ws.manager import manager as task_ws_manager


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


def _find_running_task_job(db: Session, task_id: str, engine: WorkflowEngine) -> Optional[SddAiJob]:
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
            SddAiJob.status.in_([AiJobStatus.PENDING, AiJobStatus.RUNNING, AiJobStatus.WAITING_HITL]),
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


async def interrupt_task(
    db: Session,
    *,
    task: SddTask,
    actor_user_id: str,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    engine = get_engine(task.id)
    if engine and engine.running:
        job = _find_running_task_job(db, task.id, engine)
        if not job:
            raise TaskSessionControlError("No running AI job to interrupt", status_code=409)

        now = datetime.utcnow()
        reason_text = str(reason or "User temporarily interrupted the AI session").strip()
        session_id = str(engine.session_id or job.session_id or task.session_id or "").strip() or None

        task.status = TaskStatus.INTERRUPTED
        task.session_id = session_id
        task.error_message = None
        task.interrupt_reason = reason_text
        task.interrupted_by_id = actor_user_id
        task.interrupted_at = now

        job.status = AiJobStatus.INTERRUPTED
        job.message = "AI session interrupted by user"
        job.error_message = None
        job.session_id = session_id
        job.interrupt_reason = reason_text
        job.interrupted_by_id = actor_user_id
        job.interrupted_at = now
        job.finished_at = now
        job.context_json = _merge_json(
            job.context_json,
            {
                "interrupted": True,
                "interrupted_at": now.isoformat() + "Z",
                "interrupted_by_id": actor_user_id,
            },
        )
        db.commit()
        db.refresh(task)
        db.refresh(job)

        await engine.interrupt()
        db.refresh(task)
        db.refresh(job)

        await ai_job_service.publish_job(job.id, final=False)
        job_payload = ai_job_service.serialize_job(job)
        await _broadcast_task_event("task_interrupted", task, job_payload)
        return _task_payload(task, job_payload)

    # 没有 running engine：可能是任务还在排队/刚结束，前端把停止按钮置为可点。
    # 此时不再报“No running Claude CLI session”，而是取消尚未真正启动的 AI job，
    # 让前端可以正确回刷运行状态。
    active_job = _find_active_task_job(db, task.id)
    if not active_job:
        raise TaskSessionControlError(
            "No running Claude CLI session or active AI job to interrupt",
            status_code=409,
        )

    cancelled_ids = ai_job_service.mark_task_chat_jobs_cancelled(
        db,
        workspace_id=task.workspace_id,
        task_id=task.id,
        message=str(reason or "Task execution stopped before Claude session started").strip(),
    )
    if not cancelled_ids:
        raise TaskSessionControlError(
            "No active AI job to interrupt",
            status_code=409,
        )

    db.refresh(active_job)
    for job_id in cancelled_ids:
        await ai_job_service.publish_job(job_id, final=True)
    job_payload = ai_job_service.serialize_job(active_job)
    await _broadcast_task_event("task_interrupted", task, job_payload)
    return _task_payload(task, job_payload)


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
                        return {"duplicate_payload": _task_payload(task, ai_job_service.serialize_job(existing))}

        task = db.query(SddTask).filter(SddTask.id == task_id).first()
        if task is None:
            raise TaskSessionControlError("Task not found", status_code=404)
        if task.status != TaskStatus.INTERRUPTED:
            raise TaskSessionControlError("Only interrupted tasks can be resumed", status_code=409)

        # 会话/总结互斥：总结进行中禁止恢复会话
        if ai_job_service.find_active_summary_job(db, task_id) is not None:
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
        if not session_id:
            raise TaskSessionControlError("Interrupted task has no Claude session id to resume", status_code=409)

        return {
            "duplicate_payload": None,
            "task_status": _as_text(task.status),
            "interrupt_reason": task.interrupt_reason,
            "interrupted_by_id": task.interrupted_by_id,
            "interrupted_at": task.interrupted_at.isoformat() if task.interrupted_at else None,
            "old_job_id": str(job.id),
            "session_id": session_id,
            "prompt_text": prompt_text,
        }

    prepared = await run_db_txn(_prepare_resume_sync)
    if prepared.get("duplicate_payload") is not None:
        return prepared["duplicate_payload"]

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
        job_payload = ai_job_service.serialize_job(resume_job) if resume_job is not None else {}
        task_payload = _task_payload(task, job_payload)
        return {"task_payload": task_payload, "job_payload": job_payload}

    finalized = await run_db_txn(_finalize_resume_sync)

    await ai_job_service.publish_job(prepared["old_job_id"], final=True)
    await task_ws_manager.send_message_to_room(
        task_id,
        WSMessage(type="task_resumed", payload=finalized["task_payload"]),
    )
    await ai_job_service.enqueue_task_chat_job(created.job_id)
    return finalized["task_payload"]
