"""Attempt 生命周期：fence、证据解析、进程身份、终止收敛与取消入口。

一次 attempt 指「一次被认领的作业执行」。本模块负责：

- 读取当前 attempt 的绑定上下文与执行类别；
- 从 attempt runtime / typed 异常 / stop 结果解析唯一死亡证据
  （决策表本体在 :mod:`ai_job_convergence_service`，这里只做转交）；
- 将本地进程身份持久化到作业行（PID attach fence）；
- TERMINATING/REAPER 收敛与对外终止 API（``finalize_attempt_termination``）；
- 用户取消入口（``cancel_job`` / ``mark_task_chat_jobs_cancelled``）。
"""

from __future__ import annotations

import dataclasses
from typing import Any

from app.agents import (
    EXECUTION_KIND_LOCAL_PROCESS,
    EXECUTION_KIND_REMOTE_SESSION,
    AgentAttemptContext,
    AgentAttemptRuntimeState,
    AgentStopResult,
    ProviderCallState,
    current_agent_attempt,
    current_agent_attempt_runtime,
    record_attempt_provider_call_stop,
)
from app.agents.supervision import (
    agent_stop_result_from_termination,
    process_supervisor,
)
from app.core.logging import get_logger
from app.core.offload import run_db
from app.database import SessionLocal
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services import ai_job_convergence_service as convergence
from app.domains.ai.services.ai_job_convergence_service import (
    AttemptConvergenceRequest,
    AttemptTerminationRequest,
    ConvergenceIntent,
    request_attempt_termination_in_txn,
    resolve_attempt_evidence,
)
from app.domains.ai.services.ai_job_convergence_service import (
    AttemptFinalizerEvidence as _FinalizerEvidence,
)
from app.domains.ai.services.jobs.constants import FINAL_STATUSES
from app.domains.ai.services.jobs.registry import WORKER_BOOT_ID, WORKER_ID, runtime

logger = get_logger(__name__, category="ai_session")


# ────────────────────────── 绑定上下文 ──────────────────────────


def load_attempt_context_sync(job_id: str) -> AgentAttemptContext | None:
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


def attempt_execution_kind() -> str:
    """Durable execution kind of the bound attempt (never inferred from PIDs)."""
    attempt = current_agent_attempt()
    kind = getattr(attempt, "execution_kind", None) if attempt else None
    return (
        kind if kind in (EXECUTION_KIND_LOCAL_PROCESS, EXECUTION_KIND_REMOTE_SESSION) else EXECUTION_KIND_LOCAL_PROCESS
    )


# ────────────────────────── 证据解析 ──────────────────────────


def resolve_current_attempt_evidence(
    *,
    execution_kind: str | None = None,
    runtime: AgentAttemptRuntimeState | None = None,
    stop_result: AgentStopResult | None = None,
    typed_error: BaseException | None = None,
    provider_result: Any | None = None,
    fallback_started: bool | None = None,
    fallback_dead: bool | None = None,
    fallback_failure_code: str | None = None,
    fallback_remaining_pids: tuple = (),
) -> _FinalizerEvidence:
    """唯一证据解析入口：identity-aware runtime 为权威。"""
    return resolve_attempt_evidence(
        execution_kind=execution_kind or attempt_execution_kind(),
        runtime=runtime if runtime is not None else current_agent_attempt_runtime(),
        stop_result=stop_result,
        typed_error=typed_error,
        provider_result=provider_result,
        fallback_started=fallback_started,
        fallback_dead=fallback_dead,
        fallback_failure_code=fallback_failure_code,
        fallback_remaining_pids=fallback_remaining_pids,
    )


def attempt_evidence(exc: BaseException | None = None) -> tuple[bool, bool | None]:
    """Return (process_started, dead) from the attempt runtime + typed exception.

    The identity-aware runtime aggregate is authoritative; the typed exception
    attributes are only a compatibility fallback.
    """
    evidence = resolve_current_attempt_evidence(typed_error=exc)
    return (evidence.process_started, evidence.termination_confirmed_dead)


def attempt_process_started(exc: BaseException | None = None) -> bool:
    return attempt_evidence(exc)[0]


def attempt_termination_evidence(exc: BaseException | None = None) -> bool | None:
    """Read the authoritative attempt-local death proof (with typed-exception fallback)."""
    return attempt_evidence(exc)[1]


