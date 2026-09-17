"""带 fence 的状态写入（doc §4.5.3）。

- :func:`attempt_is_current_sync`：durable attempt fence（与业务写入同事务执行）；
- :func:`update_job_state_sync`：活动状态 CAS 写入与业务终态 convergence 转交；
- :class:`AgentAttemptFencedError`：迟到 attempt 越过 fence 时抛出。

普通 CRUD / 查询在 :mod:`store`；本模块只承载「受 run token / boot id /
取消位保护」的写入路径。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from app.database import SessionLocal
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services.jobs.constants import FINAL_STATUSES
from app.domains.ai.services.jobs.registry import WORKER_BOOT_ID
from app.domains.ai.services.jobs.store import merge_json, row_execution_kind, serialize_job
from app.domains.task.models.task import SddTask


class AgentAttemptFencedError(RuntimeError):
    """Raised when a late attempt is no longer allowed to write business data."""


def attempt_is_current_sync(
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


def update_job_state_sync(
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
    evidence: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """状态更新 DB 段（线程内执行，由 run_db 包装）。

    返回 {"payload": ..., "broadcast": bool, "is_final": bool}；
    broadcast=False 表示被 fence/终态幂等拦下，仅回读当前 payload。

    finalize=True 的所有业务终态都必须经过唯一 convergence 事务
    （doc §8/C2）；本函数不再拥有独立的死亡证据决策表，传入的
    process_started/termination_confirmed_dead 只作为无身份 fallback 交给
    唯一 resolver。
    """
    from app.domains.ai.services.ai_job_convergence_service import (
        AttemptConvergenceRequest,
        ConvergenceIntent,
        resolve_attempt_evidence,
    )
    from app.domains.ai.services import ai_job_convergence_service as convergence

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
                    execution_kind=row_execution_kind(job),
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
            values["context_json"] = merge_json(job.context_json, context_patch)
        if result_patch:
            values["result_json"] = merge_json(job.result_json, result_patch)
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
