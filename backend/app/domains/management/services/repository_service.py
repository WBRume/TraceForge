"""
Repository registration service: CRUD, org-tree placement, git ref sync/validation.
"""

import re
from typing import Dict, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.domains.management.models.management import (
    RepositoryType,
    SddManagementRepoRef,
    SddManagementRepository,
)
from app.domains.management.services import git_ref_service


class RepositoryServiceError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


_SLUG_PATTERN = re.compile(r"[^a-z0-9-]+")


def build_repo_slug(name: str) -> str:
    normalized = _SLUG_PATTERN.sub("-", str(name or "").strip().lower()).strip("-")
    return normalized[:120] or "repo"


def _normalize_repo_type(value: str) -> RepositoryType:
    normalized = str(value or "OOTB").strip().upper()
    try:
        return RepositoryType(normalized)
    except ValueError as exc:
        raise RepositoryServiceError(
            f"Invalid repo_type '{value}'. Expected OOTB or CUSTOM",
            status_code=400,
        ) from exc


def serialize_repository(
    repository: SddManagementRepository,
    *,
    ref_counts: Optional[Dict[str, int]] = None,
) -> Dict[str, object]:
    counts = ref_counts or {}
    return {
        "id": repository.id,
        "name": repository.name,
        "git_url": repository.git_url,
        "repo_type": repository.repo_type.value if hasattr(repository.repo_type, "value") else str(repository.repo_type),
        "default_branch": repository.default_branch,
        "org_node_id": repository.org_node_id,
        "description": repository.description,
        "last_synced_at": repository.last_synced_at,
        "branch_count": int(counts.get("BRANCH", 0)),
        "tag_count": int(counts.get("TAG", 0)),
        "created_at": repository.created_at,
        "updated_at": repository.updated_at,
    }


def _ref_counts_for(db: Session, repository_ids: List[str]) -> Dict[str, Dict[str, int]]:
    counts: Dict[str, Dict[str, int]] = {repo_id: {"BRANCH": 0, "TAG": 0} for repo_id in repository_ids}
    if not repository_ids:
        return counts
    rows = (
        db.query(SddManagementRepoRef.repository_id, SddManagementRepoRef.ref_type)
        .filter(SddManagementRepoRef.repository_id.in_(repository_ids))
        .all()
    )
    for repository_id, ref_type in rows:
        type_value = ref_type.value if hasattr(ref_type, "value") else str(ref_type)
        bucket = counts.setdefault(repository_id, {"BRANCH": 0, "TAG": 0})
        bucket[type_value] = bucket.get(type_value, 0) + 1
    return counts


def list_repositories(
    db: Session,
    *,
    keyword: Optional[str] = None,
    repo_type: Optional[str] = None,
    org_node_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[Dict[str, object]], int]:
    query = db.query(SddManagementRepository)
    normalized_keyword = str(keyword or "").strip()
    if normalized_keyword:
        pattern = f"%{normalized_keyword}%"
        query = query.filter(
            or_(
                SddManagementRepository.name.ilike(pattern),
                SddManagementRepository.git_url.ilike(pattern),
            )
        )
    if repo_type:
        query = query.filter(SddManagementRepository.repo_type == _normalize_repo_type(repo_type))
    if org_node_id:
        query = query.filter(SddManagementRepository.org_node_id == org_node_id)

    total = query.count()
    repositories = (
        query.order_by(SddManagementRepository.created_at.desc())
        .offset((max(1, page) - 1) * page_size)
        .limit(page_size)
        .all()
    )
    counts = _ref_counts_for(db, [repo.id for repo in repositories])
    items = [serialize_repository(repo, ref_counts=counts.get(repo.id)) for repo in repositories]
    return items, total


def get_repository(db: Session, repository_id: str) -> Optional[SddManagementRepository]:
    return db.query(SddManagementRepository).filter(SddManagementRepository.id == repository_id).first()


