"""Requirement 导入与拆分确认：上传直建、preview 批次确认为 Requirement。

导入确认的三种落库形态：
- 多条 → 自动创建父 Requirement + 子 Requirement 树；
- 单条 → 直接创建独立 Requirement；
- split 确认 → 在既有父 Requirement 下创建子 Requirement。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session, selectinload

from app.domains.workspace_asset.models.workspace_asset import (
    RequirementAuditAction,
    RequirementImportBatchStatus,
    RequirementImportItemStatus,
    RequirementStatus,
    SddRequirement,
    SddRequirementImportBatch,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    RequirementDetailResponse,
    RequirementImportBatchResponse,
    RequirementImportConfirmRequest,
    RequirementSplitDraftPayload,
    RequirementSplitRequest,
)
from app.domains.workspace_asset.services.common.errors import WorkspaceAssetError
from app.domains.workspace_asset.services.common.primitives import (
    clean_optional,
    enum_value,
    normalize_list,
)
from app.domains.workspace_asset.services.requirements.presenters import (
    add_requirement_audit,
    import_batch_response,
    requirement_snapshot,
)
from app.domains.workspace_asset.services.requirements.queries import (
    get_requirement,
    get_requirement_detail,
)
from app.domains.workspace_asset.services.requirements.segmentation import (
    direct_import_title,
    document_metadata,
    extract_acceptance_criteria,
    parse_requirement_document,
)
from app.domains.workspace_asset.services.requirements.writes import normalize_requirement_status
from app.domains.workspace_asset.services.requirements.preview.job_service import get_import_batch


def _ensure_batch_open(batch: SddRequirementImportBatch, message: str) -> None:
    if enum_value(batch.status) != RequirementImportBatchStatus.PREVIEW.value:
        raise WorkspaceAssetError(message, status_code=409)


def create_requirement_direct_import(
    db: Session,
    workspace_id: str,
    actor_id: Optional[str],
    *,
    file_name: str,
    raw: bytes,
    source_kind: Optional[str] = None,
    source_uri: Optional[str] = None,
    source_ref: Optional[str] = None,
    change_reason: Optional[str] = None,
) -> RequirementDetailResponse:
    """上传文档不经 AI preview，直接按文档标题创建一条 Requirement。"""
    parsed = parse_requirement_document(file_name, raw)
    markdown = str(parsed.get("normalized_markdown") or "").strip()
    requirement = SddRequirement(
        workspace_id=workspace_id,
        created_by_id=actor_id,
        title=direct_import_title(file_name, markdown),
        body=markdown,
        status=RequirementStatus.DRAFT,
        acceptance_criteria_json=extract_acceptance_criteria(markdown.splitlines()),
        priority=None,
        source_kind=clean_optional(source_kind, limit=80) or "document",
        source_uri=clean_optional(source_uri, limit=1000),
        source_ref=clean_optional(source_ref, limit=300),
        source_metadata_json=document_metadata(parsed, extra={"created_from": "direct_import", "source_filename": file_name}),
    )
    db.add(requirement)
    db.flush()
    add_requirement_audit(
        db,
        workspace_id=workspace_id,
        requirement_id=requirement.id,
        actor_id=actor_id,
        action=RequirementAuditAction.CREATED,
        after=requirement_snapshot(requirement),
        reason=change_reason,
        source_metadata={"created_from": "direct_import", "source_filename": file_name},
    )
    db.commit()
    result = get_requirement_detail(db, workspace_id, requirement.id)
    if not result:
        raise WorkspaceAssetError("Imported Requirement could not be loaded.", status_code=500)
    return result


def _import_item_values(
    item,
    override,
) -> Optional[Dict[str, Any]]:
    title = clean_optional((override.title if override and override.title is not None else item.title), limit=300)
    if not title:
        item.status = RequirementImportItemStatus.SKIPPED
        return None
    body = override.body if override and override.body is not None else item.body
    criteria = override.acceptance_criteria if override and override.acceptance_criteria is not None else item.acceptance_criteria_json
    priority = override.priority if override and override.priority is not None else item.priority
    # import confirm 的 override 带 status；split 的 override 没有（恒为 DRAFT）。
    status_value = getattr(override, "status", None) or "DRAFT"
    item_metadata = item.source_metadata_json if isinstance(item.source_metadata_json, dict) else {}
    if override and override.task_prompt is not None:
        item_metadata = {**item_metadata, "task_prompt": clean_optional(override.task_prompt)}
        item.source_metadata_json = item_metadata
    return {
        "title": title,
        "body": body,
        "criteria": criteria,
        "priority": priority,
        "status": status_value,
        "source_ref": item.source_ref,
        "metadata": item_metadata,
    }


def _create_requirement_from_values(
    db: Session,
    *,
    workspace_id: str,
    actor_id: Optional[str],
    batch: SddRequirementImportBatch,
    values: Dict[str, Any],
    item_metadata: Dict[str, Any],
    parent: Optional[SddRequirement],
    created_from: str,
    change_reason: Optional[str],
) -> SddRequirement:
    requirement = SddRequirement(
        workspace_id=workspace_id,
        created_by_id=actor_id,
        title=values["title"],
        body=clean_optional(values["body"]),
        status=normalize_requirement_status(values["status"]),
        acceptance_criteria_json=normalize_list(values["criteria"]),
        priority=clean_optional(values["priority"], limit=40),
        parent_requirement_id=parent.id if parent else None,
        import_batch_id=batch.id,
        source_kind=batch.source_kind,
        source_uri=batch.source_uri,
        source_ref=values["source_ref"] or batch.source_ref,
        source_metadata_json={
            **(batch.source_metadata_json or {}),
            **item_metadata,
            "source_filename": batch.source_filename,
            "created_from": created_from,
        },
    )
    if parent:
        requirement.source_metadata_json = {
            **(requirement.source_metadata_json or {}),
            "parent_requirement_id": parent.id,
        }
    db.add(requirement)
    db.flush()
    add_requirement_audit(
        db,
        workspace_id=workspace_id,
        requirement_id=requirement.id,
        import_batch_id=batch.id,
        actor_id=actor_id,
        action=RequirementAuditAction.CREATED,
        after=requirement_snapshot(requirement),
        reason=change_reason,
        source_metadata={"created_from": created_from, "parent_requirement_id": parent.id} if parent else {"created_from": created_from},
    )
    return requirement


def confirm_requirement_import(
    db: Session,
    workspace_id: str,
    batch_id: str,
    actor_id: Optional[str],
    payload: RequirementImportConfirmRequest,
) -> Optional[RequirementImportBatchResponse]:
    """把 import preview 批次确认落库：多条建父+子树，单条直建。"""
    batch = get_import_batch(db, workspace_id, batch_id)
    if not batch:
        return None
    _ensure_batch_open(batch, "Import batch has already been confirmed or closed.")

    provided = {item.item_id: item for item in payload.items}
    selected_values = []
    for item in sorted(batch.items or [], key=lambda current: current.order_index):
        override = provided.get(item.id)
        include = (override is not None and bool(override.include)) if payload.items else True
        if include:
            values = _import_item_values(item, override)
            if values is not None:
                selected_values.append((item, values))
        else:
            item.status = RequirementImportItemStatus.SKIPPED

    created_count = 0
    if len(selected_values) > 1:
        parent_title = direct_import_title(batch.source_filename or "Imported Requirement", batch.normalized_markdown or "")
        parent = SddRequirement(
            workspace_id=workspace_id,
            created_by_id=actor_id,
            title=parent_title,
            body=clean_optional(batch.normalized_markdown),
            status=RequirementStatus.DRAFT,
            acceptance_criteria_json=extract_acceptance_criteria(str(batch.normalized_markdown or "").splitlines()),
            priority=None,
            import_batch_id=batch.id,
            source_kind=batch.source_kind,
            source_uri=batch.source_uri,
            source_ref=batch.source_ref,
            source_metadata_json={
                **(batch.source_metadata_json or {}),
                "source_filename": batch.source_filename,
                "created_from": "import_confirm_parent",
                "preview_item_count": len(selected_values),
            },
        )
        db.add(parent)
        db.flush()
        add_requirement_audit(
            db,
            workspace_id=workspace_id,
            requirement_id=parent.id,
            import_batch_id=batch.id,
            actor_id=actor_id,
            action=RequirementAuditAction.CREATED,
            after=requirement_snapshot(parent),
            reason=payload.change_reason,
            source_metadata={"created_from": "import_confirm_parent"},
        )
        for item, values in selected_values:
            child = _create_requirement_from_values(
                db,
                workspace_id=workspace_id,
                actor_id=actor_id,
                batch=batch,
                values=values,
                item_metadata=values["metadata"],
                parent=parent,
                created_from="import_confirm_child",
                change_reason=payload.change_reason,
            )
            item.requirement_id = child.id
            item.status = RequirementImportItemStatus.CONFIRMED
            created_count += 1
    else:
        for item, values in selected_values:
            requirement = _create_requirement_from_values(
                db,
                workspace_id=workspace_id,
                actor_id=actor_id,
                batch=batch,
                values=values,
                item_metadata=values["metadata"],
                parent=None,
                created_from="import_confirm_single",
                change_reason=payload.change_reason,
            )
            item.requirement_id = requirement.id
            item.status = RequirementImportItemStatus.CONFIRMED
            created_count += 1

    batch.status = RequirementImportBatchStatus.CONFIRMED
    batch.confirmed_count = created_count
    add_requirement_audit(
        db,
        workspace_id=workspace_id,
        import_batch_id=batch.id,
        actor_id=actor_id,
        action=RequirementAuditAction.IMPORT_CONFIRMED,
        after={"confirmed_count": created_count},
        reason=payload.change_reason,
    )
    db.commit()
    refreshed = get_import_batch(db, workspace_id, batch_id)
    return import_batch_response(refreshed) if refreshed else None


def save_requirement_split_draft(
    db: Session,
    workspace_id: str,
    batch_id: str,
    payload: RequirementSplitDraftPayload,
) -> Optional[RequirementImportBatchResponse]:
    """把拆分评审页的未提交编辑覆盖保存为批次草稿。

    草稿是 AI 原始预览之上的编辑态覆盖层：批次 items 保持 AI 原始输出不变，
    仅 PREVIEW（未确认）批次可写；同 workspace 其他用户读取时可见。
    """
    batch = get_import_batch(db, workspace_id, batch_id)
    if not batch:
        return None
    _ensure_batch_open(batch, "Split draft can only be saved while the batch is still open.")
    batch.draft_json = payload.model_dump(mode="json")
    db.commit()
    refreshed = get_import_batch(db, workspace_id, batch_id)
    return import_batch_response(refreshed) if refreshed else None


def clear_requirement_split_draft(
    db: Session,
    workspace_id: str,
    batch_id: str,
) -> Optional[RequirementImportBatchResponse]:
    """删除拆分评审页草稿（评审页「取消」语义）：删除后重新拆分会发起新的 AI 预览。"""
    batch = get_import_batch(db, workspace_id, batch_id)
    if not batch:
        return None
    batch.draft_json = None
    db.commit()
    refreshed = get_import_batch(db, workspace_id, batch_id)
    return import_batch_response(refreshed) if refreshed else None


def find_requirement_split_draft(
    db: Session,
    workspace_id: str,
    requirement_id: str,
) -> Optional[RequirementImportBatchResponse]:
    """「拆分」入口草稿回绑：该需求最近一个带未提交草稿的 PREVIEW 拆分批次。"""
    batch = (
        db.query(SddRequirementImportBatch)
        .options(selectinload(SddRequirementImportBatch.items))
        .filter(
            SddRequirementImportBatch.workspace_id == workspace_id,
            SddRequirementImportBatch.source_kind == "split",
            SddRequirementImportBatch.source_ref == str(requirement_id),
            SddRequirementImportBatch.status == RequirementImportBatchStatus.PREVIEW,
            SddRequirementImportBatch.draft_json.isnot(None),
        )
        .order_by(SddRequirementImportBatch.updated_at.desc(), SddRequirementImportBatch.created_at.desc())
        .first()
    )
    return import_batch_response(batch) if batch else None


def confirm_requirement_split(
    db: Session,
    workspace_id: str,
    requirement_id: str,
    actor_id: Optional[str],
    payload: RequirementSplitRequest,
) -> Optional[RequirementImportBatchResponse]:
    """把 split preview 批次确认为父 Requirement 下的子 Requirement。"""
    parent = get_requirement(db, workspace_id, requirement_id)
    if not parent:
        return None
    batch = get_import_batch(db, workspace_id, payload.batch_id)
    if not batch:
        raise WorkspaceAssetError("Split preview batch not found.", status_code=404)
    if batch.source_ref != requirement_id or batch.source_kind != "split":
        raise WorkspaceAssetError("Split preview batch does not belong to this Requirement.", status_code=409)
    _ensure_batch_open(batch, "Split batch has already been confirmed or closed.")

    provided = {item.item_id: item for item in payload.items}
    created_count = 0
    for item in sorted(batch.items or [], key=lambda current: current.order_index):
        override = provided.get(item.id)
        if override is not None and not override.include:
            item.status = RequirementImportItemStatus.SKIPPED
            continue
        values = _import_item_values(item, override)
        if values is None:
            continue
        child = SddRequirement(
            workspace_id=workspace_id,
            created_by_id=actor_id,
            title=values["title"],
            body=clean_optional(values["body"]),
            status=RequirementStatus.DRAFT,
            acceptance_criteria_json=normalize_list(values["criteria"]),
            priority=clean_optional(values["priority"], limit=40),
            parent_requirement_id=parent.id,
            import_batch_id=batch.id,
            source_kind=parent.source_kind or "split",
            source_uri=parent.source_uri,
            source_ref=values["source_ref"] or parent.source_ref,
            source_metadata_json={
                **(parent.source_metadata_json or {}),
                **values["metadata"],
                "parent_requirement_id": parent.id,
            },
        )
        db.add(child)
        db.flush()
        item.requirement_id = child.id
        item.status = RequirementImportItemStatus.CONFIRMED
        created_count += 1
        add_requirement_audit(
            db,
            workspace_id=workspace_id,
            requirement_id=child.id,
            import_batch_id=batch.id,
            actor_id=actor_id,
            action=RequirementAuditAction.CREATED,
            after=requirement_snapshot(child),
            reason=payload.change_reason,
            source_metadata={"created_from": "split_confirm", "parent_requirement_id": parent.id},
        )
    batch.status = RequirementImportBatchStatus.CONFIRMED
    batch.confirmed_count = created_count
    # 确认即消费草稿：批次关闭后草稿不再有意义，避免残留脏数据
    batch.draft_json = None
    add_requirement_audit(
        db,
        workspace_id=workspace_id,
        requirement_id=parent.id,
        import_batch_id=batch.id,
        actor_id=actor_id,
        action=RequirementAuditAction.SPLIT_CONFIRMED,
        after={"confirmed_count": created_count},
        reason=payload.change_reason,
    )
    db.commit()
    refreshed = get_import_batch(db, workspace_id, batch.id)
    return import_batch_response(refreshed) if refreshed else None
