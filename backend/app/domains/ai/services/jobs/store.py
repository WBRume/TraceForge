"""SddAiJob 持久层。

所有对作业行的读取、创建、认领、租约与所有权字段操作都收敛在本模块；
函数分两类：

- ``*_sync``：同步 DB 段，在线程内执行（可经 :func:`run_db`/``run_db_txn`` 包装）；
- 其余 async 包装：供事件循环直接调用的一行式 offload。

本模块不做广播、不触发调度；调用方在拿到 payload 后交给
:mod:`publishing`/:mod:`state` 处理对外副作用。带 run-token fence 的
状态写入在 :mod:`fencing`。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.core.logging import get_logger
from app.core.offload import run_db
from app.database import SessionLocal
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services.jobs import constants
from app.domains.ai.services.jobs.constants import (
    ACTIVE_STATUSES,
    BLOCKING_STATUSES,
    FINAL_STATUSES,
    JOB_KIND_DIAGNOSIS_SUMMARY,
    JOB_KIND_RESOLUTION_PROPOSAL,
    JOB_KIND_RESOLUTION_REWRITE,
    JOB_KIND_TASK_BASELINE,
    JOB_KIND_THREAD_AI_REPLY,
    SESSION_GUARD_STATUSES,
    TASK_QUEUE_PAUSED_STATUSES,
    as_status,
    queue_key_for_diagnosis_summary,
    queue_key_for_task,
    queue_key_for_task_baseline,
    queue_key_for_thread,
    task_id_from_queue_key,
)
from app.domains.ai.services.jobs.registry import WORKER_BOOT_ID, WORKER_ID, runtime
from app.agents import (
    EXECUTION_KIND_LOCAL_PROCESS,
    EXECUTION_KIND_REMOTE_SESSION,
)
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.models.task_cli_bootstrap import SddTaskCliBootstrap

# A productive turn can legitimately run longer than ten minutes now.  Stale
# cleanup must never race the hard runtime watchdog and mark a live job failed.
_RUNNING_STALE_MINUTES = max(
    10,
    int(getattr(settings, "AGENT_MAX_RUNTIME_SECONDS", 7200) or 7200) // 60 + 5,
)

logger = get_logger(__name__, category="ai_session")


# ────────────────────────── 通用 JSON/行工具 ──────────────────────────


def merge_json(original: Any, patch: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(original) if isinstance(original, dict) else {}
    if patch:
        merged.update(patch)
    return merged


def clear_process_ownership(job: SddAiJob) -> None:
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


def has_active_process_ownership(job: SddAiJob) -> bool:
    """Whether the durable row still claims a locally attached process."""
    return job.process_pid is not None or job.process_group_id is not None


def row_has_leaked_interrupted_ownership(job: SddAiJob) -> bool:
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


# ────────────────────────── 执行类别 ──────────────────────────


def row_execution_kind(job: SddAiJob) -> str:
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


def resolve_execution_kind_for_backend(backend_name: Optional[str]) -> str:
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


def resolve_execution_kind_for_claim(
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
    return resolve_execution_kind_for_backend(name)


# ────────────────────────── 序列化 ──────────────────────────


def serialize_job(job: SddAiJob) -> Dict[str, Any]:
    return {
        "id": job.id,
        "workspace_id": job.workspace_id,
        "task_id": job.task_id,
        "asset_id": job.asset_id,
        "thread_id": job.thread_id,
        "channel": as_status(job.channel),
        "queue_key": job.queue_key,
        "status": as_status(job.status),
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


# ────────────────────────── 作业类别与守卫查询 ──────────────────────────


def normalize_job_kind(value: Optional[str]) -> str:
    normalized = str(value or "").strip().upper()
    if normalized == JOB_KIND_TASK_BASELINE:
        return JOB_KIND_TASK_BASELINE
    if normalized == JOB_KIND_RESOLUTION_PROPOSAL:
        return JOB_KIND_RESOLUTION_PROPOSAL
    if normalized == JOB_KIND_RESOLUTION_REWRITE:
        return JOB_KIND_RESOLUTION_REWRITE
    return JOB_KIND_THREAD_AI_REPLY


def job_kind_from_job(job: SddAiJob) -> str:
    context = job.context_json if isinstance(job.context_json, dict) else {}
    return normalize_job_kind(str(context.get("job_kind") or ""))


def job_kind_of(job: SddAiJob) -> str:
    context = job.context_json if isinstance(job.context_json, dict) else {}
    return str(context.get("job_kind") or "").strip().upper()


def has_diagnosis_summary_job(db, task_id: str) -> bool:
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
        if job_kind_of(job) == JOB_KIND_DIAGNOSIS_SUMMARY:
            return True
    return False


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
        if job_kind_of(job) == JOB_KIND_DIAGNOSIS_SUMMARY:
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
        if job_kind_of(job) != JOB_KIND_DIAGNOSIS_SUMMARY:
            return job
    return None


def get_job(db: Session, *, job_id: str) -> Optional[SddAiJob]:
    return db.query(SddAiJob).filter(SddAiJob.id == job_id).first()


def list_thread_jobs(
    db: Session,
    *,
    thread_id: str,
    active_only: bool = True,
) -> List[SddAiJob]:
    cleanup_stale_running_jobs(db, thread_id=thread_id)
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
    cleanup_stale_running_jobs(db, task_id=task_id)
    query = db.query(SddAiJob).filter(
        SddAiJob.task_id == task_id,
        SddAiJob.channel == AiJobChannel.TASK_CHAT,
    )
    if active_only:
        query = query.filter(SddAiJob.status.in_(list(ACTIVE_STATUSES)))
    return query.order_by(SddAiJob.created_at.desc()).all()


def job_prompt_text(db: Session, thread_id: str) -> Optional[str]:
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


# ────────────────────────── 陈旧作业清理 ──────────────────────────


def apply_task_chat_job_interrupted(
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
    job.context_json = merge_json(job.context_json, patch)
    if result_patch:
        job.result_json = merge_json(job.result_json, result_patch)
    if task and task.status not in {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.BASELINED}:
        # 用户已显式关闭/失败的任务不能被引擎回调降级回 INTERRUPTED。
        task.status = TaskStatus.INTERRUPTED
        task.session_id = resolved_session_id
        task.error_message = None
        task.interrupt_reason = reason_text
        task.interrupted_by_id = None
        task.interrupted_at = now
    clear_process_ownership(job)
    runtime.clear_cancel(job.id)
    db.commit()
    db.refresh(job)
    if task:
        db.refresh(task)
    return serialize_job(job)


def cleanup_stale_running_jobs(
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
            apply_task_chat_job_interrupted(
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
            runtime.clear_cancel(job.id)
        dirty = True
    if dirty:
        db.commit()


# ────────────────────────── 作业创建 ──────────────────────────


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
    normalized_kind = normalize_job_kind(job_kind)
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
        queue_key=queue_key_for_thread(thread_id),
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
    commit: bool = True,
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
        queue_key=queue_key_for_task(task_id),
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
    if not commit:
        # The turn owner commits message, job and submission together and seeds
        # token accounting afterwards (that helper performs its own commits).
        db.flush()
        return job
    db.commit()
    db.refresh(job)
    try:
        from app.domains.task.services import context_token_service

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
        queue_key=queue_key_for_diagnosis_summary(task_id),
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
    key = queue_key_for_task_baseline(task_id)
    input_revision = str(record.spec_version_id or "missing")
    existing_jobs = (
        db.query(SddAiJob)
        .filter(SddAiJob.task_id == task_id, SddAiJob.queue_key == key)
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
        queue_key=key,
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


# ────────────────────────── 取消/终态查询 ──────────────────────────


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


def get_job_status_sync(job_id: str) -> Optional[AiJobStatus]:
    db = SessionLocal()
    try:
        job = db.query(SddAiJob.status).filter(SddAiJob.id == job_id).first()
        if not job:
            return None
        return job[0]
    finally:
        db.close()


async def get_job_status(job_id: str) -> Optional[AiJobStatus]:
    return await run_db(get_job_status_sync, job_id)


# ────────────────────────── 租约与心跳 ──────────────────────────


def lease_ttl_seconds() -> int:
    return max(5, int(getattr(settings, "AI_JOB_LEASE_SECONDS", 45) or 45))


def heartbeat_job_sync(job_id: str, run_token: str) -> bool:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        lease = now + timedelta(seconds=lease_ttl_seconds())
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


# ────────────────────────── 队列认领 ──────────────────────────


def is_task_queue_paused(db: Session, queue_key: str) -> bool:
    task_id = task_id_from_queue_key(queue_key)
    if not task_id:
        return False
    row = db.query(SddTask.status).filter(SddTask.id == task_id).first()
    if not row:
        return False
    return row[0] in TASK_QUEUE_PAUSED_STATUSES


def take_next_pending_job_id_sync(queue_key: str) -> Optional[str]:
    db = SessionLocal()
    try:
        if is_task_queue_paused(db, queue_key):
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
        execution_kind = resolve_execution_kind_for_claim(
            db,
            task_id=str(claim_target[1]) if claim_target and claim_target[1] else None,
            workspace_id=str(claim_target[0]) if claim_target and claim_target[0] else None,
        )
        now = datetime.utcnow()
        run_token = str(uuid.uuid4())
        lease_expires_at = now + timedelta(seconds=lease_ttl_seconds())
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
                    SddAiJob.process_containment_id: _containment_id_for_run_token(run_token),
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


def _containment_id_for_run_token(run_token: str) -> str:
    from app.agents.supervision import containment_id_for_run_token

    return containment_id_for_run_token(run_token)


# ────────────────────────── 恢复扫描支持 ──────────────────────────


def list_pending_queue_keys_sync() -> List[str]:
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
            f"{constants.QUEUE_KEY_DIAGNOSIS_SUMMARY}:",
            "REQUIREMENT_PREVIEW:",
            "PLAYBOOK_PROMOTION:",
            f"{constants.QUEUE_KEY_TASK_BASELINE}:",
        )
        return [
            str(row[0] or "").strip()
            for row in rows
            if str(row[0] or "").strip().startswith(managed_prefixes)
        ]
    finally:
        db.close()
