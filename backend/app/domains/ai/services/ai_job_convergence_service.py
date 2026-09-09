"""唯一 attempt 证据解析器 + 唯一 job 终态事务（doc V3 §6/§8）。

职责边界：
- ``resolve_attempt_evidence``：attempt 证据的唯一解析入口。identity-aware
  runtime 的明确聚合结果（True/False）是权威；任何无身份 fallback
  （typed exception / stop result / provider result / 旧 kwargs）都不得
  覆盖它，只允许在 runtime 完全没有证据时补充。
- ``converge_job_attempt_sync``：唯一允许写业务终态（SUCCESS / FAILED /
  CANCELLED / INTERRUPTED / REVERTED / ORPHANED）的事务入口，并按决策表
  决定是否清空 attempt ownership。

本模块不依赖 WebSocket manager，也不在事务中广播；广播由调用方在
commit 之后执行。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, Literal, Optional, Tuple

from sqlalchemy.orm import Session

from app.agents.contract import (
    EXECUTION_KIND_LOCAL_PROCESS,
    EXECUTION_KIND_REMOTE_SESSION,
    AgentAttemptRuntimeState,
    AgentRunResult,
    AgentStopResult,
    AttemptFinalizerEvidence,
    ExecutionKind,
)
from app.config import settings
from app.core.logging import get_logger
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.task.models.task import SddTask, TaskStatus

logger = get_logger(__name__, category="ai_session")

PROCESS_TREE_STILL_ALIVE = "PROCESS_TREE_STILL_ALIVE"
REMOTE_STOP_UNCONFIRMED = "REMOTE_STOP_UNCONFIRMED"
EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
CANCEL_REQUESTED = "CANCEL_REQUESTED"
USER_INTERRUPT = "USER_INTERRUPT"

EXECUTION_KINDS = (EXECUTION_KIND_LOCAL_PROCESS, EXECUTION_KIND_REMOTE_SESSION)


class AttemptFencedError(RuntimeError):
    """Raised when a fenced attempt must abort its whole business transaction.

    外层事务（run_db_txn / route transaction）必须将该异常视作幂等退出，
    但必须先执行 rollback：被 fence 的调用方不得提交任何业务副作用。
    """


class ConvergenceIntent(str, Enum):
    """收敛来源（doc §8.2 第 5 步：按 intent 决定允许的来源状态）。"""

    NORMAL_FINALIZE = "NORMAL_FINALIZE"
    TERMINATION_FINALIZE = "TERMINATION_FINALIZE"
    REAPER_FINALIZE = "REAPER_FINALIZE"


def _merge_json(original: Any, patch: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(original) if isinstance(original, dict) else {}
    if patch:
        merged.update(patch)
    return merged


def _attr_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    return bool(value)


# ────────────────────────── 唯一证据解析器 ──────────────────────────


def resolve_attempt_evidence(
    *,
    execution_kind: ExecutionKind,
    runtime: Optional[AgentAttemptRuntimeState] = None,
    stop_result: Optional[AgentStopResult] = None,
    typed_error: Optional[BaseException] = None,
    provider_result: Optional[AgentRunResult] = None,
    fallback_started: Optional[bool] = None,
    fallback_dead: Optional[bool] = None,
    fallback_failure_code: Optional[str] = None,
    fallback_remaining_pids: Tuple[int, ...] = (),
) -> AttemptFinalizerEvidence:
    """按固定优先级合并 attempt 证据（doc §6.2）。

    1. execution kind 由调用方取 durable job/attempt context，不从 PID 推断；
    2. runtime 有明确 True/False 时直接使用，禁止合并 fallback；
    3. runtime 有已启动 identity 但聚合为 None 时：fallback=False 可补充为
       未确认；fallback=True 不得把未知 identity 直接确认死亡；
    4. runtime 完全没有证据时，才读取 stop result / provider result /
       typed error / 显式 fallback；
    5. 多个无身份 fallback 互相冲突时返回 None 并写 EVIDENCE_CONFLICT；
    6. failure code 和 remaining PIDs 只作诊断，不反向改变死亡状态。
    """
    kind = execution_kind if execution_kind in EXECUTION_KINDS else EXECUTION_KIND_LOCAL_PROCESS

    if kind == EXECUTION_KIND_REMOTE_SESSION:
        remote_stop = stop_result if (
            stop_result is not None and stop_result.execution_kind == EXECUTION_KIND_REMOTE_SESSION
        ) else None
        remote_ack = (
            bool(remote_stop.stop_acknowledged)
            if remote_stop is not None and remote_stop.stop_acknowledged
            else (False if remote_stop is not None else None)
        )
        if remote_ack is None and runtime is not None:
            runtime_ack = runtime.remote_stop_acknowledged
            remote_ack = runtime_ack
        remote_started = bool(runtime.remote_session_started) if runtime is not None else False
        provider_seen = provider_result is not None
        failure_code = None
        error_message = None
        for candidate in (
            remote_stop.failure_code if remote_stop is not None else None,
            getattr(runtime, "remote_stop_result", None).failure_code
            if runtime is not None and runtime.remote_stop_result is not None
            else None,
            getattr(typed_error, "failure_code", None),
            fallback_failure_code,
        ):
            if candidate:
                failure_code = str(candidate)
                break
        for candidate in (
            remote_stop.error_message if remote_stop is not None else None,
            str(typed_error) if typed_error is not None else None,
        ):
            if candidate:
                error_message = str(candidate)
                break
        return AttemptFinalizerEvidence(
            execution_kind=kind,
            process_started=False,
            termination_confirmed_dead=None,
            remote_stop_acknowledged=remote_ack,
            failure_code=failure_code,
            error_message=error_message,
            remaining_pids=(),
            source="remote",
            remote_session_started=remote_started,
            provider_outcome_seen=provider_seen,
        )

    # ── LOCAL_PROCESS ──
    conflict = False
    runtime_dead: Optional[bool] = None
    runtime_started: Optional[bool] = None
    runtime_has_evidence = False
    if runtime is not None:
        runtime_has_evidence = bool(runtime.has_process_evidence)
        if runtime_has_evidence:
            runtime_started = bool(runtime.process_started)
            runtime_dead = runtime.termination_confirmed_dead

    fallback_candidates: list[bool] = []
    if stop_result is not None and stop_result.execution_kind == EXECUTION_KIND_LOCAL_PROCESS:
        candidate = _attr_bool(stop_result.local_process_confirmed_dead)
        if candidate is not None:
            fallback_candidates.append(candidate)
    if typed_error is not None:
        candidate = _attr_bool(getattr(typed_error, "termination_confirmed_dead", None))
        if candidate is not None:
            fallback_candidates.append(candidate)
    if provider_result is not None:
        candidate = _attr_bool(getattr(provider_result, "termination_confirmed_dead", None))
        if candidate is not None:
            fallback_candidates.append(candidate)
    if fallback_dead is not None:
        fallback_candidates.append(bool(fallback_dead))
    if any(value is True for value in fallback_candidates) and any(
        value is False for value in fallback_candidates
    ):
        # 无身份 fallback 互相冲突：不得用 False/True 优先掩盖冲突。
        conflict = True
        resolved_fallback_dead: Optional[bool] = None
    elif fallback_candidates:
        resolved_fallback_dead = fallback_candidates[0]
    else:
        resolved_fallback_dead = None

    if runtime_has_evidence and runtime_dead is not None:
        # 规则 2：runtime 明确结果权威，任何 fallback 都不得改变。
        dead = runtime_dead
        source = "runtime"
    elif runtime_has_evidence:
        # 规则 3：已启动 identity 但聚合未决；只有 fallback=False 能补充为
        # 未确认，fallback=True 不得把未知 identity 直接确认死亡。
        dead = False if resolved_fallback_dead is False else None
        source = "runtime+fallback" if dead is False else "runtime"
    else:
        # 规则 4/5：runtime 完全没有证据；冲突时保持 None 并标记冲突。
        dead = resolved_fallback_dead
        source = "fallback" if dead is not None else "none"

    if runtime_started is not None:
        started = runtime_started
    else:
        started_candidates: list[bool] = []
        if stop_result is not None and stop_result.execution_kind == EXECUTION_KIND_LOCAL_PROCESS:
            started_candidates.append(bool(stop_result.local_process_started))
        if typed_error is not None:
            candidate = getattr(typed_error, "process_started", None)
            if candidate is not None:
                started_candidates.append(bool(candidate))
        if fallback_started is not None:
            started_candidates.append(bool(fallback_started))
        started = any(started_candidates)

    failure_code: Optional[str] = None
    error_message: Optional[str] = None
    if conflict:
        failure_code = EVIDENCE_CONFLICT
    remaining: Tuple[int, ...] = ()
    if runtime is not None and runtime_has_evidence:
        remaining = tuple(runtime.remaining_pids)
        failure_code = failure_code or runtime.termination_failure_code
        error_message = runtime.termination_error
    if not remaining and stop_result is not None and stop_result.execution_kind == EXECUTION_KIND_LOCAL_PROCESS:
        remaining = tuple(stop_result.remaining_pids or ())
    failure_code = failure_code or (
        stop_result.failure_code if stop_result is not None and stop_result.execution_kind == EXECUTION_KIND_LOCAL_PROCESS else None
    )
    error_message = error_message or (
        stop_result.error_message if stop_result is not None and stop_result.execution_kind == EXECUTION_KIND_LOCAL_PROCESS else None
    )
    failure_code = failure_code or getattr(typed_error, "failure_code", None) or fallback_failure_code
    if error_message is None and typed_error is not None:
        error_message = str(typed_error) or None
    return AttemptFinalizerEvidence(
        execution_kind=kind,
        process_started=bool(started),
        termination_confirmed_dead=dead,
        remote_stop_acknowledged=None,
        failure_code=failure_code,
        error_message=error_message,
        remaining_pids=tuple(sorted(set(remaining))) or tuple(fallback_remaining_pids or ()),
        source=source,
        remote_session_started=False,
        provider_outcome_seen=provider_result is not None,
    )


def evidence_from_stop_result(
    stop_result: Optional[AgentStopResult],
    *,
    remote_session_started: Optional[bool] = None,
    execution_kind: Optional[ExecutionKind] = None,
) -> AttemptFinalizerEvidence:
    """Build finalizer evidence directly from a unified stop result.

    供 engine/interrupt 等无法访问 attempt runtime 的调用方使用；远程会话的
    ``remote_session_started`` 由调用方显式提供（例如 engine 是否已建立
    session）。
    """
    kind: ExecutionKind = (
        execution_kind
        or (stop_result.execution_kind if stop_result is not None else None)
        or EXECUTION_KIND_LOCAL_PROCESS
    )
    if kind == EXECUTION_KIND_REMOTE_SESSION:
        ack = bool(stop_result.stop_acknowledged) if stop_result is not None else None
        return AttemptFinalizerEvidence(
            execution_kind=kind,
            process_started=False,
            termination_confirmed_dead=None,
            remote_stop_acknowledged=ack,
            failure_code=(stop_result.failure_code if stop_result is not None else None),
            error_message=(stop_result.error_message if stop_result is not None else None),
            remaining_pids=(),
            source="stop_result" if stop_result is not None else "none",
            remote_session_started=(
                bool(remote_session_started) if remote_session_started is not None else False
            ),
            provider_outcome_seen=False,
        )
    if stop_result is None:
        return AttemptFinalizerEvidence(
            execution_kind=kind,
            process_started=False,
            termination_confirmed_dead=None,
            remote_stop_acknowledged=None,
            failure_code=None,
            error_message=None,
            remaining_pids=(),
            source="none",
        )
    dead = (
        None
        if stop_result.local_process_confirmed_dead is None
        else bool(stop_result.local_process_confirmed_dead)
    )
    return AttemptFinalizerEvidence(
        execution_kind=kind,
        process_started=bool(stop_result.local_process_started),
        termination_confirmed_dead=dead,
        remote_stop_acknowledged=None,
        failure_code=stop_result.failure_code,
        error_message=stop_result.error_message,
        remaining_pids=tuple(stop_result.remaining_pids or ()),
        source="stop_result",
    )


# ────────────────────────── 唯一终态事务 ──────────────────────────


@dataclass(frozen=True)
class AttemptConvergenceRequest:
    """统一终态事务请求（doc §8.1）。"""

    job_id: str
    run_token: str
    worker_boot_id: str
    requested_status: Optional[AiJobStatus]
    reason: Optional[str]
    evidence: AttemptFinalizerEvidence
    session_revision: Optional[int] = None
    result_patch: Optional[Dict[str, Any]] = None
    context_patch: Optional[Dict[str, Any]] = None
    intent: ConvergenceIntent = ConvergenceIntent.NORMAL_FINALIZE
    message: Optional[str] = None
    progress: Optional[int] = None
    error_message: Optional[str] = None
    session_id: Optional[str] = None
    agent_backend: Optional[str] = None
    mark_task_interrupted: bool = False
    interrupt_session_id: Optional[str] = None
    reap_bookkeeping: bool = False


@dataclass
class ConvergenceResult:
    """统一终态事务结果；``changed=False`` 表示被 fence/幂等拦下。"""

    job_id: str
    status: str
    payload: Optional[Dict[str, Any]] = None
    changed: bool = False
    broadcast: bool = False
    is_final: bool = False


def _has_local_ownership(job: SddAiJob) -> bool:
    return job.process_pid is not None or job.process_group_id is not None


def _clear_ownership_fields(job: SddAiJob) -> None:
    """仅当统一事务判定允许进入业务终态时调用（doc C2/§8.4）。"""
    job.heartbeat_at = None
    job.lease_expires_at = None
    job.process_pid = None
    job.process_started_at = None
    job.process_group_id = None
    job.process_containment_id = None
    job.run_token = None
    job.worker_id = None
    job.worker_boot_id = None


def _job_row_execution_kind(job: SddAiJob, evidence: AttemptFinalizerEvidence) -> ExecutionKind:
    kind = str(job.process_execution_kind or "").strip()
    if kind in EXECUTION_KINDS:
        return kind  # type: ignore[return-value]
    if evidence.execution_kind in EXECUTION_KINDS:
        return evidence.execution_kind
    return EXECUTION_KIND_LOCAL_PROCESS


def _derive_termination_business_status(
    job: SddAiJob,
    request: AttemptConvergenceRequest,
) -> AiJobStatus:
    """TERMINATION/REAPER 意图下“死亡已证明”时的业务终态（渠道策略）。"""
    if request.requested_status is not None:
        return request.requested_status
    queue_key = str(job.queue_key or "")
    if queue_key.startswith("REQUIREMENT_PREVIEW:") and int(job.attempt_count or 0) < int(
        job.max_attempts or 1
    ):
        return AiJobStatus.PENDING
    if job.cancel_requested_at is not None:
        return AiJobStatus.CANCELLED
    if queue_key.startswith("TASK_BASELINE:"):
        return AiJobStatus.FAILED
    if job.channel == AiJobChannel.TASK_CHAT:
        return AiJobStatus.INTERRUPTED
    return AiJobStatus.FAILED


def _apply_task_interrupt_in_txn(
    db: Session,
    job: SddAiJob,
    task: Optional[SddTask],
    request: AttemptConvergenceRequest,
    now: datetime,
) -> None:
    """TASK_CHAT 可恢复中断（正常失败路径）：job + task 同事务更新。"""
    reason_text = str(request.reason or "AI 执行异常")[:500]
    resolved_session_id = str(
        request.interrupt_session_id
        or request.session_id
        or job.session_id
        or (getattr(task, "session_id", None) or "")
    ).strip() or None
    patch: Dict[str, Any] = {
        "interrupted": True,
        "interrupted_at": now.isoformat() + "Z",
    }
    if request.context_patch:
        patch.update(request.context_patch)
    job.status = AiJobStatus.INTERRUPTED
    job.progress = 100
    job.message = request.message or "AI 执行异常，可继续发送消息恢复"
    job.error_message = None
    job.session_id = resolved_session_id
    job.interrupt_reason = reason_text
    job.interrupted_by_id = None
    job.interrupted_at = now
    job.finished_at = now
    job.context_json = _merge_json(job.context_json, patch)
    if request.result_patch:
        job.result_json = _merge_json(job.result_json, request.result_patch)
    if request.evidence.failure_code:
        job.failure_code = request.evidence.failure_code
    if task and task.status not in {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.BASELINED}:
        # 用户已显式关闭/失败的任务不能被引擎回调降级回 INTERRUPTED。
        task.status = TaskStatus.INTERRUPTED
        task.session_id = resolved_session_id
        task.error_message = None
        task.interrupt_reason = reason_text
        task.interrupted_by_id = None
        task.interrupted_at = now
    _clear_ownership_fields(job)


def _apply_business_status_in_txn(
    db: Session,
    job: SddAiJob,
    request: AttemptConvergenceRequest,
    final_status: AiJobStatus,
    reason: str,
    now: datetime,
) -> None:
    """写入允许的业务终态（含渠道默认文案），并清空 ownership。"""
    termination_like = request.intent != ConvergenceIntent.NORMAL_FINALIZE
    queue_key = str(job.queue_key or "")
    if final_status == AiJobStatus.PENDING:
        # Requirement preview 中断重试：回到队列而不是终态。
        job.status = AiJobStatus.PENDING
        job.progress = 0
        job.message = request.message or "Agent interrupted; preview queued for retry"
        job.error_message = request.error_message or reason or None
        job.finished_at = None
        _clear_ownership_fields(job)
    elif final_status == AiJobStatus.INTERRUPTED and request.mark_task_interrupted:
        task = (
            db.query(SddTask).filter(SddTask.id == job.task_id).first()
            if job.task_id
            else None
        )
        _apply_task_interrupt_in_txn(db, job, task, request, now)
    elif final_status == AiJobStatus.INTERRUPTED:
        job.status = AiJobStatus.INTERRUPTED
        job.progress = 100
        job.message = request.message or "AI session interrupted unexpectedly"
        job.error_message = request.error_message if request.error_message is not None else reason
        job.finished_at = now
        job.interrupt_reason = reason
        _clear_ownership_fields(job)
    else:
        job.status = final_status
        job.progress = 100
        if final_status == AiJobStatus.CANCELLED:
            job.message = request.message or "Job cancelled by user"
            job.error_message = request.error_message
        elif final_status == AiJobStatus.FAILED and queue_key.startswith("TASK_BASELINE:"):
            job.message = request.message or "Baseline process interrupted; rebuild manually"
            job.error_message = request.error_message if request.error_message is not None else reason
        elif final_status == AiJobStatus.FAILED and termination_like:
            job.message = request.message or "AI execution failed during termination"
            job.error_message = request.error_message if request.error_message is not None else reason
        else:
            job.message = request.message if request.message is not None else job.message
            job.error_message = request.error_message
        if request.result_patch:
            job.result_json = _merge_json(job.result_json, request.result_patch)
        if request.context_patch:
            job.context_json = _merge_json(job.context_json, request.context_patch)
        if request.session_id is not None:
            job.session_id = request.session_id
        if request.agent_backend is not None:
            job.agent_backend = request.agent_backend
        job.finished_at = now
        _clear_ownership_fields(job)
    if request.progress is not None and final_status != AiJobStatus.PENDING:
        job.progress = max(0, min(100, int(request.progress)))
    if not termination_like and final_status in {AiJobStatus.FAILED, AiJobStatus.INTERRUPTED}:
        # 外围异常收尾必须保留结构化 failure code（诊断，不反向改变终态）。
        if request.evidence.failure_code:
            job.failure_code = request.evidence.failure_code
    if termination_like:
        # 终止/收割路径的统一 bookkeeping（与旧 _finish_termination_sync 一致）。
        job.terminal_reason = reason
        job.failure_code = request.evidence.failure_code or reason or job.failure_code
        job.last_reap_verified_at = now
        job.next_reap_at = None


def _apply_orphaned_in_txn(
    job: SddAiJob,
    request: AttemptConvergenceRequest,
    *,
    default_failure_code: str,
    now: datetime,
) -> None:
    """ORPHANED：ownership 必须完整保留（doc §8.4）。"""
    reason = str(request.reason or default_failure_code)
    job.status = AiJobStatus.ORPHANED
    job.message = request.message or "Agent process could not be confirmed dead"
    job.error_message = request.error_message if request.error_message is not None else reason
    job.failure_code = request.evidence.failure_code or default_failure_code
    job.terminal_reason = reason
    job.lease_expires_at = now
    job.orphaned_at = job.orphaned_at or now
    job.first_failure_at = job.first_failure_at or now
    if request.evidence.remaining_pids:
        job.context_json = _merge_json(
            job.context_json,
            {
                "unconfirmed_process_pids": [int(pid) for pid in request.evidence.remaining_pids],
                "unconfirmed_failure_code": job.failure_code,
            },
        )
    if request.reap_bookkeeping:
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
        job.last_reap_attempt_at = now
        job.last_reap_verified_at = now
        job.reap_failure_count = failures
        job.last_reap_error = reason
        job.next_reap_at = now + timedelta(seconds=backoff)


def _decide_final_status(
    job: SddAiJob,
    request: AttemptConvergenceRequest,
    execution_kind: ExecutionKind,
) -> Tuple[AiJobStatus, str]:
    """决策表（doc §8.3）的唯一实现；返回 (final_status, orphan_failure_code)。"""
    evidence = request.evidence
    intent = request.intent
    reason = str(request.reason or "")
    if intent == ConvergenceIntent.NORMAL_FINALIZE:
        if execution_kind == EXECUTION_KIND_REMOTE_SESSION:
            # 远程会话的证据底线（doc 修复方案 §8.3）：业务终态必须以
            # provider outcome、明确 stop ACK 或“会话从未建立”三者之一为
            # 依据。异常断线（无 outcome、无 ACK）绝不允许清 ownership。
            if evidence.provider_outcome_seen:
                return request.requested_status or AiJobStatus.FAILED, REMOTE_STOP_UNCONFIRMED
            if evidence.remote_session_started is False and evidence.remote_stop_acknowledged is None:
                # 从未建立远程会话：没有需要停止的服务端回合。
                return request.requested_status or AiJobStatus.FAILED, REMOTE_STOP_UNCONFIRMED
            if evidence.remote_stop_acknowledged is True:
                return request.requested_status or AiJobStatus.FAILED, REMOTE_STOP_UNCONFIRMED
            # 会话已建立但既无 outcome 也无 ACK（含 stop NACK）：
            # ORPHANED，保留 ownership / durable locator 给 reaper。
            return AiJobStatus.ORPHANED, evidence.failure_code or REMOTE_STOP_UNCONFIRMED
        unresolved_local = (
            (evidence.process_started is True or evidence.termination_confirmed_dead is False)
            and evidence.termination_confirmed_dead is not True
        )
        unresolved_persisted_owner = _has_local_ownership(job) and (
            evidence.termination_confirmed_dead is not True
        )
        if unresolved_local or unresolved_persisted_owner:
            return AiJobStatus.ORPHANED, evidence.failure_code or PROCESS_TREE_STILL_ALIVE
        return request.requested_status or AiJobStatus.FAILED, PROCESS_TREE_STILL_ALIVE

    # TERMINATION_FINALIZE / REAPER_FINALIZE
    if execution_kind == EXECUTION_KIND_REMOTE_SESSION:
        if evidence.remote_stop_acknowledged is True:
            return _derive_termination_business_status(job, request), REMOTE_STOP_UNCONFIRMED
        if evidence.provider_outcome_seen:
            # 取消请求到达前远程回合已经自然结束：无需停止证明。
            return _derive_termination_business_status(job, request), REMOTE_STOP_UNCONFIRMED
        if not evidence.remote_session_started and evidence.remote_stop_acknowledged is None:
            # 远程会话从未建立且从未尝试停止：没有需要停止的服务端回合。
            return _derive_termination_business_status(job, request), REMOTE_STOP_UNCONFIRMED
        return AiJobStatus.ORPHANED, evidence.failure_code or REMOTE_STOP_UNCONFIRMED
    if evidence.termination_confirmed_dead is True:
        return _derive_termination_business_status(job, request), PROCESS_TREE_STILL_ALIVE
    if evidence.termination_confirmed_dead is False:
        # dead=False 本身就是“无法证明死亡/仍有存活进程”的权威证据。
        return AiJobStatus.ORPHANED, evidence.failure_code or PROCESS_TREE_STILL_ALIVE
    if not evidence.process_started and not _has_local_ownership(job):
        # 明确从未启动本地进程（dead 未知且无任何归属）：允许取消/中断终态。
        return _derive_termination_business_status(job, request), PROCESS_TREE_STILL_ALIVE
    return AiJobStatus.ORPHANED, evidence.failure_code or PROCESS_TREE_STILL_ALIVE


def converge_job_attempt_in_txn(
    db: Session,
    request: AttemptConvergenceRequest,
) -> ConvergenceResult:
    """唯一 job 终态事务核心（doc §8.2 / 修复方案 §7.3.1）。

    事务顺序固定：行锁 SELECT FOR UPDATE -> 幂等检查 -> run token / worker
    boot id 校验 -> TASK_CHAT session revision 校验 -> 按 intent 校验来源
    状态 -> 读取显式 execution kind -> 决策表 -> 同事务写 job/task/patch/
    ownership -> 返回。

    本核心不 commit、不 refresh：任何已经处在 ``run_db_txn()`` 或 route
    transaction 中的调用方必须使用本函数，提交所有权归最外层事务。
    """
    now = datetime.utcnow()
    job = (
        db.query(SddAiJob)
        .filter(SddAiJob.id == request.job_id)
        .with_for_update()
        .first()
    )
    if job is None:
        return ConvergenceResult(job_id=request.job_id, status="", payload=None, changed=False)

    def _noop() -> ConvergenceResult:
        return ConvergenceResult(
            job_id=job.id,
            status=str(job.status.value if hasattr(job.status, "value") else job.status),
            payload=None,
            changed=False,
        )

    # 2. 真正终态 / WAITING_HITL：幂等返回。
    if job.status in {
        AiJobStatus.SUCCESS,
        AiJobStatus.FAILED,
        AiJobStatus.CANCELLED,
        AiJobStatus.REVERTED,
    } or job.status == AiJobStatus.WAITING_HITL:
        return _noop()

    # 3. run token / worker boot id 校验。
    token = str(request.run_token or "").strip()
    boot_id = str(request.worker_boot_id or "").strip()
    if token:
        if str(job.run_token or "") != token or str(job.worker_boot_id or "") != boot_id:
            return _noop()
    else:
        # 无 durable token 的调用方只能收敛完全无归属的行。
        if job.run_token is not None or job.worker_boot_id is not None:
            return _noop()

    # 4. TASK_CHAT session revision 校验（仅正常收尾路径）。
    if (
        request.intent == ConvergenceIntent.NORMAL_FINALIZE
        and job.channel == AiJobChannel.TASK_CHAT
        and job.task_id
        and job.session_revision is not None
    ):
        task_revision_row = (
            db.query(SddTask.session_revision).filter(SddTask.id == job.task_id).first()
        )
        if not task_revision_row or int(task_revision_row[0] or -1) != int(job.session_revision):
            return _noop()

    # 5. 按 intent 校验来源状态。
    if request.intent == ConvergenceIntent.NORMAL_FINALIZE:
        # PENDING 仅覆盖未走队列 claim 的直接调用方（无并发终态交错风险）；
        # RUNNING/INTERRUPTED 是锁协议真正需要保护的业务来源。
        if job.status not in {
            AiJobStatus.PENDING,
            AiJobStatus.RUNNING,
            AiJobStatus.INTERRUPTED,
        }:
            return _noop()
        if job.cancel_requested_at is not None:
            # 取消已请求：正常收尾不得绕过 termination convergence。
            return _noop()
    else:
        if job.status not in {AiJobStatus.TERMINATING, AiJobStatus.ORPHANED}:
            return _noop()

    # 6. 读取显式 execution kind。
    execution_kind = _job_row_execution_kind(job, request.evidence)

    # 7. 决策表。
    final_status, orphan_failure_code = _decide_final_status(job, request, execution_kind)

    # 8. 同一事务写 job / task / patch / ownership。
    if final_status == AiJobStatus.ORPHANED:
        _apply_orphaned_in_txn(
            job,
            request,
            default_failure_code=orphan_failure_code,
            now=now,
        )
    else:
        _apply_business_status_in_txn(
            db,
            job,
            request,
            final_status,
            str(request.reason or ""),
            now,
        )
    payload = _serialize_converged_job(job)
    is_final = final_status in {
        AiJobStatus.SUCCESS,
        AiJobStatus.FAILED,
        AiJobStatus.CANCELLED,
        AiJobStatus.REVERTED,
    }
    return ConvergenceResult(
        job_id=job.id,
        status=str(final_status.value),
        payload=payload,
        changed=True,
        broadcast=True,
        is_final=is_final,
    )


def converge_job_attempt_sync(
    db: Session,
    request: AttemptConvergenceRequest,
) -> ConvergenceResult:
    """拥有 commit 的终态 wrapper（doc §7.3.1）。

    仅当调用方自己拥有独立事务（自建 Session / 独立 ``SessionLocal()``）时
    使用本入口；嵌套在 ``run_db_txn()`` 中的调用方必须改用
    :func:`converge_job_attempt_in_txn`，否则会把业务副作用提前提交。
    """
    result = converge_job_attempt_in_txn(db, request)
    if not result.changed:
        return result
    db.commit()
    refreshed = (
        db.query(SddAiJob).filter(SddAiJob.id == request.job_id).first()
    )
    if refreshed is not None:
        result.payload = _serialize_converged_job(refreshed)
    return result


# ────────────────────────── 唯一取消/中断请求事务 ──────────────────────────


TerminationMode = Literal["CANCEL", "INTERRUPT", "WORKER_SHUTDOWN"]


@dataclass(frozen=True)
class AttemptTerminationRequest:
    """唯一取消/中断请求（doc §4.5.1）。

    所有取消路径（单任务取消、批量取消、任务中断、worker shutdown）都必须
    通过 :func:`request_attempt_termination_in_txn` 写入 job 状态；禁止任何
    生产路径直接把活动 job 写成 TERMINATING/CANCELLED。
    """

    job_id: str
    workspace_id: Optional[str] = None
    task_id: Optional[str] = None
    actor_user_id: Optional[str] = None
    reason: str = ""
    mode: TerminationMode = "CANCEL"
    expected_run_token: Optional[str] = None
    message: Optional[str] = None
    failure_code: Optional[str] = None
    interrupt_session_id: Optional[str] = None
    interrupt_context_patch: Optional[Dict[str, Any]] = None
    mark_task_interrupted: bool = False


@dataclass
class TerminationRequestResult:
    """唯一取消/中断请求结果；``changed=False`` 表示幂等/被 fence 拦下。"""

    job_id: str
    status: str
    changed: bool
    run_token: Optional[str] = None
    session_id: Optional[str] = None
    worker_boot_id: Optional[str] = None


def _job_active_ownership(job: SddAiJob) -> bool:
    return job.process_pid is not None or job.process_group_id is not None


def request_attempt_termination_in_txn(
    db: Session,
    request: AttemptTerminationRequest,
) -> TerminationRequestResult:
    """唯一取消/中断请求事务核心（doc §4.5.1）。

    规则：
    1. 使用 ``with_for_update()`` 锁定 job 行（与业务 finalizer 共享行锁）；
    2. 持锁后重新读取 status / run token / worker boot id；
    3. 已是业务终态时幂等返回，绝不恢复为非终态；
    4. ``PENDING/WAITING_HITL`` 且无活动 ownership 时可直接写 ``CANCELLED``；
    5. ``RUNNING/TERMINATING/ORPHANED`` 统一写 ``TERMINATING``；
    6. 同一事务内写 ``cancel_requested_at``、interrupt metadata 和必要的
       task 状态；
    7. 不广播、不触发内存 cancel event —— 由最外层事务提交成功后执行。
    """
    now = datetime.utcnow()
    reason = str(request.reason or request.mode).strip() or request.mode
    job_query = db.query(SddAiJob).filter(SddAiJob.id == request.job_id)
    if request.workspace_id:
        job_query = job_query.filter(SddAiJob.workspace_id == request.workspace_id)
    if request.expected_run_token:
        job_query = job_query.filter(SddAiJob.run_token == request.expected_run_token)
    job = job_query.with_for_update().first()
    if job is None:
        return TerminationRequestResult(
            job_id=request.job_id, status="", changed=False
        )

    def _result(changed: bool) -> TerminationRequestResult:
        return TerminationRequestResult(
            job_id=str(job.id),
            status=str(
                job.status.value if hasattr(job.status, "value") else job.status
            ),
            changed=changed,
            run_token=str(job.run_token or "") or None,
            session_id=str(job.session_id or "") or None,
            worker_boot_id=str(job.worker_boot_id or "") or None,
        )

    if job.status in {
        AiJobStatus.SUCCESS,
        AiJobStatus.FAILED,
        AiJobStatus.CANCELLED,
        AiJobStatus.REVERTED,
    }:
        # 幂等：终态永不回退（doc §4.5.1 规则 3）。
        return _result(False)

    resolved_session_id = str(
        request.interrupt_session_id or (job.session_id or "")
    ).strip() or None

    if job.status in {AiJobStatus.PENDING, AiJobStatus.WAITING_HITL} and (
        request.mode != "WORKER_SHUTDOWN"
        and not _job_active_ownership(job)
    ):
        # 无活动归属的排队/HITL 作业：直接落 CANCELLED 终态。
        job.cancel_requested_at = now
        job.status = AiJobStatus.CANCELLED
        job.progress = 100
        job.message = request.message or "Job cancelled by user"
        job.error_message = None
        job.finished_at = now
        if request.mode == "INTERRUPT":
            job.interrupt_reason = reason
            job.interrupted_by_id = request.actor_user_id
            job.interrupted_at = now
            if request.interrupt_context_patch:
                job.context_json = _merge_json(
                    job.context_json, request.interrupt_context_patch
                )
        return _result(True)

    job.cancel_requested_at = now
    job.status = AiJobStatus.TERMINATING
    if request.mode == "INTERRUPT":
        job.message = request.message or "AI session interrupted by user"
    else:
        job.message = request.message or "Job cancellation requested"
    job.terminal_reason = reason
    job.failure_code = (
        request.failure_code
        or (CANCEL_REQUESTED if request.mode == "CANCEL" else reason)
    )
    job.termination_attempts = int(job.termination_attempts or 0) + 1
    job.finished_at = None
    if request.mode == "INTERRUPT":
        job.error_message = None
        job.session_id = resolved_session_id
        job.interrupt_reason = reason
        job.interrupted_by_id = request.actor_user_id
        job.interrupted_at = now
        patch: Dict[str, Any] = {
            "interrupted": True,
            "interrupted_at": now.isoformat() + "Z",
        }
        if request.actor_user_id:
            patch["interrupted_by_id"] = request.actor_user_id
        if request.interrupt_context_patch:
            patch.update(request.interrupt_context_patch)
        job.context_json = _merge_json(job.context_json, patch)
        if request.mark_task_interrupted and job.task_id:
            task = (
                db.query(SddTask).filter(SddTask.id == job.task_id).first()
            )
            if task is not None and task.status not in {
                TaskStatus.DONE,
                TaskStatus.FAILED,
                TaskStatus.BASELINED,
            }:
                task_session_id = resolved_session_id or str(
                    getattr(task, "session_id", None) or ""
                ).strip() or None
                task.status = TaskStatus.INTERRUPTED
                task.session_id = task_session_id
                task.error_message = None
                task.interrupt_reason = reason
                task.interrupted_by_id = request.actor_user_id
                task.interrupted_at = now
    return _result(True)


def _serialize_converged_job(job: SddAiJob) -> Dict[str, Any]:
    """Serialize the converged row without importing ai_job_service (no cycles)."""
    def _as_text(value: Any) -> str:
        return value.value if hasattr(value, "value") else str(value)

    return {
        "id": job.id,
        "workspace_id": job.workspace_id,
        "task_id": job.task_id,
        "asset_id": job.asset_id,
        "thread_id": job.thread_id,
        "channel": _as_text(job.channel),
        "queue_key": job.queue_key,
        "status": _as_text(job.status),
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


__all__ = [
    "ConvergenceIntent",
    "AttemptConvergenceRequest",
    "ConvergenceResult",
    "AttemptFencedError",
    "AttemptTerminationRequest",
    "TerminationRequestResult",
    "TerminationMode",
    "EVIDENCE_CONFLICT",
    "REMOTE_STOP_UNCONFIRMED",
    "PROCESS_TREE_STILL_ALIVE",
    "resolve_attempt_evidence",
    "evidence_from_stop_result",
    "converge_job_attempt_in_txn",
    "converge_job_attempt_sync",
    "request_attempt_termination_in_txn",
]
