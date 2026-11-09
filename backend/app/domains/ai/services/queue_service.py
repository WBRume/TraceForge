"""
Unified background queue aggregation and management service.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.core.logging import audit_log
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.ai.schemas.queue import QueueJobActions, QueueJobItem
from app.domains.api_mock.models.api_mock import SddApiMockJob, SddApiMockProject
from app.domains.api_mock.services import api_mock_service
from app.domains.auth.models.user import User, WorkspaceMember, WorkspacePermission
from app.domains.skill.models.skill import SddSkill, SddSkillAnalysis
from app.domains.skill.services import skill_analysis_service
from app.domains.task.models.task import SddTask
from app.domains.task.models.task_cli_bootstrap import SddTaskCliBootstrap
from app.domains.workflow.models.provision_job import ProvisionJobType, SddProvisionJob
from app.domains.workflow.services import provision_job_service
from app.domains.workspace.services import workspace_service

QUEUE_SOURCE_PROVISION = "provision"
QUEUE_SOURCE_API_MOCK = "api_mock"
QUEUE_SOURCE_BOOTSTRAP = "bootstrap"
QUEUE_SOURCE_SKILL_ANALYSIS = "skill_analysis"
QUEUE_SOURCES = {QUEUE_SOURCE_PROVISION, QUEUE_SOURCE_API_MOCK, QUEUE_SOURCE_BOOTSTRAP, QUEUE_SOURCE_SKILL_ANALYSIS}

API_MOCK_JOB_SYNC = "SYNC_TASK_SOURCE"
API_MOCK_JOB_IMPORT = "IMPORT_SWAGGER"
API_MOCK_JOB_AUTO = api_mock_service.AUTO_MOCK_JOB_TYPE


def list_orphaned_jobs(
    db: Session,
    *,
    user_id: str,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[SddAiJob], int]:
    """Admin-only ORPHANED evidence view; no status mutation is performed."""
    if not _is_admin(db, user_id):
        raise PermissionError("Only platform administrators can inspect orphaned jobs")
    query = (
        db.query(SddAiJob)
        .filter(SddAiJob.status == AiJobStatus.ORPHANED)
        .order_by(SddAiJob.orphaned_at.asc(), SddAiJob.updated_at.asc())
    )
    total = query.count()
    safe_page = max(1, int(page or 1))
    safe_size = max(1, min(int(page_size or 50), 200))
    rows = query.offset((safe_page - 1) * safe_size).limit(safe_size).all()
    return rows, total


def protect_orphaned_job(
    db: Session,
    *,
    job_id: str,
    operator_id: str,
    reason: str,
    evidence: str,
) -> SddAiJob:
    """Pause automatic reaping with explicit operator evidence.

    This is intentionally not a generic status-edit endpoint. The job stays
    ORPHANED until a separate, evidence-backed recovery workflow is performed.
    """
    if not _is_admin(db, operator_id):
        raise PermissionError("Only platform administrators can protect orphaned jobs")
    normalized_reason = str(reason or "").strip()
    normalized_evidence = str(evidence or "").strip()
    if not normalized_reason or not normalized_evidence:
        raise ValueError("reason and evidence are required")
    job = db.query(SddAiJob).filter(SddAiJob.id == str(job_id or "").strip()).first()
    if not job:
        raise LookupError("Queue job not found")
    if job.status != AiJobStatus.ORPHANED:
        raise ValueError("Only ORPHANED jobs can be protected")
    job.manual_intervention_required = True
    job.manual_intervention_operator_id = str(operator_id)
    job.manual_intervention_reason = normalized_reason
    job.manual_intervention_evidence = normalized_evidence
    job.next_reap_at = None
    db.commit()
    db.refresh(job)
    audit_log(
        action="orphaned_job_protect",
        outcome="success",
        resource_type="ai_job",
        resource_id=job.id,
        operator_id=operator_id,
        workspace_id=job.workspace_id,
        task_id=job.task_id,
        reason=normalized_reason,
        evidence=normalized_evidence,
    )
    return job


def _append_orphan_recovery_history(
    job: SddAiJob,
    *,
    action: str,
    operator_id: str,
    reason: str,
    evidence: str | None = None,
) -> None:
    context = dict(job.context_json) if isinstance(job.context_json, dict) else {}
    history = list(context.get("orphan_recovery_history") or [])
    history.append(
        {
            "action": action,
            "operator_id": str(operator_id),
            "reason": reason,
            "evidence": evidence,
            "at": datetime.utcnow().isoformat() + "Z",
        }
    )
    context["orphan_recovery_history"] = history[-50:]
    job.context_json = context


def _adopt_orphaned_job_for_manual_action(
    db: Session,
    *,
    job_id: str,
    operator_id: str,
    reason: str,
    evidence: str | None,
    action: str,
) -> dict[str, Any]:
    """CAS an ORPHANED job into a single administrator-owned termination."""
    if not _is_admin(db, operator_id):
        raise PermissionError("Only platform administrators can recover orphaned jobs")
    normalized_reason = str(reason or "").strip()
    normalized_evidence = str(evidence or "").strip() or None
    if not normalized_reason:
        raise ValueError("reason is required")
    normalized_job_id = str(job_id or "").strip()
    job = db.query(SddAiJob).filter(SddAiJob.id == normalized_job_id).with_for_update().first()
    if not job:
        raise LookupError("Queue job not found")
    if job.status != AiJobStatus.ORPHANED:
        raise ValueError(f"Queue job is no longer ORPHANED (current status: {_enum_text(job.status)})")

    from app.domains.ai.services.jobs.registry import WORKER_BOOT_ID, WORKER_ID

    previous_run_token = str(job.run_token or "") or None
    adopted_run_token = str(uuid.uuid4())
    _append_orphan_recovery_history(
        job,
        action=action,
        operator_id=operator_id,
        reason=normalized_reason,
        evidence=normalized_evidence,
    )
    job.status = AiJobStatus.TERMINATING
    job.worker_id = WORKER_ID
    job.worker_boot_id = WORKER_BOOT_ID
    job.run_token = adopted_run_token
    job.termination_attempts = int(job.termination_attempts or 0) + 1
    job.terminal_reason = normalized_reason
    job.failure_code = "MANUAL_ORPHAN_RECOVERY"
    now = datetime.utcnow()
    job.last_reap_attempt_at = now
    # Keep the automatic reaper from adopting this fresh manual fence while
    # the administrator is validating/stopping the external process.
    manual_lease_seconds = max(5, int(getattr(settings, "AI_JOB_LEASE_SECONDS", 45) or 45))
    job.lease_expires_at = now + timedelta(seconds=manual_lease_seconds)
    job.next_reap_at = now + timedelta(seconds=manual_lease_seconds)
    job.manual_intervention_required = False
    job.manual_intervention_operator_id = None
    job.manual_intervention_reason = None
    job.manual_intervention_evidence = None
    db.flush()
    return {
        "job_id": str(job.id),
        "run_token": adopted_run_token,
        "previous_run_token": previous_run_token,
        "process_pid": job.process_pid,
        "process_started_at": job.process_started_at,
        "process_group_id": job.process_group_id,
        "execution_kind": job.process_execution_kind,
        "agent_backend": job.agent_backend,
        "session_id": job.session_id,
        "queue_key": str(job.queue_key or ""),
        "reason": normalized_reason,
        "action": action,
        "workspace_id": job.workspace_id,
        "task_id": job.task_id,
    }


def begin_orphaned_retry_termination(
    db: Session,
    *,
    job_id: str,
    operator_id: str,
    reason: str,
) -> dict[str, Any]:
    return _adopt_orphaned_job_for_manual_action(
        db,
        job_id=job_id,
        operator_id=operator_id,
        reason=reason,
        evidence=None,
        action="retry_termination",
    )


def begin_orphaned_cleanup_confirmation(
    db: Session,
    *,
    job_id: str,
    operator_id: str,
    reason: str,
    evidence: str,
) -> dict[str, Any]:
    normalized_evidence = str(evidence or "").strip()
    if not normalized_evidence:
        raise ValueError("evidence is required")
    return _adopt_orphaned_job_for_manual_action(
        db,
        job_id=job_id,
        operator_id=operator_id,
        reason=reason,
        evidence=normalized_evidence,
        action="confirm_cleanup",
    )


def _enum_text(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _utcnow() -> datetime:
    return datetime.utcnow()


def _is_admin(db: Session, user_id: str) -> bool:
    normalized_user_id = str(user_id or "").strip()
    user = db.query(User).filter(User.id == normalized_user_id).first()
    return bool(user and user.is_admin)


def _workspace_member_ids(db: Session, user_id: str) -> set[str]:
    rows = db.query(WorkspaceMember.workspace_id).filter(WorkspaceMember.user_id == str(user_id or "").strip()).all()
    return {str(row[0]) for row in rows if row and row[0]}


def _can_manage_task_jobs(db: Session, *, workspace_id: str | None, user_id: str) -> bool:
    ws_id = str(workspace_id or "").strip()
    if not ws_id:
        return False
    return workspace_service.user_has_permission(
        db,
        ws_id,
        str(user_id or "").strip(),
        WorkspacePermission.MANAGE_TASK_STATUS,
    )


def _can_manage_api_mock_jobs(db: Session, *, workspace_id: str | None, user_id: str) -> bool:
    ws_id = str(workspace_id or "").strip()
    if not ws_id:
        return False
    return workspace_service.user_has_permission(
        db,
        ws_id,
        str(user_id or "").strip(),
        WorkspacePermission.MANAGE_API_MOCK,
    )


def _can_manage_skill_jobs(db: Session, *, workspace_id: str | None, user_id: str) -> bool:
    ws_id = str(workspace_id or "").strip()
    if not ws_id:
        return False
    return workspace_service.user_has_permission(
        db,
        ws_id,
        str(user_id or "").strip(),
        WorkspacePermission.MANAGE_SKILLS,
    )


def _is_mine(creator_id: str | None, user_id: str) -> bool:
    return str(creator_id or "").strip() == str(user_id or "").strip()


def _build_target_path(
    *,
    source: str,
    job_type: str,
    workspace_id: str | None,
    task_id: str | None,
    skill_id: str | None = None,
) -> str | None:
    ws_id = str(workspace_id or "").strip()
    tk_id = str(task_id or "").strip()
    sk_id = str(skill_id or "").strip()
    # target_path 指向前端 SPA 路由；前端工作区路由前缀是 /workspaces（/ws 已被后端 WebSocket 代理占用）
    if source == QUEUE_SOURCE_PROVISION:
        if job_type == ProvisionJobType.CREATE_WORKSPACE.value and ws_id:
            return f"/workspaces/{ws_id}/dashboard"
        if job_type == ProvisionJobType.CREATE_TASK.value and ws_id and tk_id:
            return f"/workspaces/{ws_id}/chat/{tk_id}"
        if job_type == ProvisionJobType.IMPORT_SKILL.value and sk_id:
            query = f"?wsId={ws_id}" if ws_id else ""
            return f"/skills/{sk_id}/edit{query}"
        return None
    if source == QUEUE_SOURCE_API_MOCK and ws_id:
        return f"/workspaces/{ws_id}/api-mock"
    if source == QUEUE_SOURCE_BOOTSTRAP and ws_id and tk_id:
        return f"/workspaces/{ws_id}/chat/{tk_id}"
    if source == QUEUE_SOURCE_SKILL_ANALYSIS and ws_id and sk_id:
        return f"/skills/{sk_id}/edit?wsId={ws_id}"
    return None


def _visible_query(db: Session, user_id: str):
    from sqlalchemy import and_, exists, or_

    member = exists().where(
        WorkspaceMember.workspace_id == SddAiJob.workspace_id,
        WorkspaceMember.user_id == user_id,
    )
    mock_workspaces = [
        workspace_id
        for workspace_id in _workspace_member_ids(db, user_id)
        if workspace_service.user_has_permission(db, workspace_id, user_id, WorkspacePermission.VIEW_API_MOCK)
    ]
    # A historical creator does not retain access after workspace membership is revoked.
    return db.query(SddAiJob).filter(
        SddAiJob.queue_source.in_(QUEUE_SOURCES),
        or_(SddAiJob.queue_source != QUEUE_SOURCE_API_MOCK, SddAiJob.workspace_id.in_(mock_workspaces)),
        or_(
            and_(SddAiJob.workspace_id.is_(None), SddAiJob.creator_id == user_id),
            and_(SddAiJob.visibility == "workspace", member),
            and_(SddAiJob.visibility == "creator", SddAiJob.creator_id == user_id, member),
        ),
    )


def _present_job(db: Session, job: SddAiJob, user_id: str) -> QueueJobItem:  # noqa: PLR0912
    source = job.queue_source
    job_type = job.job_type or "UNKNOWN"
    status = _enum_text(job.status)
    target = None
    exists = False
    business_record_exists = False
    skill_id = None
    task_id = job.task_id
    if source == QUEUE_SOURCE_PROVISION:
        row = db.get(SddProvisionJob, job.id)
        business_record_exists = row is not None
        if row:
            task_id = row.task_id
            skill_id = (job.result_json or {}).get("skill_id")
            if job_type == "CREATE_TASK":
                exists = bool(task_id and db.get(SddTask, task_id))
            elif job_type == "IMPORT_SKILL":
                exists = bool(skill_id and db.get(SddSkill, skill_id))
            else:
                from app.domains.auth.models.user import Workspace

                exists = bool(job.workspace_id and db.get(Workspace, job.workspace_id))
    elif source == QUEUE_SOURCE_API_MOCK:
        exists = db.get(SddApiMockProject, job.resource_id) is not None
        business_record_exists = db.get(SddApiMockJob, job.id) is not None
    elif source == QUEUE_SOURCE_SKILL_ANALYSIS:
        analysis = db.get(SddSkillAnalysis, job.id)
        skill_id = analysis.skill_id if analysis else None
        exists = bool(skill_id and db.get(SddSkill, skill_id))
    elif source == QUEUE_SOURCE_BOOTSTRAP:
        exists = bool(task_id and db.get(SddTask, task_id))
    # Results and names are only exposed after the common authorization query.
    if exists:
        target = _build_target_path(
            source=source,
            job_type=job_type,
            workspace_id=job.workspace_id,
            task_id=task_id,
            skill_id=skill_id,
        )
    terminal_retry = status in {"FAILED", "CANCELLED"}
    durable = job.execution_backend == "durable"
    can_retry = False
    can_stop = False
    if source == QUEUE_SOURCE_PROVISION:
        if job_type == "CREATE_WORKSPACE":
            manage = _is_mine(job.creator_id, user_id)
        elif job_type == "IMPORT_SKILL":
            manage = _can_manage_skill_jobs(db, workspace_id=job.workspace_id, user_id=user_id)
        else:
            manage = _can_manage_task_jobs(db, workspace_id=job.workspace_id, user_id=user_id)
        can_retry = (
            manage
            and terminal_retry
            and business_record_exists
            and job_type in {"CREATE_TASK", "CREATE_WORKSPACE", "IMPORT_SKILL"}
        )
        can_stop = (
            job_type == "CREATE_TASK"
            and business_record_exists
            and _is_mine(job.creator_id, user_id)
            and status in {"PENDING", "RUNNING"}
            and not job.cancel_requested_at
            and not job.completion_json
        )
    elif source == QUEUE_SOURCE_API_MOCK:
        manage = _can_manage_api_mock_jobs(db, workspace_id=job.workspace_id, user_id=user_id)
        can_retry = (
            manage
            and terminal_retry
            and exists
            and business_record_exists
            and job_type in {API_MOCK_JOB_SYNC, API_MOCK_JOB_AUTO}
        )
        can_stop = (
            manage
            and exists
            and business_record_exists
            and job_type in {API_MOCK_JOB_SYNC, API_MOCK_JOB_AUTO, API_MOCK_JOB_IMPORT}
            and status in {"PENDING", "RUNNING"}
            and not job.cancel_requested_at
            and not job.completion_json
        )
    elif source == QUEUE_SOURCE_SKILL_ANALYSIS:
        can_retry = (
            terminal_retry and exists and _can_manage_skill_jobs(db, workspace_id=job.workspace_id, user_id=user_id)
        )
    elif source == QUEUE_SOURCE_BOOTSTRAP:
        can_retry = (
            terminal_retry
            and exists
            and db.query(SddTaskCliBootstrap.id).filter_by(task_id=job.task_id, workspace_id=job.workspace_id).first()
            is not None
            and _can_manage_task_jobs(db, workspace_id=job.workspace_id, user_id=user_id)
        )
    return QueueJobItem(
        source=source,
        job_id=job.id,
        job_type=job_type,
        status=status,
        progress=int(job.progress or 0),
        stage=job.stage,
        message=job.message,
        error_message=job.error_message,
        workspace_id=job.workspace_id,
        task_id=task_id,
        creator_id=job.creator_id,
        created_at=job.created_at,
        updated_at=job.state_changed_at,
        target_path=target,
        version=int(job.version or 1),
        attempt_count=int(job.attempt_count or 0),
        retry_of_job_id=job.retry_of_job_id,
        completion=job.completion_json,
        cancel_requested=bool(job.cancel_requested_at),
        result_available=bool(exists and job.completion_json),
        actions=QueueJobActions(
            can_retry=bool(can_retry and durable),
            can_stop=bool(can_stop and durable),
            can_open=bool(
                target and (status == "SUCCESS" or source in {QUEUE_SOURCE_API_MOCK, QUEUE_SOURCE_SKILL_ANALYSIS})
            ),
        ),
    )


def list_queue_jobs(
    db: Session,
    *,
    user_id: str,
    view: str = "mine",
    workspace_id: str | None = None,
    source: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 10,
    job_type: str | None = None,
    creator_id: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
) -> tuple[list[QueueJobItem], int]:
    query = _visible_query(db, user_id)
    if view != "workspace_all":
        query = query.filter(SddAiJob.creator_id == user_id)
    if workspace_id:
        query = query.filter(SddAiJob.workspace_id == workspace_id)
    if source:
        query = query.filter(SddAiJob.queue_source == source)
    if status:
        query = query.filter(SddAiJob.status == status.upper())
    if job_type:
        query = query.filter(SddAiJob.job_type == job_type)
    if creator_id:
        query = query.filter(SddAiJob.creator_id == creator_id)
    if created_after:
        query = query.filter(SddAiJob.created_at >= created_after)
    if created_before:
        query = query.filter(SddAiJob.created_at <= created_before)
    total = query.count()
    size = max(1, min(int(page_size), 200))
    # Offset pages refresh against the current snapshot. Heartbeats do not
    # change this order; the ID is the final deterministic tie breaker.
    rows = (
        query.order_by(
            SddAiJob.state_changed_at.desc(),
            SddAiJob.created_at.desc(),
            SddAiJob.id.desc(),
        )
        .offset((max(1, int(page)) - 1) * size)
        .limit(size)
        .all()
    )
    return [_present_job(db, job, user_id) for job in rows], total


def get_queue_job(db: Session, *, source: str, job_id: str, user_id: str) -> QueueJobItem:
    if source not in QUEUE_SOURCES:
        raise ValueError("Unsupported queue source")
    job = _visible_query(db, user_id).filter(SddAiJob.id == job_id, SddAiJob.queue_source == source).first()
    if job is None:
        raise LookupError("Queue job not found")
    return _present_job(db, job, user_id)


def start_provision_job(new_job_id: str, job_type: str) -> None:
    provision_job_service.schedule_job(new_job_id)


def _start_api_mock_job(**kwargs) -> None:
    from app.domains.ai.services.jobs import domain_jobs

    domain_jobs.schedule_by_id(kwargs["job_id"])


def stop_queue_job(db: Session, *, source: str, job_id: str, user_id: str) -> dict[str, Any]:
    item = get_queue_job(db, source=source, job_id=job_id, user_id=user_id)
    if not item.actions.can_stop:
        raise ValueError("Stopping this job is not available")
    if source == QUEUE_SOURCE_PROVISION:
        provision_job_service.request_cancel(db, db.get(SddProvisionJob, job_id))
    else:
        job = db.get(SddApiMockJob, job_id)
        api_mock_service.request_job_cancel(db, job.project_id, job_id)
    audit_log(
        action="queue_stop", outcome="success", resource_type="queue_job", resource_id=job_id, operator_id=user_id
    )
    return {"source": source, "job_id": job_id, "message": "Job stop requested"}


def retry_queue_job(db: Session, *, source: str, job_id: str, user_id: str) -> dict[str, Any]:
    item = get_queue_job(db, source=source, job_id=job_id, user_id=user_id)
    if not item.actions.can_retry:
        raise ValueError("Retrying this job is not available")
    original = db.query(SddAiJob).filter_by(id=job_id).populate_existing().with_for_update().one()
    if original.status not in {AiJobStatus.FAILED, AiJobStatus.CANCELLED}:
        raise ValueError("Job is no longer retryable")
    successor = db.query(SddAiJob).filter_by(command_key=f"rerun:{job_id}").with_for_update().first()
    if successor is None:
        if source == QUEUE_SOURCE_PROVISION:
            row = provision_job_service.retry_job(db, source_job=db.get(SddProvisionJob, job_id), creator_id=user_id)
            successor = row.execution
        elif source == QUEUE_SOURCE_SKILL_ANALYSIS:
            row = skill_analysis_service.retry_analysis_job(
                db, source=db.get(SddSkillAnalysis, job_id), user_id=user_id
            )
            successor = row.execution
        elif source == QUEUE_SOURCE_API_MOCK:
            row = db.get(SddApiMockJob, job_id)
            project = db.get(SddApiMockProject, row.project_id)
            successor = api_mock_service.create_job(
                db,
                project,
                creator_id=user_id,
                job_type=original.job_type,
                execution_input=dict((original.context_json or {}).get("inputs") or {}),
                retry_of_job_id=job_id,
            ).execution
        elif source == QUEUE_SOURCE_BOOTSTRAP:
            from app.domains.ai.services.jobs.store import create_task_baseline_job

            successor = create_task_baseline_job(
                db,
                workspace_id=original.workspace_id,
                task_id=original.task_id,
                creator_id=user_id,
                retry_of_job_id=job_id,
            )
    from app.domains.ai.services.jobs import domain_jobs

    domain_jobs.schedule_by_id(successor.id)
    audit_log(
        action="queue_retry",
        outcome="success",
        resource_type="queue_job",
        resource_id=job_id,
        operator_id=user_id,
        new_job_id=successor.id,
    )
    return {
        "source": source,
        "job_id": job_id,
        "new_job_id": successor.id,
        "provision_job_type": successor.job_type,
        "queue_key": successor.queue_key,
        "message": "Retry queued",
    }
