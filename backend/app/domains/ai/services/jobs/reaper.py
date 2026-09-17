"""孤儿作业回收器（reaper）。

职责：扫描 owner 消失/租约过期的 attempt 并收养（TERMINATING + 新 token），
按固定顺序停止远程会话与本地进程树，最后经统一 convergence 事务收敛终态。
死亡未被证明的 attempt 保持 ORPHANED 并退避重试（doc §8/§10.4）。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, or_

from app.agents import (
    AgentStopResult,
    EXECUTION_KIND_REMOTE_SESSION,
)
from app.agents.process_supervisor import process_supervisor
from app.core.logging import get_logger
from app.core.offload import run_db
from app.database import SessionLocal
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.ai.services.ai_job_convergence_service import (
    REMOTE_STOP_UNCONFIRMED,
    AttemptTerminationRequest,
    evidence_from_stop_result,
    request_attempt_termination_in_txn,
)
from app.domains.ai.services.jobs import attempts as attempt_ops
from app.domains.ai.services.jobs import publishing
from app.domains.ai.services.jobs.registry import WORKER_BOOT_ID, WORKER_ID
from app.domains.ai.services.jobs.store import row_has_leaked_interrupted_ownership

logger = get_logger(__name__, category="ai_session")


def _dirty_interrupted_ownership_predicate():
    return or_(
        SddAiJob.run_token.isnot(None),
        SddAiJob.worker_boot_id.isnot(None),
        SddAiJob.process_pid.isnot(None),
        SddAiJob.process_group_id.isnot(None),
        SddAiJob.lease_expires_at.isnot(None),
    )


# ────────────────────────── 可回收扫描与收养 ──────────────────────────


def list_reclaimable_jobs_sync(task_id: Optional[str] = None) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        rows = (
            db.query(SddAiJob)
            .filter(
                SddAiJob.task_id == task_id if task_id is not None else True,
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
                        _dirty_interrupted_ownership_predicate(),
                        SddAiJob.manual_intervention_required.isnot(True),
                    ),
                ),
            )
            .all()
        )
        result: List[Dict[str, Any]] = []
        for job in rows:
            if row_has_leaked_interrupted_ownership(job):
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


def adopt_reclaimable_job_sync(
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
                        _dirty_interrupted_ownership_predicate(),
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


# ────────────────────────── 停止流程 ──────────────────────────


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


async def stop_remote_session(row: Dict[str, Any]) -> AgentStopResult:
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


async def stop_attempt_processes(row: Dict[str, Any], token: str) -> Any:
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
        remote_result = await stop_remote_session(row)
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


# ────────────────────────── 回收主流程 ──────────────────────────


async def reap_stale_jobs(*, task_id: Optional[str] = None) -> int:
    """Reclaim attempts whose owner disappeared or whose lease expired."""
    if task_id is None:
        rows = await run_db(list_reclaimable_jobs_sync)
    else:
        rows = await run_db(list_reclaimable_jobs_sync, task_id)
    reclaimed = 0
    for row in rows:
        token = row["run_token"] or str(uuid.uuid4())
        if not await run_db(
            adopt_reclaimable_job_sync,
            row["job_id"],
            row.get("expected_run_token"),
            token,
            row["reason"],
        ):
            continue
        result = await stop_attempt_processes(row, token)
        if isinstance(result, AgentStopResult):
            # 远程 reaper：ACK 才允许业务终态并清 ownership；NACK/UNKNOWN
            # 落 ORPHANED 并更新 backoff（doc §10.4.3）。
            payload = await run_db(
                attempt_ops.finish_termination_sync,
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
                attempt_ops.finish_termination_sync,
                row["job_id"],
                token,
                confirmed_dead=confirmed_dead,
                reason=_reap_stop_reason(row, result),
                failure_code=_reap_failure_code(row, result),
            )
        if payload:
            reclaimed += 1
            await publishing.broadcast_job_payload(payload)
            publishing.reschedule_if_pending(payload)
    return reclaimed


# ────────────────────────── worker 关停支持 ──────────────────────────


def mark_worker_jobs_terminating_sync(reason: str) -> List[Dict[str, Any]]:
    """Durably fence attempts before their in-process owners are stopped.

    所有 RUNNING -> TERMINATING 写入都走唯一 termination request 事务
    （doc §4.5.2）；本函数只负责收集 reaper/stop 需要的行元数据。
    """
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
