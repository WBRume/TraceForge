"""
Unified AI async job orchestration service.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import random
import re
import socket
import time
import uuid
import inspect
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_

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
    AgentAttemptRuntimeState,
    AgentProcessIdentity,
    AgentRunResult,
    AgentStopResult,
    EXECUTION_KIND_LOCAL_PROCESS,
    EXECUTION_KIND_REMOTE_SESSION,
    ProviderCallState,
    bind_agent_attempt,
    bind_agent_attempt_runtime,
    current_agent_attempt,
    current_agent_attempt_key,
    current_agent_attempt_runtime,
    mark_provider_call_unresolved,
    record_attempt_provider_call_stop,
    record_provider_call_result,
    record_provider_call_session_started,
    reset_agent_attempt,
    reset_agent_attempt_runtime,
)
from app.agents.errors import (
    AgentCancelledError,
    AgentError,
    AgentProviderError,
    AgentTimeoutError,
)
from app.agents.process_supervisor import (
    agent_stop_result_from_termination,
    containment_capability,
    containment_id_for_run_token,
    process_supervisor,
)
from app.domains.ai.services import ai_job_convergence_service as convergence
from app.domains.ai.services.ai_job_convergence_service import (
    AttemptConvergenceRequest,
    ConvergenceIntent,
    PROCESS_TREE_STILL_ALIVE,
    REMOTE_STOP_UNCONFIRMED,
    AttemptFinalizerEvidence as _FinalizerEvidence,
    evidence_from_stop_result,
    resolve_attempt_evidence,
)
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


@dataclass(frozen=True)
class JobExecutionOutcome:
    """一次 ``_execute_job`` 的明确执行结果（doc §8.3）。

    规则：
    - 只有收到 ``AgentRunResult`` 或明确的 provider terminal/result event，
      才允许 ``provider_outcome_seen=True``；
    - “函数正常返回”“异常没有逃出”“failure finalizer 已执行”都不能推断
      provider outcome；
    - ``_execute_job()`` 的所有分支都必须返回本对象；内部捕获的异常必须
      写入 ``error``，不得丢失。
    """

    requested_status: Optional[AiJobStatus] = None
    message: Optional[str] = None
    result_patch: Optional[Dict[str, Any]] = None
    context_patch: Optional[Dict[str, Any]] = None
    provider_result: Optional[AgentRunResult] = None
    stop_result: Optional[AgentStopResult] = None
    error: Optional[BaseException] = None
    provider_outcome_seen: bool = False


def _attempt_is_current_sync(
    db: Session,
    *,
    job_id: str,
    run_token: Optional[str],
    allow_waiting_hitl: bool = False,
    allowed_statuses: Optional[set] = None,
) -> bool:
    """Check the durable attempt fence inside the same DB transaction as a write."""
    if not run_token:
        return True
    job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
    if not job:
        return False
    if allowed_statuses is not None:
        allowed = set(allowed_statuses)
    else:
        allowed = {AiJobStatus.RUNNING}
        if allow_waiting_hitl:
            allowed.add(AiJobStatus.WAITING_HITL)
    return bool(
        job.status in allowed
        and str(job.run_token or "") == str(run_token)
        and str(job.worker_boot_id or "") == WORKER_BOOT_ID
        and job.cancel_requested_at is None
    )


def _attempt_execution_kind() -> str:
    """Durable execution kind of the bound attempt (never inferred from PIDs)."""
    attempt = current_agent_attempt()
    kind = getattr(attempt, "execution_kind", None) if attempt else None
    return kind if kind in (EXECUTION_KIND_LOCAL_PROCESS, EXECUTION_KIND_REMOTE_SESSION) else EXECUTION_KIND_LOCAL_PROCESS


def _resolve_attempt_evidence(
    *,
    execution_kind: Optional[str] = None,
    runtime: Optional[AgentAttemptRuntimeState] = None,
    stop_result: Optional[AgentStopResult] = None,
    typed_error: Optional[BaseException] = None,
    provider_result: Optional[Any] = None,
    fallback_started: Optional[bool] = None,
    fallback_dead: Optional[bool] = None,
    fallback_failure_code: Optional[str] = None,
    fallback_remaining_pids: tuple = (),
) -> _FinalizerEvidence:
    """唯一证据解析入口（doc §6.2）：identity-aware runtime 为权威。"""
    return resolve_attempt_evidence(
        execution_kind=execution_kind or _attempt_execution_kind(),
        runtime=runtime if runtime is not None else current_agent_attempt_runtime(),
        stop_result=stop_result,
        typed_error=typed_error,
        provider_result=provider_result,
        fallback_started=fallback_started,
        fallback_dead=fallback_dead,
        fallback_failure_code=fallback_failure_code,
        fallback_remaining_pids=fallback_remaining_pids,
    )


def _attempt_evidence(exc: Optional[BaseException] = None) -> tuple[bool, Optional[bool]]:
    """Return (process_started, dead) from the attempt runtime + typed exception.

    The identity-aware runtime aggregate is authoritative; the typed exception
    attributes are only a compatibility fallback (doc §6.2 rule 2-4).
    """
    evidence = _resolve_attempt_evidence(typed_error=exc)
    return (evidence.process_started, evidence.termination_confirmed_dead)


def _attempt_process_started(exc: Optional[BaseException] = None) -> bool:
    return _attempt_evidence(exc)[0]


def _attempt_termination_evidence(exc: Optional[BaseException] = None) -> Optional[bool]:
    """Read the authoritative attempt-local death proof (with typed-exception fallback)."""
    return _attempt_evidence(exc)[1]


def _bridge_stop_result(bridge: Any) -> Optional[AgentStopResult]:
    """Convert the bridge's last local termination into the unified stop result.

    返回 None 表示该 bridge 没有（或尚未产生）本地终止结果；远程 bridge
    （shim）的停止证据由 ``record_attempt_remote_stop`` 写入 runtime。
    """
    termination = getattr(bridge, "last_termination", None)
    if termination is None:
        return None
    return agent_stop_result_from_termination(termination)


def _close_unresolved_provider_call(
    call: Optional[Any],
    *,
    stop_acknowledged: bool = False,
    tree_dead: bool = False,
) -> None:
    """Close an unresolved provider call when its outcome can never arrive.

    P1（07e04775 §4.3/§4.4）：明确 stop ACK（绑定本次 bridge/调用的会话
    停止）或已证明死亡的本地进程树都意味着该调用已确定终结。关闭未决
    记录（STARTED/UNKNOWN -> ENDED，``result_success`` 保持 None）是为了
    让重试产生的新 ENDED 不被旧未决阻塞；它绝不伪造 provider outcome
    成败，收敛仍优先消费真实 result（``result_success``）与 stop ACK。
    已 ENDED 的记录保持不变。
    """
    if call is None or not (stop_acknowledged or tree_dead):
        return
    if call.state in (ProviderCallState.STARTED, ProviderCallState.UNKNOWN):
        call.state = ProviderCallState.ENDED
    if stop_acknowledged:
        # P0（doc 审计 0c381413 §2.4）：把本次停止 ACK 绑定到具体 call。
        # attempt 级单槽 ACK 只是诊断；只有按 call 绑定（attempt_key /
        # call_id / provider_session_id 一致）的证据才能授权该调用的终态。
        # 绑定被拒时保持已关闭状态不变——被拒绝的 ACK 绝不授权终态。
        record_attempt_provider_call_stop(
            call,
            AgentStopResult(
                execution_kind=EXECUTION_KIND_REMOTE_SESSION,
                stop_acknowledged=True,
            ),
        )


def _provider_call_ready_for_retry(
    call: Optional[Any],
    attempt: Optional[AgentAttemptContext],
) -> bool:
    """Retry gate: the previous call must be finished before overlapping.

    P1（07e04775 §4.3）：远程不能因为 ``process_started=False`` 就允许与
    未结束调用重叠——前一次调用必须已 ENDED（真实 result 或绑定 ACK 终止）
    才允许启动下一次。无证据登记能力（runtime 缺失）时保持旧行为。
    """
    if call is None:
        return True
    if call.state in (ProviderCallState.ENDED, ProviderCallState.NOT_STARTED):
        return True
    kind = getattr(attempt, "execution_kind", None) or EXECUTION_KIND_LOCAL_PROCESS
    if kind == EXECUTION_KIND_REMOTE_SESSION:
        # STARTED/UNKNOWN：与未结束的远程调用重叠被禁止。
        return False
    # 本地进程路径：重试前提（进程树确认死亡）已在外层检查；未决记录
    # 不阻塞本地新进程，但其证据绝不会被冒用（resolve 按 call 隔离）。
    return True


def process_containment_readiness() -> Dict[str, Any]:
    """Attempt-containment readiness for local Agent jobs (doc 7.4).

    When the deployment requires containment, an unavailable provider must
    make readiness fail and refuse new local CLI attempts; ordinary
    REST/read-only endpoints may keep serving per the existing readiness
    layering.
    """
    capability = containment_capability()
    required = bool(getattr(settings, "AGENT_REQUIRE_PROCESS_CONTAINMENT", False))
    return {
        **capability,
        "required": required,
        "ok": (not required) or bool(capability.get("available")),
    }


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
        declared_kind = str(job.process_execution_kind or "").strip()
        if declared_kind and declared_kind != EXECUTION_KIND_LOCAL_PROCESS:
            # 显式声明的非本地执行类别不允许 attach 本地 PID（doc §7.3）。
            logger.error(
                "Persisted process identity rejected: execution_kind mismatch: job_id={}, kind={}",
                job.id,
                declared_kind,
            )
            db.rollback()
            return False
        job.process_pid = int(identity.pid)
        job.process_started_at = identity.started_at.replace(tzinfo=None)
        job.process_group_id = identity.process_group_id
        job.process_containment_id = identity.containment_id
        # Explicit execution-kind declaration (doc 6.3): a backend that
        # attaches a local process identity is by definition LOCAL_PROCESS.
        # 这只是校验/兜底，不是首次声明位置：claim 事务已写入显式 kind。
        job.process_execution_kind = EXECUTION_KIND_LOCAL_PROCESS
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
    job.process_containment_id = None
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
        "process_containment_id": job.process_containment_id,
        "process_execution_kind": job.process_execution_kind,
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


def _clear_cancel_event_for_payload(payload: Dict[str, Any]) -> None:
    """可恢复 INTERRUPTED 行必须回收取消事件，避免恢复回合被旧信号误杀。"""
    if str(payload.get("status") or "") == AiJobStatus.INTERRUPTED.value:
        _clear_cancel_event(str(payload.get("id") or ""))


async def _broadcast_job_payload(payload: Dict[str, Any]) -> None:
    """Broadcast one job payload.

    非终态（RUNNING/WAITING_HITL/TERMINATING/ORPHANED/INTERRUPTED）只产生
    ``*_update``；``*_done``/``*_failed`` 只允许真正的 FINAL 状态
    （doc §5 C5/§9.2）。调用方无权覆盖 final 判定。
    """
    status = str(payload.get("status") or "")
    final = status in {item.value for item in FINAL_STATUSES}
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


async def _publish_job_state(job_id: str) -> None:
    payload = await _load_job_payload(job_id)
    if not payload:
        return
    await _broadcast_job_payload(payload)


def _row_execution_kind(job: SddAiJob) -> str:
    """Read the durable explicit execution kind; never infer from PIDs.

    兼容存量行（claim 之前写入的 RUNNING 行）：缺省按 LOCAL_PROCESS 处理
    （保守：要求本地死亡证明），并通过日志暴露，便于发现漏写。
    """
    kind = str(job.process_execution_kind or "").strip()
    if kind in (EXECUTION_KIND_LOCAL_PROCESS, EXECUTION_KIND_REMOTE_SESSION):
        return kind
    if job.process_execution_kind is None and job.status == AiJobStatus.RUNNING:
        logger.warning(
            "Running AI job has no explicit execution kind; defaulting to LOCAL_PROCESS: job_id={}",
            job.id,
        )
    return EXECUTION_KIND_LOCAL_PROCESS


def _resolve_execution_kind_for_backend(backend_name: Optional[str]) -> str:
    """Map a backend name to its declared execution kind (doc §7 chain)."""
    name = str(backend_name or "").strip() or "claude-code"
    if name in ("claude-code", "mock"):
        return EXECUTION_KIND_LOCAL_PROCESS
    try:
        from app.agents.registry import AGENT_BACKENDS
        from app.agents.adapters import register_all

        if not AGENT_BACKENDS:
            register_all()
        backend_cls = AGENT_BACKENDS.get(name)
        kind = str(getattr(getattr(backend_cls, "capabilities", None), "execution_kind", "") or "").strip()
        if kind in (EXECUTION_KIND_LOCAL_PROCESS, EXECUTION_KIND_REMOTE_SESSION):
            return kind
    except Exception:
        pass
    return EXECUTION_KIND_LOCAL_PROCESS


def _resolve_execution_kind_for_claim(
    db: Session,
    *,
    task_id: Optional[str],
    workspace_id: Optional[str],
) -> str:
    """Claim 时在同一事务内解析并写入 execution kind（doc §7.2）。"""
    name: Optional[str] = None
    if task_id:
        row = db.query(SddTask.agent_backend).filter(SddTask.id == task_id).first()
        name = str(row[0] or "").strip() or None if row else None
    if not name and workspace_id:
        try:
            from app.agents.selection import resolve_workspace_backend

            name = resolve_workspace_backend(db, workspace_id)
        except Exception:
            name = None
    if not name:
        try:
            from app.agents.selection import default_backend_name

            name = default_backend_name()
        except Exception:
            name = None
    return _resolve_execution_kind_for_backend(name)


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
    process_started: Optional[bool] = None,
    termination_confirmed_dead: Optional[bool] = None,
    failure_code: Optional[str] = None,
    remaining_pids: tuple = (),
    evidence: Optional[_FinalizerEvidence] = None,
) -> Optional[Dict[str, Any]]:
    """状态更新 DB 段（线程内执行，由 run_db 包装）。

    返回 {"payload": ..., "broadcast": bool, "is_final": bool}；
    broadcast=False 表示被 fence/终态幂等拦下，仅回读当前 payload。

    finalize=True 的所有业务终态都必须经过唯一 convergence 事务
    （doc §8/C2）；本函数不再拥有独立的死亡证据决策表，传入的
    process_started/termination_confirmed_dead 只作为无身份 fallback 交给
    唯一 resolver。
    """
    is_terminal_write = bool(finalize) or status in FINAL_STATUSES
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job:
            return None
        if is_terminal_write:
            resolved_evidence = evidence
            if resolved_evidence is None:
                resolved_evidence = resolve_attempt_evidence(
                    execution_kind=_row_execution_kind(job),
                    fallback_started=process_started,
                    fallback_dead=termination_confirmed_dead,
                    fallback_failure_code=failure_code,
                    fallback_remaining_pids=remaining_pids,
                )
            request = AttemptConvergenceRequest(
                job_id=job_id,
                run_token=str(run_token or ""),
                worker_boot_id=WORKER_BOOT_ID if run_token else "",
                requested_status=status,
                reason=str(error_message or ""),
                evidence=resolved_evidence,
                result_patch=result_patch,
                context_patch=context_patch,
                message=message,
                progress=progress,
                error_message=error_message,
                session_id=session_id,
                agent_backend=agent_backend,
                intent=ConvergenceIntent.NORMAL_FINALIZE,
            )
            result = convergence.converge_job_attempt_sync(db, request)
            if not result.changed:
                return {"payload": serialize_job(job), "broadcast": False, "is_final": False}
            return {"payload": result.payload, "broadcast": True, "is_final": result.is_final}
        if run_token:
            token_text = str(run_token)
        else:
            # 活动状态写入必须 fail-closed（doc §4.5.3）：无 durable run token
            # 的调用方不允许改写活动 attempt 状态（迟到的 callback 可能因
            # 缺少 fence 把已取消的 job 写回 RUNNING）。终态写入已统一走
            # convergence 事务，本分支只剩普通运行态写入。
            return {"payload": serialize_job(job), "broadcast": False, "is_final": False}
        if job.channel == AiJobChannel.TASK_CHAT and job.task_id and job.session_revision is not None:
            task = db.query(SddTask).filter(SddTask.id == job.task_id).first()
            if not task or int(task.session_revision or -1) != int(job.session_revision):
                # An undo or a newer session generation has fenced this worker.
                # Do not let a late callback resurrect the old job state.
                return {"payload": serialize_job(job), "broadcast": False, "is_final": False}
        writable_statuses = {
            AiJobStatus.PENDING,
            AiJobStatus.RUNNING,
            AiJobStatus.WAITING_HITL,
            AiJobStatus.INTERRUPTED,
        }
        values: Dict[str, Any] = {}
        if status is not None:
            values["status"] = status
        if progress is not None:
            values["progress"] = max(0, min(100, int(progress)))
        if message is not None:
            values["message"] = message
        if error_message is not None:
            values["error_message"] = error_message
        if session_id is not None:
            values["session_id"] = session_id
        if agent_backend is not None:
            values["agent_backend"] = agent_backend
        if context_patch:
            values["context_json"] = _merge_json(job.context_json, context_patch)
        if result_patch:
            values["result_json"] = _merge_json(job.result_json, result_patch)
        if status == AiJobStatus.RUNNING and job.started_at is None:
            values["started_at"] = datetime.utcnow()
        # 单条 affected-row CAS（doc §4.5.3）：token/boot/状态/取消位全部在
        # UPDATE 谓词中判定，消除 SELECT 与 UPDATE 之间的窗口。affected != 1
        # 时按 fenced no-op 处理，不得广播调用方准备的旧 payload。
        affected = (
            db.query(SddAiJob)
            .filter(
                SddAiJob.id == job_id,
                SddAiJob.run_token == token_text,
                SddAiJob.worker_boot_id == WORKER_BOOT_ID,
                SddAiJob.status.in_(writable_statuses),
                SddAiJob.cancel_requested_at.is_(None),
            )
            .update(values, synchronize_session=False)
        )
        db.commit()
        # synchronize_session=False 不会同步 identity map；expire 后重读，
        # 保证返回的 payload 反映 CAS 后的真实行状态。
        db.expire_all()
        if int(affected or 0) != 1:
            refreshed = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
            return {
                "payload": serialize_job(refreshed) if refreshed else serialize_job(job),
                "broadcast": False,
                "is_final": False,
            }
        refreshed = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        payload = serialize_job(refreshed) if refreshed else serialize_job(job)
        return {"payload": payload, "broadcast": True, "is_final": False}
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
    process_started: Optional[bool] = None,
    termination_confirmed_dead: Optional[bool] = None,
    failure_code: Optional[str] = None,
    remaining_pids: tuple = (),
    evidence: Optional[_FinalizerEvidence] = None,
    stop_result: Optional[AgentStopResult] = None,
    typed_error: Optional[BaseException] = None,
    provider_result: Optional[AgentRunResult] = None,
) -> Optional[Dict[str, Any]]:
    attempt = current_agent_attempt()
    effective_run_token = run_token or (attempt.run_token if attempt else None)
    is_terminal_write = bool(finalize) or status in FINAL_STATUSES
    resolved_evidence = evidence
    if is_terminal_write and resolved_evidence is None:
        resolved_evidence = _resolve_attempt_evidence(
            execution_kind=(
                getattr(attempt, "execution_kind", None) if attempt else None
            ),
            stop_result=stop_result,
            typed_error=typed_error,
            provider_result=provider_result,
            fallback_started=process_started,
            fallback_dead=termination_confirmed_dead,
            fallback_failure_code=failure_code,
            fallback_remaining_pids=remaining_pids,
        )
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
        evidence=resolved_evidence,
    )
    if result is None:
        return None
    payload = result["payload"]
    if not result["broadcast"]:
        return payload
    is_final = result["is_final"]
    await _broadcast_job_payload(payload)
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


def _runtime_worker_stale_seconds(name: str) -> float:
    setting_name = (
        "AI_JOB_REAPER_STALE_SECONDS"
        if name == "reaper"
        else "AI_JOB_DISPATCHER_STALE_SECONDS"
    )
    return max(0.1, float(getattr(settings, setting_name, 60.0) or 60.0))


def _runtime_worker_operation_timeout_seconds() -> float:
    return max(
        0.1,
        float(getattr(settings, "AI_JOB_WORKER_OPERATION_TIMEOUT_SECONDS", 30.0) or 30.0),
    )


def _runtime_timestamp_age(value: Any) -> Optional[float]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return max(0.0, (datetime.utcnow() - parsed).total_seconds())
        return max(0.0, (datetime.now(parsed.tzinfo) - parsed).total_seconds())
    except (TypeError, ValueError):
        return None


def runtime_worker_health() -> Dict[str, Any]:
    """Return bounded readiness telemetry for the durable runtime loops."""
    threshold = max(1, int(getattr(settings, "AI_JOB_WORKER_FAILURE_ALERT_THRESHOLD", 3) or 3))
    result: Dict[str, Any] = {}
    overall = True
    now_monotonic = time.monotonic()
    for name in ("reaper", "dispatcher"):
        task = _runtime_worker_task(name)
        state = dict(_RUNTIME_WORKER_HEALTH.get(name, {}))
        alive = bool(task is not None and not task.done())
        failure_count = int(state.get("failure_count") or 0)
        started_monotonic = state.get("iteration_started_monotonic")
        if started_monotonic is None:
            iteration_age = max(
                0.0,
                float(state.get("current_iteration_age_seconds") or 0.0),
            )
        else:
            iteration_age = max(0.0, now_monotonic - float(started_monotonic))
        last_success_monotonic = state.get("last_success_monotonic")
        last_success_age = (
            max(0.0, now_monotonic - float(last_success_monotonic))
            if last_success_monotonic is not None
            else _runtime_timestamp_age(state.get("last_success_at"))
        )
        stalled = iteration_age > _runtime_worker_operation_timeout_seconds()
        stale = last_success_age is None or last_success_age > _runtime_worker_stale_seconds(name)
        healthy = alive and failure_count < threshold and not stalled and not stale
        if stalled:
            state["state"] = "stalled"
            state.setdefault("last_error_type", "WorkerOperationTimeout")
        state.update({
            "alive": alive,
            "running": alive,
            "healthy": healthy,
            "current_iteration_age_seconds": round(iteration_age, 3),
        })
        # Monotonic timestamps are process-local implementation details and
        # should not become part of the public readiness contract.
        state.pop("iteration_started_monotonic", None)
        state.pop("last_success_monotonic", None)
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
            iteration_started_monotonic=started_monotonic,
        )
        operation_task = asyncio.create_task(_await_runtime_operation(operation))
        cancel_after_completion = False
        try:
            # asyncio.wait leaves the operation task untouched on timeout.
            # That matters for sync DB work running in a worker thread: the
            # watchdog may report a stall, but the next iteration must not
            # start until this exact operation has finished.  It also keeps
            # cancellation of the outer worker task observable on Windows'
            # Proactor event loop.
            try:
                done, _ = await asyncio.wait(
                    {operation_task},
                    timeout=_runtime_worker_operation_timeout_seconds(),
                )
            except asyncio.CancelledError:
                # If the operation completed in the same loop turn as the
                # cancellation request, record that completed iteration before
                # re-raising.  This keeps readiness telemetry truthful while
                # still allowing the worker task to stop promptly.
                if not operation_task.done():
                    raise
                result = operation_task.result()
                done = {operation_task}
                cancel_after_completion = True
            if operation_task not in done:
                _set_runtime_worker_health(
                    name,
                    state="stalled",
                    alive=True,
                    running=True,
                    last_error_at=datetime.utcnow().isoformat() + "Z",
                    last_error_type="WorkerOperationTimeout",
                    last_error=(
                        f"{name} operation exceeded "
                        f"{_runtime_worker_operation_timeout_seconds():g}s"
                    ),
                )
                # Do not launch a replacement scan.  The same operation owns
                # the worker until it genuinely completes or the process is
                # shut down.
                result = await operation_task
            else:
                result = operation_task.result()
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
                iteration_started_monotonic=None,
                last_success_monotonic=time.monotonic(),
            )
            delay = max(1, interval)
        except asyncio.CancelledError:
            if not operation_task.done():
                operation_task.cancel()
            _set_runtime_worker_health(name, state="cancelled", alive=False, running=False)
            raise
        except Exception as exc:
            if not operation_task.done():
                operation_task.cancel()
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
                iteration_started_monotonic=None,
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
        if cancel_after_completion:
            raise asyncio.CancelledError
        await asyncio.sleep(delay)


async def _await_runtime_operation(operation: Callable[[], Any]) -> Any:
    result = operation()
    if inspect.isawaitable(result):
        return await result
    return result


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


_DIRTY_INTERRUPTED_OWNERSHIP_PREDICATE = lambda: or_(
    SddAiJob.run_token.isnot(None),
    SddAiJob.worker_boot_id.isnot(None),
    SddAiJob.process_pid.isnot(None),
    SddAiJob.process_group_id.isnot(None),
    SddAiJob.lease_expires_at.isnot(None),
)


def _row_has_leaked_interrupted_ownership(job: SddAiJob) -> bool:
    """Pre-upgrade dirty INTERRUPTED rows that still claim process ownership.

    These rows must first converge back to ORPHANED and then run the existing
    stop/verify/backoff flow: the process may still be alive, so the fields
    must never be cleared directly.
    """
    if job.status != AiJobStatus.INTERRUPTED:
        return False
    return bool(
        job.run_token is not None
        or job.worker_boot_id is not None
        or job.process_pid is not None
        or job.process_group_id is not None
        or job.lease_expires_at is not None
    )


def _list_reclaimable_jobs_sync() -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        rows = (
            db.query(SddAiJob)
            .filter(
                or_(
                    and_(
                        SddAiJob.status.in_([
                            AiJobStatus.RUNNING,
                            AiJobStatus.TERMINATING,
                            AiJobStatus.ORPHANED,
                        ]),
                        SddAiJob.manual_intervention_required.isnot(True),
                        (SddAiJob.next_reap_at.is_(None) | (SddAiJob.next_reap_at <= now)),
                    ),
                    # Compatibility scan for dirty INTERRUPTED rows written by
                    # earlier releases: adopt them through the reaper instead
                    # of exposing a resumable session with a possibly live CLI.
                    and_(
                        SddAiJob.status == AiJobStatus.INTERRUPTED,
                        _DIRTY_INTERRUPTED_OWNERSHIP_PREDICATE(),
                        SddAiJob.manual_intervention_required.isnot(True),
                    ),
                )
            )
            .all()
        )
        result: List[Dict[str, Any]] = []
        for job in rows:
            if _row_has_leaked_interrupted_ownership(job):
                # The attempt already stopped writing; a leaked ownership row
                # is reclaimed immediately instead of waiting for its lease.
                reason = "INTERRUPTED_OWNERSHIP_LEAK"
            else:
                owner_gone = str(job.worker_boot_id or "") != WORKER_BOOT_ID
                lease_expired = bool(job.lease_expires_at and job.lease_expires_at <= now)
                if not owner_gone and not lease_expired:
                    continue
                reason = "WORKER_RESTART" if owner_gone else "LEASE_EXPIRED"
            result.append(
                {
                    "job_id": str(job.id),
                    "run_token": str(job.run_token or ""),
                    "expected_run_token": str(job.run_token or "") or None,
                    "process_pid": job.process_pid,
                    "process_started_at": job.process_started_at,
                    "process_group_id": job.process_group_id,
                    "process_containment_id": job.process_containment_id,
                    "job_started_at": job.started_at,
                    "queue_key": str(job.queue_key or ""),
                    "reason": reason,
                    "attempt_count": int(job.attempt_count or 0),
                    "worker_boot_id": job.worker_boot_id,
                    "reap_failure_count": int(job.reap_failure_count or 0),
                    # durable remote stop locator（doc §10.4.1）：reaper 在
                    # worker 重启后必须能凭持久化行定位并停止远程 provider
                    # session，而不是只做本地进程检查。
                    "execution_kind": str(job.process_execution_kind or "").strip() or None,
                    "agent_backend": str(job.agent_backend or "").strip() or None,
                    "session_id": str(job.session_id or "").strip() or None,
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
                or_(
                    SddAiJob.status.in_([
                        AiJobStatus.RUNNING,
                        AiJobStatus.TERMINATING,
                        AiJobStatus.ORPHANED,
                    ]),
                    and_(
                        SddAiJob.status == AiJobStatus.INTERRUPTED,
                        _DIRTY_INTERRUPTED_OWNERSHIP_PREDICATE(),
                    ),
                ),
                SddAiJob.manual_intervention_required.isnot(True),
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


def _reap_stop_reason(row: Dict[str, Any], result: Any) -> str:
    if result is not None and getattr(result, "error_message", None):
        return str(result.error_message)
    return str(row.get("reason") or "REAP")


def _reap_failure_code(row: Dict[str, Any], result: Any) -> str:
    if result is not None and (
        getattr(result, "error_code", None) or getattr(result, "failure_code", None)
    ):
        return str(
            getattr(result, "error_code", None)
            or getattr(result, "failure_code", None)
        )
    return str(row.get("reason") or "REAP")


async def _stop_remote_session(row: Dict[str, Any]) -> AgentStopResult:
    """Stop a remote provider session from durable reaper metadata (doc §10.4.2).

    - 使用持久化 backend/session id，不依赖内存 runtime；
    - 必须走 ``cancel_persisted_session(session_id)`` durable 契约：真实
      DSH/OpenCode adapter 忽略 ``cancel(run_id=...)`` 的 run_id（doc 修复
      方案 §9.3 的 P1-3），持久化 locator 绝不能被静默丢弃；
    - 只有服务端明确成功响应才 ``stop_acknowledged=True``；
    - timeout / 断线 / 找不到 backend / 缺少 session id 一律返回结构化
      NACK/UNKNOWN，绝不因为本地没有 PID 而声称远程 session 已停止；
    - ACK / NACK / 异常三条路径都必须释放 adapter 资源（``close()``）。
    """
    reason = str(row.get("reason") or "REAP")
    backend_name = str(row.get("agent_backend") or "").strip()
    session_id = str(row.get("session_id") or "").strip()
    if not backend_name or not session_id:
        return AgentStopResult(
            execution_kind=EXECUTION_KIND_REMOTE_SESSION,
            stop_acknowledged=False,
            failure_code="REMOTE_STOP_LOCATOR_MISSING",
            error_message=(
                f"Persisted remote stop locator is incomplete: backend={backend_name or '-'}, "
                f"session_id={session_id or '-'}"
            ),
        )
    from app.agents.selection import create_agent_backend_by_name

    try:
        backend = create_agent_backend_by_name(backend_name)
    except Exception as exc:
        return AgentStopResult(
            execution_kind=EXECUTION_KIND_REMOTE_SESSION,
            stop_acknowledged=False,
            failure_code="REMOTE_BACKEND_UNAVAILABLE",
            error_message=str(exc) or type(exc).__name__,
        )
    try:
        result = await backend.cancel_persisted_session(session_id)
        if not isinstance(result, AgentStopResult):
            return AgentStopResult(
                execution_kind=EXECUTION_KIND_REMOTE_SESSION,
                stop_acknowledged=False,
                failure_code=REMOTE_STOP_UNCONFIRMED,
                error_message="backend cancel returned no structured acknowledgement",
            )
        return result
    except Exception as exc:
        if isinstance(exc, asyncio.CancelledError):
            raise
        return AgentStopResult(
            execution_kind=EXECUTION_KIND_REMOTE_SESSION,
            stop_acknowledged=False,
            failure_code="REMOTE_CANCEL_FAILED",
            error_message=str(exc) or type(exc).__name__,
        )
    finally:
        try:
            await backend.close()
        except asyncio.CancelledError:
            raise
        except Exception as close_exc:
            logger.warning(
                "Remote backend close failed during reaper stop: backend={}, error={}",
                backend_name,
                close_exc,
            )


async def _stop_attempt_processes(row: Dict[str, Any], token: str) -> Any:
    """Run the fixed reaper order (doc 8 / §10.4.2) for one adopted attempt.

    0. REMOTE_SESSION 行按持久化 locator 分派 provider stop（durable stop）；
    1. in-memory registration under the current run token;
    2. persisted PID identity (stop_persisted);
    3. run-token /proc discovery fallback for a previous boot whose PID was
       never attached; the exact token match is the containment equivalent
       until a dedicated cgroup provider is deployed.
    A missing PID alone is never treated as proof of death: when discovery is
    unavailable the attempt stays ORPHANED.
    """
    if str(row.get("execution_kind") or "") == EXECUTION_KIND_REMOTE_SESSION:
        remote_result = await _stop_remote_session(row)
        # 结构化 NACK/UNKNOWN 保留给 convergence 决策（ORPHANED）。
        if not remote_result.stop_acknowledged:
            return remote_result
        # ACK：仍核对本地是否残留受管进程（同 token 的本地孤儿树）。
        local = await process_supervisor.stop_attempt(token, str(row.get("reason") or "REAP"))
        if local is not None and not local.confirmed_dead:
            return local
        return AgentStopResult(
            execution_kind=EXECUTION_KIND_REMOTE_SESSION,
            stop_acknowledged=True,
        )
    result = await process_supervisor.stop_attempt(token, str(row.get("reason") or "REAP"))
    if result is None and row.get("process_pid"):
        # root PID 已消失不代表进程组已消失：stop_persisted 会对 PGID 继续
        # 发送信号，并在提供持久化 run token 时执行完整 token discovery
        # 兜底（doc 修复方案 §5.4）。
        result = await process_supervisor.stop_persisted(
            row["process_pid"],
            row.get("process_started_at"),
            row.get("reason") or "REAP",
            process_group_id=row.get("process_group_id"),
            run_token=str(row.get("run_token") or "") or None,
            not_before=row.get("job_started_at"),
        )
    persisted_token = str(row.get("run_token") or "")
    if result is None and token and token == persisted_token:
        # Only scan for the token that was actually issued to this attempt's
        # environment.  A freshly invented adoption token was never attached
        # to any process, so an empty scan for it would be a manufactured
        # death proof, not evidence (doc 8: 没有找到 PID/新 token ≠ 已死亡).
        result = await process_supervisor.stop_by_run_token_discovery(
            token,
            str(row.get("reason") or "REAP"),
            not_before=row.get("job_started_at"),
        )
    return result


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
        result = await _stop_attempt_processes(row, token)
        if isinstance(result, AgentStopResult):
            # 远程 reaper：ACK 才允许业务终态并清 ownership；NACK/UNKNOWN
            # 落 ORPHANED 并更新 backoff（doc §10.4.3）。
            payload = await run_db(
                _finish_termination_sync,
                row["job_id"],
                token,
                confirmed_dead=bool(result.stop_acknowledged),
                reason=_reap_stop_reason(row, result),
                failure_code=_reap_failure_code(row, result),
                evidence=evidence_from_stop_result(
                    result,
                    remote_session_started=True,
                    execution_kind=EXECUTION_KIND_REMOTE_SESSION,
                ),
            )
        else:
            # Only a verified-empty tree/containment may clear ownership; an
            # unproven attempt keeps ORPHANED with backoff and a structured
            # failure reason (doc 8.7/8.8).
            confirmed_dead = bool(result is not None and result.confirmed_dead)
            payload = await run_db(
                _finish_termination_sync,
                row["job_id"],
                token,
                confirmed_dead=confirmed_dead,
                reason=_reap_stop_reason(row, result),
                failure_code=_reap_failure_code(row, result),
            )
        if payload:
            reclaimed += 1
            await _broadcast_job_payload(payload)
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
                    last_success_monotonic=time.monotonic(),
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
    """Durably fence attempts before their in-process owners are stopped.

    所有 RUNNING -> TERMINATING 写入都走唯一 termination request 事务
    （doc §4.5.2）；本函数只负责收集 reaper/stop 需要的行元数据。
    """
    from app.domains.ai.services.ai_job_convergence_service import (
        AttemptTerminationRequest,
        request_attempt_termination_in_txn,
    )

    db = SessionLocal()
    try:
        candidate_ids = [
            str(row[0])
            for row in (
                db.query(SddAiJob.id)
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
        ]
        result: List[Dict[str, Any]] = []
        changed = False
        for job_id in sorted(candidate_ids):
            termination = request_attempt_termination_in_txn(
                db,
                AttemptTerminationRequest(
                    job_id=job_id,
                    reason=reason,
                    mode="WORKER_SHUTDOWN",
                ),
            )
            job = (
                db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
            )
            if job is None:
                continue
            if termination.changed:
                changed = True
            result.append(
                {
                    "job_id": str(job.id),
                    "run_token": str(job.run_token or ""),
                    "process_pid": job.process_pid,
                    "process_started_at": job.process_started_at,
                    "process_group_id": job.process_group_id,
                    "process_containment_id": job.process_containment_id,
                    "job_started_at": job.started_at,
                    "reason": reason,
                }
            )
        if changed:
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
                run_token=token or None,
                not_before=row.get("job_started_at"),
            )
        if result is None and token:
            result = await process_supervisor.stop_by_run_token_discovery(
                token,
                "WORKER_SHUTDOWN",
                not_before=row.get("job_started_at"),
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
            _clear_cancel_event_for_payload(payload)
            await _broadcast_job_payload(payload)
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

        # Claim 必须在同一事务内解析并写入显式 execution kind（doc §7.2/C4），
        # 运行中的 job 不允许长期保持 None。
        claim_target = (
            db.query(SddAiJob.workspace_id, SddAiJob.task_id)
            .filter(SddAiJob.id == job_id)
            .first()
        )
        execution_kind = _resolve_execution_kind_for_claim(
            db,
            task_id=str(claim_target[1]) if claim_target and claim_target[1] else None,
            workspace_id=str(claim_target[0]) if claim_target and claim_target[0] else None,
        )
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
                    # Attempt containment id derived from the run token: it is
                    # durable before any child PID exists, so a worker that is
                    # SIGKILLed before PID attach can still be reclaimed by
                    # containment id / run token (doc 7.1/7.3).
                    SddAiJob.process_containment_id: containment_id_for_run_token(run_token),
                    SddAiJob.process_execution_kind: execution_kind,
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
        kind = str(job.process_execution_kind or "").strip()
        return AgentAttemptContext(
            job_id=str(job.id),
            task_id=str(job.task_id) if job.task_id else None,
            queue_key=str(job.queue_key or ""),
            run_token=str(job.run_token),
            worker_id=str(job.worker_id or WORKER_ID),
            worker_boot_id=str(job.worker_boot_id),
            attempt_count=int(job.attempt_count or 0),
            execution_kind=(
                kind
                if kind in (EXECUTION_KIND_LOCAL_PROCESS, EXECUTION_KIND_REMOTE_SESSION)
                else EXECUTION_KIND_LOCAL_PROCESS
            ),
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


def _termination_evidence_for_row(
    row: Optional[SddAiJob],
    *,
    confirmed_dead: Optional[bool],
    failure_code: Optional[str],
    reason: Optional[str],
) -> _FinalizerEvidence:
    """Build termination evidence for a row read outside the lock.

    The explicit row kind wins over any caller-provided kind; ``dead`` stays
    exactly what the stop/verify flow produced (True/False/None).  For
    REMOTE_SESSION rows, a persisted session id or an explicit unconfirmed
    stop means the remote session existed — the "never established" escape
    must not fire (it would CANCEL a live remote turn instead of ORPHANing).
    """
    kind = str(getattr(row, "process_execution_kind", None) or "").strip()
    if kind not in (EXECUTION_KIND_LOCAL_PROCESS, EXECUTION_KIND_REMOTE_SESSION):
        kind = EXECUTION_KIND_LOCAL_PROCESS
    started = bool(
        row is not None
        and (row.process_pid is not None or row.process_group_id is not None)
    )
    remote_started = False
    if kind == EXECUTION_KIND_REMOTE_SESSION:
        remote_started = bool(
            (row is not None and str(getattr(row, "session_id", None) or "").strip())
            or confirmed_dead is False
        )
    return _FinalizerEvidence(
        execution_kind=kind,
        process_started=started,
        termination_confirmed_dead=None if confirmed_dead is None else bool(confirmed_dead),
        remote_stop_acknowledged=None,
        failure_code=failure_code,
        error_message=reason,
        remaining_pids=(),
        source="termination",
        remote_session_started=remote_started,
    )


def _converge_termination_sync(
    job_id: str,
    run_token: str,
    *,
    evidence: _FinalizerEvidence,
    reason: str,
    failure_code: Optional[str] = None,
    intent: ConvergenceIntent = ConvergenceIntent.TERMINATION_FINALIZE,
) -> Optional[Dict[str, Any]]:
    """TERMINATION/REAPER 收敛 DB 段（线程内执行，由 run_db 包装）。

    死亡证据决策表只存在于统一 convergence 事务；本函数只负责把停止结果
    变成 evidence 并转交。
    """
    db = SessionLocal()
    try:
        row = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if row is not None:
            row_kind = str(row.process_execution_kind or "").strip()
            if row_kind in (EXECUTION_KIND_LOCAL_PROCESS, EXECUTION_KIND_REMOTE_SESSION) and (
                row_kind != evidence.execution_kind
            ):
                evidence = dataclasses.replace(evidence, execution_kind=row_kind)
        request = AttemptConvergenceRequest(
            job_id=job_id,
            run_token=str(run_token or ""),
            worker_boot_id=WORKER_BOOT_ID,
            requested_status=None,
            reason=str(reason or ""),
            evidence=evidence,
            intent=intent,
            reap_bookkeeping=True,
        )
        result = convergence.converge_job_attempt_sync(db, request)
        if not result.changed or not result.payload:
            return None
        return result.payload
    finally:
        db.close()


def _finish_termination_sync(
    job_id: str,
    run_token: str,
    *,
    confirmed_dead: bool,
    reason: str,
    failure_code: str,
    evidence: Optional[_FinalizerEvidence] = None,
) -> Optional[Dict[str, Any]]:
    """Compatibility wrapper: reaper/worker-shutdown terminal writes.

    兼容入口保留旧签名；终态写入与决策全部转交统一 convergence 事务。
    远程 reaper 结果必须通过 ``evidence`` 传入结构化 stop 证据。
    """
    if evidence is None:
        db = SessionLocal()
        try:
            row = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        finally:
            db.close()
        evidence = _termination_evidence_for_row(
            row,
            confirmed_dead=bool(confirmed_dead),
            failure_code=str(failure_code or "") or None,
            reason=str(reason or ""),
        )
    return _converge_termination_sync(
        job_id,
        run_token,
        evidence=evidence,
        reason=str(reason or ""),
        failure_code=str(failure_code or "") or None,
        intent=ConvergenceIntent.REAPER_FINALIZE,
    )


async def _terminate_attempt(attempt: AgentAttemptContext, reason: str) -> None:
    begun = await run_db(_begin_termination_sync, attempt.job_id, attempt.run_token, reason)
    # 心跳任务继承 runner 的 attempt/runtime 绑定：唯一 resolver 可以直接
    # 消费本 attempt 的进程/远程停止证据。
    evidence = _resolve_attempt_evidence(execution_kind=attempt.execution_kind)
    if attempt.execution_kind == EXECUTION_KIND_LOCAL_PROCESS:
        result = await process_supervisor.stop_attempt(attempt.run_token, reason)
        evidence = _resolve_attempt_evidence(
            execution_kind=attempt.execution_kind,
            stop_result=agent_stop_result_from_termination(result),
        )
        if not begun:
            return
    else:
        if not begun:
            return
    payload = await run_db(
        _converge_termination_sync,
        attempt.job_id,
        attempt.run_token,
        evidence=evidence,
        reason=str(
            evidence.error_message or reason
        ),
        failure_code=evidence.failure_code or reason,
    )
    if payload:
        _clear_cancel_event_for_payload(payload)
        await _broadcast_job_payload(payload)
        if str(payload.get("status")) == AiJobStatus.PENDING.value:
            schedule_queue(str(payload.get("queue_key") or ""))


async def finalize_attempt_termination(
    job_id: str,
    run_token: Optional[str],
    *,
    confirmed_dead: bool,
    reason: str,
    failure_code: str,
    evidence: Optional[_FinalizerEvidence] = None,
) -> Optional[Dict[str, Any]]:
    """Converge a stopped attempt only after process-death verification.

    Callers that own an engine (for example the task interrupt endpoint) use
    this after the engine has attempted to stop its CLI.  A missing token is
    deliberately not accepted: without fencing there is no safe owner for a
    durable state transition.  Remote backends must pass structured
    ``evidence`` built from the unified stop result (doc §5).
    """
    token = str(run_token or "").strip()
    if not token:
        return None
    if evidence is None:
        db = SessionLocal()
        try:
            row = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        finally:
            db.close()
        evidence = _termination_evidence_for_row(
            row,
            confirmed_dead=bool(confirmed_dead),
            failure_code=str(failure_code or "") or None,
            reason=str(reason or ""),
        )
    payload = await run_db(
        _converge_termination_sync,
        job_id,
        token,
        evidence=evidence,
        reason=str(reason or ""),
        failure_code=str(failure_code or "") or None,
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


async def _converge_runner_exit(
    attempt: AgentAttemptContext,
    runtime_state: AgentAttemptRuntimeState,
    outcome: JobExecutionOutcome,
) -> None:
    """唯一 runner 收尾点（doc §10.2 / §8.3）。

    在释放 attempt runtime 之前消费本次 attempt 的运行/停止证据：
    - 真正终态 / WAITING_HITL：幂等返回；
    - ORPHANED：保留给 reaper，不清 ownership；
    - TERMINATING：补做本地 stop（如需要）并立即收敛 CANCELLED/INTERRUPTED
      或 ORPHANED，绝不等待默认 lease 到期；
    - RUNNING：业务执行路径漏掉 finalizer，兜底写安全终态，不得静默离开
      RUNNING。

    provider outcome 只能来自 :class:`JobExecutionOutcome` 的明确字段；
    “异常没有逃出 _execute_job”绝不构成 provider outcome（doc §8.3）。
    """
    job_id = attempt.job_id
    status = await _get_job_status(job_id)
    if status is None or status in FINAL_STATUSES or status == AiJobStatus.WAITING_HITL:
        return
    if status == AiJobStatus.ORPHANED:
        return

    if status == AiJobStatus.TERMINATING:
        stop_result: Optional[AgentStopResult] = None
        if attempt.execution_kind == EXECUTION_KIND_LOCAL_PROCESS:
            # 取得或补做 backend stop：stop_attempt 会把每个身份的死亡
            # 证据写入仍处于绑定状态的 attempt runtime。
            termination = await process_supervisor.stop_attempt(
                attempt.run_token, "CANCEL_CONFIRM"
            )
            stop_result = agent_stop_result_from_termination(termination)
        evidence = _resolve_attempt_evidence(
            execution_kind=attempt.execution_kind,
            runtime=runtime_state,
            stop_result=stop_result,
        )
        if outcome.provider_outcome_seen and not evidence.provider_calls_authoritative:
            # 远程回合在取消请求到达前已自然结束：正常 provider outcome。
            # P0（doc 审计 0c381413 §2.5）：该旁路只允许给"无 per-call 记
            # 录"的旧路径补证据；per-call 记录存在时 outcome 以调用记录为
            # 权威，未决调用绝不能被 runner 的 outcome=True 覆盖。
            evidence = dataclasses.replace(evidence, provider_outcome_seen=True)
        reason = str(
            (stop_result.error_message if stop_result else None)
            or outcome.message
            or evidence.error_message
            or "USER_CANCEL"
        )
        payload = await run_db(
            _converge_termination_sync,
            job_id,
            attempt.run_token,
            evidence=evidence,
            reason=reason,
        )
        if payload:
            _clear_cancel_event_for_payload(payload)
            await _broadcast_job_payload(payload)
            if str(payload.get("status")) == AiJobStatus.PENDING.value:
                schedule_queue(str(payload.get("queue_key") or ""))
        return

    # status == RUNNING：业务执行路径漏掉 finalizer，runner 兜底收敛。
    evidence = _resolve_attempt_evidence(
        execution_kind=attempt.execution_kind,
        runtime=runtime_state,
        typed_error=outcome.error,
    )
    if outcome.provider_outcome_seen and not evidence.provider_calls_authoritative:
        # 真实 provider result 产生后必须显式传递 outcome；runner 兜底
        # 绝不从 requested status 推断 provider 已结束（doc 修复方案 §8.3）。
        # P0（doc 审计 0c381413 §2.5）：per-call 记录存在时 outcome 以调用
        # 记录为权威，未决调用绝不能被旁路覆盖（unresolved 也绝不在此清空）。
        evidence = dataclasses.replace(evidence, provider_outcome_seen=True)
    queue_key = attempt.queue_key or ""
    is_task_chat = queue_key.startswith(f"{AiJobChannel.TASK_CHAT.value}:")
    if is_task_chat and not queue_key.startswith("TASK_BASELINE:"):
        context = await run_db(_load_job_dispatch_context_sync, job_id)
        job_kind = str((context or {}).get("job_kind") or "")
        is_task_chat = job_kind not in {JOB_KIND_DIAGNOSIS_SUMMARY, JOB_KIND_TASK_BASELINE}
    requested_status = (
        outcome.requested_status
        if outcome.requested_status is not None
        else (AiJobStatus.INTERRUPTED if is_task_chat else AiJobStatus.FAILED)
    )
    reason = str(outcome.error) if outcome.error is not None else (
        "Runner exited without a business finalizer"
    )
    payload = await run_db(
        _converge_normal_sync,
        job_id,
        attempt.run_token,
        evidence=evidence,
        requested_status=requested_status,
        reason=reason[:500],
        mark_task_interrupted=is_task_chat,
    )
    if payload:
        _clear_cancel_event_for_payload(payload)
        await _broadcast_job_payload(payload)
        if str(payload.get("status")) == AiJobStatus.PENDING.value:
            schedule_queue(str(payload.get("queue_key") or ""))


def _converge_normal_sync(
    job_id: str,
    run_token: str,
    *,
    evidence: _FinalizerEvidence,
    requested_status: AiJobStatus,
    reason: str,
    message: Optional[str] = None,
    error_message: Optional[str] = None,
    result_patch: Optional[Dict[str, Any]] = None,
    context_patch: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
    agent_backend: Optional[str] = None,
    mark_task_interrupted: bool = False,
    interrupt_session_id: Optional[str] = None,
    progress: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """NORMAL_FINALIZE 收敛 DB 段（线程内执行，由 run_db 包装）。"""
    db = SessionLocal()
    try:
        request = AttemptConvergenceRequest(
            job_id=job_id,
            run_token=str(run_token or ""),
            worker_boot_id=WORKER_BOOT_ID if run_token else "",
            requested_status=requested_status,
            reason=str(reason or ""),
            evidence=evidence,
            result_patch=result_patch,
            context_patch=context_patch,
            message=message,
            progress=progress,
            error_message=error_message,
            session_id=session_id,
            agent_backend=agent_backend,
            mark_task_interrupted=mark_task_interrupted,
            interrupt_session_id=interrupt_session_id,
            intent=ConvergenceIntent.NORMAL_FINALIZE,
        )
        result = convergence.converge_job_attempt_sync(db, request)
        if not result.changed or not result.payload:
            return None
        return result.payload
    finally:
        db.close()


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
            # Attempt-local process evidence is bound with the same lifecycle
            # so wait/cancel/interrupt results can never leak across jobs.
            runtime_state = AgentAttemptRuntimeState()
            runtime_token = bind_agent_attempt_runtime(runtime_state)
            heartbeat_task = asyncio.create_task(_job_heartbeat_loop(attempt))
            _JOB_HEARTBEAT_TASKS[job_id] = heartbeat_task
            # 明确的执行 outcome 哨兵：executor 未产出 outcome / 异常逃逸时，
            # 收尾依据的是哨兵 error 而不是“正常完成”推断（doc §8.3）。
            outcome = JobExecutionOutcome(
                requested_status=None,
                error=RuntimeError("executor did not produce an outcome"),
            )
            try:
                await _publish_job_state(job_id)
                try:
                    outcome = await _execute_job(job_id)
                except BaseException as exc:
                    # 保留异常供 runner 收敛使用；继续向上传播保持原语义。
                    outcome = dataclasses.replace(outcome, error=exc)
                    raise
            finally:
                # doc §10.1：stop heartbeat -> runner convergence（runtime 仍
                # 可读）-> reset runtime/attempt -> 决定是否继续队列。
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
                _JOB_HEARTBEAT_TASKS.pop(job_id, None)
                if not _runtime_shutdown_in_progress():
                    try:
                        await _converge_runner_exit(attempt, runtime_state, outcome)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception(
                            "Runner exit convergence failed: job_id={}", job_id
                        )
                reset_agent_attempt_runtime(runtime_token)
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
        # P1（07e04775 §4.2）：provider 终局证据必须在 result 事件到达时按
        # call 身份登记，而不是 helper 返回后补记。每次调用（含重试）新建
        # 记录，绝不复用上一轮 ENDED。
        runtime = current_agent_attempt_runtime()
        attempt_key = current_agent_attempt_key()
        call = runtime.begin_provider_call(attempt_key) if runtime is not None else None
        text_parts: List[str] = []
        result_text = ""
        result_is_error = False
        cancelled = False
        session_started = False

        async def on_event(event: dict):
            nonlocal result_text, result_is_error
            event_type = str(event.get("type") or "")
            if call is not None and runtime is not None and runtime.matches_current_attempt(call):
                # 统一适配边界（Claude 风格 legacy dict）：system/init 携带
                # provider session id；result 是唯一终局事件。证据必须早于
                # JSON 解析、业务落库、错误转换和广播（doc 审计 §4.3）。
                if event_type == "system" and str(event.get("subtype") or "").lower() == "init":
                    record_provider_call_session_started(call, event.get("session_id"))
                elif event_type == "result":
                    subtype = str(event.get("subtype") or "").lower()
                    is_error = bool(event.get("is_error")) or subtype == "error"
                    record_provider_call_result(call, is_error=is_error)
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
                # start_session 成功返回是“已确认远程 session 创建”的登记点；
                # 不能只依赖它（result 可能先于返回值到达），但必须补记。
                if call is not None:
                    record_provider_call_session_started(call, resumed_session_id)
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
                    try:
                        await asyncio.wait_for(bridge.wait(), timeout=wait_seconds)
                    except asyncio.CancelledError:
                        # LegacyBridgeShim.cancel 会取消其内部 run task；该取消以
                        # CancelledError 从 wait() 冒出。取消监控已确认本次是
                        # 用户取消时，按取消路径收敛；否则保持传播语义。
                        if not cancelled:
                            raise
            except asyncio.TimeoutError as exc:
                # Cancel must finish first so its termination result becomes the
                # authoritative evidence before any retry decision.
                await bridge.cancel()
                bridge_stop = _bridge_stop_result(bridge)
                evidence = _resolve_attempt_evidence(stop_result=bridge_stop)
                process_started = evidence.process_started
                dead = evidence.termination_confirmed_dead
                if dead is False:
                    raise AgentError(
                        "Agent process tree could not be confirmed dead",
                        termination_confirmed_dead=False,
                        process_started=process_started or True,
                        failure_code=evidence.failure_code or "PROCESS_TREE_STILL_ALIVE",
                    ) from exc
                # P1（07e04775 §4.3）：明确 stop ACK 或已证明死亡的进程树
                # 都意味着该调用已确定不会再产出 result——关闭未决记录
                # （result_success 保持 None，绝不伪造 outcome）。
                _close_unresolved_provider_call(
                    call,
                    stop_acknowledged=evidence.remote_stop_acknowledged is True,
                    tree_dead=dead is True,
                )
                last_error = AgentTimeoutError(
                    "AI reply timed out",
                    phase="hard",
                    limit_seconds=float(wait_seconds),
                    termination_confirmed_dead=dead,
                    process_started=process_started,
                )
                logger.warning(
                    "Asset AI single-turn wait timeout (attempt {}/{})",
                    attempt,
                    attempts,
                )
                # Retry only after the previous tree is proven dead, or when this
                # attempt never started a local process at all.  远程会话不能
                # 因 process_started=False 就与未结束的调用重叠：上一次调用
                # 必须 ENDED（含 ACK 终止）才允许重试（doc 审计 §4.3）。
                if attempt < attempts and (dead is True or not process_started):
                    if not _provider_call_ready_for_retry(call, current_attempt):
                        raise last_error from exc
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
                # 用户取消：取消后的终止结果必须随 typed 异常携带，交由上层
                # termination finalizer 收敛（确认死亡 → 可恢复/取消态）。
                evidence = _resolve_attempt_evidence(stop_result=_bridge_stop_result(bridge))
                _close_unresolved_provider_call(
                    call, stop_acknowledged=evidence.remote_stop_acknowledged is True
                )
                raise AgentCancelledError(
                    "AI job cancelled by user",
                    termination_confirmed_dead=evidence.termination_confirmed_dead,
                    process_started=evidence.process_started,
                    failure_code="USER_CANCELLED",
                )

            merged = "\n\n".join(part for part in text_parts if part.strip()).strip()
            final_text = merged or result_text or "AI 暂时没有返回有效内容，请稍后重试。"
            final_session_id = getattr(bridge, "session_id", None) or resumed_session_id

            evidence = _resolve_attempt_evidence(stop_result=_bridge_stop_result(bridge))
            process_started = evidence.process_started
            dead = evidence.termination_confirmed_dead
            if dead is False:
                # CLI 已退出但进程树死亡未被证明：禁止重试启动下一进程，
                # 立即抛出携带证据的 typed 异常，由收尾路径转 ORPHANED。
                raise AgentError(
                    "Agent process tree could not be confirmed dead",
                    termination_confirmed_dead=False,
                    process_started=process_started or True,
                    failure_code=evidence.failure_code or "PROCESS_TREE_STILL_ALIVE",
                )

            if call is not None and call.state != ProviderCallState.ENDED:
                # P1（07e04775 §4.3）：函数正常返回 / assistant 文本 / 非空
                # dict 都不是终局结果证明——没有 result 事件绝不伪造 outcome，
                # 交由上层按“无 outcome”收敛（本地已证明死亡 → FAILED；
                # 远程会话未结束 → ORPHANED）。
                raise AgentError(
                    "provider outcome missing",
                    termination_confirmed_dead=dead,
                    process_started=process_started,
                    failure_code="PROVIDER_OUTCOME_MISSING",
                    provider_call_id=call.call_id,
                )

            if result_is_error or _looks_like_timeout_text(final_text):
                last_error = AgentProviderError(
                    final_text or "AI provider returned timeout/error",
                    termination_confirmed_dead=dead,
                    process_started=process_started,
                    failure_code="PROVIDER_ERROR",
                    provider_call_id=call.call_id if call is not None else None,
                )
                logger.warning(
                    "Asset AI single-turn got timeout/error text (attempt {}/{}): {}",
                    attempt,
                    attempts,
                    final_text[:160],
                )
                # Retry only after the previous tree is proven dead, or when this
                # attempt never started a local process at all.  本次调用已
                # 收到明确 result（ENDED），远程重试不会与未结束调用重叠。
                if attempt < attempts and (dead is True or not process_started):
                    # 上一进程树必须已确认死亡才会走到这里（dead is not False）。
                    next_session_id = None
                    continue
                raise last_error

            termination = getattr(bridge, "last_termination", None)
            return {
                "text": final_text,
                "session_id": final_session_id,
                "provider_call_id": call.call_id if call is not None else None,
                "process_started": process_started,
                "termination_confirmed_dead": (
                    bool(termination.confirmed_dead) if termination is not None else None
                )
                if dead is None
                else dead,
            }
        except BaseException:
            # P1（07e04775 §4.3）：已收到 result 的 ENDED 不能被异常覆盖；
            # 未结束调用继续保持未决（STARTED -> UNKNOWN），由上层按证据
            # 收敛，绝不伪造结束。
            mark_provider_call_unresolved(call)
            raise

    if last_error:
        raise last_error
    raise AgentError("AI reply failed with unknown reason", failure_code="AGENT_UNKNOWN_FAILURE")


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


async def _execute_asset_thread_job(job_id: str) -> Optional[bool]:
    job_kind = JOB_KIND_THREAD_AI_REPLY
    attempt = current_agent_attempt()
    run_token = attempt.run_token if attempt else None
    provider_seen = False
    try:
        base = await run_db_txn(
            lambda db: _prepare_asset_thread_context_sync(db, job_id, run_token)
        )
        if base is None:
            return None
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
                provider_seen = bool(str(result.get("text") or "").strip())
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
                    process_started=result.get("process_started"),
                    termination_confirmed_dead=result.get("termination_confirmed_dead"),
                )
                return provider_seen

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
                provider_seen = provider_seen or bool(str(result.get("text") or "").strip())
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
                    process_started=result.get("process_started"),
                    termination_confirmed_dead=result.get("termination_confirmed_dead"),
                )
                return provider_seen

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
            provider_seen = provider_seen or bool(str(result.get("text") or "").strip())
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
                process_started=result.get("process_started"),
                termination_confirmed_dead=result.get("termination_confirmed_dead"),
            )
            return provider_seen
    except AgentAttemptFencedError:
        logger.info("Discarded fenced asset attempt: job={}", job_id)
        return None
    except Exception as exc:
        status_after_error = await _get_job_status(job_id)
        if _is_cancel_requested(job_id) or status_after_error == AiJobStatus.CANCELLED:
            _clear_cancel_event(job_id)
            return None
        logger.exception(f"Asset AI job failed: {exc}")
        failed_message = "Resolution proposal failed" if job_kind == JOB_KIND_RESOLUTION_PROPOSAL else "AI reply failed"
        # 失败也必须携带 attempt 级终止证据：已证明死亡的作业直接 FAILED 并
        # 清 ownership；未证明的转 ORPHANED。typed 异常作为无身份 fallback
        # 交给唯一 resolver（runtime 为权威）。
        await _update_job_state(
            job_id,
            status=AiJobStatus.FAILED,
            progress=100,
            message=failed_message,
            error_message=str(exc),
            finalize=True,
            run_token=run_token,
            typed_error=exc,
        )
        if job_kind in {JOB_KIND_RESOLUTION_PROPOSAL, JOB_KIND_RESOLUTION_REWRITE}:
            return None
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
                        "thread_id": failure_state["thread_id"],
                        "message": failure_state["message"],
                    },
                )
        except Exception as msg_exc:
            logger.warning(f"Failed to append asset AI failure message: {msg_exc}")
        return None
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
    """把 TASK_CHAT 作业和所属任务标记为可恢复的 INTERRUPTED（纯字段赋值 helper）。

    自动失败（底层 API 报错、超时、欠费、网络抖动等）不应进入终态 FAILED；
    FAILED 只允许用户通过失败复盘/关闭流程显式标记。

    该 helper 不再承担状态判断职责：调用方必须先完成进程树死亡判定
    （confirmed_dead=True 或从未启动本地进程），因此这里总是清空全部
    ownership 字段，保证 INTERRUPTED 是干净的“当前 attempt 已停止，允许恢复”。
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
    _clear_process_ownership(job)
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
    termination_confirmed_dead: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """中断标记 DB 段（线程内执行，由 run_db_txn 包装）。

    兼容入口：普通异常回调不得再使用本函数收敛 job。仅允许“确认无活进程
    之后的内部操作”；若行上仍保留进程归属且死亡未被证明，一律转 ORPHANED
    保留 ownership，交给 reaper。
    """
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
    if _has_active_process_ownership(job) and termination_confirmed_dead is not True:
        now = datetime.utcnow()
        job.status = AiJobStatus.ORPHANED
        job.message = "Agent process could not be confirmed dead"
        job.error_message = str(reason or "")[:500]
        job.failure_code = "PROCESS_TREE_STILL_ALIVE"
        job.terminal_reason = "PROCESS_TREE_STILL_ALIVE"
        job.lease_expires_at = now
        job.orphaned_at = job.orphaned_at or now
        db.commit()
        db.refresh(job)
        return serialize_job(job)
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
        _clear_cancel_event_for_payload(payload)
        await _broadcast_job_payload(payload)
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
    # P0: the error callback must never converge the durable job.  Writing
    # INTERRUPTED here would bypass process-tree death confirmation and let a
    # user resume the session while the previous CLI tree is still alive.
    # The engine keeps last_result_* / last_termination_confirmed_dead in
    # memory and `_finalize_task_chat_job_from_engine` performs the single
    # persisted convergence after engine.run() returns.
    logger.warning(
        "Agent engine error recorded (non-terminal; finalizer decides): job={}, error={}",
        job_id,
        str(error_text or "")[:500],
    )


