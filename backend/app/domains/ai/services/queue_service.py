"""
Unified background queue aggregation and management service.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.core.logging import audit_log
from app.domains.api_mock.models.api_mock import ApiMockJobStatus, SddApiMockJob, SddApiMockProject
from app.domains.workflow.models.provision_job import (
    ProvisionJobStatus,
    ProvisionJobType,
    SddProvisionJob,
)
from app.domains.skill.models.skill import SddSkill, SddSkillAnalysis, SkillAnalysisStatus
from app.domains.task.models.task import SddTask
from app.domains.task.models.task_cli_bootstrap import (
    SddTaskCliBootstrap,
    TaskCliBootstrapStatus,
)
from app.domains.auth.models.user import WorkspaceMember, WorkspacePermission
from app.domains.ai.schemas.queue import QueueJobActions, QueueJobItem
from app.domains.api_mock.services import api_mock_service
from app.domains.skill.services import skill_analysis_service
from app.domains.task.services import task_cli_state_service
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


def _enum_text(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _utcnow() -> datetime:
    return datetime.utcnow()


def _to_queue_status(raw_status: str) -> str:
    normalized = str(raw_status or "").strip().upper()
    if normalized in {"PENDING", "RUNNING", "SUCCESS", "FAILED"}:
        return normalized
    if normalized == "READY":
        return "SUCCESS"
    if normalized in {"STALE"}:
        return "FAILED"
    return "PENDING"


def _workspace_member_ids(db: Session, user_id: str) -> set[str]:
    rows = (
        db.query(WorkspaceMember.workspace_id)
        .filter(WorkspaceMember.user_id == str(user_id or "").strip())
        .all()
    )
    return {str(row[0]) for row in rows if row and row[0]}


def _can_manage_task_jobs(db: Session, *, workspace_id: Optional[str], user_id: str) -> bool:
    ws_id = str(workspace_id or "").strip()
    if not ws_id:
        return False
    return workspace_service.user_has_permission(
        db,
        ws_id,
        str(user_id or "").strip(),
        WorkspacePermission.MANAGE_TASK_STATUS,
    )


def _can_manage_api_mock_jobs(db: Session, *, workspace_id: Optional[str], user_id: str) -> bool:
    ws_id = str(workspace_id or "").strip()
    if not ws_id:
        return False
    return workspace_service.user_has_permission(
        db,
        ws_id,
        str(user_id or "").strip(),
        WorkspacePermission.MANAGE_API_MOCK,
    )


def _can_manage_skill_jobs(db: Session, *, workspace_id: Optional[str], user_id: str) -> bool:
    ws_id = str(workspace_id or "").strip()
    if not ws_id:
        return False
    return workspace_service.user_has_permission(
        db,
        ws_id,
        str(user_id or "").strip(),
        WorkspacePermission.MANAGE_SKILLS,
    )


def _is_mine(creator_id: Optional[str], user_id: str) -> bool:
    return str(creator_id or "").strip() == str(user_id or "").strip()


def _build_target_path(
    *,
    source: str,
    job_type: str,
    workspace_id: Optional[str],
    task_id: Optional[str],
    skill_id: Optional[str] = None,
) -> Optional[str]:
    ws_id = str(workspace_id or "").strip()
    tk_id = str(task_id or "").strip()
    sk_id = str(skill_id or "").strip()
    if source == QUEUE_SOURCE_PROVISION:
        if job_type == ProvisionJobType.CREATE_WORKSPACE.value and ws_id:
            return f"/ws/{ws_id}/dashboard"
        if job_type == ProvisionJobType.CREATE_TASK.value and ws_id and tk_id:
            return f"/ws/{ws_id}/chat/{tk_id}"
        if job_type == ProvisionJobType.IMPORT_SKILL.value and sk_id:
            query = f"?wsId={ws_id}" if ws_id else ""
            return f"/skills/{sk_id}/edit{query}"
        return None
    if source == QUEUE_SOURCE_API_MOCK and ws_id:
        return f"/ws/{ws_id}/api-mock"
    if source == QUEUE_SOURCE_BOOTSTRAP and ws_id and tk_id:
        return f"/ws/{ws_id}/chat/{tk_id}"
    if source == QUEUE_SOURCE_SKILL_ANALYSIS and ws_id and sk_id:
        return f"/skills/{sk_id}/edit?wsId={ws_id}"
    return None


def _sort_items(items: Sequence[QueueJobItem]) -> List[QueueJobItem]:
    return sorted(
        items,
        key=lambda item: (
            item.updated_at or item.created_at or datetime.min,
            item.created_at or datetime.min,
        ),
        reverse=True,
    )


def _paginate(items: Sequence[QueueJobItem], page: int, page_size: int) -> Tuple[List[QueueJobItem], int]:
    safe_page = max(1, int(page or 1))
    safe_page_size = max(1, min(int(page_size or 10), 200))
    total = len(items)
    start = (safe_page - 1) * safe_page_size
    end = start + safe_page_size
    return list(items[start:end]), total


def _build_provision_actions(item_status: str, target_path: Optional[str]) -> QueueJobActions:
    return QueueJobActions(
        can_stop=False,
        can_retry=item_status == "FAILED",
        can_open=bool(item_status == "SUCCESS" and target_path),
    )


def _mark_stale_import_skill_job_failed(db: Session, job: SddProvisionJob) -> None:
    if job.job_type != ProvisionJobType.IMPORT_SKILL:
        return
    if job.status not in {ProvisionJobStatus.PENDING, ProvisionJobStatus.RUNNING}:
        return

    timeout_seconds = max(1, int(getattr(settings, "SKILL_GITHUB_IMPORT_GIT_TIMEOUT_SECONDS", 240) or 240))
    grace_seconds = max(0, int(getattr(settings, "SKILL_GITHUB_IMPORT_STALE_GRACE_SECONDS", 60) or 0))
    stale_after_seconds = timeout_seconds + grace_seconds
    marker = job.started_at if job.status == ProvisionJobStatus.RUNNING else None
    marker = marker or job.updated_at or job.created_at
    if not marker:
        return
    elapsed = (_utcnow() - marker).total_seconds()
    if elapsed < stale_after_seconds:
        return

    job.status = ProvisionJobStatus.FAILED
    job.progress = max(int(job.progress or 0), 1)
    job.stage = "FAILED"
    job.message = "Skill import failed"
    job.error_message = "GitHub repository clone timed out. Please retry from the queue after checking network access."
    job.finished_at = _utcnow()
    db.commit()
    db.refresh(job)


def _build_api_mock_actions(*, job_type: str, item_status: str, target_path: Optional[str]) -> QueueJobActions:
    active = item_status in {"PENDING", "RUNNING"}
    can_retry = item_status == "FAILED" and job_type in {API_MOCK_JOB_SYNC, API_MOCK_JOB_AUTO}
    can_stop = active and job_type in {API_MOCK_JOB_SYNC, API_MOCK_JOB_AUTO, API_MOCK_JOB_IMPORT}
    return QueueJobActions(
        can_stop=can_stop,
        can_retry=can_retry,
        can_open=bool(target_path),
    )


def _build_bootstrap_actions(item_status: str, target_path: Optional[str]) -> QueueJobActions:
    return QueueJobActions(
        can_stop=False,
        can_retry=item_status == "FAILED",
        can_open=bool(item_status == "SUCCESS" and target_path),
    )


def _build_skill_analysis_actions(item_status: str, target_path: Optional[str]) -> QueueJobActions:
    return QueueJobActions(
        can_stop=False,
        can_retry=item_status == "FAILED",
        can_open=bool(target_path),
    )


def _list_provision_items(
    db: Session,
    *,
    user_id: str,
    view: str,
    workspace_id: Optional[str],
    status_filter: Optional[str],
) -> List[QueueJobItem]:
    query = db.query(SddProvisionJob)
    ws_id = str(workspace_id or "").strip()
    mine_only = str(view or "mine").strip().lower() == "mine"
    status_filter_norm = str(status_filter or "").strip().upper()

    if mine_only:
        query = query.filter(SddProvisionJob.creator_id == str(user_id or "").strip())
    else:
        member_ids = _workspace_member_ids(db, user_id)
        if ws_id:
            if ws_id not in member_ids:
                return []
            query = query.filter(SddProvisionJob.workspace_id == ws_id)
        else:
            if not member_ids:
                return []
            query = query.filter(SddProvisionJob.workspace_id.in_(list(member_ids)))

    if ws_id and mine_only:
        query = query.filter(SddProvisionJob.workspace_id == ws_id)

    rows = query.order_by(SddProvisionJob.created_at.desc()).limit(500).all()
    items: List[QueueJobItem] = []
    for row in rows:
        _mark_stale_import_skill_job_failed(db, row)
        status = _to_queue_status(_enum_text(row.status))
        if status_filter_norm and status_filter_norm != status:
            continue
        job_type = _enum_text(row.job_type)
        result_json = row.result_json if isinstance(row.result_json, dict) else {}
        skill_id = str(result_json.get("skill_id") or "").strip()
        target_path = _build_target_path(
            source=QUEUE_SOURCE_PROVISION,
            job_type=job_type,
            workspace_id=row.workspace_id,
            task_id=row.task_id,
            skill_id=skill_id,
        )
        items.append(
            QueueJobItem(
                source=QUEUE_SOURCE_PROVISION,
                job_id=row.id,
                job_type=job_type,
                status=status,  # type: ignore[arg-type]
                progress=int(row.progress or 0),
                stage=str(row.stage or "").strip() or None,
                message=row.message,
                error_message=row.error_message,
                workspace_id=row.workspace_id,
                task_id=row.task_id,
                creator_id=str(row.creator_id or ""),
                created_at=row.created_at,
                updated_at=row.updated_at,
                target_path=target_path,
                actions=_build_provision_actions(status, target_path),
            )
        )
    return items


def _list_api_mock_items(
    db: Session,
    *,
    user_id: str,
    view: str,
    workspace_id: Optional[str],
    status_filter: Optional[str],
) -> List[QueueJobItem]:
    query = (
        db.query(SddApiMockJob, SddApiMockProject)
        .join(SddApiMockProject, SddApiMockProject.id == SddApiMockJob.project_id)
    )
    ws_id = str(workspace_id or "").strip()
    mine_only = str(view or "mine").strip().lower() == "mine"
    status_filter_norm = str(status_filter or "").strip().upper()

    if mine_only:
        query = query.filter(SddApiMockJob.creator_id == str(user_id or "").strip())
    else:
        member_ids = _workspace_member_ids(db, user_id)
        if ws_id:
            if ws_id not in member_ids:
                return []
            query = query.filter(SddApiMockProject.workspace_id == ws_id)
        else:
            if not member_ids:
                return []
            query = query.filter(SddApiMockProject.workspace_id.in_(list(member_ids)))

    if ws_id and mine_only:
        query = query.filter(SddApiMockProject.workspace_id == ws_id)

    rows = query.order_by(SddApiMockJob.created_at.desc()).limit(500).all()
    items: List[QueueJobItem] = []
    for job, project in rows:
        status = _to_queue_status(_enum_text(job.status))
        if status_filter_norm and status_filter_norm != status:
            continue
        target_path = _build_target_path(
            source=QUEUE_SOURCE_API_MOCK,
            job_type=str(job.job_type or ""),
            workspace_id=project.workspace_id,
            task_id=project.task_id,
        )
        items.append(
            QueueJobItem(
                source=QUEUE_SOURCE_API_MOCK,
                job_id=job.id,
                job_type=str(job.job_type or ""),
                status=status,  # type: ignore[arg-type]
                progress=int(job.progress or 0),
                stage=str(job.job_type or "").strip() or None,
                message=job.message,
                error_message=None,
                workspace_id=project.workspace_id,
                task_id=project.task_id,
                creator_id=str(job.creator_id or ""),
                created_at=job.created_at,
                updated_at=job.updated_at,
                target_path=target_path,
                actions=_build_api_mock_actions(
                    job_type=str(job.job_type or ""),
                    item_status=status,
                    target_path=target_path,
                ),
            )
        )
    return items


def _list_bootstrap_items(
    db: Session,
    *,
    user_id: str,
    view: str,
    workspace_id: Optional[str],
    status_filter: Optional[str],
) -> List[QueueJobItem]:
    query = (
        db.query(SddTaskCliBootstrap, SddTask)
        .join(SddTask, SddTask.id == SddTaskCliBootstrap.task_id)
    )
    ws_id = str(workspace_id or "").strip()
    mine_only = str(view or "mine").strip().lower() == "mine"
    status_filter_norm = str(status_filter or "").strip().upper()

    if mine_only:
        query = query.filter(SddTask.creator_id == str(user_id or "").strip())
    else:
        member_ids = _workspace_member_ids(db, user_id)
        if ws_id:
            if ws_id not in member_ids:
                return []
            query = query.filter(SddTaskCliBootstrap.workspace_id == ws_id)
        else:
            if not member_ids:
                return []
            query = query.filter(SddTaskCliBootstrap.workspace_id.in_(list(member_ids)))

    if ws_id and mine_only:
        query = query.filter(SddTaskCliBootstrap.workspace_id == ws_id)

    rows = query.order_by(SddTaskCliBootstrap.created_at.desc()).limit(500).all()
    items: List[QueueJobItem] = []
    for bootstrap, task in rows:
        raw_status = _enum_text(bootstrap.status)
        status = _to_queue_status(raw_status)
        if status_filter_norm and status_filter_norm != status:
            continue
        target_path = _build_target_path(
            source=QUEUE_SOURCE_BOOTSTRAP,
            job_type="TASK_CLI_BOOTSTRAP",
            workspace_id=bootstrap.workspace_id,
            task_id=bootstrap.task_id,
        )
        items.append(
            QueueJobItem(
                source=QUEUE_SOURCE_BOOTSTRAP,
                job_id=bootstrap.id,
                job_type="TASK_CLI_BOOTSTRAP",
                status=status,  # type: ignore[arg-type]
                progress=int(bootstrap.progress or 0),
                stage=raw_status,
                message=bootstrap.message,
                error_message=bootstrap.error_message,
                workspace_id=bootstrap.workspace_id,
                task_id=bootstrap.task_id,
                creator_id=str(task.creator_id or ""),
                created_at=bootstrap.created_at,
                updated_at=bootstrap.updated_at,
                target_path=target_path,
                actions=_build_bootstrap_actions(status, target_path),
            )
        )
    return items


def _list_skill_analysis_items(
    db: Session,
    *,
    user_id: str,
    view: str,
    workspace_id: Optional[str],
    status_filter: Optional[str],
) -> List[QueueJobItem]:
    query = (
        db.query(SddSkillAnalysis, SddSkill)
        .join(SddSkill, SddSkill.id == SddSkillAnalysis.skill_id)
    )
    ws_id = str(workspace_id or "").strip()
    mine_only = str(view or "mine").strip().lower() == "mine"
    status_filter_norm = str(status_filter or "").strip().upper()

    if mine_only:
        query = query.filter(SddSkillAnalysis.created_by_id == str(user_id or "").strip())
    else:
        member_ids = _workspace_member_ids(db, user_id)
        if ws_id:
            if ws_id not in member_ids:
                return []
            query = query.filter(SddSkillAnalysis.workspace_id == ws_id)
        else:
            if not member_ids:
                return []
            query = query.filter(SddSkillAnalysis.workspace_id.in_(list(member_ids)))

    if ws_id and mine_only:
        query = query.filter(SddSkillAnalysis.workspace_id == ws_id)

    rows = query.order_by(SddSkillAnalysis.created_at.desc()).limit(500).all()
    items: List[QueueJobItem] = []
    for analysis, skill in rows:
        semantic_degraded = skill_analysis_service.is_semantic_degraded_analysis(analysis)
        status = "SUCCESS" if semantic_degraded else _to_queue_status(_enum_text(analysis.status))
        if status_filter_norm and status_filter_norm != status:
            continue
        target_path = _build_target_path(
            source=QUEUE_SOURCE_SKILL_ANALYSIS,
            job_type="SKILL_ANALYSIS",
            workspace_id=analysis.workspace_id,
            task_id=None,
            skill_id=analysis.skill_id,
        )
        items.append(
            QueueJobItem(
                source=QUEUE_SOURCE_SKILL_ANALYSIS,
                job_id=analysis.id,
                job_type="SKILL_ANALYSIS",
                status=status,  # type: ignore[arg-type]
                progress=int(analysis.progress or 0),
                stage=_enum_text(analysis.ref_kind),
                message=(
                    skill_analysis_service.SEMANTIC_UNAVAILABLE_MESSAGE
                    if semantic_degraded
                    else analysis.message or f"Analyze skill: {skill.name}"
                ),
                error_message=None if semantic_degraded else analysis.error_message,
                workspace_id=analysis.workspace_id,
                task_id=None,
                creator_id=str(analysis.created_by_id or ""),
                created_at=analysis.created_at,
                updated_at=analysis.updated_at,
                target_path=target_path,
                actions=_build_skill_analysis_actions(status, target_path),
            )
        )
    return items


def list_queue_jobs(
    db: Session,
    *,
    user_id: str,
    view: str = "mine",
    workspace_id: Optional[str] = None,
    source: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 10,
) -> Tuple[List[QueueJobItem], int]:
    normalized_view = str(view or "mine").strip().lower() or "mine"
    if normalized_view not in {"mine", "workspace_all"}:
        normalized_view = "mine"

    normalized_source = str(source or "").strip().lower()
    selected_sources = (
        {normalized_source}
        if normalized_source in QUEUE_SOURCES
        else set(QUEUE_SOURCES)
    )

    items: List[QueueJobItem] = []
    if QUEUE_SOURCE_PROVISION in selected_sources:
        items.extend(
            _list_provision_items(
                db,
                user_id=user_id,
                view=normalized_view,
                workspace_id=workspace_id,
                status_filter=status,
            )
        )
    if QUEUE_SOURCE_API_MOCK in selected_sources:
        items.extend(
            _list_api_mock_items(
                db,
                user_id=user_id,
                view=normalized_view,
                workspace_id=workspace_id,
                status_filter=status,
            )
        )
    if QUEUE_SOURCE_BOOTSTRAP in selected_sources:
        items.extend(
            _list_bootstrap_items(
                db,
                user_id=user_id,
                view=normalized_view,
                workspace_id=workspace_id,
                status_filter=status,
            )
        )
    if QUEUE_SOURCE_SKILL_ANALYSIS in selected_sources:
        items.extend(
            _list_skill_analysis_items(
                db,
                user_id=user_id,
                view=normalized_view,
                workspace_id=workspace_id,
                status_filter=status,
            )
        )

    sorted_items = _sort_items(items)
    page_items, total = _paginate(sorted_items, page, page_size)
    return page_items, total


def _can_view_queue_job(
    db: Session,
    *,
    workspace_id: Optional[str],
    creator_id: Optional[str],
    user_id: str,
) -> bool:
    if _is_mine(creator_id, user_id):
        return True
    ws_id = str(workspace_id or "").strip()
    if not ws_id:
        return False
    member = (
        db.query(WorkspaceMember.id)
        .filter(
            WorkspaceMember.workspace_id == ws_id,
            WorkspaceMember.user_id == str(user_id or "").strip(),
        )
        .first()
    )
    return bool(member)


def get_queue_job(
    db: Session,
    *,
    source: str,
    job_id: str,
    user_id: str,
) -> QueueJobItem:
    normalized_source = str(source or "").strip().lower()
    normalized_job_id = str(job_id or "").strip()
    normalized_user_id = str(user_id or "").strip()

    if normalized_source == QUEUE_SOURCE_PROVISION:
        row = (
            db.query(SddProvisionJob)
            .filter(SddProvisionJob.id == normalized_job_id)
            .first()
        )
        if not row:
            raise LookupError("Queue job not found")
        if not _can_view_queue_job(
            db,
            workspace_id=row.workspace_id,
            creator_id=row.creator_id,
            user_id=normalized_user_id,
        ):
            raise PermissionError("No permission to view this queue job")
        _mark_stale_import_skill_job_failed(db, row)
        status = _to_queue_status(_enum_text(row.status))
        job_type = _enum_text(row.job_type)
        result_json = row.result_json if isinstance(row.result_json, dict) else {}
        skill_id = str(result_json.get("skill_id") or "").strip()
        target_path = _build_target_path(
            source=QUEUE_SOURCE_PROVISION,
            job_type=job_type,
            workspace_id=row.workspace_id,
            task_id=row.task_id,
            skill_id=skill_id,
        )
        return QueueJobItem(
            source=QUEUE_SOURCE_PROVISION,
            job_id=row.id,
            job_type=job_type,
            status=status,  # type: ignore[arg-type]
            progress=int(row.progress or 0),
            stage=str(row.stage or "").strip() or None,
            message=row.message,
            error_message=row.error_message,
            workspace_id=row.workspace_id,
            task_id=row.task_id,
            creator_id=str(row.creator_id or ""),
            created_at=row.created_at,
            updated_at=row.updated_at,
            target_path=target_path,
            actions=_build_provision_actions(status, target_path),
        )

    if normalized_source == QUEUE_SOURCE_API_MOCK:
        row = (
            db.query(SddApiMockJob, SddApiMockProject)
            .join(SddApiMockProject, SddApiMockProject.id == SddApiMockJob.project_id)
            .filter(SddApiMockJob.id == normalized_job_id)
            .first()
        )
        if not row:
            raise LookupError("Queue job not found")
        job, project = row
        if not _can_view_queue_job(
            db,
            workspace_id=project.workspace_id,
            creator_id=job.creator_id,
            user_id=normalized_user_id,
        ):
            raise PermissionError("No permission to view this queue job")
        status = _to_queue_status(_enum_text(job.status))
        target_path = _build_target_path(
            source=QUEUE_SOURCE_API_MOCK,
            job_type=str(job.job_type or ""),
            workspace_id=project.workspace_id,
            task_id=project.task_id,
        )
        return QueueJobItem(
            source=QUEUE_SOURCE_API_MOCK,
            job_id=job.id,
            job_type=str(job.job_type or ""),
            status=status,  # type: ignore[arg-type]
            progress=int(job.progress or 0),
            stage=str(job.job_type or "").strip() or None,
            message=job.message,
            error_message=None,
            workspace_id=project.workspace_id,
            task_id=project.task_id,
            creator_id=str(job.creator_id or ""),
            created_at=job.created_at,
            updated_at=job.updated_at,
            target_path=target_path,
            actions=_build_api_mock_actions(
                job_type=str(job.job_type or ""),
                item_status=status,
                target_path=target_path,
            ),
        )

    if normalized_source == QUEUE_SOURCE_BOOTSTRAP:
        row = (
            db.query(SddTaskCliBootstrap, SddTask)
            .join(SddTask, SddTask.id == SddTaskCliBootstrap.task_id)
            .filter(SddTaskCliBootstrap.id == normalized_job_id)
            .first()
        )
        if not row:
            raise LookupError("Queue job not found")
        record, task = row
        if not _can_view_queue_job(
            db,
            workspace_id=record.workspace_id,
            creator_id=task.creator_id,
            user_id=normalized_user_id,
        ):
            raise PermissionError("No permission to view this queue job")
        raw_status = _enum_text(record.status)
        status = _to_queue_status(raw_status)
        target_path = _build_target_path(
            source=QUEUE_SOURCE_BOOTSTRAP,
            job_type="TASK_CLI_BOOTSTRAP",
            workspace_id=record.workspace_id,
            task_id=record.task_id,
        )
        return QueueJobItem(
            source=QUEUE_SOURCE_BOOTSTRAP,
            job_id=record.id,
            job_type="TASK_CLI_BOOTSTRAP",
            status=status,  # type: ignore[arg-type]
            progress=int(record.progress or 0),
            stage=raw_status,
            message=record.message,
            error_message=record.error_message,
            workspace_id=record.workspace_id,
            task_id=record.task_id,
            creator_id=str(task.creator_id or ""),
            created_at=record.created_at,
            updated_at=record.updated_at,
            target_path=target_path,
            actions=_build_bootstrap_actions(status, target_path),
        )

    if normalized_source == QUEUE_SOURCE_SKILL_ANALYSIS:
        row = (
            db.query(SddSkillAnalysis, SddSkill)
            .join(SddSkill, SddSkill.id == SddSkillAnalysis.skill_id)
            .filter(SddSkillAnalysis.id == normalized_job_id)
            .first()
        )
        if not row:
            raise LookupError("Queue job not found")
        analysis, skill = row
        if not _can_view_queue_job(
            db,
            workspace_id=analysis.workspace_id,
            creator_id=analysis.created_by_id,
            user_id=normalized_user_id,
        ):
            raise PermissionError("No permission to view this queue job")
        semantic_degraded = skill_analysis_service.is_semantic_degraded_analysis(analysis)
        status = "SUCCESS" if semantic_degraded else _to_queue_status(_enum_text(analysis.status))
        target_path = _build_target_path(
            source=QUEUE_SOURCE_SKILL_ANALYSIS,
            job_type="SKILL_ANALYSIS",
            workspace_id=analysis.workspace_id,
            task_id=None,
            skill_id=analysis.skill_id,
        )
        return QueueJobItem(
            source=QUEUE_SOURCE_SKILL_ANALYSIS,
            job_id=analysis.id,
            job_type="SKILL_ANALYSIS",
            status=status,  # type: ignore[arg-type]
            progress=int(analysis.progress or 0),
            stage=_enum_text(analysis.ref_kind),
            message=(
                skill_analysis_service.SEMANTIC_UNAVAILABLE_MESSAGE
                if semantic_degraded
                else analysis.message or f"Analyze skill: {skill.name}"
            ),
            error_message=None if semantic_degraded else analysis.error_message,
            workspace_id=analysis.workspace_id,
            task_id=None,
            creator_id=str(analysis.created_by_id or ""),
            created_at=analysis.created_at,
            updated_at=analysis.updated_at,
            target_path=target_path,
            actions=_build_skill_analysis_actions(status, target_path),
        )

    raise ValueError("Unsupported queue source")


def _start_provision_job(new_job_id: str, job_type: str) -> None:
    loop = asyncio.get_running_loop()
    if job_type == ProvisionJobType.CREATE_WORKSPACE.value:
        loop.create_task(provision_job_service.run_create_workspace_job(new_job_id))
        return
    if job_type == ProvisionJobType.CREATE_TASK.value:
        loop.create_task(provision_job_service.run_create_task_job(new_job_id))
        return
    if job_type == ProvisionJobType.IMPORT_SKILL.value:
        loop.create_task(provision_job_service.run_import_skill_job(new_job_id))
        return
    raise ValueError("Unsupported provision job type for retry")


def _start_api_mock_job(
    *,
    job_type: str,
    job_id: str,
    workspace_id: str,
    task_id: str,
    user_id: str,
    endpoint_id: Optional[str] = None,
) -> None:
    loop = asyncio.get_running_loop()
    if job_type == API_MOCK_JOB_SYNC:
        loop.create_task(
            asyncio.to_thread(
                api_mock_service.run_sync_job_background,
                job_id,
                workspace_id,
                task_id,
                user_id,
            )
        )
        return
    if job_type == API_MOCK_JOB_AUTO:
        eid = str(endpoint_id or "").strip()
        if not eid:
            raise ValueError("Missing endpoint_id for auto mock retry")
        loop.create_task(
            asyncio.to_thread(
                api_mock_service.run_auto_mock_job_background,
                job_id,
                workspace_id,
                task_id,
                user_id,
                endpoint_id=eid,
            )
        )
        return
    raise ValueError("Unsupported API MOCK job type for retry")


def stop_queue_job(
    db: Session,
    *,
    source: str,
    job_id: str,
    user_id: str,
) -> Dict[str, Any]:
    normalized_source = str(source or "").strip().lower()
    if normalized_source == QUEUE_SOURCE_PROVISION:
        raise ValueError("Stop is not supported for provision jobs")

    if normalized_source == QUEUE_SOURCE_API_MOCK:
        row = (
            db.query(SddApiMockJob, SddApiMockProject)
            .join(SddApiMockProject, SddApiMockProject.id == SddApiMockJob.project_id)
            .filter(SddApiMockJob.id == str(job_id or "").strip())
            .first()
        )
        if not row:
            raise LookupError("Queue job not found")
        job, project = row
        if not _can_manage_api_mock_jobs(db, workspace_id=project.workspace_id, user_id=user_id):
            raise PermissionError("No permission to manage API MOCK jobs")
        if str(job.job_type or "") not in {API_MOCK_JOB_SYNC, API_MOCK_JOB_AUTO, API_MOCK_JOB_IMPORT}:
            raise ValueError("Stop is not supported for this API MOCK job type")
        api_mock_service.request_job_cancel(db, project.id, job.id)
        audit_log(
            action="queue_stop",
            outcome="success",
            resource_type="queue_job",
            resource_id=job.id,
            source=normalized_source,
            operator_id=user_id,
            workspace_id=project.workspace_id,
            task_id=project.task_id,
        )
        return {
            "source": normalized_source,
            "job_id": job.id,
            "message": "Job stop requested",
        }

    if normalized_source == QUEUE_SOURCE_BOOTSTRAP:
        raise ValueError("Stop is not supported for bootstrap jobs")

    if normalized_source == QUEUE_SOURCE_SKILL_ANALYSIS:
        raise ValueError("Stop is not supported for skill analysis jobs")

    raise ValueError("Unsupported queue source")


def retry_queue_job(
    db: Session,
    *,
    source: str,
    job_id: str,
    user_id: str,
) -> Dict[str, Any]:
    normalized_source = str(source or "").strip().lower()
    normalized_user_id = str(user_id or "").strip()

    if normalized_source == QUEUE_SOURCE_PROVISION:
        source_job = (
            db.query(SddProvisionJob)
            .filter(SddProvisionJob.id == str(job_id or "").strip())
            .first()
        )
        if not source_job:
            raise LookupError("Queue job not found")
        if source_job.job_type == ProvisionJobType.CREATE_WORKSPACE:
            if not _is_mine(source_job.creator_id, normalized_user_id):
                raise PermissionError("No permission to retry this queue job")
        elif source_job.job_type == ProvisionJobType.IMPORT_SKILL:
            can_manage = _can_manage_skill_jobs(
                db,
                workspace_id=source_job.workspace_id,
                user_id=normalized_user_id,
            )
            if not can_manage and not _is_mine(source_job.creator_id, normalized_user_id):
                raise PermissionError("No permission to retry this queue job")
        else:
            can_manage = _can_manage_task_jobs(
                db,
                workspace_id=source_job.workspace_id,
                user_id=normalized_user_id,
            )
            if not can_manage and not _is_mine(source_job.creator_id, normalized_user_id):
                raise PermissionError("No permission to retry this queue job")
        if source_job.status != ProvisionJobStatus.FAILED:
            raise ValueError("Only failed provision jobs can be retried")

        new_job = provision_job_service.retry_job(
            db,
            source_job=source_job,
            creator_id=normalized_user_id,
            message="Provision retry queued",
        )
        _start_provision_job(new_job.id, _enum_text(new_job.job_type))
        audit_log(
            action="queue_retry",
            outcome="success",
            resource_type="queue_job",
            resource_id=source_job.id,
            source=normalized_source,
            operator_id=normalized_user_id,
            new_job_id=new_job.id,
            workspace_id=new_job.workspace_id,
            task_id=new_job.task_id,
        )
        return {
            "source": normalized_source,
            "job_id": source_job.id,
            "new_job_id": new_job.id,
            "message": "Provision retry queued",
        }

    if normalized_source == QUEUE_SOURCE_API_MOCK:
        row = (
            db.query(SddApiMockJob, SddApiMockProject)
            .join(SddApiMockProject, SddApiMockProject.id == SddApiMockJob.project_id)
            .filter(SddApiMockJob.id == str(job_id or "").strip())
            .first()
        )
        if not row:
            raise LookupError("Queue job not found")
        source_job, project = row
        if not _can_manage_api_mock_jobs(db, workspace_id=project.workspace_id, user_id=normalized_user_id):
            raise PermissionError("No permission to retry API MOCK jobs")
        if source_job.status != ApiMockJobStatus.FAILED:
            raise ValueError("Only failed API MOCK jobs can be retried")
        if str(source_job.job_type or "") == API_MOCK_JOB_IMPORT:
            raise ValueError("Retry is not supported for IMPORT_SWAGGER jobs")
        if str(source_job.job_type or "") not in {API_MOCK_JOB_SYNC, API_MOCK_JOB_AUTO}:
            raise ValueError("Retry is not supported for this API MOCK job type")

        endpoint_id: Optional[str] = None
        if str(source_job.job_type or "") == API_MOCK_JOB_AUTO:
            source_payload = source_job.result_json if isinstance(source_job.result_json, dict) else {}
            endpoint_id = str(source_payload.get("target_endpoint_id") or "").strip() or None
            if not endpoint_id:
                raise ValueError("Unable to retry AUTO_GENERATE_MOCK_CASES without endpoint target")

        new_job = api_mock_service.create_job(
            db,
            project,
            creator_id=normalized_user_id,
            job_type=str(source_job.job_type or ""),
            message="Retry queued",
        )

        if str(source_job.job_type or "") == API_MOCK_JOB_AUTO:
            api_mock_service.set_auto_mock_job_target(
                db,
                project.id,
                new_job,
                endpoint_id=endpoint_id,
            )

        _start_api_mock_job(
            job_type=str(source_job.job_type or ""),
            job_id=new_job.id,
            workspace_id=str(project.workspace_id or ""),
            task_id=str(project.task_id or ""),
            user_id=normalized_user_id,
            endpoint_id=endpoint_id,
        )
        audit_log(
            action="queue_retry",
            outcome="success",
            resource_type="queue_job",
            resource_id=source_job.id,
            source=normalized_source,
            operator_id=normalized_user_id,
            new_job_id=new_job.id,
            workspace_id=project.workspace_id,
            task_id=project.task_id,
        )
        return {
            "source": normalized_source,
            "job_id": source_job.id,
            "new_job_id": new_job.id,
            "message": "API MOCK retry queued",
        }

    if normalized_source == QUEUE_SOURCE_BOOTSTRAP:
        row = (
            db.query(SddTaskCliBootstrap, SddTask)
            .join(SddTask, SddTask.id == SddTaskCliBootstrap.task_id)
            .filter(SddTaskCliBootstrap.id == str(job_id or "").strip())
            .first()
        )
        if not row:
            raise LookupError("Queue job not found")
        record, task = row
        if not _can_manage_task_jobs(db, workspace_id=record.workspace_id, user_id=normalized_user_id):
            raise PermissionError("No permission to retry bootstrap jobs")
        status_text = _enum_text(record.status)
        if status_text not in {TaskCliBootstrapStatus.FAILED.value, TaskCliBootstrapStatus.STALE.value}:
            raise ValueError("Only failed/stale bootstrap jobs can be retried")

        record.status = TaskCliBootstrapStatus.PENDING
        record.progress = 0
        record.message = "Bootstrap retry queued"
        record.error_message = None
        db.commit()
        db.refresh(record)
        task_cli_state_service.schedule_bootstrap(record.task_id)
        audit_log(
            action="queue_retry",
            outcome="success",
            resource_type="queue_job",
            resource_id=record.id,
            source=normalized_source,
            operator_id=normalized_user_id,
            workspace_id=record.workspace_id,
            task_id=record.task_id,
        )
        return {
            "source": normalized_source,
            "job_id": record.id,
            "new_job_id": None,
            "message": "Bootstrap retry queued",
        }

    if normalized_source == QUEUE_SOURCE_SKILL_ANALYSIS:
        source_job = (
            db.query(SddSkillAnalysis)
            .filter(SddSkillAnalysis.id == str(job_id or "").strip())
            .first()
        )
        if not source_job:
            raise LookupError("Queue job not found")
        if not _can_manage_skill_jobs(db, workspace_id=source_job.workspace_id, user_id=normalized_user_id):
            raise PermissionError("No permission to retry skill analysis jobs")
        if source_job.status != SkillAnalysisStatus.FAILED:
            raise ValueError("Only failed skill analysis jobs can be retried")

        new_job = skill_analysis_service.retry_analysis_job(
            db,
            source=source_job,
            user_id=normalized_user_id,
        )
        skill_analysis_service.schedule_analysis_job(new_job.id)
        audit_log(
            action="queue_retry",
            outcome="success",
            resource_type="queue_job",
            resource_id=source_job.id,
            source=normalized_source,
            operator_id=normalized_user_id,
            new_job_id=new_job.id,
            workspace_id=new_job.workspace_id,
            skill_id=new_job.skill_id,
        )
        return {
            "source": normalized_source,
            "job_id": source_job.id,
            "new_job_id": new_job.id,
            "message": "Skill analysis retry queued",
        }

    raise ValueError("Unsupported queue source")
