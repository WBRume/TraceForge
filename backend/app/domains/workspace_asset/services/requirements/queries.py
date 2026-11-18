"""Requirement 读侧：工作区列表（树/平铺/子级）与详情。

一次性声明列表卡片所需的全部关联加载（消除 N+1），排序键在内存比较。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased, selectinload

from app.domains.task.models.task import SddTask
from app.domains.workspace_asset.models.workspace_asset import (
    SddRequirement,
    SddTaskRequirement,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    RequirementDetailResponse,
    RequirementOptionsResponse,
    WorkspaceAssetsRequirementsResponse,
)
from app.domains.workspace_asset.services.common.primitives import (
    collection_state,
    enum_value,
    make_connection,
)
from app.domains.workspace_asset.services.requirements.delivery import (
    OPEN_STATUSES,
    READY_STATUSES,
    activity_times,
    matches_work_scope,
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


def list_requirement_options(
    db: Session,
    workspace_id: str,
    *,
    q: str | None = None,
    ids: list[str] | None = None,
    page: int = 1,
    page_size: int = 40,
    scope: str = "all",
    parent_id: str | None = None,
) -> RequirementOptionsResponse:
    """SQL-paged picker: no bodies, evidence, child trees or audit collections."""
    query = db.query(SddRequirement).filter(SddRequirement.workspace_id == workspace_id)
    if scope == "roots":
        query = query.filter(SddRequirement.parent_requirement_id.is_(None))
    elif scope == "children":
        query = query.filter(SddRequirement.parent_requirement_id == parent_id) if parent_id else query.filter(False)
    if ids is not None:
        query = query.filter(SddRequirement.id.in_(ids))
    search = str(q or "").strip()
    if search:
        query = query.filter(
            or_(
                SddRequirement.id.ilike(f"%{search}%"),
                SddRequirement.title.ilike(f"%{search}%"),
                SddRequirement.source_ref.ilike(f"%{search}%"),
            )
        )
    total = query.count()
    parent = aliased(SddRequirement)
    child = aliased(SddRequirement)
    child_count = (
        select(func.count(child.id))
        .where(
            child.parent_requirement_id == SddRequirement.id,
            child.workspace_id == workspace_id,
        )
        .correlate(SddRequirement)
        .scalar_subquery()
    )
    items = (
        query.outerjoin(parent, SddRequirement.parent_requirement_id == parent.id)
        .with_entities(
            SddRequirement.id,
            SddRequirement.title,
            SddRequirement.status,
            SddRequirement.source_ref,
            SddRequirement.parent_requirement_id,
            parent.title.label("parent_title"),
            child_count.label("child_count"),
        )
        .order_by(SddRequirement.updated_at.desc(), SddRequirement.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return RequirementOptionsResponse(
        items=[
            {
                "id": item.id,
                "title": item.title,
                "status": enum_value(item.status),
                "source_ref": item.source_ref,
                "parent_requirement_id": item.parent_requirement_id,
                "parent_title": item.parent_title,
                "child_count": item.child_count,
                "can_link_task": item.child_count == 0,
            }
            for item in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


def requirement_load_options() -> tuple[Any, ...]:
    return (
        selectinload(SddRequirement.owner),
        selectinload(SddRequirement.reviewer),
        selectinload(SddRequirement.acceptor),
        selectinload(SddRequirement.predecessor),
        selectinload(SddRequirement.child_requirements).selectinload(SddRequirement.reviewer),
        selectinload(SddRequirement.child_requirements).selectinload(SddRequirement.acceptor),
        selectinload(SddRequirement.child_requirements).selectinload(SddRequirement.predecessor),
        selectinload(SddRequirement.child_requirements).selectinload(SddRequirement.owner),
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
        selectinload(SddRequirement.task_links).selectinload(SddTaskRequirement.task).selectinload(SddTask.creator),
        selectinload(SddRequirement.child_requirements)
        .selectinload(SddRequirement.task_links)
        .selectinload(SddTaskRequirement.task)
        .selectinload(SddTask.creator),
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


def get_requirement(
    db: Session, workspace_id: str, requirement_id: str, *, for_update: bool = False
) -> SddRequirement | None:
    query = (
        db.query(SddRequirement)
        .options(*requirement_load_options())
        .filter(SddRequirement.workspace_id == workspace_id, SddRequirement.id == requirement_id)
    )
    if for_update:
        query = query.populate_existing().with_for_update()
    return query.first()


def list_requirements(
    db: Session,
    workspace_id: str,
    *,
    q: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    source_kind: str | None = None,
    parent_id: str | None = None,
    scope: str = "tree",
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 50,
    work_scope: str = "all",
    actor_id: str = "",
) -> WorkspaceAssetsRequirementsResponse:
    scope_value = "flat" if work_scope != "all" else scope if scope in {"tree", "flat", "children"} else "tree"
    sort_value = sort_by if sort_by in _REQUIREMENT_SORT_FIELDS else "created_at"
    page_value = max(1, int(page or 1))
    page_size_value = max(1, min(200, int(page_size or 50)))

    query = (
        db.query(SddRequirement)
        .options(*requirement_load_options())
        .filter(SddRequirement.workspace_id == workspace_id)
    )
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
        query = query.filter(
            or_(
                SddRequirement.title.ilike(like), SddRequirement.body.ilike(like), SddRequirement.source_ref.ilike(like)
            )
        )
    if status:
        query = query.filter(SddRequirement.status == status)
    if priority:
        query = query.filter(SddRequirement.priority == priority)
    if source_kind:
        query = query.filter(SddRequirement.source_kind == source_kind)

    if work_scope != "all":
        query = query.filter(SddRequirement.status.in_(OPEN_STATUSES), ~SddRequirement.child_requirements.any())
        if work_scope == "mine":
            query = query.filter(SddRequirement.owner_id == actor_id)
        elif work_scope == "claimable":
            query = query.filter(SddRequirement.owner_id.is_(None), SddRequirement.status.in_(READY_STATUSES))
    requirements = query.all()
    starts = None
    if work_scope != "all":
        starts = _activity_times(db, workspace_id, requirements)
        requirements = [item for item in requirements if matches_work_scope(item, starts, work_scope, actor_id)]
    reverse = sort_order != "asc"
    requirements = sorted(requirements, key=lambda item: _requirement_sort_key(item, sort_value), reverse=reverse)
    total = len(requirements)
    offset = (page_value - 1) * page_size_value
    page_items = requirements[offset : offset + page_size_value]
    if starts is None:
        starts = _activity_times(db, workspace_id, page_items)
    return WorkspaceAssetsRequirementsResponse(
        workspace_id=workspace_id,
        items=[
            requirement_summary(item, include_linked_tasks=True, include_children=scope_value == "tree", starts=starts)
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


def _activity_times(db: Session, workspace_id: str, requirements: list[SddRequirement]) -> dict[str, datetime]:
    return activity_times(
        db,
        workspace_id,
        (
            link.task_id
            for requirement in requirements
            for item in [requirement, *requirement.child_requirements]
            for link in item.task_links
        ),
    )


def get_requirement_detail(db: Session, workspace_id: str, requirement_id: str) -> RequirementDetailResponse | None:
    requirement = get_requirement(db, workspace_id, requirement_id)
    if not requirement:
        return None
    links = sorted(requirement.task_links or [], key=lambda item: item.created_at, reverse=True)
    logs = sorted(requirement.audit_logs or [], key=lambda item: item.created_at, reverse=True)
    starts = _activity_times(db, workspace_id, [requirement])
    return RequirementDetailResponse(
        requirement=requirement_summary(requirement, include_linked_tasks=True, include_children=True, starts=starts),
        linked_tasks=[requirement_linked_task(link) for link in links],
        children=[
            requirement_summary(child, include_linked_tasks=True, starts=starts)
            for child in sorted(
                requirement.child_requirements or [],
                key=lambda item: item.created_at or datetime.min,
                reverse=True,
            )
        ],
        audit_logs=[requirement_audit_response(log) for log in logs],
    )