async def _execute_task_chat_job(job_id: str) -> Optional[bool]:
    try:
        return await _execute_task_chat_job_inner(job_id)
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


async def _execute_task_chat_job_inner(job_id: str) -> Optional[bool]:
    state = await run_db(_load_task_chat_job_dispatch_sync, job_id)
    if state is None:
        return None
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

        return await _run_task_chat_turn(job_id, prompt)


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


async def _execute_diagnosis_summary_job(job_id: str) -> Optional[bool]:
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
        return None
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
                return False
            raise

        # 用户已停止（或任务已终态）时丢弃结果：不能反填定位结果卡片、不能广播
        if await _is_job_cancelled_or_final(job_id):
            logger.info("Diagnosis summary cancelled after run; discard result: job={}", job_id)
            return True

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
            process_started=result.get("process_started"),
            termination_confirmed_dead=result.get("termination_confirmed_dead"),
        )
        return True


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


async def _run_task_chat_turn(job_id: str, prompt: str) -> Optional[bool]:
    state = await run_db_txn(lambda db: _load_task_chat_turn_state_sync(db, job_id))
    if state is None:
        return None
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
        # provider outcome 只能来自引擎收到的真实 provider result；
        # “run/send_message 正常返回”不构成 outcome，引擎异常路径赋的
        # last_result_success=False 也绝不构成 outcome（doc 审计 P1-1）。
        return getattr(engine, "last_result", None) is not None