def bridge_stop_result(bridge: Any) -> AgentStopResult | None:
    """Convert the bridge's last local termination into the unified stop result.

    返回 None 表示该 bridge 没有（或尚未产生）本地终止结果；远程 bridge
    （shim）的停止证据由 ``record_attempt_remote_stop`` 写入 runtime。
    """
    termination = getattr(bridge, "last_termination", None)
    if termination is None:
        return None
    return agent_stop_result_from_termination(termination)


def close_unresolved_provider_call(
    call: Any | None,
    *,
    stop_acknowledged: bool = False,
    tree_dead: bool = False,
) -> None:
    """Close an unresolved provider call when its outcome can never arrive.

    P1：明确 stop ACK（绑定本次 bridge/调用的会话
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
        # P0：把本次停止 ACK 绑定到具体 call。
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


def provider_call_ready_for_retry(
    call: Any | None,
    attempt: AgentAttemptContext | None,
) -> bool:
    """Retry gate: the previous call must be finished before overlapping.

    P1：远程不能因为 ``process_started=False`` 就允许与
    未结束调用重叠——前一次调用必须已 ENDED（真实 result 或绑定 ACK 终止）
    才允许启动下一次。无证据登记能力（runtime 缺失）时保持旧行为。
    """
    if call is None:
        return True
    if call.state in (ProviderCallState.ENDED, ProviderCallState.NOT_STARTED):
        return True
    kind = getattr(attempt, "execution_kind", None) or EXECUTION_KIND_LOCAL_PROCESS
    # 远程 STARTED/UNKNOWN 禁止重叠；本地进程的死亡证据已由调用方检查。
    return kind != EXECUTION_KIND_REMOTE_SESSION


# ────────────────────────── 进程身份落库 ──────────────────────────


def persist_process_identity_sync(job_id: str, run_token: str, identity) -> bool:
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
            # 显式声明的非本地执行类别不允许 attach 本地 PID。
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


def _merge_json(original: Any, patch: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(original) if isinstance(original, dict) else {}
    if patch:
        merged.update(patch)
    return merged


async def persist_process_identity(identity, attempt: AgentAttemptContext | None) -> bool:
    """Engine 注入的 ``on_process_started`` 钩子：attach 本地进程身份。"""
    if getattr(identity, "pid", None) is None or attempt is None:
        return True
    return await run_db(
        persist_process_identity_sync,
        attempt.job_id,
        attempt.run_token,
        identity,
    )


# ────────────────────────── 取消/终态判定 ──────────────────────────


def is_job_cancelled_or_final_sync(job_id: str) -> bool:
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


async def is_job_cancelled_or_final(job_id: str) -> bool:
    """取消已请求，或 DB 中任务已进入终态（如被中断/停止标记为 CANCELLED）。"""
    if runtime.is_cancel_requested(job_id):
        return True
    return await run_db(is_job_cancelled_or_final_sync, job_id)


# ────────────────────────── 终止收敛 ──────────────────────────


def begin_termination_sync(job_id: str, run_token: str, reason: str) -> bool:
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


def termination_evidence_for_row(
    row: SddAiJob | None,
    *,
    confirmed_dead: bool | None,
    failure_code: str | None,
    reason: str | None,
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
    started = bool(row is not None and (row.process_pid is not None or row.process_group_id is not None))
    remote_started = False
    if kind == EXECUTION_KIND_REMOTE_SESSION:
        remote_started = bool(
            (row is not None and str(getattr(row, "session_id", None) or "").strip()) or confirmed_dead is False
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


def converge_termination_sync(
    job_id: str,
    run_token: str,
    *,
    evidence: _FinalizerEvidence,
    reason: str,
    failure_code: str | None = None,
    intent: ConvergenceIntent = ConvergenceIntent.TERMINATION_FINALIZE,
    termination_mode: str | None = None,
) -> dict[str, Any] | None:
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
            termination_mode=termination_mode,
        )
        result = convergence.converge_job_attempt_sync(db, request)
        if not result.changed or not result.payload:
            return None
        return result.payload
    finally:
        db.close()


def finish_termination_sync(
    job_id: str,
    run_token: str,
    *,
    confirmed_dead: bool,
    reason: str,
    failure_code: str,
    evidence: _FinalizerEvidence | None = None,
) -> dict[str, Any] | None:
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
        evidence = termination_evidence_for_row(
            row,
            confirmed_dead=bool(confirmed_dead),
            failure_code=str(failure_code or "") or None,
            reason=str(reason or ""),
        )
    return converge_termination_sync(
        job_id,
        run_token,
        evidence=evidence,
        reason=str(reason or ""),
        failure_code=str(failure_code or "") or None,
        intent=ConvergenceIntent.REAPER_FINALIZE,
    )


# ────────────────────────── 心跳与 attempt 终止 ──────────────────────────


async def terminate_attempt(attempt: AgentAttemptContext, reason: str) -> None:
    from app.domains.ai.services.jobs.publishing import (
        broadcast_job_payload,
        reschedule_if_pending,
    )

    begun = await run_db(begin_termination_sync, attempt.job_id, attempt.run_token, reason)
    # 心跳任务继承 runner 的 attempt/runtime 绑定：唯一 resolver 可以直接
    # 消费本 attempt 的进程/远程停止证据。
    evidence = resolve_current_attempt_evidence(execution_kind=attempt.execution_kind)
    if attempt.execution_kind == EXECUTION_KIND_LOCAL_PROCESS:
        result = await process_supervisor.stop_attempt(attempt.run_token, reason)
        evidence = resolve_current_attempt_evidence(
            execution_kind=attempt.execution_kind,
            stop_result=agent_stop_result_from_termination(result),
        )
        if not begun:
            return
    else:
        if not begun:
            return
    payload = await run_db(
        converge_termination_sync,
        attempt.job_id,
        attempt.run_token,
        evidence=evidence,
        reason=str(evidence.error_message or reason),
        failure_code=evidence.failure_code or reason,
    )
    if payload:
        runtime.clear_cancel_for_payload(payload)
        await broadcast_job_payload(payload)
        reschedule_if_pending(payload)


async def finalize_attempt_termination(
    job_id: str,
    run_token: str | None,
    *,
    confirmed_dead: bool,
    reason: str,
    failure_code: str,
    evidence: _FinalizerEvidence | None = None,
    termination_mode: str | None = None,
) -> dict[str, Any] | None:
    """Converge a stopped attempt only after process-death verification.

    Callers that own an engine (for example the task interrupt endpoint) use
    this after the engine has attempted to stop its CLI.  A missing token is
    deliberately not accepted: without fencing there is no safe owner for a
    durable state transition.  Remote backends must pass structured
    ``evidence`` built from the unified stop result.
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
        evidence = termination_evidence_for_row(
            row,
            confirmed_dead=bool(confirmed_dead),
            failure_code=str(failure_code or "") or None,
            reason=str(reason or ""),
        )
    payload = await run_db(
        converge_termination_sync,
        job_id,
        token,
        evidence=evidence,
        reason=str(reason or ""),
        failure_code=str(failure_code or "") or None,
        termination_mode=termination_mode,
    )
    if payload:
        from app.domains.ai.services.jobs.publishing import reschedule_if_pending

        reschedule_if_pending(payload)
    return payload


