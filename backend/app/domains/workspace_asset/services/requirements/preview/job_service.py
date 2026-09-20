"""Requirement preview 作业的创建、查询与 preview 批次落库。

作业输入（上传文档解析结果）在创建时持久化进 ``context_json``，服务重启
后可由 ``recover_pending_queues`` 重新调度执行；原始字节不留在进程内。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session, selectinload

from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.auth.models.user import Workspace
from app.domains.ai.services.jobs.registry import runtime as ai_job_runtime
from app.domains.workspace_asset.models.workspace_asset import (
    RequirementAuditAction,
    RequirementImportBatchStatus,
    RequirementImportItemStatus,
    SddRequirementImportBatch,
    SddRequirementImportItem,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    RequirementPreviewJobResponse,
)
from app.domains.workspace_asset.services.common.errors import WorkspaceAssetError
from app.domains.workspace_asset.services.common.primitives import clean_optional, enum_value
from app.domains.workspace_asset.services.requirements.presenters import (
    add_requirement_audit,
    import_batch_response,
)

REQUIREMENT_PREVIEW_QUEUE_PREFIX = "REQUIREMENT_PREVIEW:"
REQUIREMENT_IMPORT_MAX_BYTES = 20 * 1024 * 1024


def schedule_requirement_preview_queue(workspace_id: str) -> None:
    """Requirement preview 作业统一走 AI 任务队列（可恢复、按 workspace 串行）。"""
    ai_job_runtime.schedule_queue(f"{REQUIREMENT_PREVIEW_QUEUE_PREFIX}{workspace_id}")


def workspace_project_path_or_error(db: Session, workspace_id: str) -> str:
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    project_path = str((workspace.project_path if workspace else "") or "").strip()
    if not project_path or not os.path.isdir(project_path):
        raise WorkspaceAssetError(
            "Workspace project_path is required for AI preview and must point to an existing directory.",
            status_code=409,
        )
    return os.path.abspath(project_path)


def get_import_batch(db: Session, workspace_id: str, batch_id: str) -> Optional[SddRequirementImportBatch]:
    return (
        db.query(SddRequirementImportBatch)
        .options(selectinload(SddRequirementImportBatch.items))
        .filter(SddRequirementImportBatch.workspace_id == workspace_id, SddRequirementImportBatch.id == batch_id)
        .first()
    )


def create_requirement_preview_batch(
    db: Session,
    *,
    workspace_id: str,
    actor_id: Optional[str],
    file_name: Optional[str],
    markdown: str,
    source_kind: Optional[str],
    source_uri: Optional[str],
    source_ref: Optional[str],
    source_metadata: Dict[str, Any],
    items: List[Dict[str, Any]],
    audit_action: RequirementAuditAction,
    requirement_id: Optional[str] = None,
    reason: Optional[str] = None,
) -> SddRequirementImportBatch:
    """落一条 PREVIEW 批次与全部预览条目，并写 preview 创建审计。"""
    batch = SddRequirementImportBatch(
        workspace_id=workspace_id,
        created_by_id=actor_id,
        source_kind=clean_optional(source_kind, limit=80) or "document",
        source_filename=clean_optional(file_name, limit=500),
        source_uri=clean_optional(source_uri, limit=1000),
        source_ref=clean_optional(source_ref, limit=300),
        source_metadata_json=source_metadata,
        normalized_markdown=markdown,
        status=RequirementImportBatchStatus.PREVIEW,
        item_count=len(items),
        confirmed_count=0,
    )
    db.add(batch)
    db.flush()
    for item_data in items:
        db.add(
            SddRequirementImportItem(
                workspace_id=workspace_id,
                batch_id=batch.id,
                title=item_data["title"],
                body=item_data.get("body"),
                acceptance_criteria_json=item_data.get("acceptance_criteria") or [],
                priority=clean_optional(item_data.get("priority"), limit=40),
                source_ref=item_data.get("source_ref"),
                source_metadata_json=item_data.get("source_metadata"),
                order_index=int(item_data.get("order_index") or 0),
                status=RequirementImportItemStatus.PENDING,
            )
        )
    add_requirement_audit(
        db,
        workspace_id=workspace_id,
        requirement_id=requirement_id,
        import_batch_id=batch.id,
        actor_id=actor_id,
        action=audit_action,
        after={"item_count": len(items), "source_filename": file_name},
        reason=reason,
        source_metadata=source_metadata,
    )
    return batch


def preview_job_response(db: Session, job: SddAiJob) -> RequirementPreviewJobResponse:
    context = job.context_json if isinstance(job.context_json, dict) else {}
    batch = None
    batch_id = str(context.get("preview_batch_id") or "").strip()
    if batch_id:
        loaded = get_import_batch(db, job.workspace_id, batch_id)
        if loaded:
            batch = import_batch_response(loaded)
    requirement_id = str(context.get("requirement_id") or "").strip() or None
    # 导入预览没有 requirement_id，用来源文件名给浮窗当标题
    requirement_title = (
        str(context.get("requirement_title") or "").strip()
        or str(context.get("source_filename") or "").strip()
        or None
    )
    return RequirementPreviewJobResponse(
        job_id=job.id,
        workspace_id=job.workspace_id,
        status=enum_value(job.status),
        progress=int(job.progress or 0),
        message=job.message,
        error=job.error_message,
        batch=batch,
        job_kind=str(context.get("job_kind") or "").strip() or None,
        requirement_id=requirement_id,
        requirement_title=requirement_title,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def list_active_requirement_preview_jobs(
    db: Session,
    creator_id: str,
    *,
    limit: int = 20,
) -> List[RequirementPreviewJobResponse]:
    """浮窗刷新恢复：当前用户名下未终态的 requirement preview 作业。"""
    jobs = (
        db.query(SddAiJob)
        .filter(
            SddAiJob.creator_id == creator_id,
            SddAiJob.queue_key.like(f"{REQUIREMENT_PREVIEW_QUEUE_PREFIX}%"),
            SddAiJob.status.in_([AiJobStatus.PENDING, AiJobStatus.RUNNING]),
        )
        .order_by(SddAiJob.created_at.desc())
        .limit(max(1, min(int(limit or 20), 100)))
        .all()
    )
    return [preview_job_response(db, job) for job in jobs]


def get_requirement_preview_job(db: Session, workspace_id: str, job_id: str) -> Optional[RequirementPreviewJobResponse]:
    job = (
        db.query(SddAiJob)
        .filter(
            SddAiJob.workspace_id == workspace_id,
            SddAiJob.id == job_id,
        )
        .first()
    )
    context = job.context_json if job and isinstance(job.context_json, dict) else {}
    if context.get("job_kind") not in {"REQUIREMENT_IMPORT_PREVIEW", "REQUIREMENT_SPLIT_PREVIEW"}:
        return None
    return preview_job_response(db, job) if job else None


def create_requirement_import_preview_job(
    db: Session,
    workspace_id: str,
    actor_id: str,
    *,
    file_name: str,
    raw: bytes,
    source_kind: Optional[str] = None,
    source_uri: Optional[str] = None,
    source_ref: Optional[str] = None,
) -> RequirementPreviewJobResponse:
    """创建 import preview 作业：请求时同步解析文档并把内容持久化进 context_json。"""
    from app.domains.workspace_asset.services.requirements.segmentation import parse_requirement_document

    if len(raw) > REQUIREMENT_IMPORT_MAX_BYTES:
        raise WorkspaceAssetError(
            "Requirement import file is too large (max 20MB).",
            status_code=413,
        )
    parsed = parse_requirement_document(file_name, raw)
    markdown = str(parsed.get("normalized_markdown") or "").strip()
    project_path = workspace_project_path_or_error(db, workspace_id)
    job = SddAiJob(
        workspace_id=workspace_id,
        task_id=None,
        asset_id=None,
        thread_id=None,
        channel=AiJobChannel.ASSET_THREAD,
        queue_key=f"{REQUIREMENT_PREVIEW_QUEUE_PREFIX}{workspace_id}",
        status=AiJobStatus.PENDING,
        max_attempts=2,
        progress=0,
        message="Requirement AI preview queued",
        context_json={
            "job_kind": "REQUIREMENT_IMPORT_PREVIEW",
            "project_path": project_path,
            "source_kind": source_kind or "document",
            "source_filename": file_name,
            "source_uri": source_uri,
            "source_ref": source_ref,
            "normalized_markdown": markdown,
            "source_ext": parsed.get("source_ext"),
            "source_mime": parsed.get("source_mime"),
            "render_json": parsed.get("render_json"),
        },
        creator_id=actor_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return preview_job_response(db, job)


def create_requirement_split_preview_job(
    db: Session,
    workspace_id: str,
    requirement_id: str,
    actor_id: str,
    change_reason: Optional[str] = None,
) -> Optional[RequirementPreviewJobResponse]:
    from app.domains.ai.services.jobs.constants import FINAL_STATUSES
    from app.domains.workspace_asset.services.requirements.queries import get_requirement

    requirement = get_requirement(db, workspace_id, requirement_id)
    if not requirement:
        return None
    # 幂等守卫：同一需求同一时刻最多一个拆分预览作业。取消收敛 / reaper
    # 回收尚未完成时再次发起拆分，直接复用未收敛的旧作业，绝不并行拉起
    # 第二个 CLI（旧 CLI 的进程树可能尚未确认死亡）。
    unconverged = (
        db.query(SddAiJob)
        .filter(
            SddAiJob.workspace_id == workspace_id,
            SddAiJob.queue_key == f"{REQUIREMENT_PREVIEW_QUEUE_PREFIX}{workspace_id}",
            SddAiJob.status.notin_(list(FINAL_STATUSES)),
        )
        .order_by(SddAiJob.created_at.desc())
        .all()
    )
    for stale in unconverged:
        stale_context = stale.context_json if isinstance(stale.context_json, dict) else {}
        if str(stale_context.get("job_kind") or "") != "REQUIREMENT_SPLIT_PREVIEW":
            continue
        if str(stale_context.get("requirement_id") or "") != str(requirement.id):
            continue
        return preview_job_response(db, stale)
    project_path = workspace_project_path_or_error(db, workspace_id)
    job = SddAiJob(
        workspace_id=workspace_id,
        task_id=None,
        asset_id=None,
        thread_id=None,
        channel=AiJobChannel.ASSET_THREAD,
        queue_key=f"{REQUIREMENT_PREVIEW_QUEUE_PREFIX}{workspace_id}",
        status=AiJobStatus.PENDING,
        max_attempts=2,
        progress=0,
        message="Requirement split preview queued",
        context_json={
            "job_kind": "REQUIREMENT_SPLIT_PREVIEW",
            "project_path": project_path,
            "requirement_id": requirement.id,
            "requirement_title": requirement.title,
            "source_kind": "split",
            "source_uri": requirement.source_uri,
            "source_ref": requirement.id,
            "change_reason": change_reason,
        },
        creator_id=actor_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return preview_job_response(db, job)


__all__ = [
    "REQUIREMENT_IMPORT_MAX_BYTES",
    "REQUIREMENT_PREVIEW_QUEUE_PREFIX",
    "create_requirement_import_preview_job",
    "create_requirement_preview_batch",
    "create_requirement_split_preview_job",
    "get_import_batch",
    "get_requirement_preview_job",
    "list_active_requirement_preview_jobs",
    "preview_job_response",
    "schedule_requirement_preview_queue",
    "workspace_project_path_or_error",
]