def _finalize_task_chat_job_sync(
    db: Session,
    *,
    job_id: str,
    last_result_success: Optional[bool],
    last_result_text: str,
    is_timeout_interrupted: bool,
    engine_session_id: Optional[str],
    run_token: Optional[str] = None,
    process_started: Optional[bool] = None,
    termination_confirmed_dead: Optional[bool] = None,
    failure_code: Optional[str] = None,
    remaining_pids: tuple = (),
    evidence: Optional[_FinalizerEvidence] = None,
) -> Optional[Dict[str, Any]]:
    """finalize DB 段（线程内执行，由 run_db 包装）；返回 None 表示无需收尾。

    本函数不再拥有独立的死亡证据决策表（doc §11）：只负责把引擎结果和
    attempt 证据构造成统一 convergence 请求，终态由
    ``converge_job_attempt_in_txn()`` 的唯一决策表计算；提交由最外层
    run_db_txn 负责。
    """
    if evidence is None:
        evidence = resolve_attempt_evidence(
            execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
            fallback_started=process_started,
            fallback_dead=termination_confirmed_dead,
            fallback_failure_code=failure_code,
            fallback_remaining_pids=remaining_pids,
        )
    job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
    if job is None or job.channel != AiJobChannel.TASK_CHAT:
        return None
    dirty_interrupted = job.status == AiJobStatus.INTERRUPTED
    if dirty_interrupted and not _row_has_leaked_interrupted_ownership(job):
        # 已经是干净的 INTERRUPTED：收尾已完成，无需重复处理。
        return None
    success = last_result_success is True and not dirty_interrupted
    text = str(last_result_text or "")
    if is_timeout_interrupted:
        context_patch = {
            "timeout_interrupted": True,
            "timeout_message": text,
        }
        reason = text or "AI 会话超时"
        message = "AI 会话超时，可继续发送消息恢复"
    else:
        context_patch = {"interrupted_reason": text or "AI 执行异常"}
        reason = text or "AI 执行异常"
        message = "AI 执行异常，可继续发送消息恢复"
    request = AttemptConvergenceRequest(
        job_id=job_id,
        run_token=str(run_token or ""),
        worker_boot_id=WORKER_BOOT_ID if run_token else "",
        requested_status=AiJobStatus.SUCCESS if success else AiJobStatus.INTERRUPTED,
        reason=reason,
        evidence=evidence,
        result_patch={"result_preview": text[:1600]} if success else None,
        context_patch=None if success else context_patch,
        message="AI reply completed" if success else message,
        error_message=None,
        mark_task_interrupted=not success,
        interrupt_session_id=engine_session_id,
        intent=ConvergenceIntent.NORMAL_FINALIZE,
    )
    # 本函数运行在外层 run_db_txn 中：必须使用事务内核心，禁止内部提交
    # （doc §7.3.1），否则会把外层业务副作用提前提交。
    result = convergence.converge_job_attempt_in_txn(db, request)
    if not result.changed or not result.payload:
        return None
    return result.payload


