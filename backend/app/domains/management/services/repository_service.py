"""
Repository registration service: CRUD and repo-group placement.
"""

import re
from typing import Dict, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.domains.management.models.management import (
    RepositoryType,
    SddManagementProduct,
    SddManagementProductRepo,
    SddManagementProductVersion,
    SddManagementProductVersionRepo,
    SddManagementProject,
    SddManagementProjectRelease,
    SddManagementProjectReleaseRepo,
    SddManagementRepoGroup,
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


def _collect_group_subtree_ids(db: Session, group_id: str) -> List[str]:
    """Return the given group id and all descendant group ids."""
    groups = db.query(SddManagementRepoGroup).all()
    children_by_parent: Dict[str, List[str]] = {}
    for group in groups:
        if group.parent_id:
            children_by_parent.setdefault(group.parent_id, []).append(group.id)

    group_ids: List[str] = [group_id]
    visited = {group_id}
    stack = [group_id]
    while stack:
        parent_id = stack.pop()
        for child_id in children_by_parent.get(parent_id, []):
            if child_id in visited:
                continue
            visited.add(child_id)
            group_ids.append(child_id)
            stack.append(child_id)
    return group_ids


def _normalize_repo_type(value: str) -> RepositoryType:
    normalized = str(value or "OOTB").strip().upper()
    try:
        return RepositoryType(normalized)
    except ValueError as exc:
        raise RepositoryServiceError(
            f"Invalid repo_type '{value}'. Expected OOTB or CUSTOM",
            status_code=400,
        ) from exc


def serialize_repository(repository: SddManagementRepository) -> Dict[str, object]:
    group = repository.group
    return {
        "id": repository.id,
        "name": repository.name,
        "git_url": repository.git_url,
        "repo_type": repository.repo_type.value if hasattr(repository.repo_type, "value") else str(repository.repo_type),
        "default_branch": repository.default_branch,
        "group_id": repository.group_id,
        "group_name": group.name if group else None,
        "description": repository.description,
        "created_at": repository.created_at,
        "updated_at": repository.updated_at,
    }


def list_repositories(
    db: Session,
    *,
    keyword: Optional[str] = None,
    repo_type: Optional[str] = None,
    group_id: Optional[str] = None,
    repository_id: Optional[str] = None,
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
    if group_id:
        group_ids = _collect_group_subtree_ids(db, group_id)
        query = query.filter(SddManagementRepository.group_id.in_(group_ids))
    if repository_id:
        query = query.filter(SddManagementRepository.id == repository_id)

    total = query.count()
    repositories = (
        query.order_by(SddManagementRepository.created_at.desc())
        .offset((max(1, page) - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [serialize_repository(repo) for repo in repositories], total


def get_repository(db: Session, repository_id: str) -> Optional[SddManagementRepository]:
    return db.query(SddManagementRepository).filter(SddManagementRepository.id == repository_id).first()


def create_repository(
    db: Session,
    *,
    name: str,
    git_url: str,
    repo_type: str,
    default_branch: str = "main",
    group_id: Optional[str] = None,
    description: Optional[str] = None,
    creator_id: Optional[str] = None,
) -> SddManagementRepository:
    normalized_name = str(name or "").strip()
    normalized_url = str(git_url or "").strip()
    if not normalized_name:
        raise RepositoryServiceError("Repository name is required", status_code=400)
    if not normalized_url:
        raise RepositoryServiceError("git_url is required", status_code=400)

    normalized_group_id = str(group_id or "").strip()
    group = (
        db.query(SddManagementRepoGroup)
        .filter(SddManagementRepoGroup.id == normalized_group_id)
        .first()
    )
    if not group:
        raise RepositoryServiceError(
            "group_id is required and must reference an existing repository group",
            status_code=400,
        )

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
        group_id=group.id,
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
    group_id: Optional[str] = None,
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
    if group_id is not None:
        if not group_id:
            raise RepositoryServiceError(
                "group_id cannot be empty; every repository must belong to a group",
                status_code=400,
            )
        group = (
            db.query(SddManagementRepoGroup)
            .filter(SddManagementRepoGroup.id == group_id)
            .first()
        )
        if not group:
            raise RepositoryServiceError("Repository group not found", status_code=404)
        repository.group_id = group.id
    if description is not None:
        repository.description = description
    db.commit()
    db.refresh(repository)
    return repository


def _repository_reference_lines(
    db: Session,
    repository: SddManagementRepository,
) -> List[str]:
    """Return human-readable references to a repository from products/projects."""
    lines: List[str] = []

    base_refs = (
        db.query(SddManagementProductRepo, SddManagementProduct)
        .join(SddManagementProduct, SddManagementProduct.id == SddManagementProductRepo.product_id)
        .filter(SddManagementProductRepo.repository_id == repository.id)
        .all()
    )
    for _, product in base_refs:
        lines.append(f"product '{product.name}' base repositories")

    product_refs = (
        db.query(
            SddManagementProductVersionRepo,
            SddManagementProductVersion,
            SddManagementProduct,
        )
        .join(
            SddManagementProductVersion,
            SddManagementProductVersion.id == SddManagementProductVersionRepo.product_version_id,
        )
        .join(
            SddManagementProduct,
            SddManagementProduct.id == SddManagementProductVersion.product_id,
        )
        .filter(SddManagementProductVersionRepo.repository_id == repository.id)
        .all()
    )
    for _, version, product in product_refs:
        lines.append(f"product '{product.name}' version '{version.version_no}'")

    project_refs = (
        db.query(
            SddManagementProjectReleaseRepo,
            SddManagementProjectRelease,
            SddManagementProject,
        )
        .join(
            SddManagementProjectRelease,
            SddManagementProjectRelease.id == SddManagementProjectReleaseRepo.release_id,
        )
        .join(
            SddManagementProject,
            SddManagementProject.id == SddManagementProjectRelease.project_id,
        )
        .filter(SddManagementProjectReleaseRepo.repository_id == repository.id)
        .all()
    )
    for _, release, project in project_refs:
        lines.append(f"project '{project.name}' release '{release.release_no}'")

    return lines


def delete_repository(db: Session, repository: SddManagementRepository) -> None:
    references = _repository_reference_lines(db, repository)
    if references:
        raise RepositoryServiceError(
            "Cannot delete repository '{name}' because it is still referenced by: {refs}".format(
                name=repository.name,
                refs="; ".join(references),
            ),
            status_code=409,
        )
    db.delete(repository)
    db.commit()


def move_repository_to_group(
    db: Session,
    repository: SddManagementRepository,
    group_id: Optional[str],
) -> SddManagementRepository:
    normalized_group_id = str(group_id or "").strip()
    if not normalized_group_id:
        raise RepositoryServiceError(
            "group_id is required; every repository must belong to a group",
            status_code=400,
        )
    group = db.query(SddManagementRepoGroup).filter(SddManagementRepoGroup.id == normalized_group_id).first()
    if not group:
        raise RepositoryServiceError("Repository group not found", status_code=404)
    repository.group_id = group.id
    db.commit()
    db.refresh(repository)
    return repository


def validate_repository_access(db: Session, git_url: str) -> Dict[str, object]:
    payload = git_ref_service.list_refs_for_picker(git_url)
    payload["branch_count"] = len(payload["branches"])
    payload["tag_count"] = len(payload["tags"])
    return payload


def validate_repository_ref(
    db: Session,
    repository: SddManagementRepository,
    ref_type: str,
    ref_name: str,
) -> Dict[str, object]:
    git_ref_service.validate_ref_exists(repository.git_url, ref_type, ref_name)
    return {"repository_id": repository.id, "ref_type": str(ref_type).upper(), "ref_name": ref_name, "exists": True}


__all__ = [
    "RepositoryServiceError",
    "build_repo_slug",
    "list_repositories",
    "get_repository",
    "create_repository",
    "update_repository",
    "delete_repository",
    "serialize_repository",
    "move_repository_to_group",
    "validate_repository_access",
    "validate_repository_ref",
]