# ────────────────────────── 用户取消入口 ──────────────────────────


def mark_task_chat_jobs_cancelled(
    db,
    *,
    workspace_id: str,
    task_id: str,
    message: str = "Task execution stopped",
) -> list[str]:
    """批量取消请求：候选 id -> 排序 -> 逐个唯一 termination 事务。

    本函数不再直接写 job 状态：所有 TERMINATING/CANCELLED 写入都通过
    :func:`request_attempt_termination_in_txn`（与业务 finalizer 共享行锁）。
    cancel signal 在最外层 commit 之后才触发。
    """
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
    job_ids: list[str] = []
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
        # commit 之后才触发 runner 的 cancellation signal。
        for job_id in job_ids:
            runtime.request_cancel(job_id)
    return job_ids


def cancel_job(
    db,
    *,
    workspace_id: str,
    job_id: str,
) -> SddAiJob | None:
    """取消请求事务：唯一 termination request 入口。

    与 finalizer 共享同一 job 行锁，因此两种锁顺序只能得到：
    - cancel 先获得锁 -> finalizer 看到 TERMINATING 并转 termination convergence；
    - finalizer 先获得锁 -> cancel 看到真正终态并幂等返回。
    取消信号在 commit 之后才触发当前 runner。
    """
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
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id, SddAiJob.workspace_id == workspace_id).first()
        return job
    db.commit()
    job = db.query(SddAiJob).filter(SddAiJob.id == job_id, SddAiJob.workspace_id == workspace_id).first()
    if job is None:
        return None
    # commit 后才触发当前 runner 的 cancellation signal。
    runtime.request_cancel(job.id)
    return job
