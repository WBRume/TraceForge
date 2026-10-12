"""Expose immutable local handoffs as task human changes without rescanning Git."""

from sqlalchemy.orm import Session

from app.domains.auth.models.user import User
from app.domains.task.models.task_repository import SddTaskRepository
from app.domains.workspace_asset.models.workspace_asset import HumanDeltaStatus, SddHumanDelta

from .models import CollaborationHandoff


def record_delta(db: Session, task, handoff: CollaborationHandoff) -> None:
    # The handoff and its task-detail index commit together. File bytes stay in
    # the immutable object store and are fetched only when a file is opened.
    db.add(
        SddHumanDelta(
            workspace_id=task.workspace_id,
            task_id=task.id,
            created_by_id=handoff.actor_user_id,
            collaboration_handoff_id=handoff.id,
            status=HumanDeltaStatus.READY,
            changed_files_count=sum(len(repo["files"]) for repo in handoff.repository_deltas_json),
            change_category="LOCAL_COLLABORATION",
        )
    )


def list_changes(db: Session, task_id: str, page: int, page_size: int) -> dict:
    query = db.query(CollaborationHandoff).filter_by(task_id=task_id)
    total = query.count()
    # Sort only small IDs, not the potentially large JSON change manifests.
    ids = [
        row.id
        for row in query.with_entities(CollaborationHandoff.id)
        .order_by(CollaborationHandoff.created_at.desc(), CollaborationHandoff.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ]
    rows = {row.id: row for row in query.filter(CollaborationHandoff.id.in_(ids))} if ids else {}
    users = dict(db.query(User.id, User.display_name).filter(User.id.in_({row.actor_user_id for row in rows.values()})))
    delta_ids = dict(
        db.query(SddHumanDelta.collaboration_handoff_id, SddHumanDelta.id).filter(
            SddHumanDelta.task_id == task_id, SddHumanDelta.collaboration_handoff_id.in_(ids)
        )
    )
    items = []
    for identity in ids:
        row = rows[identity]
        items.append(
            {
                "id": row.id,
                "delta_id": delta_ids.get(row.id),
                "actor_name": users.get(row.actor_user_id),
                "submission_id": row.submission_id,
                "created_at": row.created_at.isoformat(),
                "changed_files_count": sum(len(repo["files"]) for repo in row.repository_deltas_json),
                "repository_count": len(row.repository_deltas_json),
            }
        )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def change_detail(db: Session, task_id: str, handoff_id: str) -> dict:
    from .service import CollaborationError

    row = db.query(CollaborationHandoff).filter_by(task_id=task_id, id=handoff_id).first()
    if row is None:
        raise CollaborationError("HANDOFF_NOT_FOUND", "Local change record not found", 404)
    repositories = {repo.id: repo for repo in db.query(SddTaskRepository).filter_by(task_id=task_id)}
    files = []
    for changed_repo in row.repository_deltas_json:
        repo_id = changed_repo["task_repository_id"]
        repo = repositories.get(repo_id)
        for entry in changed_repo["files"]:
            files.append(
                {
                    **entry,
                    "task_repository_id": repo_id,
                    "repo_slug": changed_repo.get("repo_slug") or (repo.repo_slug if repo else repo_id),
                    "branch_name": changed_repo.get("branch_name") or (repo.branch_name if repo else ""),
                }
            )
    return {
        "id": row.id,
        "base_snapshot_id": row.base_snapshot_id,
        "input_snapshot_id": row.input_snapshot_id,
        "created_at": row.created_at.isoformat(),
        "files": files,
    }
