"""队列 runner：认领 → 绑定 attempt → 心跳 → 执行 → 统一收敛收尾。

runner 是唯一把「作业行」变成「活动 attempt」的地方：认领事务写入
run token / lease / 执行类别；退出时经 :func:`_converge_runner_exit`
消费本次 attempt 的运行/停止证据，绝不静默离开 RUNNING（doc §10.2/§8.3）。
"""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any, Dict, Optional

from app.agents import (
    AgentAttemptContext,
    AgentAttemptRuntimeState,
    AgentStopResult,
    EXECUTION_KIND_LOCAL_PROCESS,
    bind_agent_attempt,
    bind_agent_attempt_runtime,
    reset_agent_attempt,
    reset_agent_attempt_runtime,
)
from app.agents.supervision import agent_stop_result_from_termination, process_supervisor
from app.config import settings
from app.core.distributed_lock import LockAcquireTimeout, lock_ai_queue
from app.core.logging import get_logger
from app.core.offload import run_db
from app.database import SessionLocal
from app.domains.ai.models.ai_job import AiJobStatus
from app.domains.ai.services import ai_job_convergence_service as convergence
from app.domains.ai.services.ai_job_convergence_service import (
    AttemptConvergenceRequest,
    AttemptFinalizerEvidence as _FinalizerEvidence,
    ConvergenceIntent,
)
from app.domains.ai.services.jobs import attempts as attempt_ops
from app.domains.ai.services.jobs import store
from app.domains.ai.services.jobs.constants import (
    FINAL_STATUSES,
    JOB_KIND_DIAGNOSIS_SUMMARY,
    JOB_KIND_TASK_BASELINE,
    QUEUE_KEY_TASK_BASELINE,
    QUEUE_KEY_TASK_CHAT,
)
from app.domains.ai.services.jobs import executors
from app.domains.ai.services.jobs.executors import JobExecutionOutcome
from app.domains.ai.services.jobs import publishing
from app.domains.ai.services.jobs.registry import WORKER_BOOT_ID, runtime

logger = get_logger(__name__, category="ai_session")


# ────────────────────────── 认领 ──────────────────────────


async def claim_next_pending_job_id(queue_key: str) -> Optional[str]:
    try:
        async with lock_ai_queue(queue_key):
            # 取队 4 stmts + commit 在 Redis 锁内完成，全部 off-loop
            return await run_db(store.take_next_pending_job_id_sync, queue_key)
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


# ────────────────────────── 心跳 ──────────────────────────


async def job_heartbeat_loop(attempt: AgentAttemptContext) -> None:
    interval = max(1, int(getattr(settings, "AI_JOB_HEARTBEAT_SECONDS", 10) or 10))
    try:
        while True:
            await asyncio.sleep(interval)
            if not await run_db(store.heartbeat_job_sync, attempt.job_id, attempt.run_token):
                await attempt_ops.terminate_attempt(attempt, "LEASE_LOST")
                return
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("AI job heartbeat failed: job_id={}", attempt.job_id)
        await attempt_ops.terminate_attempt(attempt, "HEARTBEAT_FAILURE")


# ────────────────────────── runner 收尾收敛 ──────────────────────────


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


async def _converge_runner_exit(
    attempt: AgentAttemptContext,
    runtime_state: AgentAttemptRuntimeState,
    outcome: JobExecutionOutcome,
) -> None:
    """唯一 runner 收尾点（doc §10.2 / §8.3）。

    在释放 attempt runtime 之前消费本次 attempt 的运行/停止证据：
    - 真正终态 / WAITING_HITL：幂等返回；
    - ORPHANED：保留给 reaper，不清 ownership；
    - TERMINATING：补做本地 stop（如需要）并立即按 termination 意图收敛
      CANCELLED/INTERRUPTED 或 ORPHANED，绝不等待默认 lease 到期；
    - RUNNING：业务执行路径漏掉 finalizer，兜底写安全终态，不得静默离开
      RUNNING。

    provider outcome 只能来自 :class:`JobExecutionOutcome` 的明确字段；
    “异常没有逃出 execute_job”绝不构成 provider outcome（doc §8.3）。
    """
    job_id = attempt.job_id
    status = await store.get_job_status(job_id)
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
        evidence = attempt_ops.resolve_current_attempt_evidence(
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
        # TERMINATING 行只接受 termination 意图（convergence 入口状态校验
        # §5）；业务终态由 `_derive_termination_business_status` 按取消位/
        # 渠道推导。
        payload = await run_db(
            attempt_ops.converge_termination_sync,
            job_id,
            attempt.run_token,
            evidence=evidence,
            reason=reason,
        )
        if payload:
            runtime.clear_cancel_for_payload(payload)
            await publishing.broadcast_job_payload(payload)
            publishing.reschedule_if_pending(payload)
        return

    # status == RUNNING：业务执行路径漏掉 finalizer，runner 兜底收敛。
    evidence = attempt_ops.resolve_current_attempt_evidence(
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
    is_task_chat = queue_key.startswith(f"{QUEUE_KEY_TASK_CHAT}:")
    if is_task_chat and not queue_key.startswith(f"{QUEUE_KEY_TASK_BASELINE}:"):
        context = await run_db(executors.load_dispatch_context_sync, job_id)
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
        runtime.clear_cancel_for_payload(payload)
        await publishing.broadcast_job_payload(payload)
        publishing.reschedule_if_pending(payload)


# ────────────────────────── 队列主循环 ──────────────────────────


async def run_queue(queue_key: str) -> None:
    lock = runtime.queue_lock(queue_key)
    async with lock:
        while True:
            if runtime.shutdown_in_progress():
                return
            job_id = await claim_next_pending_job_id(queue_key)
            if not job_id:
                return
            attempt = await run_db(attempt_ops.load_attempt_context_sync, job_id)
            if attempt is None:
                logger.warning("Claimed AI job has no current attempt context: {}", job_id)
                return
            context_token = bind_agent_attempt(attempt)
            # Attempt-local process evidence is bound with the same lifecycle
            # so wait/cancel/interrupt results can never leak across jobs.
            runtime_state = AgentAttemptRuntimeState()
            runtime_token = bind_agent_attempt_runtime(runtime_state)
            heartbeat_task = asyncio.create_task(job_heartbeat_loop(attempt))
            runtime.heartbeat_tasks[job_id] = heartbeat_task
            # 明确的执行 outcome 哨兵：executor 未产出 outcome / 异常逃逸时，
            # 收尾依据的是哨兵 error 而不是“正常完成”推断（doc §8.3）。
            outcome = JobExecutionOutcome(
                requested_status=None,
                error=RuntimeError("executor did not produce an outcome"),
            )
            try:
                await publishing.publish_job_state(job_id)
                try:
                    outcome = await executors.execute_job(job_id)
                except BaseException as exc:
                    # 保留异常供 runner 收敛使用；继续向上传播保持原语义。
                    outcome = dataclasses.replace(outcome, error=exc)
                    raise
            finally:
                # doc §10.1：stop heartbeat -> runner convergence（runtime 仍
                # 可读）-> reset runtime/attempt -> 决定是否继续队列。
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
                runtime.heartbeat_tasks.pop(job_id, None)
                if not runtime.shutdown_in_progress():
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
            status = await store.get_job_status(job_id)
            if status in {AiJobStatus.WAITING_HITL, AiJobStatus.INTERRUPTED}:
                return