def create_repository(
    db: Session,
    *,
    name: str,
    git_url: str,
    repo_type: str,
    default_branch: str = "main",
    org_node_id: Optional[str] = None,
    description: Optional[str] = None,
    creator_id: Optional[str] = None,
) -> SddManagementRepository:
    normalized_name = str(name or "").strip()
    normalized_url = str(git_url or "").strip()
    if not normalized_name:
        raise RepositoryServiceError("Repository name is required", status_code=400)
    if not normalized_url:
        raise RepositoryServiceError("git_url is required", status_code=400)

    existing = (
        db.query(SddManagementRepository)
        .filter(SddManagementRepository.git_url == normalized_url)
        .first()
    )
    if existing:
        raise RepositoryServiceError("A repository with this git_url already exists", status_code=409)

    repository = SddManagementRepository(
        name=normalized_name,
        git_url=normalized_url,
        repo_type=_normalize_repo_type(repo_type),
        default_branch=(str(default_branch or "").strip() or "main"),
        org_node_id=org_node_id or None,
        description=description,
        created_by=creator_id,
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


def update_repository(
    db: Session,
    repository: SddManagementRepository,
    *,
    name: Optional[str] = None,
    git_url: Optional[str] = None,
    repo_type: Optional[str] = None,
    default_branch: Optional[str] = None,
    org_node_id: Optional[str] = None,
    description: Optional[str] = None,
) -> SddManagementRepository:
    if name is not None:
        normalized_name = str(name).strip()
        if not normalized_name:
            raise RepositoryServiceError("Repository name is required", status_code=400)
        repository.name = normalized_name
    if git_url is not None:
        normalized_url = str(git_url).strip()
        if not normalized_url:
            raise RepositoryServiceError("git_url is required", status_code=400)
        existing = (
            db.query(SddManagementRepository)
            .filter(
                SddManagementRepository.git_url == normalized_url,
                SddManagementRepository.id != repository.id,
            )
            .first()
        )
        if existing:
            raise RepositoryServiceError("A repository with this git_url already exists", status_code=409)
        repository.git_url = normalized_url
    if repo_type is not None:
        repository.repo_type = _normalize_repo_type(repo_type)
    if default_branch is not None:
        repository.default_branch = str(default_branch).strip() or repository.default_branch
    if org_node_id is not None:
        repository.org_node_id = org_node_id or None
    if description is not None:
        repository.description = description
    db.commit()
    db.refresh(repository)
    return repository


def delete_repository(db: Session, repository: SddManagementRepository) -> None:
    # Repository deletion cascades refs and version bindings; workspace/task
    # snapshots keep denormalized copies via SET NULL foreign keys.
    db.delete(repository)
    db.commit()


def sync_repository_refs(db: Session, repository: SddManagementRepository) -> Dict[str, object]:
    count = git_ref_service.sync_repository_refs(db, repository)
    from datetime import datetime

    repository.last_synced_at = datetime.utcnow()
    db.commit()
    db.refresh(repository)
    return {"repository_id": repository.id, "ref_count": int(count), "last_synced_at": repository.last_synced_at}


def validate_repository_access(db: Session, git_url: str) -> Dict[str, object]:
    refs = git_ref_service.fetch_remote_refs(git_url)
    branches = sorted({name for ref_type, name, _sha in refs if ref_type == "BRANCH"})
    tags = sorted({name for ref_type, name, _sha in refs if ref_type == "TAG"})
    return {
        "git_url": git_url,
        "accessible": True,
        "branch_count": len(branches),
        "tag_count": len(tags),
        "branches": branches[:200],
        "tags": tags[:200],
    }


def validate_repository_branch(db: Session, repository: SddManagementRepository, branch_name: str) -> Dict[str, object]:
    git_ref_service.validate_branch_exists(repository.git_url, branch_name)
    return {"repository_id": repository.id, "branch_name": branch_name, "exists": True}


__all__ = [
    "RepositoryServiceError",
    "build_repo_slug",
    "list_repositories",
    "get_repository",
    "create_repository",
    "update_repository",
    "delete_repository",
    "serialize_repository",
    "sync_repository_refs",
    "validate_repository_access",
    "validate_repository_branch",
]
