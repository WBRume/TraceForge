"""Query task records and follower relationships without provisioning resources."""

from typing import Optional, List, Tuple
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import or_, exists
from app.domains.task.models.task import SddTask, SddTaskFollower, TaskStatus
from app.domains.workspace_asset.models.workspace_asset import SddTaskRequirement
from app.domains.task.models.chat import ChatMessage, MessageRole
from app.domains.task.models.pre_input import SddTaskPreInput


def list_tasks(
    db: Session,
    workspace_id: str,
    status_filter: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    task_type: Optional[str] = None,
    relation: Optional[str] = None,
    current_user_id: Optional[str] = None,
    requirement_id: Optional[str] = None,
    independent: bool = False,
    following: bool = False,
) -> Tuple[List[SddTask], int]:
    query = db.query(SddTask).options(
        joinedload(SddTask.creator),
        selectinload(SddTask.requirement_links).selectinload(SddTaskRequirement.requirement),
    ).filter(SddTask.workspace_id == workspace_id)

    linked = exists().where(
        SddTaskRequirement.task_id == SddTask.id,
        SddTaskRequirement.workspace_id == workspace_id,
    )
    if independent:
        query = query.filter(~linked)
    if requirement_id:
        query = query.filter(linked.where(SddTaskRequirement.requirement_id == requirement_id))
    if following:
        query = query.filter(exists().where(
            SddTaskFollower.task_id == SddTask.id,
            SddTaskFollower.workspace_id == workspace_id,
            SddTaskFollower.user_id == str(current_user_id or ""),
        ))

    # 准备中的任务不在任务列表展示：进度由创建人的全局浮窗跟踪，
    # 任务就绪（PENDING）后才会出现在列表中。
    query = query.filter(SddTask.status != TaskStatus.PROVISIONING)

    if status_filter:
        query = query.filter(SddTask.status == status_filter)

    if task_type:
        query = query.filter(SddTask.task_type == task_type)

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
            # Mentions currently originate from the collaboration pre-input JSON.
            # Keep the compatibility read here while the mention relation remains
            # unnormalised in existing databases.
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

    total = query.count()
    items = (
        query.order_by(SddTask.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def list_following_task_ids(
    db: Session,
    workspace_id: str,
    user_id: str,
    task_ids: Optional[List[str]] = None,
) -> set[str]:
    query = db.query(SddTaskFollower.task_id).filter(
        SddTaskFollower.workspace_id == workspace_id,
        SddTaskFollower.user_id == str(user_id),
    )
    if task_ids is not None:
        if not task_ids:
            return set()
        query = query.filter(SddTaskFollower.task_id.in_(task_ids))
    return {str(task_id) for (task_id,) in query.all()}


def get_task(db: Session, task_id: str, workspace_id: str) -> Optional[SddTask]:
    return (
        db.query(SddTask)
        .options(joinedload(SddTask.creator), selectinload(SddTask.requirement_links).selectinload(SddTaskRequirement.requirement))
        .filter(SddTask.id == task_id, SddTask.workspace_id == workspace_id)
        .first()
    )