def _engine_provider_result(engine: Any) -> Optional[AgentRunResult]:
    """Extract the provider outcome evidence from an engine (doc 审计 P1-1).

    优先使用真实 ``AgentRunResult``（引擎异常/持久化失败都不会设置它）；
    兼容路径仅在 ``last_result_success is True`` 时合成最小 result——异常/
    超时/中断路径只会把它赋成 False/None，因此 ``True`` 只能来自真实
    result 事件。``False``（provider 明确失败）绝不在此合成为 outcome：
    远程会话的明确失败必须由真实 result 对象或 stop ACK 证明。
    """
    provider_result = getattr(engine, "last_result", None)
    if provider_result is not None:
        return provider_result
    if getattr(engine, "last_result_success", None) is True:
        return AgentRunResult(
            session_id=str(getattr(engine, "session_id", "") or ""),
            success=True,
            result_text=str(getattr(engine, "last_result_text", "") or ""),
        )
    return None


async def _finalize_task_chat_job_from_engine(job_id: str, engine: WorkflowEngine) -> None:
    # Fallback for missing callback updates.
    is_timeout_interrupted = bool(getattr(engine, "last_result_interrupted", False)) or _looks_like_timeout_text(
        engine.last_result_text or ""
    )
    attempt = current_agent_attempt()
    run_token = attempt.run_token if attempt else None
    # Attempt-local runtime evidence is authoritative (it survives CLI exits
    # followed by parse/persist failures); engine attributes are the fallback
    # consumed by the unique resolver (doc §6.2).
    evidence = _resolve_attempt_evidence(
        fallback_dead=getattr(engine, "last_termination_confirmed_dead", None),
        provider_result=_engine_provider_result(engine),
    )
    payload = await run_db_txn(
        lambda db: _finalize_task_chat_job_sync(
            db,
            job_id=job_id,
            last_result_success=getattr(engine, "last_result_success", None),
            last_result_text=engine.last_result_text or "",
            is_timeout_interrupted=is_timeout_interrupted,
            engine_session_id=getattr(engine, "session_id", None),
            run_token=run_token,
            evidence=evidence,
        )
    )
    if payload is None:
        return
    is_success = str(payload.get("status") or "") == AiJobStatus.SUCCESS.value
    _clear_cancel_event_for_payload(payload)
    await _broadcast_job_payload(payload)
    if not is_success:
        return
    queue_key = str(payload.get("queue_key") or "")
    if queue_key:
        schedule_queue(queue_key)


