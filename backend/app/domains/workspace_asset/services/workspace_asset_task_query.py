from datetime import datetime
from typing import Any, Iterable, List, Optional

from sqlalchemy import exists, func, or_
from sqlalchemy.orm import Session, selectinload

from app.domains.task.models.task import SddTask, SddTaskFollower
from app.domains.task.models.chat import ChatMessage, MessageRole
from app.domains.task.models.pre_input import SddTaskPreInput
from app.domains.workspace_asset.models.workspace_asset import (
    EvidenceStatus,
    HumanReviewStatus,
    SddClarification,
    SddEvidence,
    SddHumanDelta,
    SddHumanReview,
    SddRequirement,
    SddTaskRequirement,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    TaskListSummaryStats,
    WorkspaceAssetsTasksResponse,
)
from app.domains.workspace_asset.services.workspace_asset_service import _task_summary, _enum_value


def _task_sort_key(task: SddTask, sort_by: str) -> Any:
    if sort_by == "name":
        return (task.name or "").lower()
    if sort_by == "status":
        return _enum_value(task.status)
    if sort_by == "current_phase":
        return task.current_phase or ""
    if sort_by == "updated_at":
        return task.updated_at or task.created_at or datetime.min
    if sort_by == "requirement_count":
        return len(task.requirement_links or [])
    if sort_by == "evidence_count":
        return len(task.evidence_items or [])
    return task.created_at or datetime.min


