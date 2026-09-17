"""Requirement 写侧：创建、更新、关联/解关联 Task，全部落审计。

状态与关联类型归一化也在这里（写侧专属的输入校验）。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domains.task.models.task import SddTask
from app.domains.workspace_asset.models.workspace_asset import (
    RequirementAuditAction,
    RequirementStatus,
    SddRequirement,
    SddTaskRequirement,
    TaskRequirementRelationType,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    RequirementCreateRequest,
    RequirementDetailResponse,
    RequirementTaskLinkRequest,
    RequirementUpdateRequest,
)
from app.domains.workspace_asset.services.common.errors import WorkspaceAssetError
from app.domains.workspace_asset.services.common.primitives import (
    clean_optional,
    enum_value,
    json_dict,
    normalize_list,
    payload_has_field,
)
from app.domains.workspace_asset.services.requirements.presenters import (
    add_requirement_audit,
    requirement_snapshot,
)
from app.domains.workspace_asset.services.requirements.queries import (
    get_requirement,
    get_requirement_detail,
)


def normalize_requirement_status(
    value: Optional[str], *, default: RequirementStatus = RequirementStatus.DRAFT
) -> RequirementStatus:
    raw = str(value or default.value).strip().upper()
    try:
        return RequirementStatus(raw)
    except ValueError as exc:
        raise WorkspaceAssetError(f"Unsupported requirement status: {value}", status_code=422) from exc


def _normalize_relation_type(value: Optional[str]) -> TaskRequirementRelationType:
    raw = str(value or TaskRequirementRelationType.RELATES_TO.value).strip().upper()
    try:
        return TaskRequirementRelationType(raw)
    except ValueError as exc:
        raise WorkspaceAssetError(
            f"Unsupported requirement-task relation type: {value}", status_code=422
        ) from exc


def create_requirement(
    db: Session,
    workspace_id: str,
    actor_id: Optional[str],
    payload: RequirementCreateRequest,
) -> RequirementDetailResponse:
    title = clean_optional(payload.title, limit=300)
    if not title:
        raise WorkspaceAssetError("Requirement title is required.", status_code=422)
    parent_id = clean_optional(payload.parent_requirement_id, limit=36)
    if parent_id:
        parent = get_requirement(db, workspace_id, parent_id)
        if not parent:
            raise WorkspaceAssetError("Parent Requirement not found.", status_code=404)
        if parent.parent_requirement_id:
            raise WorkspaceAssetError("Nested child Requirements are not supported in this phase.", status_code=409)

    requirement = SddRequirement(
        workspace_id=workspace_id,
        created_by_id=actor_id,
        title=title,
        body=clean_optional(payload.body),
        status=normalize_requirement_status(payload.status),
        acceptance_criteria_json=normalize_list(payload.acceptance_criteria),
        priority=clean_optional(payload.priority, limit=40),
        parent_requirement_id=parent_id,
        source_kind=clean_optional(payload.source_kind, limit=80),
        source_uri=clean_optional(payload.source_uri, limit=1000),
        source_ref=clean_optional(payload.source_ref, limit=300),
        source_metadata_json=json_dict(payload.source_metadata),
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
        reason=payload.change_reason,
    )
    db.commit()
    db.expire_all()
    detail = get_requirement_detail(db, workspace_id, requirement.id)
    if not detail:
        raise WorkspaceAssetError("Requirement was created but could not be loaded.", status_code=500)
    return detail


def update_requirement(
    db: Session,
    workspace_id: str,
    requirement_id: str,
    actor_id: Optional[str],
    payload: RequirementUpdateRequest,
) -> Optional[RequirementDetailResponse]:
    requirement = get_requirement(db, workspace_id, requirement_id)
    if not requirement:
        return None

    before = requirement_snapshot(requirement)
    if payload_has_field(payload, "title"):
        title = clean_optional(payload.title, limit=300)
        if not title:
            raise WorkspaceAssetError("Requirement title is required.", status_code=422)
        requirement.title = title
    if payload_has_field(payload, "body"):
        requirement.body = clean_optional(payload.body)
    if payload_has_field(payload, "acceptance_criteria"):
        requirement.acceptance_criteria_json = normalize_list(payload.acceptance_criteria)
    if payload_has_field(payload, "priority"):
        requirement.priority = clean_optional(payload.priority, limit=40)
    if payload_has_field(payload, "status"):
        requirement.status = normalize_requirement_status(payload.status)
    if payload_has_field(payload, "source_kind"):
        requirement.source_kind = clean_optional(payload.source_kind, limit=80)
    if payload_has_field(payload, "source_uri"):
        requirement.source_uri = clean_optional(payload.source_uri, limit=1000)
    if payload_has_field(payload, "source_ref"):
        requirement.source_ref = clean_optional(payload.source_ref, limit=300)
    if payload_has_field(payload, "source_metadata"):
        requirement.source_metadata_json = json_dict(payload.source_metadata)

    db.flush()
    after = requirement_snapshot(requirement)
    if before != after:
        action = (
            RequirementAuditAction.STATUS_CHANGED
            if before.get("status") != after.get("status") and {k: v for k, v in before.items() if k != "status"} == {k: v for k, v in after.items() if k != "status"}
            else RequirementAuditAction.UPDATED
        )
        add_requirement_audit(
            db,
            workspace_id=workspace_id,
            requirement_id=requirement.id,
            actor_id=actor_id,
            action=action,
            before=before,
            after=after,
            reason=payload.change_reason,
        )
    db.commit()
    db.expire_all()
    return get_requirement_detail(db, workspace_id, requirement.id)


def link_requirement_task(
    db: Session,
    workspace_id: str,
    requirement_id: str,
    actor_id: Optional[str],
    payload: RequirementTaskLinkRequest,
) -> Optional[RequirementDetailResponse]:
    requirement = get_requirement(db, workspace_id, requirement_id)
    if not requirement:
        return None
    if not requirement.parent_requirement_id and requirement.child_requirements:
        raise WorkspaceAssetError(
            "Parent Requirement has child Requirements; link Task to a child Requirement.",
            status_code=409,
        )
    task = db.query(SddTask).filter(SddTask.workspace_id == workspace_id, SddTask.id == payload.task_id).first()
    if not task:
        raise WorkspaceAssetError("Task not found in this workspace.", status_code=404)
    existing = (
        db.query(SddTaskRequirement)
        .filter(SddTaskRequirement.requirement_id == requirement_id, SddTaskRequirement.task_id == task.id)
        .first()
    )
    if existing:
        raise WorkspaceAssetError("Requirement is already linked to this Task.", status_code=409)

    link = SddTaskRequirement(
        workspace_id=workspace_id,
        requirement_id=requirement_id,
        task_id=task.id,
        relation_type=_normalize_relation_type(payload.relation_type),
        created_by_id=actor_id,
    )
    db.add(link)
    db.flush()
    add_requirement_audit(
        db,
        workspace_id=workspace_id,
        requirement_id=requirement_id,
        task_id=task.id,
        actor_id=actor_id,
        action=RequirementAuditAction.LINKED_TASK,
        after={"task_id": task.id, "relation_type": enum_value(link.relation_type)},
        reason=payload.change_reason,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise WorkspaceAssetError("Requirement is already linked to this Task.", status_code=409) from exc
    db.expire_all()
    return get_requirement_detail(db, workspace_id, requirement_id)


def unlink_requirement_task(
    db: Session,
    workspace_id: str,
    requirement_id: str,
    task_id: str,
    actor_id: Optional[str],
    change_reason: Optional[str] = None,
) -> Optional[RequirementDetailResponse]:
    requirement = get_requirement(db, workspace_id, requirement_id)
    if not requirement:
        return None
    link = (
        db.query(SddTaskRequirement)
        .filter(
            SddTaskRequirement.workspace_id == workspace_id,
            SddTaskRequirement.requirement_id == requirement_id,
            SddTaskRequirement.task_id == task_id,
        )
        .first()
    )
    if not link:
        raise WorkspaceAssetError("Requirement-Task link not found.", status_code=404)
    before = {"task_id": link.task_id, "relation_type": enum_value(link.relation_type)}
    db.delete(link)
    add_requirement_audit(
        db,
        workspace_id=workspace_id,
        requirement_id=requirement_id,
        task_id=task_id,
        actor_id=actor_id,
        action=RequirementAuditAction.UNLINKED_TASK,
        before=before,
        reason=change_reason,
    )
    db.commit()
    db.expire_all()
    return get_requirement_detail(db, workspace_id, requirement_id)
