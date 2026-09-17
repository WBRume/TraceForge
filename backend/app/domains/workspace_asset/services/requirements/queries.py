"""Requirement 读侧：工作区列表（树/平铺/子级）与详情。

一次性声明列表卡片所需的全部关联加载（消除 N+1），排序键在内存比较。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.domains.task.models.task import SddTask
from app.domains.workspace_asset.models.workspace_asset import (
    SddRequirement,
    SddTaskRequirement,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    RequirementDetailResponse,
    WorkspaceAssetsRequirementsResponse,
)
from app.domains.workspace_asset.services.common.primitives import (
    collection_state,
    enum_value,
    make_connection,
)
from app.domains.workspace_asset.services.requirements.presenters import (
    requirement_audit_response,
    requirement_linked_task,
    requirement_summary,
    requirement_task_links,
)

_REQUIREMENT_SORT_FIELDS = {
    "created_at",
    "updated_at",
    "title",
    "status",
    "priority",
    "child_count",
    "related_task_count",
}


def requirement_load_options() -> tuple[Any, ...]:
    return (
        selectinload(SddRequirement.parent_requirement),
        selectinload(SddRequirement.child_requirements),
        selectinload(SddRequirement.child_requirements).selectinload(SddRequirement.task_links),
        selectinload(SddRequirement.child_requirements)
        .selectinload(SddRequirement.task_links)
        .selectinload(SddTaskRequirement.task)
        .selectinload(SddTask.requirement_links),
        selectinload(SddRequirement.child_requirements)
        .selectinload(SddRequirement.task_links)
        .selectinload(SddTaskRequirement.task)
        .selectinload(SddTask.evidence_items),
        selectinload(SddRequirement.child_requirements)
        .selectinload(SddRequirement.task_links)
        .selectinload(SddTaskRequirement.task)
        .selectinload(SddTask.human_reviews),
        selectinload(SddRequirement.child_requirements)
        .selectinload(SddRequirement.task_links)
        .selectinload(SddTaskRequirement.task)
        .selectinload(SddTask.human_deltas),
        selectinload(SddRequirement.child_requirements).selectinload(SddRequirement.evidence_items),
        selectinload(SddRequirement.child_requirements).selectinload(SddRequirement.audit_logs),
        selectinload(SddRequirement.task_links)
        .selectinload(SddTaskRequirement.task)
        .selectinload(SddTask.requirement_links),
        selectinload(SddRequirement.task_links)
        .selectinload(SddTaskRequirement.task)
        .selectinload(SddTask.evidence_items),
        selectinload(SddRequirement.task_links)
        .selectinload(SddTaskRequirement.task)
        .selectinload(SddTask.human_reviews),
        selectinload(SddRequirement.task_links)
        .selectinload(SddTaskRequirement.task)
        .selectinload(SddTask.human_deltas),
        selectinload(SddRequirement.evidence_items),
        selectinload(SddRequirement.audit_logs),
    )


def _requirement_sort_key(requirement: SddRequirement, sort_by: str) -> Any:
    if sort_by == "title":
        return (requirement.title or "").lower()
    if sort_by == "status":
        return enum_value(requirement.status)
    if sort_by == "priority":
        return requirement.priority or ""
    if sort_by == "updated_at":
        return requirement.updated_at or requirement.created_at or datetime.min
    if sort_by == "child_count":
        return len(requirement.child_requirements or [])
    if sort_by == "related_task_count":
        return len(requirement_task_links(requirement))
    return requirement.created_at or datetime.min


def get_requirement(db: Session, workspace_id: str, requirement_id: str) -> Optional[SddRequirement]:
    return (
        db.query(SddRequirement)
        .options(*requirement_load_options())
        .filter(SddRequirement.workspace_id == workspace_id, SddRequirement.id == requirement_id)
        .first()
    )


def list_requirements(
    db: Session,
    workspace_id: str,
    *,
    q: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    source_kind: Optional[str] = None,
    parent_id: Optional[str] = None,
    scope: str = "tree",
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 50,
) -> WorkspaceAssetsRequirementsResponse:
    scope_value = scope if scope in {"tree", "flat", "children"} else "tree"
    sort_value = sort_by if sort_by in _REQUIREMENT_SORT_FIELDS else "created_at"
    page_value = max(1, int(page or 1))
    page_size_value = max(1, min(200, int(page_size or 50)))

    query = db.query(SddRequirement).options(*requirement_load_options()).filter(SddRequirement.workspace_id == workspace_id)
    if scope_value == "tree":
        query = query.filter(SddRequirement.parent_requirement_id.is_(None))
    elif scope_value == "children":
        if parent_id:
            query = query.filter(SddRequirement.parent_requirement_id == parent_id)
        else:
            query = query.filter(SddRequirement.parent_requirement_id.isnot(None))
    elif parent_id:
        query = query.filter(SddRequirement.parent_requirement_id == parent_id)

    search = str(q or "").strip()
    if search:
        like = f"%{search}%"
        query = query.filter(or_(SddRequirement.title.ilike(like), SddRequirement.body.ilike(like), SddRequirement.source_ref.ilike(like)))
    if status:
        query = query.filter(SddRequirement.status == status)
    if priority:
        query = query.filter(SddRequirement.priority == priority)
    if source_kind:
        query = query.filter(SddRequirement.source_kind == source_kind)

    requirements = query.all()
    reverse = sort_order != "asc"
    requirements = sorted(requirements, key=lambda item: _requirement_sort_key(item, sort_value), reverse=reverse)
    total = len(requirements)
    offset = (page_value - 1) * page_size_value
    page_items = requirements[offset:offset + page_size_value]
    return WorkspaceAssetsRequirementsResponse(
        workspace_id=workspace_id,
        items=[
            requirement_summary(item, include_linked_tasks=True, include_children=scope_value == "tree")
            for item in page_items
        ],
        total=total,
        page=page_value,
        page_size=page_size_value,
        scope=scope_value,
        state=collection_state(total, "Requirement source is not connected or has no records."),
        connection_status=[
            make_connection(
                "requirement_source",
                "Requirement source",
                "AVAILABLE" if total else "NOT_CONNECTED",
                "Workspace-level requirement records are available."
                if total
                else "Waiting for requirement source connection.",
            )
        ],
    )


def get_requirement_detail(db: Session, workspace_id: str, requirement_id: str) -> Optional[RequirementDetailResponse]:
    requirement = get_requirement(db, workspace_id, requirement_id)
    if not requirement:
        return None
    links = sorted(requirement.task_links or [], key=lambda item: item.created_at, reverse=True)
    logs = sorted(requirement.audit_logs or [], key=lambda item: item.created_at, reverse=True)
    return RequirementDetailResponse(
        requirement=requirement_summary(requirement, include_linked_tasks=True, include_children=True),
        linked_tasks=[requirement_linked_task(link) for link in links],
        children=[
            requirement_summary(child, include_linked_tasks=True)
            for child in sorted(list(requirement.child_requirements or []), key=lambda item: item.created_at or datetime.min, reverse=True)
        ],
        audit_logs=[requirement_audit_response(log) for log in logs],
    )