def list_tasks(
    db: Session,
    workspace_id: str,
    *,
    q: Optional[str] = None,
    requirement_q: Optional[str] = None,
    status: Optional[str] = None,
    current_phase: Optional[str] = None,
    relation: Optional[str] = None,
    current_user_id: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 50,
) -> WorkspaceAssetsTasksResponse:
    sort_value = sort_by if sort_by in {
        "created_at",
        "updated_at",
        "name",
        "status",
        "current_phase",
        "requirement_count",
        "evidence_count",
    } else "created_at"
    page_value = max(1, int(page or 1))
    page_size_value = max(1, min(200, int(page_size or 50)))

    query = (
        db.query(SddTask)
        .options(
            selectinload(SddTask.requirement_links),
            selectinload(SddTask.ai_jobs),
            selectinload(SddTask.human_reviews),
            selectinload(SddTask.human_deltas).selectinload(SddHumanDelta.decisions),
            selectinload(SddTask.evidence_items),
            selectinload(SddTask.decisions),
            selectinload(SddTask.clarifications),
        )
        .filter(SddTask.workspace_id == workspace_id)
    )

    search = str(q or "").strip()
    if search or requirement_q:
        query = query.outerjoin(SddTaskRequirement, SddTask.id == SddTaskRequirement.task_id)
        query = query.outerjoin(SddRequirement, SddTaskRequirement.requirement_id == SddRequirement.id)

        filters = []
        if search:
            like = f"%{search}%"
            filters.append(
                or_(
                    SddTask.name.ilike(like),
                    SddTask.description.ilike(like),
                    SddRequirement.title.ilike(like)
                )
            )
        if requirement_q:
            req_like = f"%{str(requirement_q).strip()}%"
            filters.append(SddRequirement.title.ilike(req_like))
        
        for f in filters:
            query = query.filter(f)

    if status:
        query = query.filter(SddTask.status == status)
    if current_phase:
        query = query.filter(SddTask.current_phase == current_phase)

    normalized_relations = {
        value.strip().lower()
        for value in str(relation or "").split(",")
        if value.strip()
    }
    normalized_relations.discard("all")
    actor_id = str(current_user_id or "").strip()
    if normalized_relations and actor_id:
        relation_filters = []
        if "created_by_me" in normalized_relations:
            relation_filters.append(SddTask.creator_id == actor_id)
        if "messaged_by_me" in normalized_relations:
            relation_filters.append(
                exists().where(
                    ChatMessage.task_id == SddTask.id,
                    ChatMessage.workspace_id == workspace_id,
                    ChatMessage.creator_id == actor_id,
                    ChatMessage.role == MessageRole.USER,
                )
            )
        if "followed_by_me" in normalized_relations:
            relation_filters.append(
                exists().where(
                    SddTaskFollower.task_id == SddTask.id,
                    SddTaskFollower.workspace_id == workspace_id,
                    SddTaskFollower.user_id == actor_id,
                )
            )
        if "mentioned_me" in normalized_relations:
            mentioned_task_ids = {
                str(task_id)
                for task_id, mentioned_user_ids in db.query(
                    SddTaskPreInput.task_id,
                    SddTaskPreInput.mentioned_user_ids,
                ).filter(
                    SddTaskPreInput.workspace_id == workspace_id,
                ).all()
                if actor_id in {str(value) for value in (mentioned_user_ids or [])}
            }
            relation_filters.append(SddTask.id.in_(mentioned_task_ids))
        if relation_filters:
            query = query.filter(or_(*relation_filters))

    # Note: query.all() is still fine for in-memory sort if total task rows < 10000, 
    # but grouping/counting for stats is better done via subqueries to be efficient.
    # However, since we load everything anyway for stats calculation based on complex 
    # nested relations, we compute stats in python to ensure exact match with UI status mapping.
    
    tasks = query.all()
    
    # Deduplicate in case outer joins returned multiple identical tasks
    task_map = {t.id: t for t in tasks}
    tasks = list(task_map.values())
    
    reverse = sort_order != "asc"
    tasks = sorted(tasks, key=lambda item: _task_sort_key(item, sort_value), reverse=reverse)
    
    total = len(tasks)
    offset = (page_value - 1) * page_size_value
    page_items = tasks[offset:offset + page_size_value]

    # Calculate summary stats based on ALL filtered tasks (or unfiltered if you prefer, but usually it matches current list view)
    # The requirement specifically mentions calculating the stats for the workspace. 
    # If it's for the whole workspace regardless of filters, we should query DB separately.
    # The wording "汇总功能区当前错位不可用" implies we need the true workspace-wide stats.
    # Let's run separate count queries for the whole workspace.
    
    review_pending_count = (
        db.query(func.count(SddTask.id.distinct()))
        .join(SddHumanReview, SddTask.id == SddHumanReview.task_id)
        .filter(
            SddTask.workspace_id == workspace_id,
            SddHumanReview.status.in_([
                HumanReviewStatus.OPEN,
                HumanReviewStatus.IN_REVIEW,
                HumanReviewStatus.NEED_CLARIFICATION,
                HumanReviewStatus.NEED_EVIDENCE,
                HumanReviewStatus.REJECTED,
                HumanReviewStatus.REOPENED,
            ])
        )
        .scalar() or 0
    )

    clarification_pending_count = (
        db.query(func.count(SddTask.id.distinct()))
        .join(SddClarification, SddTask.id == SddClarification.task_id)
        .filter(
            SddTask.workspace_id == workspace_id,
            SddClarification.status.in_(["OPEN", "ANSWERED", "REJECTED"])
        )
        .scalar() or 0
    )

    human_delta_count = (
        db.query(func.count(SddTask.id.distinct()))
        .join(SddHumanDelta, SddTask.id == SddHumanDelta.task_id)
        .filter(SddTask.workspace_id == workspace_id)
        .scalar() or 0
    )

    # waiting_evidence means there are no confirmed evidence items. 
    # We can calculate this by counting tasks that have requirement_links but no CONFIRMED evidence
    # It's easier to compute using the in-memory tasks if the number is small, but for workspace-wide:
    evidence_missing_count = 0
    workspace_tasks_query = (
        db.query(SddTask)
        .options(
            selectinload(SddTask.requirement_links),
            selectinload(SddTask.evidence_items)
        )
        .filter(SddTask.workspace_id == workspace_id)
    )
    for t in workspace_tasks_query.all():
        if len(t.requirement_links) > 0:
            confirmed = [e for e in t.evidence_items if _enum_value(e.status) == EvidenceStatus.CONFIRMED.value]
            if not confirmed:
                evidence_missing_count += 1

    stats = TaskListSummaryStats(
        review_pending_count=review_pending_count,
        evidence_missing_count=evidence_missing_count,
        human_delta_count=human_delta_count,
        clarification_pending_count=clarification_pending_count,
    )

    following_ids = set()
    if current_user_id and page_items:
        following_ids = {
            str(task_id)
            for (task_id,) in db.query(SddTaskFollower.task_id).filter(
                SddTaskFollower.workspace_id == workspace_id,
                SddTaskFollower.user_id == str(current_user_id),
                SddTaskFollower.task_id.in_([item.id for item in page_items]),
            ).all()
        }

    return WorkspaceAssetsTasksResponse(
        workspace_id=workspace_id,
        items=[_task_summary(db, item, is_following=item.id in following_ids) for item in page_items],
        total=total,
        page=page_value,
        page_size=page_size_value,
        stats=stats,
    )
