from typing import Any, Dict, List, Optional

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.domains.asset.models.asset import AssetType, SddAsset
from app.domains.task.models.task import SddPlanNode, SddTask, SddTaskFollower
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


def _task_count_subqueries() -> Dict[str, Any]:
    """requirement_count / evidence_count 的相关标量子查询，供 SQL 排序使用。"""
    requirement_count = (
        select(func.count(SddTaskRequirement.id))
        .where(SddTaskRequirement.task_id == SddTask.id)
        .correlate(SddTask)
        .scalar_subquery()
    )
    evidence_count = (
        select(func.count(SddEvidence.id))
        .where(SddEvidence.task_id == SddTask.id)
        .correlate(SddTask)
        .scalar_subquery()
    )
    return {"requirement_count": requirement_count, "evidence_count": evidence_count}


def _task_sort_expressions(sort_by: str) -> List[Any]:
    """排序白名单 -> SQL 表达式（与旧内存排序键等价）。"""
    count_sq = _task_count_subqueries()
    if sort_by == "name":
        return [func.lower(SddTask.name)]
    if sort_by == "status":
        return [SddTask.status]
    if sort_by == "current_phase":
        return [func.coalesce(SddTask.current_phase, "")]
    if sort_by == "updated_at":
        return [func.coalesce(SddTask.updated_at, SddTask.created_at)]
    if sort_by == "requirement_count":
        return [count_sq["requirement_count"]]
    if sort_by == "evidence_count":
        return [count_sq["evidence_count"]]
    return [SddTask.created_at]


def _requirement_title_exists(pattern: str):
    return exists().where(
        SddTaskRequirement.task_id == SddTask.id,
        SddTaskRequirement.requirement_id == SddRequirement.id,
        SddRequirement.title.ilike(pattern),
    )


def _load_page_items(db: Session, page_ids: List[str]) -> List[SddTask]:
    """按当前页 id 加载完整实体（含列表卡片所需的全部关联）。"""
    loaded = (
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
        .filter(SddTask.id.in_(page_ids))
        .all()
    )
    by_id = {task.id: task for task in loaded}
    return [by_id[task_id] for task_id in page_ids if task_id in by_id]


def _page_asset_counts(
    db: Session,
    workspace_id: str,
    page_ids: List[str],
) -> tuple:
    """当前页任务的 spec / plan 资产与 plan 节点计数，2 条 GROUP BY 汇总。"""
    spec_counts: Dict[str, int] = {}
    plan_asset_counts: Dict[str, int] = {}
    plan_node_counts: Dict[str, int] = {}
    if not page_ids:
        return spec_counts, plan_asset_counts, plan_node_counts

    asset_count_rows = (
        db.query(SddAsset.task_id, SddAsset.asset_type, func.count(SddAsset.id))
        .filter(
            SddAsset.workspace_id == workspace_id,
            SddAsset.task_id.in_(page_ids),
            SddAsset.asset_type.in_([AssetType.SPEC, AssetType.PLAN]),
        )
        .group_by(SddAsset.task_id, SddAsset.asset_type)
        .all()
    )
    for row_task_id, row_asset_type, row_count in asset_count_rows:
        type_value = _enum_value(row_asset_type)
        if type_value == AssetType.SPEC.value:
            spec_counts[str(row_task_id)] = int(row_count)
        elif type_value == AssetType.PLAN.value:
            plan_asset_counts[str(row_task_id)] = int(row_count)

    plan_node_rows = (
        db.query(SddPlanNode.task_id, func.count(SddPlanNode.id))
        .filter(
            SddPlanNode.workspace_id == workspace_id,
            SddPlanNode.task_id.in_(page_ids),
        )
        .group_by(SddPlanNode.task_id)
        .all()
    )
    plan_node_counts = {str(row[0]): int(row[1]) for row in plan_node_rows}
    return spec_counts, plan_asset_counts, plan_node_counts


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

    # 过滤查询只负责筛 id；实体加载（selectinload）推迟到拿到分页 id 之后，
    # 避免为排序/分页把整个 workspace 的任务和关联全量拉进内存。
    query = db.query(SddTask).filter(SddTask.workspace_id == workspace_id)

    # 搜索用 EXISTS 子查询而非 outerjoin，避免关联行膨胀，也无需再去重。
    search = str(q or "").strip()
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                SddTask.name.ilike(like),
                SddTask.description.ilike(like),
                _requirement_title_exists(like),
            )
        )
    if requirement_q:
        req_like = f"%{str(requirement_q).strip()}%"
        query = query.filter(_requirement_title_exists(req_like))

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

    # 排序与分页下推 SQL，只取当前页的任务 id。
    reverse = sort_order != "asc"
    order_by = [
        expr.desc() if reverse else expr.asc()
        for expr in _task_sort_expressions(sort_value)
    ]
    order_by.append(SddTask.id.desc() if reverse else SddTask.id.asc())

    total = query.with_entities(func.count(SddTask.id)).scalar() or 0
    offset = (page_value - 1) * page_size_value
    page_ids = [
        row[0]
        for row in query.with_entities(SddTask.id)
        .order_by(*order_by)
        .offset(offset)
        .limit(page_size_value)
        .all()
    ]
    page_items = _load_page_items(db, page_ids) if page_ids else []

    # 汇总统计均为独立 count/EXISTS 查询，覆盖整个 workspace（不受列表过滤影响）。
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

    # “待补证据”= 有需求关联但没有任何已确认证据的任务数；
    # 用 EXISTS / NOT EXISTS 下推 SQL，替代原来的全量加载 + Python 循环。
    evidence_missing_count = (
        db.query(func.count(SddTask.id))
        .filter(
            SddTask.workspace_id == workspace_id,
            exists().where(SddTaskRequirement.task_id == SddTask.id),
            ~exists().where(
                SddEvidence.task_id == SddTask.id,
                SddEvidence.status == EvidenceStatus.CONFIRMED,
            ),
        )
        .scalar() or 0
    )

    stats = TaskListSummaryStats(
        review_pending_count=review_pending_count,
        evidence_missing_count=evidence_missing_count,
        human_delta_count=human_delta_count,
        clarification_pending_count=clarification_pending_count,
    )

    following_ids = set()
    if current_user_id and page_ids:
        following_ids = {
            str(task_id)
            for (task_id,) in db.query(SddTaskFollower.task_id).filter(
                SddTaskFollower.workspace_id == workspace_id,
                SddTaskFollower.user_id == str(current_user_id),
                SddTaskFollower.task_id.in_(page_ids),
            ).all()
        }

    spec_counts, plan_asset_counts, plan_node_counts = _page_asset_counts(
        db, workspace_id, page_ids
    )

    return WorkspaceAssetsTasksResponse(
        workspace_id=workspace_id,
        items=[
            _task_summary(
                db,
                item,
                is_following=item.id in following_ids,
                counts={
                    "spec_count": spec_counts.get(item.id, 0),
                    "plan_asset_count": plan_asset_counts.get(item.id, 0),
                    "plan_node_count": plan_node_counts.get(item.id, 0),
                },
            )
            for item in page_items
        ],
        total=total,
        page=page_value,
        page_size=page_size_value,
        stats=stats,
    )