async def _finalize_task_chat_job_failure(
    job_id: str,
    reason: str,
    *,
    is_timeout_interrupted: bool = False,
    engine_session_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """统一 TASK_CHAT 失败收尾（引擎外围异常/恢复失败共用）。

    不得回退到 `_mark_task_chat_job_interrupted()`：本函数与
    `_finalize_task_chat_job_from_engine` 共享同一个唯一 convergence 决策表，
    由 attempt-local 证据决定 ORPHANED 或干净的 INTERRUPTED。
    """
    if not job_id:
        return None
    attempt = current_agent_attempt()
    evidence = _resolve_attempt_evidence()
    payload = await run_db_txn(
        lambda db: _finalize_task_chat_job_sync(
            db,
            job_id=job_id,
            last_result_success=False,
            last_result_text=str(reason or "AI execution failed"),
            is_timeout_interrupted=is_timeout_interrupted,
            engine_session_id=engine_session_id,
            run_token=attempt.run_token if attempt else None,
            evidence=evidence,
        )
    )
    if payload is None:
        return None
    await _broadcast_job_payload(payload)
    return payload


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


async def _execute_task_baseline_job(job_id: str, task_id: str) -> Optional[bool]:
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
        process_started=payload.get("process_started"),
        termination_confirmed_dead=payload.get("termination_confirmed_dead"),
    )
    # bootstrap 完成返回即代表 CLI 回合产出了明确结果。
    return bool(payload)


