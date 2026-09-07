"""
Unified AI async job orchestration service.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import socket
import time
import uuid
import inspect
from contextlib import ExitStack
from datetime import datetime
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.core.distributed_lock import LockAcquireTimeout, lock_ai_queue
from app.core.logging import bind_ai_context, bind_task_context, get_logger
from app.core.offload import run_db, run_db_txn
from app.database import SessionLocal
from app.engine.claude_bridge import create_cli_bridge
from app.agents.selection import (
    backend_supports_fork,
    create_legacy_bridge,
    fork_session_for_backend,
    resolve_task_backend,
    resolve_workspace_backend,
)
from app.engine.workflow_engine import WorkflowEngine, get_engine
from app.agents import (
    AgentAttemptContext,
    AgentProcessIdentity,
    bind_agent_attempt,
    current_agent_attempt,
    reset_agent_attempt,
)
from app.agents.process_supervisor import process_supervisor
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.asset.models.asset import (
    AssetThreadMessageRole,
    SddAssetResolutionProposal,
    SddAssetThread,
    SddAssetThreadMessage,
    SddAssetVersion,
)
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.models.task_cli_bootstrap import SddTaskCliBootstrap, TaskCliBootstrapStatus
from app.domains.ai.schemas.websocket import WSMessage
from app.domains.asset.services import asset_discussion_service, asset_resolution_service
from app.domains.task.services import context_token_service, task_cli_state_service
from app.domains.task.services import diagnosis_result_service
from app.domains.task.services.ai_context_service import (
    build_asset_thread_prompt,
    build_resolution_proposal_prompt,
    build_resolution_rewrite_prompt,
)
from app.domains.asset.ws.asset_discussion_manager import asset_discussion_ws_manager
from app.domains.websocket.ws.manager import manager as task_ws_manager

logger = get_logger(__name__, category="ai_session")


ACTIVE_STATUSES = {
    AiJobStatus.PENDING,
    AiJobStatus.RUNNING,
    AiJobStatus.WAITING_HITL,
    AiJobStatus.INTERRUPTED,
    AiJobStatus.TERMINATING,
    AiJobStatus.ORPHANED,
}
FINAL_STATUSES = {AiJobStatus.SUCCESS, AiJobStatus.FAILED, AiJobStatus.CANCELLED, AiJobStatus.REVERTED}
BLOCKING_STATUSES = {
    AiJobStatus.RUNNING,
    AiJobStatus.WAITING_HITL,
    AiJobStatus.INTERRUPTED,
    AiJobStatus.TERMINATING,
    AiJobStatus.ORPHANED,
}
ACTIVE_GUARD_STATUSES = {AiJobStatus.PENDING, *BLOCKING_STATUSES}
SESSION_GUARD_STATUSES = {
    AiJobStatus.PENDING,
    AiJobStatus.RUNNING,
    AiJobStatus.WAITING_HITL,
    AiJobStatus.TERMINATING,
    AiJobStatus.ORPHANED,
}
TASK_QUEUE_PAUSED_STATUSES = {TaskStatus.INTERRUPTED, TaskStatus.FAILED}
JOB_KIND_THREAD_AI_REPLY = "THREAD_AI_REPLY"
JOB_KIND_RESOLUTION_PROPOSAL = "RESOLUTION_PROPOSAL"
JOB_KIND_RESOLUTION_REWRITE = "RESOLUTION_REWRITE"
JOB_KIND_DIAGNOSIS_SUMMARY = "DIAGNOSIS_SUMMARY"
JOB_KIND_TASK_BASELINE = "TASK_BASELINE"

_QUEUE_LOCKS: Dict[str, asyncio.Lock] = {}
_QUEUE_RUNNERS: Dict[str, asyncio.Task] = {}
_JOB_CANCEL_EVENTS: Dict[str, asyncio.Event] = {}
_JOB_HEARTBEAT_TASKS: Dict[str, asyncio.Task] = {}
_REAPER_TASK: Optional[asyncio.Task] = None
_DISPATCHER_TASK: Optional[asyncio.Task] = None
_SHUTTING_DOWN = False
_RUNTIME_WORKER_HEALTH: Dict[str, Dict[str, Any]] = {}
WORKER_BOOT_ID = str(uuid.uuid4())
WORKER_ID = (
    f"{socket.gethostname()}:{getattr(settings, 'WORKER_SERVICE_NAME', 'traceforge-api')}"
    f":{getattr(settings, 'WORKER_INDEX', '0')}"
)

# A productive turn can legitimately run longer than ten minutes now.  Stale
# cleanup must never race the hard runtime watchdog and mark a live job failed.
_RUNNING_STALE_MINUTES = max(
    10,
    int(getattr(settings, "AGENT_MAX_RUNTIME_SECONDS", 7200) or 7200) // 60 + 5,
)

_TIMEOUT_TEXT_MARKERS = (
    "request timed out",
    "timed out",
    "timeout",
    "etimedout",
    "network timeout",
    "连接超时",
    "请求超时",
)


class AiJobConflictError(Exception):
    """AI 任务状态冲突（会话/总结互斥等）。由调用方转换为 409 或用户可读错误。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AgentAttemptFencedError(RuntimeError):
    """Raised when a late attempt is no longer allowed to write business data."""


def _attempt_is_current_sync(
    db: Session,
    *,
    job_id: str,
    run_token: Optional[str],
    allow_waiting_hitl: bool = False,
) -> bool:
    """Check the durable attempt fence inside the same DB transaction as a write."""
    if not run_token:
        return True
    job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
    if not job:
        return False
    allowed_statuses = {AiJobStatus.RUNNING}
    if allow_waiting_hitl:
        allowed_statuses.add(AiJobStatus.WAITING_HITL)
    return bool(
        job.status in allowed_statuses
        and str(job.run_token or "") == str(run_token)
        and str(job.worker_boot_id or "") == WORKER_BOOT_ID
        and job.cancel_requested_at is None
    )


def _queue_key_for_task(task_id: str) -> str:
    return f"TASK_CHAT:{task_id}"


def _queue_key_for_thread(thread_id: str) -> str:
    return f"ASSET_THREAD:{thread_id}"


def _queue_key_for_diagnosis_summary(task_id: str) -> str:
    # 总结与聊天各自独立队列：任务 INTERRUPTED/FAILED 时聊天队列会暂停、
    # INTERRUPTED 会话 job 也会阻塞取队，若共用队列「停止会话→一键总结」
    # 将永远无法执行。会话/总结的互斥不由队列保证，而由创建期守卫保证：
    # 所有会话/总结创建入口都会拒绝对方处于进行中（PENDING/RUNNING/WAITING_HITL），
    # 因此同一任务同一时刻最多只有一个非终态 AI job 在执行。
    return f"DIAGNOSIS_SUMMARY:{task_id}"


def _queue_key_for_task_baseline(task_id: str) -> str:
    return f"TASK_BASELINE:{task_id}"


def _get_queue_lock(queue_key: str) -> asyncio.Lock:
    lock = _QUEUE_LOCKS.get(queue_key)
    if lock is None:
        lock = asyncio.Lock()
        _QUEUE_LOCKS[queue_key] = lock
    return lock


def _reap_queue_runner(queue_key: str, task: "asyncio.Task") -> None:
    """Runner 结束后回收注册表条目（单事件循环内同步判定，无 await 夹缝）。

    仅当条目仍指向本 task 时摘除（避免误删后继 runner）；同 key 锁在无后继
    runner 且未被持有时一并回收。顺带消费未检视的异常避免告警噪音。
    """
    if _QUEUE_RUNNERS.get(queue_key) is not task:
        return
    _QUEUE_RUNNERS.pop(queue_key, None)
    if not task.cancelled():
        exc = task.exception()
        if exc is not None:
            logger.warning(f"AI queue runner exited with error: queue_key={queue_key}, error={exc}")
    lock = _QUEUE_LOCKS.get(queue_key)
    if lock is not None and not lock.locked():
        _QUEUE_LOCKS.pop(queue_key, None)


def _get_or_create_cancel_event(job_id: str) -> asyncio.Event:
    event = _JOB_CANCEL_EVENTS.get(job_id)
    if event is None:
        event = asyncio.Event()
        _JOB_CANCEL_EVENTS[job_id] = event
    return event


def _request_job_cancel(job_id: str) -> None:
    event = _get_or_create_cancel_event(job_id)
    event_loop = getattr(event, "_loop", None)
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None
    if event_loop is not None and event_loop.is_running() and event_loop is not current_loop:
        event_loop.call_soon_threadsafe(event.set)
    else:
        event.set()


def _is_cancel_requested(job_id: str) -> bool:
    event = _JOB_CANCEL_EVENTS.get(job_id)
    return bool(event and event.is_set())


def _clear_cancel_event(job_id: str) -> None:
    _JOB_CANCEL_EVENTS.pop(job_id, None)


def _is_job_cancelled_or_final_sync(job_id: str) -> bool:
    """DB 部分取消/终态检查（线程内执行，由 run_db 包装）。"""
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        return bool(
            job
            and (
                job.status in FINAL_STATUSES
                or job.status in {AiJobStatus.TERMINATING, AiJobStatus.ORPHANED}
                or job.cancel_requested_at is not None
            )
        )
    finally:
        db.close()


async def _is_job_cancelled_or_final(job_id: str) -> bool:
    """取消已请求，或 DB 中任务已进入终态（如被中断/停止标记为 CANCELLED）。"""
    if _is_cancel_requested(job_id):
        return True
    return await run_db(_is_job_cancelled_or_final_sync, job_id)


