"""
Repository group service: a plain tree grouping repositories.
"""

from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.domains.management.models.management import (
    SddManagementRepoGroup,
    SddManagementRepository,
)


class RepoGroupServiceError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def get_group(db: Session, group_id: str) -> Optional[SddManagementRepoGroup]:
    return db.query(SddManagementRepoGroup).filter(SddManagementRepoGroup.id == group_id).first()


def create_group(
    db: Session,
    *,
    name: str,
    parent_id: Optional[str] = None,
    order_index: int = 0,
) -> SddManagementRepoGroup:
    normalized_name = str(name or "").strip()
    if not normalized_name:
        raise RepoGroupServiceError("Group name is required", status_code=400)
    if parent_id:
        parent = get_group(db, parent_id)
        if not parent:
            raise RepoGroupServiceError("Parent group not found", status_code=404)
    group = SddManagementRepoGroup(
        name=normalized_name,
        parent_id=parent_id or None,
        order_index=int(order_index or 0),
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def update_group(
    db: Session,
    group: SddManagementRepoGroup,
    *,
    name: Optional[str] = None,
    parent_id: Optional[str] = None,
    order_index: Optional[int] = None,
) -> SddManagementRepoGroup:
    if name is not None:
        normalized_name = str(name).strip()
        if not normalized_name:
            raise RepoGroupServiceError("Group name is required", status_code=400)
        group.name = normalized_name
    if parent_id is not None and parent_id != group.parent_id:
        if parent_id == group.id:
            raise RepoGroupServiceError("A group cannot be its own parent", status_code=409)
        if parent_id:
            parent = get_group(db, parent_id)
            if not parent:
                raise RepoGroupServiceError("Parent group not found", status_code=404)
            # Prevent cycles: parent cannot be a descendant of this group.
            cursor = parent
            seen = {group.id}
            while cursor and cursor.id not in seen:
                seen.add(cursor.id)
                cursor = cursor.parent
            if cursor is not None:
                raise RepoGroupServiceError("Cannot move a group under its own descendant", status_code=409)
        group.parent_id = parent_id
    if order_index is not None:
        group.order_index = int(order_index)
    db.commit()
    db.refresh(group)
    return group


def delete_group(db: Session, group: SddManagementRepoGroup) -> None:
    repo_count = (
        db.query(SddManagementRepository)
        .filter(SddManagementRepository.group_id == group.id)
        .count()
    )
    child_count = (
        db.query(SddManagementRepoGroup)
        .filter(SddManagementRepoGroup.parent_id == group.id)
        .count()
    )
    if repo_count > 0 or child_count > 0:
        raise RepoGroupServiceError(
            "Cannot delete a group that still contains repositories or subgroups",
            status_code=409,
        )
    db.delete(group)
    db.commit()


def build_repo_group_tree(db: Session) -> List[Dict[str, object]]:
    groups = (
        db.query(SddManagementRepoGroup)
        .order_by(SddManagementRepoGroup.order_index.asc(), SddManagementRepoGroup.name.asc())
        .all()
    )
    repos = db.query(SddManagementRepository).order_by(SddManagementRepository.name.asc()).all()
    repos_by_group: Dict[str, List[Dict[str, object]]] = {}
    for repo in repos:
        key = str(repo.group_id or "")
        repos_by_group.setdefault(key, []).append(
            {
                "id": repo.id,
                "name": repo.name,
                "git_url": repo.git_url,
                "repo_type": repo.repo_type.value if hasattr(repo.repo_type, "value") else str(repo.repo_type),
            }
        )

    payloads_by_id: Dict[str, Dict[str, object]] = {}
    roots: List[Dict[str, object]] = []
    for group in groups:
        payload = {
            "id": group.id,
            "parent_id": group.parent_id,
            "name": group.name,
            "order_index": group.order_index,
            "repositories": repos_by_group.get(group.id, []),
            "children": [],
        }
        payloads_by_id[group.id] = payload
        if not group.parent_id:
            roots.append(payload)

    for group in groups:
        if group.parent_id and group.parent_id in payloads_by_id:
            payloads_by_id[group.parent_id]["children"].append(payloads_by_id[group.id])

    return roots


__all__ = [
    "RepoGroupServiceError",
    "get_group",
    "create_group",
    "update_group",
    "delete_group",
    "build_repo_group_tree",
]