async def _execute_job(job_id: str) -> JobExecutionOutcome:
    """执行一个 job；必须返回明确的 :class:`JobExecutionOutcome`（doc §8.3）。

    所有分支都不得通过“是否抛异常”推断 provider outcome；内部捕获的异常
    必须写入 ``outcome.error``。
    """
    dispatch = await run_db(_load_job_dispatch_context_sync, job_id)
    if dispatch is None:
        return JobExecutionOutcome(requested_status=None)
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
                    provider_seen = bool(await runner(job_id, run_token=attempt.run_token))
                else:
                    # Keep direct/unit callers and older extension runners
                    # compatible while production runners receive the fence.
                    provider_seen = bool(await runner(job_id))
                return JobExecutionOutcome(
                    requested_status=None,
                    provider_outcome_seen=provider_seen,
                )
            if queue_key.startswith("TASK_BASELINE:") or job_kind == JOB_KIND_TASK_BASELINE:
                provider_seen = await _execute_task_baseline_job(
                    job_id,
                    str(dispatch.get("task_id") or ""),
                )
                return JobExecutionOutcome(
                    requested_status=None,
                    provider_outcome_seen=bool(provider_seen),
                )
            if channel == AiJobChannel.ASSET_THREAD:
                provider_seen = await _execute_asset_thread_job(job_id)
                return JobExecutionOutcome(
                    requested_status=None,
                    provider_outcome_seen=bool(provider_seen),
                )
            if channel == AiJobChannel.TASK_CHAT:
                provider_seen = await _execute_task_chat_job(job_id)
                return JobExecutionOutcome(
                    requested_status=None,
                    provider_outcome_seen=bool(provider_seen),
                )
            raise ValueError(f"Unsupported AI job channel: {channel}")
        except Exception as exc:
            logger.exception(f"AI job execution failed: job={job_id}, error={exc}")
            failure_context = await run_db(_load_job_failure_context_sync, job_id)
            if failure_context is None:
                # 异常已被内部处理：必须保留在 outcome 中，绝不丢失。
                return JobExecutionOutcome(requested_status=None, error=exc)
            job_channel = failure_context["channel"]
            job_kind = failure_context["job_kind"]
            if (
                job_channel == AiJobChannel.TASK_CHAT
                and job_kind not in {JOB_KIND_DIAGNOSIS_SUMMARY, JOB_KIND_TASK_BASELINE}
            ):
                # 引擎外围异常也必须走同一个 TASK_CHAT failure finalizer，
                # 由 attempt 证据决定 ORPHANED 或干净的 INTERRUPTED。
                await _finalize_task_chat_job_failure(
                    job_id,
                    str(exc),
                    is_timeout_interrupted=_looks_like_timeout_text(str(exc)),
                )
            else:
                # 非 TASK_CHAT：attempt-local 死亡证据必须随失败写入，
                # 已证明死亡的作业直接 FAILED；未证明的转 ORPHANED。
                # typed 异常作为无身份 fallback 交给唯一 resolver。
                attempt = current_agent_attempt()
                await _update_job_state(
                    job_id,
                    status=AiJobStatus.FAILED,
                    progress=100,
                    message="AI execution failed",
                    error_message=str(exc),
                    finalize=True,
                    run_token=attempt.run_token if attempt else None,
                    typed_error=exc,
                )
            return JobExecutionOutcome(requested_status=None, error=exc)


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

    await _broadcast_job_payload(payload)
    if queue_key:
        schedule_queue(queue_key)
    return payload


