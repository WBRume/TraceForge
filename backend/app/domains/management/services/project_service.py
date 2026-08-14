"""
Project management service: projects, delivery lifecycle state machine,
release records and product/repository associations.
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.core.logging import audit_log
from app.domains.management.models.management import (
    ProjectLifecycleStatus,
    ReleaseRepoKind,
    ReleaseStatus,
    SddManagementProduct,
    SddManagementProductVersion,
    SddManagementProject,
    SddManagementProjectProductDep,
    SddManagementProjectRelease,
    SddManagementProjectReleaseRepo,
    SddManagementProjectRepo,
    SddManagementRepository,
)
from app.domains.management.services import git_ref_service


class ProjectServiceError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# Delivery lifecycle state machine: strictly forward transitions.
LIFECYCLE_TRANSITIONS: Dict[ProjectLifecycleStatus, ProjectLifecycleStatus] = {
    ProjectLifecycleStatus.INITIATED: ProjectLifecycleStatus.DEVELOPING,
    ProjectLifecycleStatus.DEVELOPING: ProjectLifecycleStatus.DELIVERING,
    ProjectLifecycleStatus.DELIVERING: ProjectLifecycleStatus.MAINTAINING,
    ProjectLifecycleStatus.MAINTAINING: ProjectLifecycleStatus.RETIRED,
}


def _normalize_lifecycle(value: str) -> ProjectLifecycleStatus:
    normalized = str(value or "").strip().upper()
    try:
        return ProjectLifecycleStatus(normalized)
    except ValueError as exc:
        raise ProjectServiceError(f"Invalid lifecycle status '{value}'", status_code=400) from exc


def _normalize_release_status(value: str) -> ReleaseStatus:
    normalized = str(value or "").strip().upper()
    try:
        return ReleaseStatus(normalized)
    except ValueError as exc:
        raise ProjectServiceError(f"Invalid release status '{value}'", status_code=400) from exc


def _value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def next_lifecycle_status(current: ProjectLifecycleStatus) -> Optional[ProjectLifecycleStatus]:
    return LIFECYCLE_TRANSITIONS.get(current)


def serialize_project(project: SddManagementProject) -> Dict[str, object]:
    return {
        "id": project.id,
        "name": project.name,
        "code": project.code,
        "customer": project.customer,
        "organization": project.organization,
        "lifecycle_status": _value(project.lifecycle_status),
        "description": project.description,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def list_projects(
    db: Session,
    *,
    keyword: Optional[str] = None,
    lifecycle_status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[Dict[str, object]], int]:
    query = db.query(SddManagementProject)
    normalized_keyword = str(keyword or "").strip()
    if normalized_keyword:
        pattern = f"%{normalized_keyword}%"
        query = query.filter(
            or_(
                SddManagementProject.name.ilike(pattern),
                SddManagementProject.code.ilike(pattern),
                SddManagementProject.customer.ilike(pattern),
                SddManagementProject.organization.ilike(pattern),
            )
        )
    if lifecycle_status:
        query = query.filter(
            SddManagementProject.lifecycle_status == _normalize_lifecycle(lifecycle_status)
        )

    total = query.count()
    projects = (
        query.order_by(SddManagementProject.created_at.desc())
        .offset((max(1, page) - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [serialize_project(project) for project in projects], total


def get_project(db: Session, project_id: str) -> Optional[SddManagementProject]:
    return (
        db.query(SddManagementProject)
        .options(
            joinedload(SddManagementProject.releases).joinedload(SddManagementProjectRelease.repos),
            joinedload(SddManagementProject.product_deps),
            joinedload(SddManagementProject.repo_associations),
        )
        .filter(SddManagementProject.id == project_id)
        .first()
    )


def serialize_release(release: SddManagementProjectRelease) -> Dict[str, object]:
    product = release.product
    version = release.product_version
    return {
        "id": release.id,
        "project_id": release.project_id,
        "release_no": release.release_no,
        "name": release.name,
        "product_id": release.product_id,
        "product_name": product.name if product else None,
        "product_version_id": release.product_version_id,
        "product_version_no": version.version_no if version else None,
        "status": _value(release.status),
        "release_date": release.release_date,
        "notes": release.notes,
        "created_at": release.created_at,
        "repos": [
            {
                "id": repo.id,
                "repository_id": repo.repository_id,
                "repository_name": repo.repository.name if repo.repository else None,
                "git_url": repo.repository.git_url if repo.repository else None,
                "branch_name": repo.branch_name,
                "repo_kind": _value(repo.repo_kind),
            }
            for repo in release.repos
        ],
    }


def serialize_project_detail(project: SddManagementProject) -> Dict[str, object]:
    payload = serialize_project(project)
    payload["releases"] = [serialize_release(release) for release in project.releases]
    payload["product_deps"] = [
        {
            "id": dep.id,
            "product_id": dep.product_id,
            "product_name": dep.product.name if dep.product else None,
            "product_version_id": dep.product_version_id,
            "product_version_no": dep.product_version.version_no if dep.product_version else None,
        }
        for dep in project.product_deps
    ]
    payload["repo_associations"] = [
        {
            "id": assoc.id,
            "repository_id": assoc.repository_id,
            "repository_name": assoc.repository.name if assoc.repository else None,
            "git_url": assoc.repository.git_url if assoc.repository else None,
            "repo_type": _value(assoc.repository.repo_type) if assoc.repository and hasattr(assoc.repository.repo_type, "value") else None,
            "branch_name": assoc.branch_name,
        }
        for assoc in project.repo_associations
    ]
    return payload


def create_project(
    db: Session,
    *,
    name: str,
    code: str,
    customer: Optional[str] = None,
    organization: Optional[str] = None,
    description: Optional[str] = None,
    creator_id: Optional[str] = None,
) -> SddManagementProject:
    normalized_name = str(name or "").strip()
    normalized_code = str(code or "").strip()
    if not normalized_name or not normalized_code:
        raise ProjectServiceError("Project name and code are required", status_code=400)
    existing = db.query(SddManagementProject).filter(SddManagementProject.code == normalized_code).first()
    if existing:
        raise ProjectServiceError("A project with this code already exists", status_code=409)
    project = SddManagementProject(
        name=normalized_name,
        code=normalized_code,
        customer=(str(customer or "").strip() or None),
        organization=(str(organization or "").strip() or None),
        description=description,
        created_by=creator_id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def update_project(
    db: Session,
    project: SddManagementProject,
    *,
    name: Optional[str] = None,
    code: Optional[str] = None,
    customer: Optional[str] = None,
    organization: Optional[str] = None,
    description: Optional[str] = None,
) -> SddManagementProject:
    if name is not None:
        project.name = str(name).strip() or project.name
    if code is not None:
        normalized_code = str(code).strip()
        existing = (
            db.query(SddManagementProject)
            .filter(SddManagementProject.code == normalized_code, SddManagementProject.id != project.id)
            .first()
        )
        if existing:
            raise ProjectServiceError("A project with this code already exists", status_code=409)
        project.code = normalized_code
    if customer is not None:
        project.customer = str(customer).strip() or None
    if organization is not None:
        project.organization = str(organization).strip() or None
    if description is not None:
        project.description = description
    db.commit()
    db.refresh(project)
    return project


def delete_project(db: Session, project: SddManagementProject) -> None:
    db.delete(project)
    db.commit()


def transition_lifecycle(
    db: Session,
    project: SddManagementProject,
    target_status: str,
    actor_user_id: str,
) -> SddManagementProject:
    target = _normalize_lifecycle(target_status)
    expected = next_lifecycle_status(project.lifecycle_status)
    if target == project.lifecycle_status:
        raise ProjectServiceError("Project is already in this lifecycle status", status_code=409)
    if expected != target:
        raise ProjectServiceError(
            f"Invalid lifecycle transition: {_value(project.lifecycle_status)} -> {_value(target)}. "
            f"Next allowed status is {_value(expected) if expected else '(none)'}.",
            status_code=409,
        )
    previous = _value(project.lifecycle_status)
    project.lifecycle_status = target
    db.commit()
    db.refresh(project)
    audit_log(
        action="transition_project_lifecycle",
        outcome="success",
        resource_type="project",
        resource_id=project.id,
        user_id=actor_user_id,
        previous_status=previous,
        target_status=_value(target),
    )
    return project


def create_release(
    db: Session,
    project: SddManagementProject,
    *,
    release_no: str,
    name: str,
    product_id: Optional[str],
    product_version_id: Optional[str],
    status: str = "DRAFT",
    release_date: Optional[datetime] = None,
    notes: Optional[str] = None,
    custom_repos: Optional[List[Dict[str, str]]] = None,
    creator_id: Optional[str] = None,
) -> SddManagementProjectRelease:
    normalized_no = str(release_no or "").strip()
    normalized_name = str(name or "").strip()
    if not normalized_no or not normalized_name:
        raise ProjectServiceError("release_no and name are required", status_code=400)
    existing = (
        db.query(SddManagementProjectRelease)
        .filter(
            SddManagementProjectRelease.project_id == project.id,
            SddManagementProjectRelease.release_no == normalized_no,
        )
        .first()
    )
    if existing:
        raise ProjectServiceError("This release number already exists for the project", status_code=409)

    product = None
    version = None
    if product_id:
        product = db.query(SddManagementProduct).filter(SddManagementProduct.id == product_id).first()
        if not product:
            raise ProjectServiceError("Product not found", status_code=404)
    if product_version_id:
        version = (
            db.query(SddManagementProductVersion)
            .filter(SddManagementProductVersion.id == product_version_id)
            .first()
        )
        if not version:
            raise ProjectServiceError("Product version not found", status_code=404)
        if not product or version.product_id != product.id:
            raise ProjectServiceError("Product version does not belong to the selected product", status_code=409)
    if product_id and not product_version_id:
        raise ProjectServiceError("product_version_id is required when product_id is provided", status_code=400)

    release = SddManagementProjectRelease(
        project_id=project.id,
        release_no=normalized_no,
        name=normalized_name,
        product_id=product.id if product else None,
        product_version_id=version.id if version else None,
        status=_normalize_release_status(status or "DRAFT"),
        release_date=release_date,
        notes=notes,
        created_by=creator_id,
    )
    db.add(release)
    db.flush()

    # OOTB repo set: product-version bindings (bound to branch), snapshotted into the release.
    if version:
        from app.domains.management.models.management import SddManagementProductVersionRepo

        bindings = (
            db.query(SddManagementProductVersionRepo)
            .filter(SddManagementProductVersionRepo.product_version_id == version.id)
            .all()
        )
        for binding in bindings:
            db.add(
                SddManagementProjectReleaseRepo(
                    release_id=release.id,
                    repository_id=binding.repository_id,
                    branch_name=binding.branch_name,
                    repo_kind=ReleaseRepoKind.OOTB,
                )
            )

    # Custom repositories appended to the release.
    for item in custom_repos or []:
        repository_id = str((item or {}).get("repository_id") or "").strip()
        branch_name = str((item or {}).get("branch_name") or "").strip()
        if not repository_id:
            continue
        repository = db.query(SddManagementRepository).filter(SddManagementRepository.id == repository_id).first()
        if not repository:
            raise ProjectServiceError(f"Repository not found: {repository_id}", status_code=404)
        if not branch_name:
            branch_name = repository.default_branch
        git_ref_service.validate_branch_exists(repository.git_url, branch_name)
        db.add(
            SddManagementProjectReleaseRepo(
                release_id=release.id,
                repository_id=repository.id,
                branch_name=branch_name,
                repo_kind=ReleaseRepoKind.CUSTOM,
            )
        )

    db.commit()
    db.refresh(release)
    return release


def get_release(db: Session, project_id: str, release_id: str) -> Optional[SddManagementProjectRelease]:
    return (
        db.query(SddManagementProjectRelease)
        .options(joinedload(SddManagementProjectRelease.repos))
        .filter(
            SddManagementProjectRelease.id == release_id,
            SddManagementProjectRelease.project_id == project_id,
        )
        .first()
    )


def update_release(
    db: Session,
    release: SddManagementProjectRelease,
    *,
    release_no: Optional[str] = None,
    name: Optional[str] = None,
    status: Optional[str] = None,
    release_date: Optional[datetime] = None,
    notes: Optional[str] = None,
) -> SddManagementProjectRelease:
    if release_no is not None:
        normalized_no = str(release_no).strip()
        existing = (
            db.query(SddManagementProjectRelease)
            .filter(
                SddManagementProjectRelease.project_id == release.project_id,
                SddManagementProjectRelease.release_no == normalized_no,
                SddManagementProjectRelease.id != release.id,
            )
            .first()
        )
        if existing:
            raise ProjectServiceError("This release number already exists for the project", status_code=409)
        release.release_no = normalized_no
    if name is not None:
        release.name = str(name).strip() or release.name
    if status is not None:
        release.status = _normalize_release_status(status)
    if release_date is not None:
        release.release_date = release_date
    if notes is not None:
        release.notes = notes
    db.commit()
    db.refresh(release)
    return release


def delete_release(db: Session, release: SddManagementProjectRelease) -> None:
    db.delete(release)
    db.commit()


def add_product_dep(
    db: Session,
    project: SddManagementProject,
    *,
    product_id: str,
    product_version_id: Optional[str] = None,
    creator_id: Optional[str] = None,
) -> SddManagementProjectProductDep:
    product = db.query(SddManagementProduct).filter(SddManagementProduct.id == product_id).first()
    if not product:
        raise ProjectServiceError("Product not found", status_code=404)
    if product_version_id:
        version = (
            db.query(SddManagementProductVersion)
            .filter(SddManagementProductVersion.id == product_version_id)
            .first()
        )
        if not version or version.product_id != product.id:
            raise ProjectServiceError("Product version does not belong to the selected product", status_code=409)
    existing = (
        db.query(SddManagementProjectProductDep)
        .filter(
            SddManagementProjectProductDep.project_id == project.id,
            SddManagementProjectProductDep.product_id == product.id,
        )
        .first()
    )
    if existing:
        raise ProjectServiceError("This product dependency already exists", status_code=409)
    dep = SddManagementProjectProductDep(
        project_id=project.id,
        product_id=product.id,
        product_version_id=product_version_id,
        created_by=creator_id,
    )
    db.add(dep)
    db.commit()
    db.refresh(dep)
    return dep


def update_product_dep(
    db: Session,
    dep: SddManagementProjectProductDep,
    *,
    product_version_id: Optional[str] = None,
) -> SddManagementProjectProductDep:
    if product_version_id:
        version = (
            db.query(SddManagementProductVersion)
            .filter(SddManagementProductVersion.id == product_version_id)
            .first()
        )
        if not version or version.product_id != dep.product_id:
            raise ProjectServiceError("Product version does not belong to the dependency product", status_code=409)
    dep.product_version_id = product_version_id or None
    db.commit()
    db.refresh(dep)
    return dep


def remove_product_dep(db: Session, dep: SddManagementProjectProductDep) -> None:
    db.delete(dep)
    db.commit()


def associate_repository(
    db: Session,
    project: SddManagementProject,
    *,
    repository_id: str,
    branch_name: Optional[str] = None,
    creator_id: Optional[str] = None,
) -> SddManagementProjectRepo:
    repository = db.query(SddManagementRepository).filter(SddManagementRepository.id == repository_id).first()
    if not repository:
        raise ProjectServiceError("Repository not found", status_code=404)
    normalized_branch = str(branch_name or "").strip() or repository.default_branch
    git_ref_service.validate_branch_exists(repository.git_url, normalized_branch)
    existing = (
        db.query(SddManagementProjectRepo)
        .filter(
            SddManagementProjectRepo.project_id == project.id,
            SddManagementProjectRepo.repository_id == repository.id,
        )
        .first()
    )
    if existing:
        raise ProjectServiceError("This repository is already associated with the project", status_code=409)
    assoc = SddManagementProjectRepo(
        project_id=project.id,
        repository_id=repository.id,
        branch_name=normalized_branch,
        created_by=creator_id,
    )
    db.add(assoc)
    db.commit()
    db.refresh(assoc)
    return assoc


def dissociate_repository(db: Session, project: SddManagementProject, repository_id: str) -> None:
    assoc = (
        db.query(SddManagementProjectRepo)
        .filter(
            SddManagementProjectRepo.project_id == project.id,
            SddManagementProjectRepo.repository_id == repository_id,
        )
        .first()
    )
    if not assoc:
        raise ProjectServiceError("Repository association not found", status_code=404)
    db.delete(assoc)
    db.commit()


def resolve_project_repo_set(
    db: Session,
    project: SddManagementProject,
    *,
    branch_overrides: Optional[Dict[str, str]] = None,
) -> List[Dict[str, object]]:
    """Resolve the effective repository set of a project:

    - OOTB: version-bound repositories of the latest version of each product dependency.
    - Custom: repositories explicitly associated with the project.
    Branch overrides win over bound branches.
    """
    overrides = {str(k): str(v) for k, v in (branch_overrides or {}).items()}
    repo_map: Dict[str, Dict[str, object]] = {}

    deps = (
        db.query(SddManagementProjectProductDep)
        .filter(SddManagementProjectProductDep.project_id == project.id)
        .all()
    )
    for dep in deps:
        version_id = dep.product_version_id
        version = None
        if version_id:
            version = (
                db.query(SddManagementProductVersion)
                .filter(SddManagementProductVersion.id == version_id)
                .first()
            )
        if not version:
            version = (
                db.query(SddManagementProductVersion)
                .filter(SddManagementProductVersion.product_id == dep.product_id)
                .order_by(SddManagementProductVersion.created_at.desc())
                .first()
            )
        if not version:
            continue
        from app.domains.management.models.management import SddManagementProductVersionRepo

        bindings = (
            db.query(SddManagementProductVersionRepo)
            .filter(SddManagementProductVersionRepo.product_version_id == version.id)
            .all()
        )
        for binding in bindings:
            repo = binding.repository
            if not repo:
                continue
            branch = overrides.get(binding.repository_id, binding.branch_name)
            repo_map[binding.repository_id] = {
                "repository_id": repo.id,
                "repository_name": repo.name,
                "git_url": repo.git_url,
                "repo_type": _value(repo.repo_type),
                "default_branch": repo.default_branch,
                "branch_name": branch,
                "repo_kind": "OOTB",
            }

    for assoc in project.repo_associations:
        repo = assoc.repository
        if not repo:
            continue
        branch = overrides.get(assoc.repository_id, assoc.branch_name or repo.default_branch)
        repo_map[assoc.repository_id] = {
            "repository_id": repo.id,
            "repository_name": repo.name,
            "git_url": repo.git_url,
            "repo_type": _value(repo.repo_type),
            "default_branch": repo.default_branch,
            "branch_name": branch,
            "repo_kind": "CUSTOM",
        }

    return list(repo_map.values())


__all__ = [
    "ProjectServiceError",
    "LIFECYCLE_TRANSITIONS",
    "next_lifecycle_status",
    "serialize_project",
    "serialize_project_detail",
    "list_projects",
    "get_project",
    "create_project",
    "update_project",
    "delete_project",
    "transition_lifecycle",
    "create_release",
    "get_release",
    "update_release",
    "delete_release",
    "add_product_dep",
    "update_product_dep",
    "remove_product_dep",
    "associate_repository",
    "dissociate_repository",
    "resolve_project_repo_set",
]
