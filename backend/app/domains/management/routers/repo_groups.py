"""
Repository group API routes (plain tree grouping repositories).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.logging import audit_log
from app.dependencies import get_current_user, get_db, require_admin
from app.domains.auth.models.user import User
from app.domains.management.schemas.management import (
    RepoGroupCreate,
    RepoGroupUpdate,
    RepoMoveRequest,
)
from app.domains.management.services import repo_group_service, repository_service

router = APIRouter(prefix="/management/repo-groups", tags=["Management Repo Groups"])


@router.get("/tree")
def get_repo_group_tree(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"items": repo_group_service.build_repo_group_tree(db)}


@router.post("", status_code=201)
def create_repo_group(
    data: RepoGroupCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        group = repo_group_service.create_group(
            db,
            name=data.name,
            parent_id=data.parent_id,
            order_index=data.order_index,
        )
        audit_log(
            action="create_repo_group",
            outcome="success",
            resource_type="repo_group",
            resource_id=group.id,
            user_id=current_user.id,
        )
        return {
            "id": group.id,
            "parent_id": group.parent_id,
            "name": group.name,
            "order_index": group.order_index,
        }
    except repo_group_service.RepoGroupServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.put("/{group_id}")
def update_repo_group(
    group_id: str,
    data: RepoGroupUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    group = repo_group_service.get_group(db, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Repository group not found")
    try:
        updated = repo_group_service.update_group(
            db,
            group,
            name=data.name,
            parent_id=data.parent_id,
            order_index=data.order_index,
        )
        return {
            "id": updated.id,
            "parent_id": updated.parent_id,
            "name": updated.name,
            "order_index": updated.order_index,
        }
    except repo_group_service.RepoGroupServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.delete("/{group_id}")
def delete_repo_group(
    group_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    group = repo_group_service.get_group(db, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Repository group not found")
    try:
        repo_group_service.delete_group(db, group)
        return {"msg": "Repository group deleted"}
    except repo_group_service.RepoGroupServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/repositories/{repository_id}/move")
def move_repository_to_group(
    repository_id: str,
    data: RepoMoveRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    repository = repository_service.get_repository(db, repository_id)
    if not repository:
        raise HTTPException(status_code=404, detail="Repository not found")
    try:
        updated = repository_service.move_repository_to_group(db, repository, data.group_id)
        return repository_service.serialize_repository(updated)
    except repository_service.RepositoryServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