async def enqueue_asset_thread_job(job_id: str) -> Optional[Dict[str, Any]]:
    return await _enqueue_job(job_id, expected_channel=AiJobChannel.ASSET_THREAD)


async def enqueue_task_chat_job(job_id: str) -> Optional[Dict[str, Any]]:
    return await _enqueue_job(job_id, expected_channel=AiJobChannel.TASK_CHAT)


async def publish_job(job_id: str) -> None:
    """Broadcast the durable job payload; final 判定由 payload 状态决定。

    调用方无权覆盖 final（doc §9.2）：TERMINATING/ORPHANED/INTERRUPTED 等
    非终态绝不产生 ``*_done``/``*_failed``。
    """
    await _publish_job_state(job_id)


async def run_task_chat_job_now(job_id: str) -> None:
    await _execute_task_chat_job(job_id)


def mark_task_chat_jobs_cancelled(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    message: str = "Task execution stopped",
) -> List[str]:
    """批量取消请求（doc §4.5.2）：候选 id -> 排序 -> 逐个唯一 termination 事务。

    本函数不再直接写 job 状态：所有 TERMINATING/CANCELLED 写入都通过
    :func:`request_attempt_termination_in_txn`（与业务 finalizer 共享行锁）。
    cancel signal 在最外层 commit 之后才触发。
    """
    from app.domains.ai.services.ai_job_convergence_service import (
        AttemptTerminationRequest,
        request_attempt_termination_in_txn,
    )

    candidate_ids = [
        str(row[0])
        for row in (
            db.query(SddAiJob.id)
            .filter(
                SddAiJob.workspace_id == workspace_id,
                SddAiJob.task_id == task_id,
                SddAiJob.channel == AiJobChannel.TASK_CHAT,
                SddAiJob.status.notin_(list(FINAL_STATUSES)),
            )
            .all()
        )
    ]
    # 排序保证多行加锁顺序一致，避免与其它批量路径互相死锁。
    job_ids: List[str] = []
    for job_id in sorted(candidate_ids):
        result = request_attempt_termination_in_txn(
            db,
            AttemptTerminationRequest(
                job_id=job_id,
                workspace_id=workspace_id,
                task_id=task_id,
                reason=str(message or "USER_CANCEL").strip() or "USER_CANCEL",
                mode="CANCEL",
                message=message,
            ),
        )
        if result.changed:
            job_ids.append(job_id)
    if job_ids:
        db.commit()
        # commit 之后才触发 runner 的 cancellation signal（doc §9.1）。
        for job_id in job_ids:
            _request_job_cancel(job_id)
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
    engine: Optional[WorkflowEngine] = None
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
        # HITL 恢复失败同样必须走统一 finalizer：由 attempt 证据决定
        # ORPHANED 或干净的 INTERRUPTED，不得绕过进程死亡确认。
        await _finalize_task_chat_job_failure(
            job_id,
            str(exc),
            is_timeout_interrupted=_looks_like_timeout_text(str(exc)),
            engine_session_id=getattr(engine, "session_id", None),
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

    await _broadcast_job_payload(payload)
    await enqueue_task_chat_job(payload["id"])
    return payload


def cancel_job(
    db: Session,
    *,
    workspace_id: str,
    job_id: str,
) -> Optional[SddAiJob]:
    """取消请求事务（doc §9.1 / §4.5.1）：唯一 termination request 入口。

    与 finalizer 共享同一 job 行锁，因此两种锁顺序只能得到：
    - cancel 先获得锁 -> finalizer 看到 TERMINATING 并转 termination convergence；
    - finalizer 先获得锁 -> cancel 看到真正终态并幂等返回。
    取消信号在 commit 之后才触发当前 runner。
    """
    from app.domains.ai.services.ai_job_convergence_service import (
        AttemptTerminationRequest,
        request_attempt_termination_in_txn,
    )

    result = request_attempt_termination_in_txn(
        db,
        AttemptTerminationRequest(
            job_id=job_id,
            workspace_id=workspace_id,
            reason="USER_CANCEL",
            mode="CANCEL",
        ),
    )
    if not result.changed:
        job = (
            db.query(SddAiJob)
            .filter(SddAiJob.id == job_id, SddAiJob.workspace_id == workspace_id)
            .first()
        )
        return job
    db.commit()
    job = (
        db.query(SddAiJob)
        .filter(SddAiJob.id == job_id, SddAiJob.workspace_id == workspace_id)
        .first()
    )
    if job is None:
        return None
    # commit 后才触发当前 runner 的 cancellation signal（doc §9.1 第 5 步）。
    _request_job_cancel(job.id)
    return job