def _as_status(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _looks_like_timeout_text(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    return any(marker in normalized for marker in _TIMEOUT_TEXT_MARKERS)


def _persist_process_identity_sync(
    job_id: str,
    run_token: str,
    identity: AgentProcessIdentity,
) -> bool:
    if not job_id or not run_token:
        return False
    db = SessionLocal()
    try:
        job = (
            db.query(SddAiJob)
            .filter(
                SddAiJob.id == job_id,
                SddAiJob.status == AiJobStatus.RUNNING,
                SddAiJob.run_token == run_token,
                SddAiJob.worker_boot_id == WORKER_BOOT_ID,
            )
            # Serialize the process-start attach with cancellation/finalizer
            # updates.  The status/run-token predicates are the attempt CAS;
            # the row lock prevents a late callback from attaching after the
            # attempt has been terminalized.
            .with_for_update()
            .first()
        )
        if job is None:
            db.rollback()
            return False
        job.process_pid = int(identity.pid)
        job.process_started_at = identity.started_at.replace(tzinfo=None)
        job.process_group_id = identity.process_group_id
        job.context_json = _merge_json(
            job.context_json,
            {
                "process_identity": {
                    "pid": identity.pid,
                    "started_at": identity.started_at.isoformat(),
                    "process_group_id": identity.process_group_id,
                    "containment_id": identity.containment_id,
                }
            },
        )
        db.commit()
        return True
    finally:
        db.close()


def _clear_process_ownership(job: SddAiJob) -> None:
    """Clear the live owner fence after complete process-tree death."""
    job.heartbeat_at = None
    job.lease_expires_at = None
    job.process_pid = None
    job.process_started_at = None
    job.process_group_id = None
    job.run_token = None
    job.worker_id = None
    job.worker_boot_id = None


def _has_active_process_ownership(job: SddAiJob) -> bool:
    """Whether the durable row still claims a locally attached process."""
    return job.process_pid is not None or job.process_group_id is not None


def _normalize_job_kind(value: Optional[str]) -> str:
    normalized = str(value or "").strip().upper()
    if normalized == JOB_KIND_TASK_BASELINE:
        return JOB_KIND_TASK_BASELINE
    if normalized == JOB_KIND_RESOLUTION_PROPOSAL:
        return JOB_KIND_RESOLUTION_PROPOSAL
    if normalized == JOB_KIND_RESOLUTION_REWRITE:
        return JOB_KIND_RESOLUTION_REWRITE
    return JOB_KIND_THREAD_AI_REPLY


def _job_kind_from_job(job: SddAiJob) -> str:
    context = job.context_json if isinstance(job.context_json, dict) else {}
    return _normalize_job_kind(str(context.get("job_kind") or ""))


def _has_diagnosis_summary_job(db, task_id: str) -> bool:
    """任务是否发起过「一键总结问题案例」任务（含进行中/成功/失败历史）。"""
    jobs = (
        db.query(SddAiJob)
        .filter(
            SddAiJob.task_id == task_id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
        )
        .all()
    )
    for job in jobs:
        if _job_kind_of(job) == JOB_KIND_DIAGNOSIS_SUMMARY:
            return True
    return False


def _job_kind_of(job: SddAiJob) -> str:
    context = job.context_json if isinstance(job.context_json, dict) else {}
    return str(context.get("job_kind") or "").strip().upper()


def find_active_summary_job(db, task_id: str) -> Optional[SddAiJob]:
    """进行中的一键总结任务（PENDING/RUNNING）。"""
    jobs = (
        db.query(SddAiJob)
        .filter(
            SddAiJob.task_id == task_id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
            SddAiJob.status.in_([status.value for status in SESSION_GUARD_STATUSES]),
        )
        .order_by(SddAiJob.created_at.desc())
        .all()
    )
    for job in jobs:
        if _job_kind_of(job) == JOB_KIND_DIAGNOSIS_SUMMARY:
            return job
    return None


def find_active_chat_job(db, task_id: str) -> Optional[SddAiJob]:
    """进行中的聊天任务（PENDING/RUNNING/WAITING_HITL；WAITING_HITL 视为会话进行中）。"""
    jobs = (
        db.query(SddAiJob)
        .filter(
            SddAiJob.task_id == task_id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
            SddAiJob.status.in_([status.value for status in SESSION_GUARD_STATUSES]),
        )
        .order_by(SddAiJob.created_at.desc())
        .all()
    )
    for job in jobs:
        if _job_kind_of(job) != JOB_KIND_DIAGNOSIS_SUMMARY:
            return job
    return None


def serialize_job(job: SddAiJob) -> Dict[str, Any]:
    return {
        "id": job.id,
        "workspace_id": job.workspace_id,
        "task_id": job.task_id,
        "asset_id": job.asset_id,
        "thread_id": job.thread_id,
        "channel": _as_status(job.channel),
        "queue_key": job.queue_key,
        "status": _as_status(job.status),
        "progress": int(job.progress or 0),
        "message": job.message,
        "prompt_text": job.prompt_text,
        "context_json": job.context_json if isinstance(job.context_json, dict) else {},
        "result_json": job.result_json if isinstance(job.result_json, dict) else {},
        "error_message": job.error_message,
        "session_id": job.session_id,
        "session_turn_id": job.session_turn_id,
        "session_generation": job.session_generation,
        "session_revision": job.session_revision,
        "interrupt_reason": job.interrupt_reason,
        "interrupted_by_id": job.interrupted_by_id,
        "interrupted_at": job.interrupted_at.isoformat() if job.interrupted_at else None,
        "creator_id": job.creator_id,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "attempt_count": int(job.attempt_count or 0),
        "max_attempts": int(job.max_attempts or 1),
        "run_token": job.run_token,
        "worker_id": job.worker_id,
        "worker_boot_id": job.worker_boot_id,
        "heartbeat_at": job.heartbeat_at.isoformat() if job.heartbeat_at else None,
        "lease_expires_at": job.lease_expires_at.isoformat() if job.lease_expires_at else None,
        "cancel_requested_at": job.cancel_requested_at.isoformat() if job.cancel_requested_at else None,
        "process_pid": job.process_pid,
        "process_started_at": job.process_started_at.isoformat() if job.process_started_at else None,
        "process_group_id": job.process_group_id,
        "termination_attempts": int(job.termination_attempts or 0),
        "failure_code": job.failure_code,
        "terminal_reason": job.terminal_reason,
        "orphaned_at": job.orphaned_at.isoformat() if job.orphaned_at else None,
        "first_failure_at": job.first_failure_at.isoformat() if job.first_failure_at else None,
        "last_reap_attempt_at": job.last_reap_attempt_at.isoformat() if job.last_reap_attempt_at else None,
        "last_reap_verified_at": job.last_reap_verified_at.isoformat() if job.last_reap_verified_at else None,
        "next_reap_at": job.next_reap_at.isoformat() if job.next_reap_at else None,
        "reap_failure_count": int(job.reap_failure_count or 0),
        "last_reap_error": job.last_reap_error,
        "manual_intervention_required": bool(job.manual_intervention_required),
        "manual_intervention_operator_id": job.manual_intervention_operator_id,
        "manual_intervention_reason": job.manual_intervention_reason,
        "manual_intervention_evidence": job.manual_intervention_evidence,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def _merge_json(original: Any, patch: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(original) if isinstance(original, dict) else {}
    if patch:
        merged.update(patch)
    return merged


async def _broadcast_job_payload(payload: Dict[str, Any], *, final: bool = False) -> None:
    channel = str(payload.get("channel") or "")
    if channel == AiJobChannel.ASSET_THREAD.value:
        asset_id = str(payload.get("asset_id") or "")
        if not asset_id:
            return
        await asset_discussion_ws_manager.broadcast(
            asset_id,
            {
                "type": "ai_job_update",
                "asset_id": asset_id,
                "thread_id": payload.get("thread_id"),
                "job": payload,
            },
        )
        if final:
            status = str(payload.get("status") or "")
            done_type = "ai_job_done" if status == AiJobStatus.SUCCESS.value else "ai_job_failed"
            await asset_discussion_ws_manager.broadcast(
                asset_id,
                {
                    "type": done_type,
                    "asset_id": asset_id,
                    "thread_id": payload.get("thread_id"),
                    "job": payload,
                    "error": payload.get("error_message"),
                },
            )
        return

    if channel == AiJobChannel.TASK_CHAT.value:
        task_id = str(payload.get("task_id") or "")
        if not task_id:
            return
        await task_ws_manager.send_message_to_room(
            task_id,
            WSMessage(
                type="chat_job_update",
                payload={"task_id": task_id, "job": payload},
            ),
        )
        if final:
            status = str(payload.get("status") or "")
            done_type = "chat_job_done" if status == AiJobStatus.SUCCESS.value else "chat_job_failed"
            await task_ws_manager.send_message_to_room(
                task_id,
                WSMessage(
                    type=done_type,
                    payload={
                        "task_id": task_id,
                        "job": payload,
                        "error": payload.get("error_message"),
                    },
                ),
            )


def _load_job_payload_sync(job_id: str) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job:
            return None
        return serialize_job(job)
    finally:
        db.close()


async def _load_job_payload(job_id: str) -> Optional[Dict[str, Any]]:
    return await run_db(_load_job_payload_sync, job_id)


async def _publish_job_state(job_id: str, *, final: bool = False) -> None:
    payload = await _load_job_payload(job_id)
    if not payload:
        return
    await _broadcast_job_payload(payload, final=final)


def _update_job_state_sync(
    job_id: str,
    *,
    status: Optional[AiJobStatus] = None,
    progress: Optional[int] = None,
    message: Optional[str] = None,
    context_patch: Optional[Dict[str, Any]] = None,
    result_patch: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
    session_id: Optional[str] = None,
    agent_backend: Optional[str] = None,
    finalize: bool = False,
    run_token: Optional[str] = None,
    termination_confirmed_dead: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """状态更新 DB 段（线程内执行，由 run_db 包装）。

    返回 {"payload": ..., "broadcast": bool, "is_final": bool}；
    broadcast=False 表示被 fence/终态幂等拦下，仅回读当前 payload。
    """
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job:
            return None
        if run_token:
            if (
                str(job.run_token or "") != str(run_token)
                or str(job.worker_boot_id or "") != WORKER_BOOT_ID
                or job.status in FINAL_STATUSES
                or job.status in {AiJobStatus.TERMINATING, AiJobStatus.ORPHANED}
                or job.cancel_requested_at is not None
            ):
                return {"payload": serialize_job(job), "broadcast": False, "is_final": False}
        if job.channel == AiJobChannel.TASK_CHAT and job.task_id and job.session_revision is not None:
            task = db.query(SddTask).filter(SddTask.id == job.task_id).first()
            if not task or int(task.session_revision or -1) != int(job.session_revision):
                # An undo or a newer session generation has fenced this worker.
                # Do not let a late callback resurrect the old job state.
                return {"payload": serialize_job(job), "broadcast": False, "is_final": False}
        if (
            _has_active_process_ownership(job)
            and (finalize or status in FINAL_STATUSES)
            and termination_confirmed_dead is not True
        ):
            job.status = AiJobStatus.ORPHANED
            job.message = "Agent process could not be confirmed dead"
            job.error_message = "Agent process tree remained alive after finalization"
            job.failure_code = "PROCESS_TREE_STILL_ALIVE"
            job.terminal_reason = "PROCESS_TREE_STILL_ALIVE"
            job.lease_expires_at = datetime.utcnow()
            job.orphaned_at = job.orphaned_at or datetime.utcnow()
            db.commit()
            db.refresh(job)
            return {"payload": serialize_job(job), "broadcast": True, "is_final": False}
        current_status = job.status
        requested_status = status
        if current_status in FINAL_STATUSES:
            if requested_status is None or requested_status != current_status:
                return {"payload": serialize_job(job), "broadcast": False, "is_final": False}
        if status is not None:
            job.status = status
        if progress is not None:
            job.progress = max(0, min(100, int(progress)))
        if message is not None:
            job.message = message
        if context_patch:
            job.context_json = _merge_json(job.context_json, context_patch)
        if result_patch:
            job.result_json = _merge_json(job.result_json, result_patch)
        if error_message is not None:
            job.error_message = error_message
        if session_id is not None:
            job.session_id = session_id
        if agent_backend is not None:
            job.agent_backend = agent_backend
        if status == AiJobStatus.RUNNING and job.started_at is None:
            job.started_at = datetime.utcnow()
        if finalize or (status in FINAL_STATUSES):
            job.finished_at = datetime.utcnow()
        if status in FINAL_STATUSES:
            _clear_process_ownership(job)
        db.commit()
        db.refresh(job)
        payload = serialize_job(job)
        is_final = finalize or (status in FINAL_STATUSES)
        return {"payload": payload, "broadcast": True, "is_final": is_final}
    finally:
        db.close()


async def _update_job_state(
    job_id: str,
    *,
    status: Optional[AiJobStatus] = None,
    progress: Optional[int] = None,
    message: Optional[str] = None,
    context_patch: Optional[Dict[str, Any]] = None,
    result_patch: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
    session_id: Optional[str] = None,
    agent_backend: Optional[str] = None,
    finalize: bool = False,
    run_token: Optional[str] = None,
    termination_confirmed_dead: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    attempt = current_agent_attempt()
    effective_run_token = run_token or (attempt.run_token if attempt else None)
    result = await run_db(
        _update_job_state_sync,
        job_id,
        status=status,
        progress=progress,
        message=message,
        context_patch=context_patch,
        result_patch=result_patch,
        error_message=error_message,
        session_id=session_id,
        agent_backend=agent_backend,
        finalize=finalize,
        run_token=effective_run_token,
        termination_confirmed_dead=termination_confirmed_dead,
    )
    if result is None:
        return None
    payload = result["payload"]
    if not result["broadcast"]:
        return payload
    is_final = result["is_final"]
    await _broadcast_job_payload(payload, final=is_final)
    if is_final:
        _clear_cancel_event(job_id)
        queue_key = str(payload.get("queue_key") or "")
        if queue_key:
            schedule_queue(queue_key)
    return payload


def list_thread_jobs(
    db: Session,
    *,
    thread_id: str,
    active_only: bool = True,
) -> List[SddAiJob]:
    _cleanup_stale_running_jobs(db, thread_id=thread_id)
    query = db.query(SddAiJob).filter(
        SddAiJob.thread_id == thread_id,
        SddAiJob.channel == AiJobChannel.ASSET_THREAD,
    )
    if active_only:
        query = query.filter(SddAiJob.status.in_(list(ACTIVE_STATUSES)))
    return query.order_by(SddAiJob.created_at.desc()).all()


def list_task_jobs(
    db: Session,
    *,
    task_id: str,
    active_only: bool = True,
) -> List[SddAiJob]:
    _cleanup_stale_running_jobs(db, task_id=task_id)
    query = db.query(SddAiJob).filter(
        SddAiJob.task_id == task_id,
        SddAiJob.channel == AiJobChannel.TASK_CHAT,
    )
    if active_only:
        query = query.filter(SddAiJob.status.in_(list(ACTIVE_STATUSES)))
    return query.order_by(SddAiJob.created_at.desc()).all()


def get_job(db: Session, *, job_id: str) -> Optional[SddAiJob]:
    return db.query(SddAiJob).filter(SddAiJob.id == job_id).first()


def _cleanup_stale_running_jobs(
    db: Session,
    *,
    thread_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> None:
    cutoff = datetime.utcnow() - timedelta(minutes=_RUNNING_STALE_MINUTES)
    query = db.query(SddAiJob).filter(
        SddAiJob.status == AiJobStatus.RUNNING,
    )
    if thread_id:
        query = query.filter(
            SddAiJob.thread_id == thread_id,
            SddAiJob.channel == AiJobChannel.ASSET_THREAD,
        )
    if task_id:
        query = query.filter(
            SddAiJob.task_id == task_id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
        )
    jobs = query.all()
    dirty = False
    for job in jobs:
        # Lease-owned attempts are handled by the independent reaper, which
        # first verifies/terminates the process tree.  Query-time cleanup must
        # not forge a terminal state while a CLI may still be alive.
        if job.run_token or job.lease_expires_at:
            continue
        heartbeat = job.updated_at or job.started_at or job.created_at
        if heartbeat and heartbeat >= cutoff:
            continue
        job_context = job.context_json if isinstance(job.context_json, dict) else {}
        if (
            job.channel == AiJobChannel.TASK_CHAT
            and job.task_id
            and str(job_context.get("job_kind") or "").strip().upper() != JOB_KIND_DIAGNOSIS_SUMMARY
        ):
            task = db.query(SddTask).filter(SddTask.id == job.task_id).first()
            _apply_task_chat_job_interrupted(
                db,
                job,
                task,
                "AI job was interrupted unexpectedly (restart/crash). Please retry.",
                message="Job interrupted unexpectedly",
            )
        else:
            job.status = AiJobStatus.FAILED
            job.progress = 100
            job.message = "Job interrupted unexpectedly"
            job.error_message = "AI job was interrupted unexpectedly (restart/crash). Please retry."
            job.finished_at = datetime.utcnow()
            _clear_cancel_event(job.id)
        dirty = True
    if dirty:
        db.commit()


def create_asset_thread_job(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    asset_id: str,
    thread_id: str,
    creator_id: str,
    prompt_text: Optional[str],
    job_kind: str = JOB_KIND_THREAD_AI_REPLY,
    context_json: Optional[Dict[str, Any]] = None,
) -> SddAiJob:
    normalized_kind = _normalize_job_kind(job_kind)
    payload_context = {
        "job_kind": normalized_kind,
    }
    if isinstance(context_json, dict):
        payload_context.update(context_json)
    job = SddAiJob(
        workspace_id=workspace_id,
        task_id=task_id,
        asset_id=asset_id,
        thread_id=thread_id,
        channel=AiJobChannel.ASSET_THREAD,
        queue_key=_queue_key_for_thread(thread_id),
        status=AiJobStatus.PENDING,
        progress=0,
        message="Job queued",
        prompt_text=(prompt_text or "").strip() or None,
        context_json=payload_context,
        creator_id=creator_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def create_task_chat_job(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    creator_id: str,
    prompt_text: str,
    context_json: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
    chat_message_id: Optional[str] = None,
    session_turn_id: Optional[str] = None,
    session_generation: Optional[int] = None,
    session_revision: Optional[int] = None,
) -> SddAiJob:
    payload_context = {"source": "task_chat"}
    if isinstance(context_json, dict):
        payload_context.update(context_json)
    job = SddAiJob(
        workspace_id=workspace_id,
        task_id=task_id,
        asset_id=None,
        thread_id=None,
        channel=AiJobChannel.TASK_CHAT,
        queue_key=_queue_key_for_task(task_id),
        status=AiJobStatus.PENDING,
        progress=0,
        message="Job queued",
        prompt_text=(prompt_text or "").strip(),
        session_id=(str(session_id or "").strip() or None),
        creator_id=creator_id,
        context_json=payload_context,
        session_turn_id=session_turn_id,
        session_generation=session_generation,
        session_revision=session_revision,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        context_token_service.seed_snapshot_for_job(
            db,
            job=job,
            prompt_text=prompt_text,
            chat_message_id=chat_message_id,
        )
    except Exception as exc:
        logger.warning(f"Failed to seed context token snapshot for job {job.id}: {exc}")
    return job


def create_diagnosis_summary_job(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    creator_id: str,
) -> SddAiJob:
    """创建独立队列中的只读诊断总结任务。"""
    task = db.query(SddTask).filter(SddTask.id == task_id).first()
    source_session_id = str(getattr(task, "session_id", None) or "").strip()
    source_job_id: Optional[str] = None
    if not source_session_id:
        source_job = (
            db.query(SddAiJob)
            .filter(
                SddAiJob.task_id == task_id,
                SddAiJob.channel == AiJobChannel.TASK_CHAT,
                SddAiJob.session_id.isnot(None),
            )
            .order_by(SddAiJob.created_at.desc())
            .first()
        )
        if source_job:
            source_session_id = str(source_job.session_id or "").strip()
            source_job_id = source_job.id
    payload_context = {
        "source": "task_chat",
        "job_kind": JOB_KIND_DIAGNOSIS_SUMMARY,
        "source_session_id": source_session_id or None,
        "source_job_id": source_job_id,
        "summary_session_mode": "fork_read_only" if source_session_id else "transcript_fallback",
    }
    job = SddAiJob(
        workspace_id=workspace_id,
        task_id=task_id,
        asset_id=None,
        thread_id=None,
        channel=AiJobChannel.TASK_CHAT,
        queue_key=_queue_key_for_diagnosis_summary(task_id),
        status=AiJobStatus.PENDING,
        progress=0,
        message="一键总结问题案例已进入队列",
        prompt_text="[一键总结问题案例]",
        context_json=payload_context,
        creator_id=creator_id,
        session_id=source_session_id or None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def create_task_baseline_job(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    creator_id: str,
) -> SddAiJob:
    """Create/reuse the durable baseline job for the current spec revision."""
    record = (
        db.query(SddTaskCliBootstrap)
        .filter(
            SddTaskCliBootstrap.task_id == task_id,
            SddTaskCliBootstrap.workspace_id == workspace_id,
        )
        .first()
    )
    if not record:
        raise ValueError("Specification baseline is not initialized")
    queue_key = _queue_key_for_task_baseline(task_id)
    input_revision = str(record.spec_version_id or "missing")
    existing_jobs = (
        db.query(SddAiJob)
        .filter(SddAiJob.task_id == task_id, SddAiJob.queue_key == queue_key)
        .order_by(SddAiJob.created_at.desc())
        .all()
    )
    for existing in existing_jobs:
        context = existing.context_json if isinstance(existing.context_json, dict) else {}
        if str(context.get("input_revision") or "") != input_revision:
            continue
        baseline_active_statuses = {
            AiJobStatus.PENDING,
            AiJobStatus.RUNNING,
            AiJobStatus.WAITING_HITL,
            AiJobStatus.TERMINATING,
            AiJobStatus.ORPHANED,
        }
        if existing.status in baseline_active_statuses or existing.status == AiJobStatus.SUCCESS:
            return existing
        # A failed/cancelled attempt for the same immutable input revision is
        # safely reusable as a manual retry; do not create duplicate baselines.
        existing.status = AiJobStatus.PENDING
        existing.progress = 0
        existing.message = "Baseline build queued"
        existing.error_message = None
        existing.finished_at = None
        existing.run_token = None
        existing.worker_id = None
        existing.worker_boot_id = None
        existing.attempt_count = 0
        existing.context_json = {
            **context,
            "job_kind": JOB_KIND_TASK_BASELINE,
            "input_revision": input_revision,
        }
        db.commit()
        db.refresh(existing)
        return existing

    job = SddAiJob(
        workspace_id=workspace_id,
        task_id=task_id,
        channel=AiJobChannel.TASK_CHAT,
        queue_key=queue_key,
        status=AiJobStatus.PENDING,
        progress=0,
        message="Baseline build queued",
        prompt_text="[TASK_BASELINE]",
        context_json={
            "source": "task_specification",
            "job_kind": JOB_KIND_TASK_BASELINE,
            "input_revision": input_revision,
            "bootstrap_id": record.id,
        },
        creator_id=creator_id,
        max_attempts=1,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


async def enqueue_task_baseline_job(
    *,
    workspace_id: str,
    task_id: str,
    creator_id: str,
) -> Optional[Dict[str, Any]]:
    queue_key = _queue_key_for_task_baseline(task_id)
    # The durable row is the source of truth; the queue lock closes the
    # cross-process create/retry race before the database unique boundary is
    # reached, while the input revision in context makes the key explicit.
    async with lock_ai_queue(queue_key):
        job_id = await run_db_txn(
            lambda db: create_task_baseline_job(
                db,
                workspace_id=workspace_id,
                task_id=task_id,
                creator_id=creator_id,
            ).id
        )
    return await _enqueue_job(job_id, expected_channel=AiJobChannel.TASK_CHAT)


def _runtime_shutdown_in_progress() -> bool:
    """Return true only while shutdown is actively draining workers.

    After shutdown has fully completed, a new application lifecycle (or an
    isolated event loop in tests) may schedule a queue again.  The durable
    process itself is still protected because claims are blocked while the
    reaper/dispatcher workers are being drained.
    """
    return bool(_SHUTTING_DOWN and (_REAPER_TASK is not None or _DISPATCHER_TASK is not None))


def _runtime_worker_task(name: str) -> Optional[asyncio.Task]:
    return _REAPER_TASK if name == "reaper" else _DISPATCHER_TASK


def _set_runtime_worker_health(name: str, **updates: Any) -> None:
    state = _RUNTIME_WORKER_HEALTH.setdefault(name, {})
    state.update(updates)


def runtime_worker_health() -> Dict[str, Any]:
    """Return bounded readiness telemetry for the durable runtime loops."""
    threshold = max(1, int(getattr(settings, "AI_JOB_WORKER_FAILURE_ALERT_THRESHOLD", 3) or 3))
    result: Dict[str, Any] = {}
    overall = True
    for name in ("reaper", "dispatcher"):
        task = _runtime_worker_task(name)
        state = dict(_RUNTIME_WORKER_HEALTH.get(name, {}))
        alive = bool(task is not None and not task.done())
        failure_count = int(state.get("failure_count") or 0)
        healthy = alive and failure_count < threshold
        state.update({"alive": alive, "running": alive, "healthy": healthy})
        result[name] = state
        overall = overall and healthy
    result["healthy"] = overall
    return result


def _runtime_worker_done(name: str, task: asyncio.Task) -> None:
    if _runtime_worker_task(name) is not task:
        return
    if task.cancelled():
        _set_runtime_worker_health(name, state="cancelled", alive=False)
        return
    try:
        error = task.exception()
    except asyncio.CancelledError:
        error = None
    if error is not None:
        logger.error("AI runtime worker exited unexpectedly: name={}, error={}", name, error)
        _set_runtime_worker_health(
            name,
            state="exited",
            alive=False,
            running=False,
            last_error_at=datetime.utcnow().isoformat() + "Z",
            last_error_type=type(error).__name__,
            last_error=str(error)[:800],
            failure_count=int(_RUNTIME_WORKER_HEALTH.get(name, {}).get("failure_count") or 0) + 1,
            consecutive_failures=int(_RUNTIME_WORKER_HEALTH.get(name, {}).get("consecutive_failures") or 0) + 1,
        )
        try:
            loop = asyncio.get_running_loop()
            delay = min(
                max(1, int(getattr(settings, "AI_JOB_WORKER_MAX_BACKOFF_SECONDS", 60) or 60)),
                2 ** min(int(_RUNTIME_WORKER_HEALTH.get(name, {}).get("failure_count") or 1), 6),
            )
            loop.call_later(delay, _restart_runtime_worker, name, task)
        except RuntimeError:
            pass


def _restart_runtime_worker(name: str, previous: asyncio.Task) -> None:
    global _REAPER_TASK, _DISPATCHER_TASK
    if _SHUTTING_DOWN or _runtime_worker_task(name) is not previous:
        return
    task = asyncio.create_task(_reaper_loop() if name == "reaper" else _dispatcher_loop())
    if name == "reaper":
        _REAPER_TASK = task
    else:
        _DISPATCHER_TASK = task
    task.add_done_callback(lambda done: _runtime_worker_done(name, done))
    _set_runtime_worker_health(name, state="running", alive=True, restarted=True)


async def _run_runtime_worker_loop(name: str, operation: Callable[[], Any], interval: int) -> None:
    failures = 0
    _set_runtime_worker_health(name, state="starting", alive=True, running=True, failure_count=0, consecutive_failures=0)
    while not _SHUTTING_DOWN:
        started_at = datetime.utcnow()
        started_monotonic = time.monotonic()
        _set_runtime_worker_health(
            name,
            state="running",
            alive=True,
            running=True,
            last_started_at=started_at.isoformat() + "Z",
        )
        try:
            result = await operation()
            failures = 0
            duration_ms = max(0, int((time.monotonic() - started_monotonic) * 1000))
            _set_runtime_worker_health(
                name,
                state="healthy",
                alive=True,
                running=True,
                failure_count=0,
                consecutive_failures=0,
                last_success_at=datetime.utcnow().isoformat() + "Z",
                last_error=None,
                last_error_type=None,
                iteration_duration_ms=duration_ms,
                last_scan_count=int(result) if isinstance(result, int) else 0,
            )
            delay = max(1, interval)
        except asyncio.CancelledError:
            _set_runtime_worker_health(name, state="cancelled", alive=False, running=False)
            raise
        except Exception as exc:
            failures += 1
            duration_ms = max(0, int((time.monotonic() - started_monotonic) * 1000))
            _set_runtime_worker_health(
                name,
                state="degraded",
                alive=True,
                running=True,
                failure_count=failures,
                consecutive_failures=failures,
                last_error_at=datetime.utcnow().isoformat() + "Z",
                last_error_type=type(exc).__name__,
                last_error=str(exc)[:800],
                iteration_duration_ms=duration_ms,
            )
            logger.exception("AI runtime worker iteration failed: name={}, failure_count={}", name, failures)
            base = min(
                max(1, int(getattr(settings, "AI_JOB_WORKER_MAX_BACKOFF_SECONDS", 60) or 60)),
                max(1, interval) * (2 ** min(failures - 1, 6)),
            )
            jitter = random.uniform(
                0.0,
                max(0.0, float(getattr(settings, "AI_JOB_WORKER_JITTER_SECONDS", 0.5) or 0.5)),
            )
            delay = base + jitter
        await asyncio.sleep(delay)


def schedule_queue(queue_key: str) -> None:
    if _runtime_shutdown_in_progress():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    running = _QUEUE_RUNNERS.get(queue_key)
    if running and not running.done():
        return
    runner = loop.create_task(_run_queue(queue_key))
    _QUEUE_RUNNERS[queue_key] = runner
    runner.add_done_callback(lambda task: _reap_queue_runner(queue_key, task))


def _list_reclaimable_jobs_sync() -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        rows = (
            db.query(SddAiJob)
            .filter(
                SddAiJob.status.in_([
                    AiJobStatus.RUNNING,
                    AiJobStatus.TERMINATING,
                    AiJobStatus.ORPHANED,
                ]),
                SddAiJob.manual_intervention_required.isnot(True),
                (SddAiJob.next_reap_at.is_(None) | (SddAiJob.next_reap_at <= now)),
            )
            .all()
        )
        result: List[Dict[str, Any]] = []
        for job in rows:
            owner_gone = str(job.worker_boot_id or "") != WORKER_BOOT_ID
            lease_expired = bool(job.lease_expires_at and job.lease_expires_at <= now)
            if not owner_gone and not lease_expired:
                continue
            result.append(
                {
                    "job_id": str(job.id),
                    "run_token": str(job.run_token or ""),
                    "expected_run_token": str(job.run_token or "") or None,
                    "process_pid": job.process_pid,
                    "process_started_at": job.process_started_at,
                    "process_group_id": job.process_group_id,
                    "queue_key": str(job.queue_key or ""),
                    "reason": "WORKER_RESTART" if owner_gone else "LEASE_EXPIRED",
                    "attempt_count": int(job.attempt_count or 0),
                    "worker_boot_id": job.worker_boot_id,
                    "reap_failure_count": int(job.reap_failure_count or 0),
                }
            )
        return result
    finally:
        db.close()


def _adopt_reclaimable_job_sync(
    job_id: str,
    expected_run_token: Optional[str],
    adopted_run_token: str,
    reason: str,
) -> bool:
    db = SessionLocal()
    try:
        query = db.query(SddAiJob).filter(SddAiJob.id == job_id)
        query = query.filter(
            SddAiJob.run_token == expected_run_token
            if expected_run_token
            else SddAiJob.run_token.is_(None)
        )
        affected = (
            query.filter(
                SddAiJob.status.in_([
                    AiJobStatus.RUNNING,
                    AiJobStatus.TERMINATING,
                    AiJobStatus.ORPHANED,
                ]),
            )
            .update(
                {
                    SddAiJob.status: AiJobStatus.TERMINATING,
                    SddAiJob.worker_id: WORKER_ID,
                    SddAiJob.worker_boot_id: WORKER_BOOT_ID,
                    SddAiJob.run_token: adopted_run_token,
                    SddAiJob.termination_attempts: SddAiJob.termination_attempts + 1,
                    SddAiJob.terminal_reason: reason,
                    SddAiJob.failure_code: reason,
                    SddAiJob.last_reap_attempt_at: datetime.utcnow(),
                },
                synchronize_session=False,
            )
        )
        db.commit()
        return int(affected or 0) == 1
    finally:
        db.close()


async def reap_stale_jobs() -> int:
    """Reclaim attempts whose owner disappeared or whose lease expired."""
    rows = await run_db(_list_reclaimable_jobs_sync)
    reclaimed = 0
    for row in rows:
        token = row["run_token"] or str(uuid.uuid4())
        if not await run_db(
            _adopt_reclaimable_job_sync,
            row["job_id"],
            row.get("expected_run_token"),
            token,
            row["reason"],
        ):
            continue
        # A process owned by this worker can be found by run_token.  A process
        # from a previous boot is deliberately not guessed at: until PID
        # create-time/command verification succeeds it remains ORPHANED.
        result = await process_supervisor.stop_attempt(token, row["reason"])
        if result is None and row.get("process_pid"):
            result = await process_supervisor.stop_persisted(
                row["process_pid"],
                row.get("process_started_at"),
                row["reason"],
                process_group_id=row.get("process_group_id"),
            )
        # A previous boot without a persisted PID cannot prove that the
        # spawn window was empty.  Keep the queue blocked as ORPHANED rather
        # than manufacturing a terminal state from missing evidence.
        confirmed_dead = bool(result is not None and result.confirmed_dead)
        payload = await run_db(
            _finish_termination_sync,
            row["job_id"],
            token,
            confirmed_dead=confirmed_dead,
            reason=(result.error_message if result and result.error_message else row["reason"]),
            failure_code=(result.error_code if result and result.error_code else row["reason"]),
        )
        if payload:
            reclaimed += 1
            await _broadcast_job_payload(
                payload,
                final=str(payload.get("status")) in {s.value for s in FINAL_STATUSES},
            )
            if str(payload.get("status")) == AiJobStatus.PENDING.value:
                schedule_queue(str(payload.get("queue_key") or ""))
    return reclaimed


async def _reaper_loop() -> None:
    await _run_runtime_worker_loop(
        "reaper",
        reap_stale_jobs,
        max(1, int(getattr(settings, "AI_JOB_REAPER_INTERVAL_SECONDS", 10) or 10)),
    )


async def _dispatcher_loop() -> None:
    await _run_runtime_worker_loop(
        "dispatcher",
        recover_pending_queues,
        max(1, int(getattr(settings, "AI_JOB_DISPATCH_INTERVAL_SECONDS", 2) or 2)),
    )


async def start_runtime_workers() -> int:
    """Run recovery before readiness, then start independent durable workers."""
    global _REAPER_TASK, _DISPATCHER_TASK, _SHUTTING_DOWN
    _SHUTTING_DOWN = False
    already_running = bool(
        _REAPER_TASK is not None
        and not _REAPER_TASK.done()
        and _DISPATCHER_TASK is not None
        and not _DISPATCHER_TASK.done()
    )
    count = 0
    if not already_running:
        try:
            count = await recover_pending_queues()
            recovered_at = datetime.utcnow().isoformat() + "Z"
            for name in ("reaper", "dispatcher"):
                _set_runtime_worker_health(
                    name,
                    state="starting",
                    last_success_at=recovered_at,
                    last_error=None,
                    last_error_type=None,
                    failure_count=0,
                    consecutive_failures=0,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Initial AI runtime recovery failed")
            for name in ("reaper", "dispatcher"):
                _set_runtime_worker_health(
                    name,
                    state="degraded",
                    last_error_at=datetime.utcnow().isoformat() + "Z",
                    last_error_type=type(exc).__name__,
                    last_error=str(exc)[:800],
                    failure_count=1,
                    consecutive_failures=1,
                )
    if _REAPER_TASK is None or _REAPER_TASK.done():
        _REAPER_TASK = asyncio.create_task(_reaper_loop())
        _REAPER_TASK.add_done_callback(lambda task: _runtime_worker_done("reaper", task))
    if _DISPATCHER_TASK is None or _DISPATCHER_TASK.done():
        _DISPATCHER_TASK = asyncio.create_task(_dispatcher_loop())
        _DISPATCHER_TASK.add_done_callback(lambda task: _runtime_worker_done("dispatcher", task))
    return count


def _mark_worker_jobs_terminating_sync(reason: str) -> List[Dict[str, Any]]:
    """Durably fence attempts before their in-process owners are stopped."""
    db = SessionLocal()
    try:
        rows = (
            db.query(SddAiJob)
            .filter(
                SddAiJob.worker_boot_id == WORKER_BOOT_ID,
                SddAiJob.status.in_([
                    AiJobStatus.RUNNING,
                    AiJobStatus.TERMINATING,
                    AiJobStatus.ORPHANED,
                ]),
            )
            .all()
        )
        result: List[Dict[str, Any]] = []
        for job in rows:
            if job.status == AiJobStatus.RUNNING:
                job.status = AiJobStatus.TERMINATING
                job.terminal_reason = reason
                job.failure_code = reason
                job.termination_attempts = int(job.termination_attempts or 0) + 1
            result.append(
                {
                    "job_id": str(job.id),
                    "run_token": str(job.run_token or ""),
                    "process_pid": job.process_pid,
                    "process_started_at": job.process_started_at,
                    "process_group_id": job.process_group_id,
                    "reason": reason,
                }
            )
        if rows:
            db.commit()
        return result
    finally:
        db.close()


async def shutdown_runtime_workers() -> None:
    """Stop dispatch/queue/heartbeat tasks before infrastructure shutdown."""
    global _REAPER_TASK, _DISPATCHER_TASK, _SHUTTING_DOWN
    _SHUTTING_DOWN = True
    background = [task for task in (_REAPER_TASK, _DISPATCHER_TASK) if task is not None]
    for task in background:
        task.cancel()
    if background:
        await asyncio.gather(*background, return_exceptions=True)
    runners = list(_QUEUE_RUNNERS.values())
    for task in runners:
        task.cancel()
    if runners:
        await asyncio.gather(*runners, return_exceptions=True)
    _QUEUE_RUNNERS.clear()
    _REAPER_TASK = None
    _DISPATCHER_TASK = None
    owned_attempts = await run_db(_mark_worker_jobs_terminating_sync, "WORKER_SHUTDOWN")
    heartbeats = list(_JOB_HEARTBEAT_TASKS.values())
    for task in heartbeats:
        task.cancel()
    if heartbeats:
        await asyncio.gather(*heartbeats, return_exceptions=True)
    _JOB_HEARTBEAT_TASKS.clear()
    for row in owned_attempts:
        token = str(row.get("run_token") or "")
        result = await process_supervisor.stop_attempt(token, "WORKER_SHUTDOWN") if token else None
        if result is None and row.get("process_pid"):
            result = await process_supervisor.stop_persisted(
                row["process_pid"],
                row.get("process_started_at"),
                "WORKER_SHUTDOWN",
                process_group_id=row.get("process_group_id"),
            )
        confirmed_dead = bool(result is not None and result.confirmed_dead)
        payload = await run_db(
            _finish_termination_sync,
            row["job_id"],
            token,
            confirmed_dead=confirmed_dead,
            reason=(result.error_message if result and result.error_message else "WORKER_SHUTDOWN"),
            failure_code=(result.error_code if result and result.error_code else "WORKER_SHUTDOWN"),
        ) if token else None
        if payload:
            await _broadcast_job_payload(
                payload,
                final=str(payload.get("status")) in {s.value for s in FINAL_STATUSES},
            )
    # Catch any process whose owner row was not visible during the durable
    # snapshot (for example a spawn race); ProcessSupervisor remains the final
    # in-memory safety net.
    await process_supervisor.stop_all("WORKER_SHUTDOWN")


async def recover_pending_queues() -> int:
    """Schedule durable PENDING jobs after an API process restart."""
    await reap_stale_jobs()
    queue_keys = await run_db(_list_pending_queue_keys_sync)
    for queue_key in queue_keys:
        schedule_queue(queue_key)
    return len(queue_keys)


def _list_pending_queue_keys_sync() -> List[str]:
    """List queue keys in a worker thread; never open ORM sessions on-loop."""
    db = SessionLocal()
    try:
        rows = (
            db.query(SddAiJob.queue_key)
            .filter(SddAiJob.status == AiJobStatus.PENDING)
            .distinct()
            .all()
        )
        managed_prefixes = (
            f"{AiJobChannel.TASK_CHAT.value}:",
            f"{AiJobChannel.ASSET_THREAD.value}:",
            "DIAGNOSIS_SUMMARY:",
            "REQUIREMENT_PREVIEW:",
            "TASK_BASELINE:",
        )
        return [
            str(row[0] or "").strip()
            for row in rows
            if str(row[0] or "").strip().startswith(managed_prefixes)
        ]
    finally:
        db.close()


def _task_id_from_queue_key(queue_key: str) -> Optional[str]:
    normalized = str(queue_key or "")
    prefixes = (f"{AiJobChannel.TASK_CHAT.value}:", "TASK_BASELINE:")
    prefix = next((candidate for candidate in prefixes if normalized.startswith(candidate)), None)
    if prefix is None:
        return None
    task_id = normalized[len(prefix):].strip()
    return task_id or None


def _is_task_queue_paused(db: Session, queue_key: str) -> bool:
    task_id = _task_id_from_queue_key(queue_key)
    if not task_id:
        return False
    row = db.query(SddTask.status).filter(SddTask.id == task_id).first()
    if not row:
        return False
    return row[0] in TASK_QUEUE_PAUSED_STATUSES


def _take_next_pending_job_id_sync(queue_key: str) -> Optional[str]:
    db = SessionLocal()
    try:
        if _is_task_queue_paused(db, queue_key):
            return None
        active = (
            db.query(SddAiJob)
            .filter(
                SddAiJob.queue_key == queue_key,
                SddAiJob.status.in_(list(BLOCKING_STATUSES)),
            )
            .order_by(SddAiJob.created_at.asc())
            .first()
        )
        if active:
            return None
        candidate = (
            db.query(SddAiJob.id)
            .filter(
                SddAiJob.queue_key == queue_key,
                SddAiJob.status == AiJobStatus.PENDING,
            )
            .order_by(SddAiJob.created_at.asc())
            .first()
        )
        if not candidate:
            return None
        job_id = str(candidate[0] or "").strip()
        if not job_id:
            return None

        now = datetime.utcnow()
        run_token = str(uuid.uuid4())
        lease_expires_at = now + timedelta(
            seconds=max(5, int(getattr(settings, "AI_JOB_LEASE_SECONDS", 45) or 45))
        )
        affected_rows = (
            db.query(SddAiJob)
            .filter(
                SddAiJob.id == job_id,
                SddAiJob.status == AiJobStatus.PENDING,
            )
            .update(
                {
                    SddAiJob.status: AiJobStatus.RUNNING,
                    SddAiJob.started_at: now,
                    SddAiJob.finished_at: None,
                    SddAiJob.progress: 5,
                    SddAiJob.message: "Job running",
                    SddAiJob.attempt_count: SddAiJob.attempt_count + 1,
                    SddAiJob.run_token: run_token,
                    SddAiJob.worker_id: WORKER_ID,
                    SddAiJob.worker_boot_id: WORKER_BOOT_ID,
                    SddAiJob.heartbeat_at: now,
                    SddAiJob.lease_expires_at: lease_expires_at,
                    SddAiJob.cancel_requested_at: None,
                    SddAiJob.process_pid: None,
                    SddAiJob.process_started_at: None,
                    SddAiJob.process_group_id: None,
                    SddAiJob.termination_attempts: 0,
                    SddAiJob.failure_code: None,
                    SddAiJob.terminal_reason: None,
                },
                synchronize_session=False,
            )
        )
        if int(affected_rows or 0) != 1:
            db.rollback()
            return None
        db.commit()
        return job_id
    finally:
        db.close()


async def _take_next_pending_job_id(queue_key: str) -> Optional[str]:
    try:
        async with lock_ai_queue(queue_key):
            # 取队 4 stmts + commit 在 Redis 锁内完成，全部 off-loop
            return await run_db(_take_next_pending_job_id_sync, queue_key)
    except LockAcquireTimeout as exc:
        logger.warning(
            "AI queue lock timeout: queue_key={}, resource_type={}, resource_id={}, lock_key={}, backend={}",
            queue_key,
            exc.resource_type,
            exc.resource_id,
            exc.lock_key,
            exc.backend,
        )
        return None


def _get_job_status_sync(job_id: str) -> Optional[AiJobStatus]:
    db = SessionLocal()
    try:
        job = db.query(SddAiJob.status).filter(SddAiJob.id == job_id).first()
        if not job:
            return None
        return job[0]
    finally:
        db.close()


async def _get_job_status(job_id: str) -> Optional[AiJobStatus]:
    return await run_db(_get_job_status_sync, job_id)


def _load_attempt_context_sync(job_id: str) -> Optional[AgentAttemptContext]:
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job or not job.run_token or job.worker_boot_id != WORKER_BOOT_ID:
            return None
        return AgentAttemptContext(
            job_id=str(job.id),
            task_id=str(job.task_id) if job.task_id else None,
            queue_key=str(job.queue_key or ""),
            run_token=str(job.run_token),
            worker_id=str(job.worker_id or WORKER_ID),
            worker_boot_id=str(job.worker_boot_id),
            attempt_count=int(job.attempt_count or 0),
        )
    finally:
        db.close()


def _heartbeat_job_sync(job_id: str, run_token: str) -> bool:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        lease = now + timedelta(
            seconds=max(5, int(getattr(settings, "AI_JOB_LEASE_SECONDS", 45) or 45))
        )
        affected = (
            db.query(SddAiJob)
            .filter(
                SddAiJob.id == job_id,
                SddAiJob.status == AiJobStatus.RUNNING,
                SddAiJob.run_token == run_token,
                SddAiJob.worker_boot_id == WORKER_BOOT_ID,
                SddAiJob.cancel_requested_at.is_(None),
            )
            .update(
                {
                    SddAiJob.heartbeat_at: now,
                    SddAiJob.lease_expires_at: lease,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        return int(affected or 0) == 1
    finally:
        db.close()


def _begin_termination_sync(job_id: str, run_token: str, reason: str) -> bool:
    db = SessionLocal()
    try:
        affected = (
            db.query(SddAiJob)
            .filter(
                SddAiJob.id == job_id,
                SddAiJob.status == AiJobStatus.RUNNING,
                SddAiJob.run_token == run_token,
                SddAiJob.worker_boot_id == WORKER_BOOT_ID,
            )
            .update(
                {
                    SddAiJob.status: AiJobStatus.TERMINATING,
                    SddAiJob.termination_attempts: SddAiJob.termination_attempts + 1,
                    SddAiJob.terminal_reason: reason,
                    SddAiJob.failure_code: reason,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        return int(affected or 0) == 1
    finally:
        db.close()


def _finish_termination_sync(
    job_id: str,
    run_token: str,
    *,
    confirmed_dead: bool,
    reason: str,
    failure_code: str,
) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        job = (
            db.query(SddAiJob)
            .filter(
                SddAiJob.id == job_id,
                SddAiJob.run_token == run_token,
                SddAiJob.worker_boot_id == WORKER_BOOT_ID,
                SddAiJob.status.in_([AiJobStatus.TERMINATING, AiJobStatus.ORPHANED]),
            )
            .with_for_update()
            .first()
        )
        if not job:
            return None
        if not confirmed_dead:
            now = datetime.utcnow()
            failures = int(job.reap_failure_count or 0) + 1
            interval = max(1, int(getattr(settings, "AI_JOB_REAPER_INTERVAL_SECONDS", 10) or 10))
            cap = max(
                interval,
                int(getattr(settings, "AI_JOB_REAPER_MAX_BACKOFF_SECONDS", 3600) or 3600),
            )
            backoff = min(cap, interval * (2 ** min(failures - 1, 8)))
            backoff += random.uniform(
                0.0,
                max(0.0, float(getattr(settings, "AI_JOB_WORKER_JITTER_SECONDS", 0.5) or 0.5)),
            )
            job.status = AiJobStatus.ORPHANED
            job.message = "Agent process could not be confirmed dead"
            job.error_message = reason
            job.failure_code = failure_code
            job.terminal_reason = reason
            job.orphaned_at = job.orphaned_at or now
            job.first_failure_at = job.first_failure_at or now
            job.last_reap_attempt_at = now
            job.last_reap_verified_at = now
            job.reap_failure_count = failures
            job.last_reap_error = reason
            job.next_reap_at = now + timedelta(seconds=backoff)
            job.lease_expires_at = now
            db.commit()
            db.refresh(job)
            return serialize_job(job)

        retryable_preview = str(job.queue_key or "").startswith("REQUIREMENT_PREVIEW:")
        if retryable_preview and int(job.attempt_count or 0) < int(job.max_attempts or 1):
            job.status = AiJobStatus.PENDING
            job.progress = 0
            job.message = "Agent interrupted; preview queued for retry"
            job.error_message = reason
            _clear_process_ownership(job)
        elif job.cancel_requested_at is not None:
            job.status = AiJobStatus.CANCELLED
            job.progress = 100
            job.message = "Job cancelled by user"
            job.finished_at = datetime.utcnow()
            job.error_message = None
        elif str(job.queue_key or "").startswith("TASK_BASELINE:"):
            # A dead baseline attempt must become explicitly retryable.  The
            # next manual request resets this row to PENDING for the same
            # immutable input revision; no automatic CLI rerun is hidden here.
            job.status = AiJobStatus.FAILED
            job.progress = 100
            job.message = "Baseline process interrupted; rebuild manually"
            job.finished_at = datetime.utcnow()
            job.error_message = reason
        elif job.channel == AiJobChannel.TASK_CHAT:
            job.status = AiJobStatus.INTERRUPTED
            job.progress = 100
            job.message = "AI session interrupted unexpectedly"
            job.finished_at = datetime.utcnow()
            job.error_message = reason
            job.interrupt_reason = reason
        else:
            job.status = AiJobStatus.FAILED
            job.progress = 100
            job.message = "AI execution failed during termination"
            job.finished_at = datetime.utcnow()
            job.error_message = reason
        _clear_process_ownership(job)
        job.failure_code = failure_code
        job.terminal_reason = reason
        job.last_reap_verified_at = datetime.utcnow()
        job.next_reap_at = None
        db.commit()
        db.refresh(job)
        return serialize_job(job)
    finally:
        db.close()


async def _terminate_attempt(attempt: AgentAttemptContext, reason: str) -> None:
    begun = await run_db(_begin_termination_sync, attempt.job_id, attempt.run_token, reason)
    result = await process_supervisor.stop_attempt(attempt.run_token, reason)
    # A failed begin CAS means this token no longer owns the durable attempt.
    # We may still stop an in-memory process for safety, but must not let its
    # late termination result mutate the current/new attempt.
    if not begun:
        return
    confirmed_dead = bool(result is not None and result.confirmed_dead)
    payload = await finalize_attempt_termination(
        attempt.job_id,
        attempt.run_token,
        confirmed_dead=confirmed_dead,
        reason=(result.error_message if result and result.error_message else reason),
        failure_code=(result.error_code if result and result.error_code else reason),
    )
    if payload:
        await _broadcast_job_payload(payload, final=str(payload.get("status")) in {s.value for s in FINAL_STATUSES})


async def finalize_attempt_termination(
    job_id: str,
    run_token: Optional[str],
    *,
    confirmed_dead: bool,
    reason: str,
    failure_code: str,
) -> Optional[Dict[str, Any]]:
    """Converge a stopped attempt only after process-death verification.

    Callers that own an engine (for example the task interrupt endpoint) use
    this after the engine has attempted to stop its CLI.  A missing token is
    deliberately not accepted: without fencing there is no safe owner for a
    durable state transition.
    """
    token = str(run_token or "").strip()
    if not token:
        return None
    payload = await run_db(
        _finish_termination_sync,
        job_id,
        token,
        confirmed_dead=confirmed_dead,
        reason=reason,
        failure_code=failure_code,
    )
    if payload and str(payload.get("status")) == AiJobStatus.PENDING.value:
        schedule_queue(str(payload.get("queue_key") or ""))
    return payload


async def _job_heartbeat_loop(attempt: AgentAttemptContext) -> None:
    interval = max(1, int(getattr(settings, "AI_JOB_HEARTBEAT_SECONDS", 10) or 10))
    try:
        while True:
            await asyncio.sleep(interval)
            if not await run_db(_heartbeat_job_sync, attempt.job_id, attempt.run_token):
                await _terminate_attempt(attempt, "LEASE_LOST")
                return
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("AI job heartbeat failed: job_id={}", attempt.job_id)
        await _terminate_attempt(attempt, "HEARTBEAT_FAILURE")


async def _run_queue(queue_key: str) -> None:
    lock = _get_queue_lock(queue_key)
    async with lock:
        while True:
            if _runtime_shutdown_in_progress():
                return
            job_id = await _take_next_pending_job_id(queue_key)
            if not job_id:
                return
            attempt = await run_db(_load_attempt_context_sync, job_id)
            if attempt is None:
                logger.warning("Claimed AI job has no current attempt context: {}", job_id)
                return
            context_token = bind_agent_attempt(attempt)
            heartbeat_task = asyncio.create_task(_job_heartbeat_loop(attempt))
            _JOB_HEARTBEAT_TASKS[job_id] = heartbeat_task
            try:
                await _publish_job_state(job_id)
                await _execute_job(job_id)
            finally:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
                _JOB_HEARTBEAT_TASKS.pop(job_id, None)
                reset_agent_attempt(context_token)
            status = await _get_job_status(job_id)
            if status in {AiJobStatus.WAITING_HITL, AiJobStatus.INTERRUPTED}:
                return


def _extract_block_text(block: Any) -> str:
    if not isinstance(block, dict):
        return ""
    text = str(block.get("text") or "").strip()
    if text:
        return text
    runs = block.get("runs")
    if isinstance(runs, list):
        merged = "".join(str(item.get("text") or "") for item in runs if isinstance(item, dict)).strip()
        if merged:
            return merged
    cells = block.get("cells")
    if isinstance(cells, list):
        chunks: List[str] = []
        for row in cells:
            if not isinstance(row, list):
                continue
            for cell in row:
                if isinstance(cell, dict):
                    cell_text = str(cell.get("text") or "").strip()
                    if cell_text:
                        chunks.append(cell_text)
        if chunks:
            return " | ".join(chunks)
    return ""


def _resolve_thread_anchor_text(
    thread: SddAssetThread,
    block: Any,
    *,
    selected_text: Optional[str] = None,
    char_start: Optional[int] = None,
    char_end: Optional[int] = None,
) -> Dict[str, str]:
    block_text = _extract_block_text(block).strip()
    selected_text = str(selected_text if selected_text is not None else thread.selected_text or "").strip()
    start_candidate = char_start if char_start is not None else thread.char_start
    end_candidate = char_end if char_end is not None else thread.char_end
    if block_text and start_candidate is not None and end_candidate is not None:
        try:
            start = int(start_candidate)
            end = int(end_candidate)
        except Exception:
            start, end = -1, -1
        if 0 <= start < end <= len(block_text):
            range_selected_text = block_text[start:end].strip()
            if range_selected_text and (not selected_text or selected_text == block_text):
                selected_text = range_selected_text
    anchor_text = selected_text or block_text
    return {
        "anchor_text": anchor_text,
        "block_text": block_text,
        "selected_text": selected_text,
    }


def _thread_history_lines(thread: SddAssetThread, limit: int = 18) -> List[str]:
    messages = sorted(list(thread.messages or []), key=lambda item: item.created_at)
    lines: List[str] = []
    for message in messages[-limit:]:
        role = _as_status(message.role)
        if role == AssetThreadMessageRole.AI.value:
            continue
        content = str(message.content or "").strip()
        if content:
            lines.append(f"[{role}] {content}")
    return lines


def _proposal_discussion_lines(thread: SddAssetThread, limit: int = 28) -> List[str]:
    messages = sorted(list(thread.messages or []), key=lambda item: item.created_at)
    lines: List[str] = []
    for message in messages:
        role = _as_status(message.role)
        if role not in {AssetThreadMessageRole.USER.value, AssetThreadMessageRole.AI.value}:
            continue
        content = str(message.content or "").strip()
        if not content:
            continue
        label = "成员" if role == AssetThreadMessageRole.USER.value else "AI"
        lines.append(f"[{label}] {content}")
    if len(lines) > limit:
        return lines[-limit:]
    return lines


def _proposal_source_message_ids(thread: SddAssetThread) -> List[str]:
    messages = sorted(list(thread.messages or []), key=lambda item: item.created_at)
    return [
        item.id
        for item in messages
        if _as_status(item.role) in {AssetThreadMessageRole.USER.value, AssetThreadMessageRole.AI.value}
        and str(item.content or "").strip()
    ]


def _resolve_context_version(
    db: Session,
    *,
    thread: SddAssetThread,
    requested_version_id: Optional[str],
):
    version_id = str(requested_version_id or "").strip()
    if version_id:
        version = (
            db.query(SddAssetVersion)
            .filter(
                SddAssetVersion.id == version_id,
                SddAssetVersion.asset_id == thread.asset_id,
            )
            .first()
        )
        if version:
            return version
    if thread.asset and thread.asset.active_version_id:
        active_version = (
            db.query(SddAssetVersion)
            .filter(
                SddAssetVersion.id == thread.asset.active_version_id,
                SddAssetVersion.asset_id == thread.asset_id,
            )
            .first()
        )
        if active_version:
            return active_version
    return thread.version


def _normalize_relocated_anchor(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    block_id = str(raw.get("block_id") or "").strip()
    if not block_id:
        return None
    selected_text = str(raw.get("selected_text") or "").strip() or None
    char_start = raw.get("char_start")
    char_end = raw.get("char_end")
    try:
        char_start = int(char_start) if char_start is not None else None
    except Exception:
        char_start = None
    try:
        char_end = int(char_end) if char_end is not None else None
    except Exception:
        char_end = None
    return {
        "block_id": block_id,
        "selected_text": selected_text,
        "char_start": char_start,
        "char_end": char_end,
    }


def _serialize_proposal_for_ws(proposal: Any) -> Dict[str, Any]:
    status = proposal.status.value if hasattr(proposal.status, "value") else str(proposal.status)
    return {
        "id": proposal.id,
        "thread_id": proposal.thread_id,
        "base_version_id": proposal.base_version_id,
        "proposed_patch_json": proposal.proposed_patch_json,
        "diff_text": proposal.diff_text,
        "status": status,
        "creator_id": proposal.creator_id,
        "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
        "updated_at": proposal.updated_at.isoformat() if proposal.updated_at else None,
    }


def _clean_rewrite_text(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].rstrip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _parse_rewrite_payload(raw: str) -> Dict[str, str]:
    text = str(raw or "").strip()
    if not text:
        return {"scope": "anchor", "anchor_text": ""}

    candidate = text
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].rstrip().startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()

    json_text = candidate
    if not (json_text.startswith("{") and json_text.endswith("}")):
        match = re.search(r"\{[\s\S]*\}", candidate)
        if match:
            json_text = match.group(0).strip()

    try:
        parsed = json.loads(json_text)
    except Exception:
        return {"scope": "anchor", "anchor_text": _clean_rewrite_text(text)}

    if not isinstance(parsed, dict):
        return {"scope": "anchor", "anchor_text": _clean_rewrite_text(text)}

    scope = str(parsed.get("scope") or parsed.get("rewrite_scope") or "anchor").strip().lower()
    if scope == "document":
        markdown = str(
            parsed.get("document_markdown")
            or parsed.get("markdown")
            or parsed.get("document")
            or ""
        ).strip()
        if markdown:
            return {"scope": "document", "document_markdown": markdown}

    anchor_text = str(
        parsed.get("anchor_text")
        or parsed.get("text")
        or parsed.get("rewritten_text")
        or ""
    ).strip()
    return {"scope": "anchor", "anchor_text": _clean_rewrite_text(anchor_text or text)}


async def run_cli_single_turn(
    prompt: str,
    project_path: str,
    *,
    session_id: Optional[str] = None,
    max_attempts: int = 2,
    should_cancel: Optional[Callable[[], bool]] = None,
    backend_name: Optional[str] = None,
    fork_session: bool = False,
    permission_mode: str = "default",
    run_token: Optional[str] = None,
) -> Dict[str, Any]:
    attempts = max(1, int(max_attempts or 1))
    next_session_id = session_id
    last_error: Optional[Exception] = None

    for attempt in range(1, attempts + 1):
        current_attempt = current_agent_attempt()
        effective_run_token = run_token or (current_attempt.run_token if current_attempt else None)
        # 指定 backend（工作区配置或线程粘性）走统一适配层；否则保持旧全局行为
        bridge = create_legacy_bridge(backend_name) if backend_name else create_cli_bridge()
        text_parts: List[str] = []
        result_text = ""
        result_is_error = False
        cancelled = False
        session_started = False

        async def on_event(event: dict):
            nonlocal result_text, result_is_error
            event_type = str(event.get("type") or "")
            if event_type == "assistant":
                message = event.get("message") or {}
                blocks = message.get("content") if isinstance(message, dict) else []
                if not isinstance(blocks, list):
                    return
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    if str(block.get("type") or "") == "text":
                        text = str(block.get("text") or "").strip()
                        if text:
                            text_parts.append(text)
            elif event_type == "result":
                subtype = str(event.get("subtype") or "").lower()
                result_is_error = bool(event.get("is_error")) or subtype == "error"
                text = str(event.get("result") or "").strip()
                if text:
                    result_text = text

        env_overrides: Dict[str, str] = {}
        if effective_run_token:
            env_overrides.update(
                {
                    "TRACEFORGE_RUN_TOKEN": effective_run_token,
                    "AI_JOB_ID": current_attempt.job_id if current_attempt else "",
                    "WORKER_BOOT_ID": current_attempt.worker_boot_id if current_attempt else WORKER_BOOT_ID,
                }
            )
        async def on_process_started(identity: AgentProcessIdentity) -> bool:
            if getattr(identity, "pid", None) is None:
                return True
            return await run_db(
                _persist_process_identity_sync,
                current_attempt.job_id if current_attempt else "",
                effective_run_token or "",
                identity,
            )

        monitor_task: Optional[asyncio.Task] = None
        try:
            resumed_session_id = await bridge.start_session(
                prompt=prompt,
                project_path=project_path,
                event_callback=on_event,
                session_id=next_session_id,
                env_overrides=env_overrides or None,
                fork_session=fork_session and attempt == 1,
                permission_mode=permission_mode,
                on_process_started=on_process_started,
            )
            session_started = True
            if should_cancel:
                async def _cancel_monitor() -> None:
                    nonlocal cancelled
                    while True:
                        if should_cancel():
                            cancelled = True
                            await bridge.cancel()
                            return
                        await asyncio.sleep(0.2)

                monitor_task = asyncio.create_task(_cancel_monitor())

            # 文档讨论是异步作业，允许更长执行时长，避免误超时。
            wait_seconds = max(600, int(settings.AGENT_MAX_RUNTIME_SECONDS or 7200))
            if hasattr(bridge, "wait"):
                await asyncio.wait_for(bridge.wait(), timeout=wait_seconds)
        except asyncio.TimeoutError as exc:
            await bridge.cancel()
            termination = getattr(bridge, "last_termination", None)
            if termination is not None and not termination.confirmed_dead:
                raise RuntimeError("Agent process tree could not be confirmed dead") from exc
            last_error = TimeoutError("AI reply timed out")
            logger.warning(
                "Asset AI single-turn wait timeout (attempt {}/{})",
                attempt,
                attempts,
            )
            if attempt < attempts:
                next_session_id = None
                continue
            raise last_error from exc
        finally:
            if monitor_task:
                monitor_task.cancel()
                await asyncio.gather(monitor_task, return_exceptions=True)
            if not session_started or getattr(bridge, "is_running", lambda: False)():
                await asyncio.shield(bridge.cancel())

        if cancelled:
            raise RuntimeError("AI job cancelled by user")

        merged = "\n\n".join(part for part in text_parts if part.strip()).strip()
        final_text = merged or result_text or "AI 暂时没有返回有效内容，请稍后重试。"
        final_session_id = getattr(bridge, "session_id", None) or resumed_session_id

        if result_is_error or _looks_like_timeout_text(final_text):
            last_error = RuntimeError(final_text or "AI provider returned timeout/error")
            logger.warning(
                "Asset AI single-turn got timeout/error text (attempt {}/{}): {}",
                attempt,
                attempts,
                final_text[:160],
            )
            if attempt < attempts:
                next_session_id = None
                continue
            raise last_error

        termination = getattr(bridge, "last_termination", None)
        return {
            "text": final_text,
            "session_id": final_session_id,
            "termination_confirmed_dead": (
                bool(termination.confirmed_dead) if termination is not None else None
            ),
        }

    if last_error:
        raise last_error
    raise RuntimeError("AI reply failed with unknown reason")


def _prepare_asset_thread_context_sync(
    db: Session,
    job_id: str,
    run_token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """asset thread job 上下文准备段 A（线程内执行，由 run_db_txn 包装）。

    只做读取与轻量状态推进，返回纯数据；CLI 前后的其余 DB 段各自独立事务。
    """
    job = (
        db.query(SddAiJob)
        .options(
            joinedload(SddAiJob.thread)
            .joinedload(SddAssetThread.task),
            joinedload(SddAiJob.thread).joinedload(SddAssetThread.asset),
        )
        .filter(SddAiJob.id == job_id)
        .first()
    )
    if not job or job.channel != AiJobChannel.ASSET_THREAD:
        return None
    if not _attempt_is_current_sync(db, job_id=job_id, run_token=run_token):
        raise AgentAttemptFencedError(f"Asset job attempt is no longer current: {job_id}")
    thread = job.thread
    if not thread:
        raise ValueError("Thread not found for AI job")
    job_kind = _job_kind_from_job(job)
    task = thread.task
    if not thread.task_id or not task:
        raise ValueError("Thread task is required for AI job")

    bootstrap = task_cli_state_service.ensure_bootstrap_ready(
        db,
        workspace_id=thread.workspace_id,
        task_id=thread.task_id,
    )
    return {
        "job_id": str(job.id),
        "job_kind": job_kind,
        "run_token": run_token or str(job.run_token or "") or None,
        "creator_id": job.creator_id,
        "thread_id": thread.id,
        "asset_id": thread.asset_id,
        "task_id": thread.task_id,
        "workspace_id": thread.workspace_id,
        "task_name": str(task.name or ""),
        "task_project_path": str(task.project_path or ""),
        "document_name": thread.asset.name if thread.asset else "",
        "bootstrap_status": _as_status(bootstrap.status),
        "bootstrap_version_id": bootstrap.spec_version_id,
        "context_json": job.context_json if isinstance(job.context_json, dict) else {},
    }


def _build_asset_thread_run_sync(
    db: Session,
    *,
    job_id: str,
    base: Dict[str, Any],
    session_plan,
) -> Dict[str, Any]:
    """asset thread job 准备段 B（线程内执行）：prompt 构建与执行参数解析。"""
    job_kind = base["job_kind"]
    thread = asset_discussion_service.get_thread(db, asset_id=base["asset_id"], thread_id=base["thread_id"])
    if not thread:
        raise ValueError("Thread not found for AI job")
    task = thread.task
    version = thread.version
    thread_backend = session_plan.backend
    resume_session_id = session_plan.session_id
    fork_first_turn = session_plan.fork_first_turn
    if not fork_first_turn:
        resume_session_id = (
            task_cli_state_service.get_latest_thread_session_id(db, thread.id)
            or resume_session_id
        )
    # 线程执行目录 = 任务目录（含 git worktree），评审答疑可直接读仓库内容
    from app.domains.task.services import task_service as task_service_module

    project_path = (
        task_service_module.resolve_task_cli_dir(db, task)
        if task
        else "."
    )
    if not os.path.isdir(project_path):
        project_path = (task.project_path if task and task.project_path else ".").strip() or "."
    if not os.path.isdir(project_path):
        project_path = "."
    thread_cwd = project_path

    run_state: Dict[str, Any] = {
        **base,
        "thread_backend": thread_backend,
        "resume_session_id": resume_session_id,
        "fork_first_turn": fork_first_turn,
        "thread_cwd": thread_cwd,
        "project_path": project_path,
    }

    if job_kind == JOB_KIND_RESOLUTION_PROPOSAL:
        context_json = base.get("context_json") or {}
        overwrite_existing_draft = bool(context_json.get("overwrite_existing_draft"))
        context_version = _resolve_context_version(
            db,
            thread=thread,
            requested_version_id=str(context_json.get("context_version_id") or "").strip() or None,
        )
        anchor_eval = asset_discussion_service.resolve_thread_anchor_for_version(
            db,
            thread=thread,
            context_version=context_version,
        )
        effective_anchor = anchor_eval.get("effective_anchor") if isinstance(anchor_eval, dict) else {}
        effective_block_id = str(
            (effective_anchor or {}).get("block_id")
            or thread.block_id
            or ""
        ).strip() or thread.block_id
        selected_block = (
            asset_discussion_service.get_block_by_id(context_version, effective_block_id)
            if context_version
            else None
        )
        if not selected_block and version:
            selected_block = asset_discussion_service.get_block_by_id(version, thread.block_id)
            effective_block_id = thread.block_id
            effective_anchor = {
                "block_id": thread.block_id,
                "selected_text": thread.selected_text,
                "char_start": thread.char_start,
                "char_end": thread.char_end,
            }
        anchor_meta = _resolve_thread_anchor_text(
            thread,
            selected_block,
            selected_text=(effective_anchor or {}).get("selected_text"),
            char_start=(effective_anchor or {}).get("char_start"),
            char_end=(effective_anchor or {}).get("char_end"),
        )
        discussion_lines = _proposal_discussion_lines(thread)
        source_message_ids = _proposal_source_message_ids(thread)
        prompt = build_resolution_proposal_prompt(
            task_name=task.name if task else "",
            document_name=thread.asset.name if thread.asset else "",
            document_version_label=(f"v{context_version.version_no}" if context_version else "unknown"),
            block_id=effective_block_id or "",
            thread_id=thread.id or "",
            anchor_text=anchor_meta["anchor_text"],
            block_context_text=anchor_meta["block_text"],
            discussion_lines=discussion_lines,
        )
        run_state.update({
            "prompt": prompt,
            "overwrite_existing_draft": overwrite_existing_draft,
            "source_message_ids": source_message_ids,
            "effective_anchor": effective_anchor,
            "context_version_id": context_version.id if context_version else None,
            "anchor_text": anchor_meta["anchor_text"],
            "block_text": anchor_meta["block_text"],
            "discussion_lines_tail": discussion_lines[-12:],
        })
        return run_state

    if job_kind == JOB_KIND_RESOLUTION_REWRITE:
        context_json = base.get("context_json") or {}
        proposal_id = str(context_json.get("proposal_id") or "").strip()
        if not proposal_id:
            raise ValueError("proposal_id is required for rewrite job")

        proposal = (
            db.query(SddAssetResolutionProposal)
            .filter(
                SddAssetResolutionProposal.id == proposal_id,
                SddAssetResolutionProposal.thread_id == thread.id,
            )
            .first()
        )
        if not proposal:
            raise ValueError("Resolution proposal not found for rewrite")

        proposal_text = str(context_json.get("proposal_text") or "").strip()
        if not proposal_text:
            patch = proposal.proposed_patch_json if isinstance(proposal.proposed_patch_json, dict) else {}
            proposal_text = str(patch.get("proposal_text") or "").strip()
        if not proposal_text:
            raise ValueError("proposal_text is required for rewrite")
        requested_scope = str(context_json.get("rewrite_scope") or "").strip().lower()
        if requested_scope not in {"anchor", "document"}:
            requested_scope = "anchor"
        context_version = _resolve_context_version(
            db,
            thread=thread,
            requested_version_id=str(context_json.get("context_version_id") or "").strip() or proposal.base_version_id,
        )
        anchor_eval = asset_discussion_service.resolve_thread_anchor_for_version(
            db,
            thread=thread,
            context_version=context_version,
        )
        effective_anchor = anchor_eval.get("effective_anchor") if isinstance(anchor_eval, dict) else {}
        relocated_anchor = _normalize_relocated_anchor(context_json.get("relocated_anchor"))
        if relocated_anchor:
            effective_anchor = relocated_anchor
        effective_block_id = str(
            (effective_anchor or {}).get("block_id")
            or thread.block_id
            or ""
        ).strip() or thread.block_id
        selected_block = (
            asset_discussion_service.get_block_by_id(context_version, effective_block_id)
            if context_version
            else None
        )
        if not selected_block:
            raise ValueError("Anchor block not found for rewrite context")
        anchor_meta = _resolve_thread_anchor_text(
            thread,
            selected_block,
            selected_text=(effective_anchor or {}).get("selected_text"),
            char_start=(effective_anchor or {}).get("char_start"),
            char_end=(effective_anchor or {}).get("char_end"),
        )
        selection_mode = bool(anchor_meta["selected_text"])
        prompt = build_resolution_rewrite_prompt(
            task_name=task.name if task else "",
            document_name=thread.asset.name if thread.asset else "",
            document_version_label=(f"v{context_version.version_no}" if context_version else "unknown"),
            block_id=effective_block_id or "",
            thread_id=thread.id or "",
            anchor_text=anchor_meta["anchor_text"],
            block_context_text=anchor_meta["block_text"],
            proposal_text=proposal_text,
            rewrite_scope=requested_scope,
            selection_mode=selection_mode,
        )
        run_state.update({
            "prompt": prompt,
            "proposal_id": proposal_id,
            "proposal_text": proposal_text,
            "rewrite_scope": requested_scope,
            "selection_mode": selection_mode,
            "effective_anchor": effective_anchor,
            "context_version_id": context_version.id if context_version else None,
            "anchor_text": anchor_meta["anchor_text"],
            "block_text": anchor_meta["block_text"],
        })
        return run_state

    context = (
        asset_discussion_service.get_block_context(version, thread.block_id)
        if version else {"selected": None, "neighbors": []}
    )
    selected_block = context.get("selected") if isinstance(context, dict) else None
    neighbor_blocks = context.get("neighbors") if isinstance(context, dict) else []
    anchor_meta = _resolve_thread_anchor_text(thread, selected_block)
    selected_text = anchor_meta["anchor_text"]
    anchor_block_text = anchor_meta["block_text"]
    neighbor_text = "\n".join(
        f"- {_extract_block_text(item)}"
        for item in (neighbor_blocks or [])
        if _extract_block_text(item)
    ).strip()
    history_lines = _thread_history_lines(thread)
    prompt = build_asset_thread_prompt(
        task_name=task.name if task else "",
        document_name=thread.asset.name if thread.asset else "",
        document_version_label=(f"v{version.version_no}" if version else "unknown"),
        block_id=thread.block_id or "",
        thread_id=thread.id or "",
        project_path=project_path,
        selected_text=selected_text or (thread.selected_text or ""),
        anchor_block_text=anchor_block_text,
        neighbor_text=neighbor_text,
        history_lines=history_lines,
        manual_prompt=_job_prompt_text(db, base["thread_id"]),
    )
    run_state.update({
        "prompt": prompt,
        "selected_text": selected_text,
        "anchor_block_text": anchor_block_text,
        "neighbor_text": neighbor_text,
        "history_lines": history_lines,
    })
    return run_state


def _job_prompt_text(db: Session, thread_id: str) -> Optional[str]:
    job = (
        db.query(SddAiJob.prompt_text)
        .filter(
            SddAiJob.thread_id == thread_id,
            SddAiJob.channel == AiJobChannel.ASSET_THREAD,
        )
        .order_by(SddAiJob.created_at.desc())
        .first()
    )
    return job[0] if job else None


def _persist_asset_proposal_sync(
    db: Session,
    *,
    base: Dict[str, Any],
    proposal_text: str,
    run_token: Optional[str] = None,
) -> Dict[str, Any]:
    if not _attempt_is_current_sync(db, job_id=str(base.get("job_id") or ""), run_token=run_token):
        raise AgentAttemptFencedError("Asset proposal attempt is no longer current")
    thread = asset_discussion_service.get_thread(db, asset_id=base["asset_id"], thread_id=base["thread_id"])
    if not thread:
        raise ValueError("Thread disappeared during proposal generation")
    context_version = _resolve_context_version(
        db,
        thread=thread,
        requested_version_id=base.get("context_version_id"),
    )
    proposal = asset_resolution_service.create_resolution_proposal(
        db,
        thread=thread,
        creator_id=base["creator_id"],
        proposed_text=proposal_text,
        overwrite_existing_draft=bool(base.get("overwrite_existing_draft")),
        source_message_ids=base.get("source_message_ids") or [],
        version=context_version,
        effective_anchor=base.get("effective_anchor") if isinstance(base.get("effective_anchor"), dict) else None,
    )
    db.commit()
    db.refresh(proposal)
    return {
        "proposal": _serialize_proposal_for_ws(proposal),
        "proposal_id": str(proposal.id),
    }


def _persist_asset_rewrite_sync(
    db: Session,
    *,
    base: Dict[str, Any],
    proposal_text: str,
    rewritten_text: str,
    rewrite_scope: str,
    rewritten_markdown: str,
    selection_mode: bool,
    run_token: Optional[str] = None,
) -> Dict[str, Any]:
    if not _attempt_is_current_sync(db, job_id=str(base.get("job_id") or ""), run_token=run_token):
        raise AgentAttemptFencedError("Asset rewrite attempt is no longer current")
    thread = asset_discussion_service.get_thread(db, asset_id=base["asset_id"], thread_id=base["thread_id"])
    if not thread:
        raise ValueError("Thread disappeared during proposal rewrite")
    proposal = (
        db.query(SddAssetResolutionProposal)
        .filter(
            SddAssetResolutionProposal.id == base["proposal_id"],
            SddAssetResolutionProposal.thread_id == thread.id,
        )
        .first()
    )
    if not proposal:
        raise ValueError("Resolution proposal not found after rewrite")

    proposal = asset_resolution_service.update_resolution_proposal_rewrite(
        db,
        thread=thread,
        proposal=proposal,
        proposal_text=proposal_text,
        rewritten_text=rewritten_text,
        rewrite_scope=rewrite_scope,
        rewritten_markdown=rewritten_markdown or None,
        selection_mode=selection_mode,
        context_version_id=base.get("context_version_id"),
        relocated_anchor=base.get("effective_anchor") if isinstance(base.get("effective_anchor"), dict) else None,
    )
    db.commit()
    db.refresh(proposal)
    proposal_patch = proposal.proposed_patch_json if isinstance(proposal.proposed_patch_json, dict) else {}
    rewrite_ready = str(proposal_patch.get("rewrite_status") or "").strip().lower() == "ready"
    has_merged = bool(
        (isinstance(proposal_patch.get("merged_block_ast"), dict) and proposal_patch.get("merged_block_ast"))
        or (
            isinstance(proposal_patch.get("merged_blocks_ast"), list)
            and len(proposal_patch.get("merged_blocks_ast") or []) > 0
        )
    )
    if not rewrite_ready or not has_merged:
        raise ValueError(
            "Resolution rewrite persisted without merged AST payload"
        )
    return {
        "proposal": _serialize_proposal_for_ws(proposal),
        "proposal_id": str(proposal.id),
    }


def _persist_asset_reply_sync(
    db: Session,
    *,
    base: Dict[str, Any],
    reply: str,
    thread_backend: Optional[str],
    job_id: str,
    run_token: Optional[str] = None,
) -> Dict[str, Any]:
    if not _attempt_is_current_sync(db, job_id=job_id, run_token=run_token):
        raise AgentAttemptFencedError("Asset reply attempt is no longer current")
    thread = asset_discussion_service.get_thread(db, asset_id=base["asset_id"], thread_id=base["thread_id"])
    if not thread:
        raise ValueError("Thread disappeared during AI execution")

    ai_message = asset_discussion_service.add_thread_message(
        db,
        thread=thread,
        role=AssetThreadMessageRole.AI,
        content=reply,
        creator_id=None,
        metadata_json={"provider": thread_backend or "claude-cli", "job_id": job_id},
    )
    db.commit()
    db.refresh(ai_message)
    return {
        "message": {
            "id": ai_message.id,
            "thread_id": ai_message.thread_id,
            "role": _as_status(ai_message.role),
            "content": ai_message.content,
            "creator_id": ai_message.creator_id,
            "creator_display_name": None,
            "creator_avatar_svg": None,
            "metadata_json": ai_message.metadata_json,
            "created_at": ai_message.created_at.isoformat() if ai_message.created_at else None,
        },
        "message_id": str(ai_message.id),
    }


def _persist_asset_failure_message_sync(
    db: Session,
    *,
    job_id: str,
    error_text: str,
    run_token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    failed_job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
    if not failed_job or not failed_job.thread_id:
        return None
    if not _attempt_is_current_sync(db, job_id=job_id, run_token=run_token):
        return None
    thread = asset_discussion_service.get_thread(
        db, asset_id=failed_job.asset_id, thread_id=failed_job.thread_id
    )
    if not thread:
        return None
    failure_message = asset_discussion_service.add_thread_message(
        db,
        thread=thread,
        role=AssetThreadMessageRole.SYSTEM,
        content=f"AI 回复失败: {error_text}\n\n可重试：已自动采用超时重试策略，如仍失败请稍后再次触发。",
        creator_id=failed_job.creator_id,
        metadata_json={"error": error_text, "job_id": job_id},
    )
    db.commit()
    db.refresh(failure_message)
    return {
        "asset_id": thread.asset_id,
        "message": {
            "id": failure_message.id,
            "thread_id": failure_message.thread_id,
            "role": _as_status(failure_message.role),
            "content": failure_message.content,
            "creator_id": failure_message.creator_id,
            "creator_display_name": None,
            "creator_avatar_svg": None,
            "metadata_json": failure_message.metadata_json,
            "created_at": failure_message.created_at.isoformat() if failure_message.created_at else None,
        },
    }


async def _execute_asset_thread_job(job_id: str) -> None:
    job_kind = JOB_KIND_THREAD_AI_REPLY
    attempt = current_agent_attempt()
    run_token = attempt.run_token if attempt else None
    try:
        base = await run_db_txn(
            lambda db: _prepare_asset_thread_context_sync(db, job_id, run_token)
        )
        if base is None:
            return
        job_kind = base["job_kind"]
        with ExitStack() as context_stack:
            context_stack.enter_context(
                bind_task_context(
                    task_id=base["task_id"],
                    workspace_id=base["workspace_id"],
                    user_id=base["creator_id"],
                )
            )
            context_stack.enter_context(
                bind_ai_context(
                    job_id=job_id,
                    task_id=base["task_id"],
                    session_id=None,
                    event_type=job_kind,
                )
            )

            await _update_job_state(job_id, progress=12, message="Building discussion context")

            await _update_job_state(
                job_id,
                progress=18,
                message="Preparing isolated thread workspace",
                context_patch={
                    "bootstrap_status": base["bootstrap_status"],
                    "bootstrap_version_id": base["bootstrap_version_id"],
                    "job_kind": job_kind,
                },
            )
            # 线程专属会话：首次使用时从 baseline fork（各讨论上下文独立），
            # 之后一直用线程自己的会话；绝不直接 resume baseline 会话。
            session_plan = await task_cli_state_service.ensure_thread_session(
                base["thread_id"],
                require_ready=True,
            )
            # 准备段 B：prompt 构建 + 执行参数（线程内，无长持 session）
            run_state = await run_db_txn(
                lambda db: _build_asset_thread_run_sync(db, job_id=job_id, base=base, session_plan=session_plan)
            )
            thread_cwd = run_state["thread_cwd"]
            thread_backend = run_state["thread_backend"]
            resume_session_id = run_state["resume_session_id"]
            fork_first_turn = run_state["fork_first_turn"]
            prompt = run_state["prompt"]

            if job_kind == JOB_KIND_RESOLUTION_PROPOSAL:
                await _update_job_state(
                    job_id,
                    progress=46,
                    message="Generating resolution proposal",
                    context_patch={
                        "thread_workspace": thread_cwd,
                        "discussion_lines": run_state["discussion_lines_tail"],
                        "anchor_text": run_state["anchor_text"],
                        "block_text": run_state["block_text"],
                        "context_version_id": run_state["context_version_id"],
                        "effective_anchor": run_state["effective_anchor"],
                    },
                )
                result = await run_cli_single_turn(
                    prompt,
                    thread_cwd,
                    session_id=resume_session_id,
                    should_cancel=lambda: _is_cancel_requested(job_id),
                    backend_name=thread_backend,
                    fork_session=fork_first_turn,
                )
                if fork_first_turn:
                    await task_cli_state_service.record_thread_session_id_async(
                        base["thread_id"], str(result.get("session_id") or "")
                    )
                proposal_text = str(result.get("text") or "").strip()
                final_session_id = str(result.get("session_id") or "").strip()
                if not proposal_text:
                    raise ValueError("Resolution proposal text is empty")

                persisted = await run_db_txn(
                    lambda db: _persist_asset_proposal_sync(
                        db,
                        base=run_state,
                        proposal_text=proposal_text,
                        run_token=run_token,
                    )
                )
                await asset_discussion_ws_manager.broadcast(
                    base["asset_id"],
                    {
                        "type": "proposal_created",
                        "asset_id": base["asset_id"],
                        "thread_id": base["thread_id"],
                        "proposal": persisted["proposal"],
                    },
                )
                await _update_job_state(
                    job_id,
                    status=AiJobStatus.SUCCESS,
                    progress=100,
                    message="Resolution proposal generated",
                    result_patch={
                        "proposal_id": persisted["proposal_id"],
                        "proposal_excerpt": proposal_text[:1200],
                    },
                    session_id=final_session_id or None,
                    agent_backend=thread_backend,
                    finalize=True,
                    termination_confirmed_dead=result.get("termination_confirmed_dead"),
                )
                return

            if job_kind == JOB_KIND_RESOLUTION_REWRITE:
                await _update_job_state(
                    job_id,
                    progress=48,
                    message="Rewriting document from proposal",
                    context_patch={
                        "proposal_id": run_state["proposal_id"],
                        "thread_workspace": thread_cwd,
                        "rewrite_scope": run_state["rewrite_scope"],
                        "selection_mode": run_state["selection_mode"],
                        "anchor_text": run_state["anchor_text"],
                        "block_text": run_state["block_text"],
                        "context_version_id": run_state["context_version_id"],
                        "effective_anchor": run_state["effective_anchor"],
                    },
                )
                result = await run_cli_single_turn(
                    prompt,
                    thread_cwd,
                    session_id=resume_session_id,
                    should_cancel=lambda: _is_cancel_requested(job_id),
                    backend_name=thread_backend,
                    fork_session=fork_first_turn,
                )
                if fork_first_turn:
                    await task_cli_state_service.record_thread_session_id_async(
                        base["thread_id"], str(result.get("session_id") or "")
                    )
                rewrite_payload = _parse_rewrite_payload(str(result.get("text") or ""))
                rewrite_scope = run_state["rewrite_scope"] or str(rewrite_payload.get("scope") or "anchor").strip().lower()
                rewritten_text = str(rewrite_payload.get("anchor_text") or "").strip()
                rewritten_markdown = str(rewrite_payload.get("document_markdown") or "").strip()
                final_session_id = str(result.get("session_id") or "").strip()
                if rewrite_scope == "document" and not rewritten_markdown:
                    raise ValueError("Rewritten document markdown is empty")
                if rewrite_scope != "document" and not rewritten_text:
                    raise ValueError("Rewritten block text is empty")

                persisted = await run_db_txn(
                    lambda db: _persist_asset_rewrite_sync(
                        db,
                        base=run_state,
                        proposal_text=run_state["proposal_text"],
                        rewritten_text=rewritten_text,
                        rewrite_scope=rewrite_scope,
                        rewritten_markdown=rewritten_markdown,
                        selection_mode=run_state["selection_mode"],
                        run_token=run_token,
                    )
                )
                await asset_discussion_ws_manager.broadcast(
                    base["asset_id"],
                    {
                        "type": "proposal_created",
                        "asset_id": base["asset_id"],
                        "thread_id": base["thread_id"],
                        "proposal": persisted["proposal"],
                    },
                )
                await _update_job_state(
                    job_id,
                    status=AiJobStatus.SUCCESS,
                    progress=100,
                    message="Resolution proposal rewrite completed",
                    result_patch={
                        "proposal_id": persisted["proposal_id"],
                        "rewrite_excerpt": (rewritten_text or rewritten_markdown)[:1200],
                    },
                    session_id=final_session_id or None,
                    agent_backend=thread_backend,
                    finalize=True,
                    termination_confirmed_dead=result.get("termination_confirmed_dead"),
                )
                return

            await _update_job_state(job_id, progress=24, message="Preparing AI prompt")

            await _update_job_state(
                job_id,
                progress=46,
                message="Calling AI engine",
                context_patch={
                    "selected_text": run_state["selected_text"] or "",
                    "anchor_block_text": run_state["anchor_block_text"],
                    "neighbor_text": run_state["neighbor_text"],
                    "history_lines": run_state["history_lines"][-10:],
                    "project_path": run_state["project_path"],
                    "thread_workspace": thread_cwd,
                },
            )

            result = await run_cli_single_turn(
                prompt,
                thread_cwd,
                session_id=resume_session_id,
                should_cancel=lambda: _is_cancel_requested(job_id),
                backend_name=thread_backend,
                fork_session=fork_first_turn,
            )
            if fork_first_turn:
                await task_cli_state_service.record_thread_session_id_async(
                    base["thread_id"], str(result.get("session_id") or "")
                )
            reply = str(result.get("text") or "").strip()
            final_session_id = str(result.get("session_id") or "").strip()

            persisted = await run_db_txn(
                lambda db: _persist_asset_reply_sync(
                    db,
                    base=run_state,
                    reply=reply,
                    thread_backend=thread_backend,
                    job_id=job_id,
                    run_token=run_token,
                )
            )
            await asset_discussion_ws_manager.broadcast(
                base["asset_id"],
                {
                    "type": "message_created",
                    "asset_id": base["asset_id"],
                    "thread_id": base["thread_id"],
                    "message": persisted["message"],
                },
            )
            await _update_job_state(
                job_id,
                status=AiJobStatus.SUCCESS,
                progress=100,
                message="AI reply completed",
                result_patch={"message_id": persisted["message_id"]},
                session_id=final_session_id or None,
                agent_backend=thread_backend,
                finalize=True,
                termination_confirmed_dead=result.get("termination_confirmed_dead"),
            )
    except AgentAttemptFencedError:
        logger.info("Discarded fenced asset attempt: job={}", job_id)
        return
    except Exception as exc:
        status_after_error = await _get_job_status(job_id)
        if _is_cancel_requested(job_id) or status_after_error == AiJobStatus.CANCELLED:
            _clear_cancel_event(job_id)
            return
        logger.exception(f"Asset AI job failed: {exc}")
        failed_message = "Resolution proposal failed" if job_kind == JOB_KIND_RESOLUTION_PROPOSAL else "AI reply failed"
        await _update_job_state(
            job_id,
            status=AiJobStatus.FAILED,
            progress=100,
            message=failed_message,
            error_message=str(exc),
            finalize=True,
        )
        if job_kind in {JOB_KIND_RESOLUTION_PROPOSAL, JOB_KIND_RESOLUTION_REWRITE}:
            return
        try:
            failure_state = await run_db_txn(
                lambda db: _persist_asset_failure_message_sync(
                    db,
                    job_id=job_id,
                    error_text=str(exc),
                    run_token=run_token,
                )
            )
            if failure_state:
                await asset_discussion_ws_manager.broadcast(
                    failure_state["asset_id"],
                    {
                        "type": "message_created",
                        "asset_id": failure_state["asset_id"],
                        "thread_id": failure_state["message"]["thread_id"],
                        "message": failure_state["message"],
                    },
                )
        except Exception as msg_exc:
            logger.warning(f"Failed to append asset AI failure message: {msg_exc}")
def _sync_engine_session_sync(
    db: Session,
    job_id: str,
    session_id: str,
    run_token: Optional[str] = None,
) -> bool:
    """引擎 session 上报落库（线程内执行，由 run_db_txn 包装）；返回是否继续广播。"""
    job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
    if not job or not job.task_id:
        return True
    if not _attempt_is_current_sync(db, job_id=job_id, run_token=run_token):
        return False
    task = db.query(SddTask).filter(SddTask.id == job.task_id).first()
    if task and (
        job.session_revision is None
        or int(task.session_revision or -1) == int(job.session_revision)
    ):
        task.session_id = session_id
        return True
    return False


async def _on_engine_session(session_id: str, job_id: str) -> None:
    if not job_id:
        return
    attempt = current_agent_attempt()
    run_token = attempt.run_token if attempt else None
    proceed = await run_db_txn(
        lambda db: _sync_engine_session_sync(db, job_id, session_id, run_token)
    )
    if not proceed:
        return
    await _update_job_state(job_id, session_id=session_id)


async def _on_engine_hitl(
    prompt: str,
    hitl_type: str,
    options: Optional[list],
    context: Optional[str],
    job_id: str,
) -> None:
    if not job_id:
        return
    await _update_job_state(
        job_id,
        progress=58,
        message="Waiting for confirmation input",
        context_patch={
            "pending_confirmation": {
                "prompt": prompt,
                "kind": hitl_type,
                "options": options or [],
                "context": context or "",
                "requested_at": datetime.utcnow().isoformat() + "Z",
            }
        },
    )


def _apply_task_chat_job_interrupted(
    db: Session,
    job: SddAiJob,
    task: Optional[SddTask],
    reason: str,
    *,
    message: Optional[str] = None,
    session_id: Optional[str] = None,
    context_patch: Optional[Dict[str, Any]] = None,
    result_patch: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """把 TASK_CHAT 作业和所属任务标记为可恢复的 INTERRUPTED。

    自动失败（底层 API 报错、超时、欠费、网络抖动等）不应进入终态 FAILED；
    FAILED 只允许用户通过失败复盘/关闭流程显式标记。
    """
    now = datetime.utcnow()
    resolved_session_id = str(
        session_id or job.session_id or (getattr(task, "session_id", None) or "")
    ).strip() or None
    reason_text = str(reason or "AI 执行异常")[:500]
    job.status = AiJobStatus.INTERRUPTED
    job.progress = 100
    job.message = message or "AI 执行异常，可继续发送消息恢复"
    job.error_message = None
    job.session_id = resolved_session_id
    job.interrupt_reason = reason_text
    job.interrupted_by_id = None
    job.interrupted_at = now
    job.finished_at = now
    patch = {"interrupted": True, "interrupted_at": now.isoformat() + "Z"}
    if context_patch:
        patch.update(context_patch)
    job.context_json = _merge_json(job.context_json, patch)
    if result_patch:
        job.result_json = _merge_json(job.result_json, result_patch)
    if task and task.status not in {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.BASELINED}:
        # 用户已显式关闭/失败的任务不能被引擎回调降级回 INTERRUPTED。
        task.status = TaskStatus.INTERRUPTED
        task.session_id = resolved_session_id
        task.error_message = None
        task.interrupt_reason = reason_text
        task.interrupted_by_id = None
        task.interrupted_at = now
    _clear_cancel_event(job.id)
    db.commit()
    db.refresh(job)
    if task:
        db.refresh(task)
    return serialize_job(job)


def _mark_task_chat_job_interrupted_sync(
    db: Session,
    *,
    job_id: str,
    reason: str,
    message: Optional[str],
    session_id: Optional[str],
    context_patch: Optional[Dict[str, Any]],
    result_patch: Optional[Dict[str, Any]],
    run_token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """中断标记 DB 段（线程内执行，由 run_db_txn 包装）。"""
    token = str(run_token or "").strip()
    query = db.query(SddAiJob).filter(
        SddAiJob.id == job_id,
        SddAiJob.channel == AiJobChannel.TASK_CHAT,
        SddAiJob.status == AiJobStatus.RUNNING,
        SddAiJob.cancel_requested_at.is_(None),
    )
    if token:
        query = query.filter(
            SddAiJob.run_token == token,
            SddAiJob.worker_boot_id == WORKER_BOOT_ID,
        )
    else:
        # Direct/unit callers can execute the legacy path before the durable
        # queue has claimed an attempt.  It is safe only for an entirely
        # unowned RUNNING row; any claimed attempt still requires its token.
        query = query.filter(
            SddAiJob.run_token.is_(None),
            SddAiJob.worker_boot_id.is_(None),
        )
    job = query.with_for_update().first()
    if (
        not job
    ):
        return None
    task = db.query(SddTask).filter(SddTask.id == job.task_id).first() if job.task_id else None
    if (
        task
        and job.session_revision is not None
        and int(task.session_revision or -1) != int(job.session_revision)
    ):
        return None
    return _apply_task_chat_job_interrupted(
        db,
        job,
        task,
        reason,
        message=message,
        session_id=session_id,
        context_patch=context_patch,
        result_patch=result_patch,
    )


async def _mark_task_chat_job_interrupted(
    job_id: str,
    reason: str,
    *,
    message: Optional[str] = None,
    session_id: Optional[str] = None,
    context_patch: Optional[Dict[str, Any]] = None,
    result_patch: Optional[Dict[str, Any]] = None,
    run_token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if not job_id:
        return None
    payload = await run_db_txn(
        lambda db: _mark_task_chat_job_interrupted_sync(
            db,
            job_id=job_id,
            reason=reason,
            message=message,
            session_id=session_id,
            context_patch=context_patch,
            result_patch=result_patch,
            run_token=run_token or (
                current_agent_attempt().run_token if current_agent_attempt() else None
            ),
        )
    )
    if payload:
        await _broadcast_job_payload(payload, final=False)
    return payload


def _engine_result_gate_sync(
    job_id: str,
    *,
    success: bool,
    run_token: Optional[str] = None,
) -> bool:
    """结果回调前置检查（线程内执行，由 run_db 包装）；返回是否继续处理。

    WAITING_HITL 的失败结果不改变作业状态（保持挂起等待人工输入）；
    成功结果照常走 finalize。
    """
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job or job.status in FINAL_STATUSES:
            return False
        if not _attempt_is_current_sync(
            db,
            job_id=job_id,
            run_token=run_token,
            allow_waiting_hitl=True,
        ):
            return False
        if job.status in {AiJobStatus.INTERRUPTED, AiJobStatus.REVERTED}:
            return False
        if job.status == AiJobStatus.WAITING_HITL and not success:
            return False
        return True
    finally:
        db.close()


async def _on_engine_result(
    success: bool,
    result: str,
    duration_ms: Optional[int],
    cost_usd: Optional[float],
    job_id: str,
) -> None:
    if not job_id:
        return
    attempt = current_agent_attempt()
    run_token = attempt.run_token if attempt else None
    proceed = await run_db(
        _engine_result_gate_sync,
        job_id,
        success=success,
        run_token=run_token,
    )


    if not proceed:
        return

    await _update_job_state(
        job_id,
        progress=90,
        message="Agent result received; finalizing process lifecycle",
        result_patch={
            "candidate_success": bool(success),
            "candidate_result": str(result or "")[:1600],
            "duration_ms": duration_ms,
            "cost_usd": cost_usd,
        },
        run_token=run_token,
    )


async def confirmation_delivery_available(
    *,
    task_id: str,
    interaction_id: str,
    job_id: Optional[str] = None,
) -> bool:
    """Return whether the current long-connection engine owns this confirmation."""
    engine = get_engine(task_id)
    if engine is None:
        return False
    if job_id and str(engine.current_job_id or "") != str(job_id):
        return False
    return bool(engine.can_deliver_confirmation(interaction_id))


async def deliver_confirmation_response(
    *,
    task_id: str,
    interaction_id: str,
    response: str,
    job_id: Optional[str] = None,
) -> bool:
    """Wake the already-running provider through the service boundary."""
    engine = get_engine(task_id)
    if engine is None:
        return False
    if job_id and str(engine.current_job_id or "") != str(job_id):
        return False
    return await engine.deliver_confirmation_response(interaction_id, response)


async def _on_engine_error(error_text: str, job_id: str) -> None:
    if not job_id:
        return
    attempt = current_agent_attempt()
    await _mark_task_chat_job_interrupted(
        job_id,
        str(error_text or "AI execution failed"),
        message="AI 执行异常，可继续发送消息恢复",
        run_token=attempt.run_token if attempt else None,
    )


async def _execute_task_chat_job(job_id: str) -> None:
    try:
        await _execute_task_chat_job_inner(job_id)
    finally:
        # 取消事件在执行结束（含取消/异常/超时）后统一回收，避免泄漏；
        # 置位后不能立刻清除（见 mark_task_chat_jobs_cancelled）。
        _clear_cancel_event(job_id)


def _load_task_chat_job_dispatch_sync(job_id: str) -> Optional[Dict[str, Any]]:
    """任务聊天 job 分发前置查询（线程内执行，由 run_db 包装）。

    返回 None：job 不存在/通道不符/已终态（无需执行）；
    返回 {"job_kind": "diagnosis_summary"}：转交诊断总结执行器；
    否则返回完整分发上下文。
    """
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job or job.channel != AiJobChannel.TASK_CHAT:
            return None
        # 防止“停止/中断”发生在排队阶段时，任务稍后仍被启动
        if job.status in {
            AiJobStatus.INTERRUPTED,
            AiJobStatus.CANCELLED,
            AiJobStatus.REVERTED,
            AiJobStatus.TERMINATING,
            AiJobStatus.ORPHANED,
        }:
            return None
        job_context = job.context_json if isinstance(job.context_json, dict) else {}
        if str(job_context.get("job_kind") or "").strip().upper() == JOB_KIND_DIAGNOSIS_SUMMARY:
            return {"job_kind": "diagnosis_summary"}
        task = db.query(SddTask).filter(SddTask.id == job.task_id).first()
        if not task:
            raise ValueError("Task not found for AI job")
        return {
            "task_id": task.id,
            "workspace_id": task.workspace_id,
            "creator_id": job.creator_id,
            "session_id": job.session_id,
            "prompt_text": job.prompt_text,
            "hitl_resume_prompt": str(job_context.get("hitl_resume_prompt") or "").strip() or None,
        }
    finally:
        db.close()


async def _execute_task_chat_job_inner(job_id: str) -> None:
    state = await run_db(_load_task_chat_job_dispatch_sync, job_id)
    if state is None:
        return
    if state.get("job_kind") == "diagnosis_summary":
        # 问题定位任务「一键总结问题案例」：一次性总结任务，不写会话气泡，走独立执行器
        return await _execute_diagnosis_summary_job(job_id)

    with bind_task_context(
        task_id=state["task_id"],
        workspace_id=state["workspace_id"],
        user_id=state["creator_id"],
    ), bind_ai_context(
        job_id=job_id,
        task_id=state["task_id"],
        session_id=state["session_id"],
        event_type="execute_task_chat_job",
    ):
        prompt = str(state.get("hitl_resume_prompt") or state["prompt_text"] or "").strip()
        if not prompt:
            raise ValueError("Empty task chat prompt")

        await _update_job_state(
            job_id,
            progress=45,
            message="Dispatching user prompt to AI engine",
            context_patch={"source": "task_chat_user_input"},
        )

        await _run_task_chat_turn(job_id, prompt)


def _collect_diagnosis_transcript(task_id: str, max_chars: int = 60000) -> str:
    """汇总问题定位任务的会话文本（user/assistant/system），供一键总结使用。"""
    from app.domains.task.models.chat import ChatMessage, MessageRole, MessageType
    from app.domains.task.services import task_service as task_service_module

    db = SessionLocal()
    try:
        rows = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.task_id == task_id,
                ChatMessage.message_type.in_([MessageType.TEXT, MessageType.INIT_REASON]),
            )
            .all()
        )
        rows = task_service_module.sort_chat_messages(rows)
        parts: List[str] = []
        for row in rows:
            role = str(row.role.value) if hasattr(row.role, "value") else str(row.role)
            if role == "user":
                label = "用户"
            elif role == "system":
                label = "系统"
            else:
                label = "AI"
            content = str(row.content or "").strip()
            if not content:
                continue
            parts.append(f"[{label}] {content}")
        transcript = "\n\n".join(parts).strip()
    finally:
        db.close()
    if not transcript:
        return ""
    limit = max(0, int(max_chars or 60000))
    if len(transcript) > limit:
        head = transcript[: limit * 3 // 4]
        tail = transcript[-limit // 4:]
        transcript = f"{head}\n\n…（中间内容过长已截断）…\n\n{tail}"
    return transcript


def _resolve_task_project_path(task) -> str:
    """解析任务 CLI 工作目录（与正常会话引擎一致）。"""
    project_path = str(getattr(task, "project_path", None) or "").strip() or "."
    try:
        os.makedirs(project_path, exist_ok=True)
    except Exception:
        pass
    return project_path


def _prepare_diagnosis_summary_sync(
    db: Session,
    job_id: str,
    run_token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """诊断总结准备段（线程内执行，由 run_db_txn 包装）。

    一次性完成 job/task 加载、transcript 汇总、project_path 解析与
    任务粘性 backend 解析，返回纯数据（prompt 文本 + 各字段）。
    """
    job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
    if not job:
        return None
    if not _attempt_is_current_sync(db, job_id=job_id, run_token=run_token):
        raise AgentAttemptFencedError(f"Diagnosis summary attempt is no longer current: {job_id}")
    task = db.query(SddTask).filter(SddTask.id == job.task_id).first()
    if not task or getattr(task, "task_type", None) != "DIAGNOSIS":
        raise ValueError("Only diagnosis tasks support diagnosis summary")
    job_context = job.context_json if isinstance(job.context_json, dict) else {}
    source_session_id = str(
        job_context.get("source_session_id") or job.session_id or task.session_id or ""
    ).strip()
    project_path = _resolve_task_project_path(task)
    transcript = _collect_diagnosis_transcript_sync(db, task.id)
    prompt = diagnosis_result_service.build_diagnosis_summary_prompt(task, transcript)
    task_backend = resolve_task_backend(db, task.id) if task.id else None
    return {
        "job_id": str(job.id),
        "run_token": run_token or str(job.run_token or "") or None,
        "task_id": task.id,
        "workspace_id": task.workspace_id,
        "creator_id": str(job.creator_id or ""),
        "source_session_id": source_session_id,
        "project_path": project_path,
        "prompt": prompt,
        "task_backend": task_backend,
    }


def _collect_diagnosis_transcript_sync(db: Session, task_id: str, max_chars: int = 60000) -> str:
    """汇总问题定位任务的会话文本（user/assistant/system），供一键总结使用。"""
    from app.domains.task.models.chat import ChatMessage, MessageType
    from app.domains.task.services import task_service as task_service_module

    rows = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.task_id == task_id,
            ChatMessage.message_type.in_([MessageType.TEXT, MessageType.INIT_REASON]),
        )
        .all()
    )
    rows = task_service_module.sort_chat_messages(rows)
    parts: List[str] = []
    for row in rows:
        role = str(row.role.value) if hasattr(row.role, "value") else str(row.role)
        if role == "user":
            label = "用户"
        elif role == "system":
            label = "系统"
        else:
            label = "AI"
        content = str(row.content or "").strip()
        if not content:
            continue
        parts.append(f"[{label}] {content}")
    transcript = "\n\n".join(parts).strip()
    if not transcript:
        return ""
    limit = max(0, int(max_chars or 60000))
    if len(transcript) > limit:
        head = transcript[: limit * 3 // 4]
        tail = transcript[-limit // 4:]
        transcript = f"{head}\n\n…（中间内容过长已截断）…\n\n{tail}"
    return transcript


def _collect_diagnosis_transcript(task_id: str, max_chars: int = 60000) -> str:
    """兼容入口：自建 session 汇总 transcript（调用方应在线程内调用）。"""
    db = SessionLocal()
    try:
        return _collect_diagnosis_transcript_sync(db, task_id, max_chars)
    finally:
        db.close()


async def _execute_diagnosis_summary_job(job_id: str) -> None:
    """问题定位任务「一键总结问题案例」执行器。

    汇总会话 → 按原定位结果 JSON 契约生成结构化结果 → 反填定位结果卡片并广播。
    与正常聊天不同：不向会话写入 AI 回复气泡。
    准备段/结果落库段经 DB executor；CLI 调用期间不持有任何 session。
    """
    attempt = current_agent_attempt()
    run_token = attempt.run_token if attempt else None
    prepared = await run_db_txn(
        lambda db: _prepare_diagnosis_summary_sync(db, job_id, run_token)
    )
    if prepared is None:
        return
    task_id = prepared["task_id"]
    creator_id = prepared["creator_id"]
    source_session_id = prepared["source_session_id"]

    with bind_task_context(
        task_id=task_id,
        workspace_id=prepared["workspace_id"],
        user_id=creator_id,
    ), bind_ai_context(
        job_id=job_id,
        task_id=task_id,
        session_id=None,
        event_type="diagnosis_summary",
    ):
        await _update_job_state(
            job_id,
            status=AiJobStatus.RUNNING,
            progress=40,
            message="正在汇总会话并生成定位结果",
            context_patch={"job_kind": JOB_KIND_DIAGNOSIS_SUMMARY},
        )
        project_path = prepared["project_path"]
        task_backend = prepared["task_backend"]
        prompt = prepared["prompt"]

        await _update_job_state(job_id, progress=55, message="AI 正在生成结构化定位结果")
        can_fork = bool(source_session_id and backend_supports_fork(task_backend))
        summary_mode = "fork_read_only" if can_fork else "transcript_fallback"
        await _update_job_state(
            job_id,
            context_patch={"summary_session_mode": summary_mode},
        )
        summary_session_id: Optional[str] = None
        native_fork_on_resume = False
        if can_fork:
            try:
                summary_session_id = await fork_session_for_backend(
                    task_backend,
                    source_session_id,
                    source_dir=project_path,
                    target_dir=project_path,
                )
                # Claude's adapter stages the snapshot and the CLI performs the
                # actual child-session creation with --fork-session.  Server
                # adapters already return the newly-created child id.
                native_fork_on_resume = str(task_backend or "") == "claude-code"
            except Exception as exc:
                # Fork preserves provider-side context.  The persisted
                # transcript is the deterministic fallback for stale snapshots.
                logger.warning(
                    "Diagnosis summary fork failed; using transcript fallback: task={}, backend={}, error={}",
                    task_id,
                    task_backend,
                    exc,
                )
                can_fork = False
                summary_mode = "transcript_fallback"
                await _update_job_state(
                    job_id,
                    progress=55,
                    message="原会话快照不可用，正在使用持久化会话记录生成总结",
                    context_patch={
                        "summary_session_mode": summary_mode,
                        "fork_error": str(exc)[:800],
                    },
                )

        try:
            result = await run_cli_single_turn(
                prompt,
                project_path,
                session_id=summary_session_id if can_fork else None,
                max_attempts=1,
                should_cancel=lambda: _is_cancel_requested(job_id),
                backend_name=task_backend,
                fork_session=native_fork_on_resume,
                permission_mode="read-only",
            )
        except RuntimeError as exc:
            if await _is_job_cancelled_or_final(job_id):
                logger.info("Diagnosis summary run cancelled; discard result: job={}", job_id)
                return
            raise

        # 用户已停止（或任务已终态）时丢弃结果：不能反填定位结果卡片、不能广播
        if await _is_job_cancelled_or_final(job_id):
            logger.info("Diagnosis summary cancelled after run; discard result: job={}", job_id)
            return

        summary_text = str(result.get("text") or "").strip()
        if not summary_text:
            raise ValueError("Diagnosis summary reply is empty")

        payload = diagnosis_result_service.extract_payload_from_text(summary_text)
        if payload is None:
            raise ValueError("Failed to parse structured diagnosis summary")

        def _persist_diagnosis_result_sync(db: Session) -> Dict[str, Any]:
            if not _attempt_is_current_sync(db, job_id=job_id, run_token=run_token):
                raise AgentAttemptFencedError(
                    f"Diagnosis summary attempt is no longer current: {job_id}"
                )
            latest_task = db.query(SddTask).filter(SddTask.id == task_id).first()
            if not latest_task:
                raise ValueError("Task disappeared during diagnosis summary")
            result_record = diagnosis_result_service.upsert_diagnosis_result_from_ai(
                db,
                task=latest_task,
                payload=payload,
                actor_user_id=creator_id,
            )
            return {
                "task_id": str(latest_task.id),
                "source_chat_message_id": str(result_record.source_chat_message_id or "") or None,
            }

        summary_state = await run_db_txn(_persist_diagnosis_result_sync)
        if summary_state["source_chat_message_id"]:
            await diagnosis_result_service.publish_diagnosis_result_message(
                task_id=summary_state["task_id"],
                message_id=summary_state["source_chat_message_id"],
            )

        await _update_job_state(
            job_id,
            status=AiJobStatus.SUCCESS,
            progress=100,
            message="定位结果已生成",
            result_patch={
                "summary_excerpt": str(
                    payload.summary or payload.root_cause or summary_text
                )[:1200],
                "summary_source": "diagnosis_summary",
            },
            session_id=str(result.get("session_id") or "") or None,
            agent_backend=task_backend,
            finalize=True,
            termination_confirmed_dead=result.get("termination_confirmed_dead"),
        )


def _load_task_chat_turn_state_sync(db: Session, job_id: str) -> Optional[Dict[str, Any]]:
    job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
    if not job or not job.task_id:
        return None
    task = db.query(SddTask).filter(SddTask.id == job.task_id).first()
    if not task:
        raise ValueError("Task not found")
    # 任务粘性 backend：首次运行固化到 sdd_tasks，之后工作区切换不影响本任务
    task_backend = resolve_task_backend(db, task.id)
    return {
        "task_id": task.id,
        "workspace_id": task.workspace_id,
        "creator_id": job.creator_id,
        "fresh_session": bool((job.context_json if isinstance(job.context_json, dict) else {}).get("fresh_session")),
        "task_backend": task_backend,
        "job_session_id": job.session_id,
        "session_turn_id": getattr(job, "session_turn_id", None),
        "session_revision": getattr(job, "session_revision", None),
    }


async def _run_task_chat_turn(job_id: str, prompt: str) -> None:
    state = await run_db_txn(lambda db: _load_task_chat_turn_state_sync(db, job_id))
    if state is None:
        return
    fresh_session = state["fresh_session"]
    task_backend = state["task_backend"]
    engine = get_engine(state["task_id"])
    if not engine:
        engine = WorkflowEngine(
            task_id=state["task_id"],
            ws_id=state["workspace_id"],
            user_id=state["creator_id"],
            job_id=job_id,
            backend_name=task_backend,
            on_result=_on_engine_result,
            on_hitl=_on_engine_hitl,
            on_session=_on_engine_session,
            on_error=_on_engine_error,
            attempt=current_agent_attempt(),
        )
        if state["job_session_id"] and not fresh_session:
            engine.session_id = state["job_session_id"]
    else:
        engine.set_job_callbacks(
            job_id=job_id,
            on_result=_on_engine_result,
            on_hitl=_on_engine_hitl,
            on_session=_on_engine_session,
            on_error=_on_engine_error,
            attempt=current_agent_attempt(),
        )
        if fresh_session:
            engine.session_id = None
        elif state["job_session_id"]:
            # 恢复上次中断（或继续）的会话：总是以 DB 持久化的 session_id
            # 为准，保证下次启动使用 --resume 重新进入原会话，而不是新开会话。
            engine.session_id = state["job_session_id"]
    engine.session_turn_id = state["session_turn_id"]
    engine.session_revision = state["session_revision"]

    with bind_task_context(
        task_id=state["task_id"],
        workspace_id=state["workspace_id"],
        user_id=state["creator_id"],
    ), bind_ai_context(
        job_id=job_id,
        task_id=state["task_id"],
        session_id=state["job_session_id"],
        event_type="run_task_chat_turn",
    ):
        await _update_job_state(job_id, status=AiJobStatus.RUNNING, progress=55, message="AI is processing")

        if fresh_session:
            await engine.run(prompt, fresh_session=True)
        elif engine.session_id and not engine.running:
            await engine.send_message(prompt, job_id=job_id)
        else:
            await engine.run(prompt)

        await _finalize_task_chat_job_from_engine(job_id, engine)


def _finalize_task_chat_job_sync(
    db: Session,
    *,
    job_id: str,
    last_result_success: Optional[bool],
    last_result_text: str,
    is_timeout_interrupted: bool,
    engine_session_id: Optional[str],
    run_token: Optional[str] = None,
    termination_confirmed_dead: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """finalize DB 段（线程内执行，由 run_db 包装）；返回 None 表示无需收尾。"""
    job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
    if (
        not job
        or job.status in FINAL_STATUSES
        or job.status in {AiJobStatus.WAITING_HITL, AiJobStatus.INTERRUPTED}
    ):
        return None
    if not _attempt_is_current_sync(db, job_id=job_id, run_token=run_token):
        return None
    if run_token and (
        str(job.run_token or "") != run_token
        or job.worker_boot_id != WORKER_BOOT_ID
        or job.cancel_requested_at is not None
    ):
        return None
    task = db.query(SddTask).filter(SddTask.id == job.task_id).first() if job.task_id else None
    if (
        task
        and job.session_revision is not None
        and int(task.session_revision or -1) != int(job.session_revision)
    ):
        return None
    if (
        _has_active_process_ownership(job)
        and termination_confirmed_dead is not True
    ):
        job.status = AiJobStatus.ORPHANED
        job.message = "Agent process could not be confirmed dead"
        job.error_message = "Agent process tree remained alive after timeout"
        job.failure_code = "PROCESS_TREE_STILL_ALIVE"
        job.terminal_reason = "PROCESS_TREE_STILL_ALIVE"
        job.lease_expires_at = datetime.utcnow()
        job.orphaned_at = job.orphaned_at or datetime.utcnow()
        db.commit()
        db.refresh(job)
        return serialize_job(job)
    if last_result_success is True:
        job.status = AiJobStatus.SUCCESS
        job.progress = 100
        job.message = "AI reply completed"
        payload = _merge_json(job.result_json, {"result_preview": (last_result_text or "")[:1600]})
        job.result_json = payload
        job.finished_at = datetime.utcnow()
        _clear_process_ownership(job)
        db.commit()
        db.refresh(job)
        return serialize_job(job)
    session_id = str(
        engine_session_id or job.session_id or (getattr(task, "session_id", None) or "")
    ).strip() or None
    if is_timeout_interrupted:
        message = "AI 会话超时，可继续发送消息恢复"
        context_patch = {
            "timeout_interrupted": True,
            "timeout_message": last_result_text or "",
        }
        reason = last_result_text or "AI 会话超时"
    else:
        message = "AI 执行异常，可继续发送消息恢复"
        context_patch = {
            "interrupted_reason": last_result_text or "AI 执行异常",
        }
        reason = last_result_text or "AI 执行异常"
    return _apply_task_chat_job_interrupted(
        db,
        job,
        task,
        reason,
        message=message,
        session_id=session_id,
        context_patch=context_patch,
    )


async def _finalize_task_chat_job_from_engine(job_id: str, engine: WorkflowEngine) -> None:
    # Fallback for missing callback updates.
    is_timeout_interrupted = bool(getattr(engine, "last_result_interrupted", False)) or _looks_like_timeout_text(
        engine.last_result_text or ""
    )
    attempt = current_agent_attempt()
    run_token = attempt.run_token if attempt else None
    payload = await run_db_txn(
        lambda db: _finalize_task_chat_job_sync(
            db,
            job_id=job_id,
            last_result_success=getattr(engine, "last_result_success", None),
            last_result_text=engine.last_result_text or "",
            is_timeout_interrupted=is_timeout_interrupted,
            engine_session_id=getattr(engine, "session_id", None),
            run_token=run_token,
            termination_confirmed_dead=getattr(
                engine, "last_termination_confirmed_dead", None
            ),
        )
    )
    if payload is None:
        return
    is_success = str(payload.get("status") or "") == AiJobStatus.SUCCESS.value
    await _broadcast_job_payload(payload, final=is_success)
    if not is_success:
        return
    queue_key = str(payload.get("queue_key") or "")
    if queue_key:
        schedule_queue(queue_key)


def _load_job_dispatch_context_sync(job_id: str) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job:
            return None
        job_context = job.context_json if isinstance(job.context_json, dict) else {}
        return {
            "channel": job.channel,
            "queue_key": str(job.queue_key or ""),
            "task_id": str(job.task_id or ""),
            "job_kind": str(job_context.get("job_kind") or "").strip().upper(),
            "input_revision": str(job_context.get("input_revision") or ""),
        }
    finally:
        db.close()


def _load_job_failure_context_sync(job_id: str) -> Optional[Dict[str, Any]]:
    """异常收尾查询（线程内执行，由 run_db 包装）；None 表示已终态/不存在。"""
    db = SessionLocal()
    try:
        latest = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not latest or latest.status in FINAL_STATUSES or latest.status == AiJobStatus.INTERRUPTED:
            return None
        job_context = latest.context_json if isinstance(latest.context_json, dict) else {}
        return {
            "channel": latest.channel,
            "job_kind": str(job_context.get("job_kind") or "").strip().upper(),
        }
    finally:
        db.close()


async def _execute_task_baseline_job(job_id: str, task_id: str) -> None:
    if not task_id:
        raise ValueError("Baseline job has no task")
    attempt = current_agent_attempt()
    dispatch = await run_db(_load_job_dispatch_context_sync, job_id)
    env_overrides: Dict[str, str] = {}
    if attempt is not None:
        env_overrides = {
            "TRACEFORGE_RUN_TOKEN": attempt.run_token,
            "AI_JOB_ID": attempt.job_id,
            "WORKER_BOOT_ID": attempt.worker_boot_id,
        }

    async def on_process_started(identity: AgentProcessIdentity) -> bool:
        if getattr(identity, "pid", None) is None:
            return True
        if attempt is None:
            return False
        return await run_db(
            _persist_process_identity_sync,
            attempt.job_id,
            attempt.run_token,
            identity,
        )

    payload = await task_cli_state_service.run_bootstrap_for_job(
        task_id,
        run_token=attempt.run_token if attempt else None,
        expected_input_revision=(dispatch or {}).get("input_revision") or None,
        env_overrides=env_overrides or None,
        on_process_started=on_process_started,
    )
    await _update_job_state(
        job_id,
        status=AiJobStatus.SUCCESS,
        progress=100,
        message="Specification baseline ready",
        result_patch={
            "bootstrap_status": payload.get("status"),
            "spec_version_id": payload.get("spec_version_id"),
            "baseline_session_id": payload.get("baseline_session_id"),
        },
        finalize=True,
        run_token=attempt.run_token if attempt else None,
        termination_confirmed_dead=payload.get("termination_confirmed_dead"),
    )


async def _execute_job(job_id: str) -> None:
    dispatch = await run_db(_load_job_dispatch_context_sync, job_id)
    if dispatch is None:
        return
    channel = dispatch.get("channel")
    queue_key = str(dispatch.get("queue_key") or "")
    job_kind = str(dispatch.get("job_kind") or "")

    with bind_ai_context(job_id=job_id, event_type="execute_job"):
        try:
            if queue_key.startswith("REQUIREMENT_PREVIEW:"):
                # Requirement preview 作业（import/split）：输入内容持久化在
                # job.context_json，走独立队列 runner，可跨重启恢复。
                from app.domains.workspace_asset.services import workspace_asset_service
                attempt = current_agent_attempt()
                runner = (
                    workspace_asset_service.run_requirement_split_preview_job
                    if job_kind == "REQUIREMENT_SPLIT_PREVIEW"
                    else workspace_asset_service.run_requirement_import_preview_job
                )
                if attempt and "run_token" in inspect.signature(runner).parameters:
                    await runner(job_id, run_token=attempt.run_token)
                else:
                    # Keep direct/unit callers and older extension runners
                    # compatible while production runners receive the fence.
                    await runner(job_id)
                return
            if queue_key.startswith("TASK_BASELINE:") or job_kind == JOB_KIND_TASK_BASELINE:
                await _execute_task_baseline_job(
                    job_id,
                    str(dispatch.get("task_id") or ""),
                )
                return
            if channel == AiJobChannel.ASSET_THREAD:
                await _execute_asset_thread_job(job_id)
                return
            if channel == AiJobChannel.TASK_CHAT:
                await _execute_task_chat_job(job_id)
                return
            raise ValueError(f"Unsupported AI job channel: {channel}")
        except Exception as exc:
            logger.exception(f"AI job execution failed: job={job_id}, error={exc}")
            failure_context = await run_db(_load_job_failure_context_sync, job_id)
            if failure_context is None:
                return
            job_channel = failure_context["channel"]
            job_kind = failure_context["job_kind"]
            if (
                job_channel == AiJobChannel.TASK_CHAT
                and job_kind not in {JOB_KIND_DIAGNOSIS_SUMMARY, JOB_KIND_TASK_BASELINE}
            ):
                await _mark_task_chat_job_interrupted(
                    job_id,
                    str(exc),
                    message="AI 执行异常，可继续发送消息恢复",
                    run_token=(
                        current_agent_attempt().run_token
                        if current_agent_attempt()
                        else None
                    ),
                )
            else:
                await _update_job_state(
                    job_id,
                    status=AiJobStatus.FAILED,
                    progress=100,
                    message="AI execution failed",
                    error_message=str(exc),
                    finalize=True,
                )


def _load_enqueue_state_sync(job_id: str, expected_channel: Optional[AiJobChannel]) -> Optional[Dict[str, Any]]:
    """入队前置查询（线程内执行，由 run_db 包装）。"""
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job:
            return None
        if expected_channel and job.channel != expected_channel:
            raise ValueError(f"Job {job_id} channel mismatch")
        return {
            "payload": serialize_job(job),
            "queue_key": job.queue_key,
        }
    finally:
        db.close()


async def _enqueue_job(job_id: str, expected_channel: Optional[AiJobChannel] = None) -> Optional[Dict[str, Any]]:
    state = await run_db(_load_enqueue_state_sync, job_id, expected_channel)
    if state is None:
        return None
    payload = state["payload"]
    queue_key = state["queue_key"]

    await _broadcast_job_payload(payload, final=False)
    if queue_key:
        schedule_queue(queue_key)
    return payload


async def enqueue_asset_thread_job(job_id: str) -> Optional[Dict[str, Any]]:
    return await _enqueue_job(job_id, expected_channel=AiJobChannel.ASSET_THREAD)


async def enqueue_task_chat_job(job_id: str) -> Optional[Dict[str, Any]]:
    return await _enqueue_job(job_id, expected_channel=AiJobChannel.TASK_CHAT)


async def publish_job(job_id: str, *, final: bool = False) -> None:
    await _publish_job_state(job_id, final=final)


async def run_task_chat_job_now(job_id: str) -> None:
    await _execute_task_chat_job(job_id)


def mark_task_chat_jobs_cancelled(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    message: str = "Task execution stopped",
) -> List[str]:
    jobs = (
        db.query(SddAiJob)
        .filter(
            SddAiJob.workspace_id == workspace_id,
            SddAiJob.task_id == task_id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
            SddAiJob.status.notin_(list(FINAL_STATUSES)),
        )
        .all()
    )
    now = datetime.utcnow()
    job_ids: List[str] = []
    for job in jobs:
        _request_job_cancel(job.id)
        job.cancel_requested_at = now
        if job.status == AiJobStatus.PENDING:
            job.status = AiJobStatus.CANCELLED
            job.progress = 100
            job.message = message
            job.error_message = None
            job.finished_at = now
        elif job.status in {AiJobStatus.RUNNING, AiJobStatus.TERMINATING, AiJobStatus.ORPHANED}:
            job.status = AiJobStatus.TERMINATING
            job.message = "Job cancellation requested"
            job.terminal_reason = message
            job.failure_code = "CANCEL_REQUESTED"
        elif job.status == AiJobStatus.WAITING_HITL:
            # WAITING_HITL has no local CLI by contract; it can converge
            # immediately because there is no process to wait for.
            job.status = AiJobStatus.CANCELLED
            job.progress = 100
            job.message = message
            job.finished_at = now
        job_ids.append(job.id)
    if job_ids:
        db.commit()
    return job_ids


def _merge_hitl_context(
    context_json: Any,
    response: str,
    *,
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    merged = dict(context_json) if isinstance(context_json, dict) else {}
    now_iso = datetime.utcnow().isoformat() + "Z"
    pending_hitl = merged.get("pending_hitl")
    if isinstance(pending_hitl, dict):
        last_hitl = dict(pending_hitl)
        last_hitl["answered_at"] = now_iso
        last_hitl["response"] = response
        if actor_user_id:
            last_hitl["actor_user_id"] = actor_user_id
        merged["last_hitl"] = last_hitl
        merged.pop("pending_hitl", None)

    history = merged.get("hitl_responses")
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "response": response,
            "answered_at": now_iso,
            "actor_user_id": actor_user_id,
        }
    )
    merged["hitl_responses"] = history[-20:]
    return merged


def _load_hitl_resume_state_sync(db: Session, *, job_id: str, response: str) -> Optional[Dict[str, Any]]:
    """HITL 恢复准备段（线程内执行，由 run_db_txn 包装）。"""
    job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
    if not job or job.channel != AiJobChannel.TASK_CHAT or not job.task_id:
        return None
    task = db.query(SddTask).filter(SddTask.id == job.task_id).first()
    if not task:
        raise ValueError("Task not found")
    return {
        "task_id": task.id,
        "workspace_id": task.workspace_id,
        "user_id": job.creator_id,
        "session_id": job.session_id,
        # 任务粘性 backend：与任务聊天保持同一后端
        "task_backend": resolve_task_backend(db, task.id),
    }


async def _resume_task_chat_job(job_id: str, response: str) -> None:
    try:
        state = await run_db_txn(
            lambda db: _load_hitl_resume_state_sync(db, job_id=job_id, response=response)
        )
        if state is None:
            return
        task_backend = state["task_backend"]
        engine = get_engine(state["task_id"])
        if not engine:
            engine = WorkflowEngine(
                task_id=state["task_id"],
                ws_id=state["workspace_id"],
                user_id=state["user_id"],
                job_id=job_id,
                backend_name=task_backend,
                on_result=_on_engine_result,
                on_hitl=_on_engine_hitl,
                on_session=_on_engine_session,
                on_error=_on_engine_error,
                attempt=current_agent_attempt(),
            )
            if state["session_id"]:
                engine.session_id = state["session_id"]
        else:
            engine.set_job_callbacks(
                job_id=job_id,
                on_result=_on_engine_result,
                on_hitl=_on_engine_hitl,
                on_session=_on_engine_session,
                on_error=_on_engine_error,
                attempt=current_agent_attempt(),
            )
            if state["session_id"]:
                # 恢复中断/HITL 挂起会话：以 DB 持久化的 session_id 为准，
                # 保证下一步用 --resume 回到原会话而非新开会话。
                engine.session_id = state["session_id"]

        with bind_task_context(
            task_id=state["task_id"],
            workspace_id=state["workspace_id"],
            user_id=state["user_id"],
        ), bind_ai_context(
            job_id=job_id,
            task_id=state["task_id"],
            session_id=state["session_id"],
            event_type="resume_waiting_hitl_job",
        ):
            await _update_job_state(
                job_id,
                status=AiJobStatus.RUNNING,
                progress=70,
                message="Resuming AI job after human input",
            )

            if engine.session_id and not engine.running:
                await engine.send_message(response, job_id=job_id)
            else:
                await engine.run(response)

            await _finalize_task_chat_job_from_engine(job_id, engine)
    except Exception as exc:
        logger.exception(f"Failed to resume HITL AI job {job_id}: {exc}")
        await _mark_task_chat_job_interrupted(
            job_id,
            str(exc),
            message="Failed to resume job after HITL",
            run_token=(
                current_agent_attempt().run_token
                if current_agent_attempt()
                else None
            ),
        )


def _claim_hitl_response_sync(
    db: Session,
    *,
    task_id: str,
    response: str,
    job_id: Optional[str],
    actor_user_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """HITL 认领段（线程内单事务）：互斥检查 + WAITING_HITL 认领 + context 归因。"""
    # 会话/总结互斥：总结进行中禁止恢复会话（HITL 回复会重启 AI 执行）
    if find_active_summary_job(db, task_id) is not None:
        raise AiJobConflictError("一键总结问题案例进行中，请等待完成或停止后再回复")
    query = (
        db.query(SddAiJob)
        .filter(
            SddAiJob.task_id == task_id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
            SddAiJob.status == AiJobStatus.WAITING_HITL,
        )
        .order_by(SddAiJob.created_at.asc())
    )
    if job_id:
        query = query.filter(SddAiJob.id == job_id)
    job = query.first()
    if not job:
        return None

    # WAITING_HITL has no local process.  The response starts a fresh durable
    # attempt through the normal queue claim path, so it must not be marked
    # RUNNING by the request handler without a new lease/run_token.
    job.status = AiJobStatus.PENDING
    job.progress = 0
    job.message = "Human response queued"
    job.error_message = None
    job.run_token = None
    job.worker_id = None
    job.worker_boot_id = None
    job.heartbeat_at = None
    job.lease_expires_at = None
    job.process_pid = None
    job.process_started_at = None
    job.process_group_id = None
    job.cancel_requested_at = None
    pending_hitl = job.context_json.get("pending_hitl") if isinstance(job.context_json, dict) else None
    job.context_json = _merge_hitl_context(
        job.context_json,
        response,
        actor_user_id=actor_user_id,
    )
    job.context_json["hitl_resume_prompt"] = response
    db.commit()
    db.refresh(job)
    if isinstance(pending_hitl, dict):
        try:
            context_token_service.record_hitl(
                db,
                workspace_id=job.workspace_id,
                task_id=str(job.task_id or ""),
                ai_job_id=job.id,
                session_id=job.session_id,
                prompt=str(pending_hitl.get("prompt") or ""),
                response=response,
                source_kind="hitl_response",
            )
        except Exception as exc:
            logger.warning(f"Failed to record HITL context attribution for job {job.id}: {exc}")
    return serialize_job(job)


async def resume_waiting_hitl_job(
    *,
    task_id: str,
    response: str,
    job_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    payload = await run_db_txn(
        lambda db: _claim_hitl_response_sync(
            db, task_id=task_id, response=response, job_id=job_id, actor_user_id=actor_user_id,
        )
    )
    if payload is None:
        return None

    await _broadcast_job_payload(payload, final=False)
    await enqueue_task_chat_job(payload["id"])
    return payload


def cancel_job(
    db: Session,
    *,
    workspace_id: str,
    job_id: str,
) -> Optional[SddAiJob]:
    job = (
        db.query(SddAiJob)
        .filter(
            SddAiJob.id == job_id,
            SddAiJob.workspace_id == workspace_id,
        )
        .first()
    )
    if not job:
        return None
    if job.status in FINAL_STATUSES:
        return job
    _request_job_cancel(job.id)
    now = datetime.utcnow()
    job.cancel_requested_at = now
    if job.status == AiJobStatus.PENDING or job.status == AiJobStatus.WAITING_HITL:
        job.status = AiJobStatus.CANCELLED
        job.progress = 100
        job.message = "Job cancelled by user"
        job.error_message = None
        job.finished_at = now
    else:
        job.status = AiJobStatus.TERMINATING
        job.message = "Job cancellation requested"
        job.terminal_reason = "USER_CANCEL"
        job.failure_code = "CANCEL_REQUESTED"
    db.commit()
    db.refresh(job)
    return job
