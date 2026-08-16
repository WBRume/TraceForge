"""
Project management service.

The project is the top-level entity: it contains multiple products, each
tracking its own delivery progress (delivery_status state machine). Release
records select a product and snapshot its repository bindings plus optional
custom repositories.
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
    RepoRefType,
    SddManagementProduct,
    SddManagementProductVersion,
    SddManagementProductVersionRepo,
    SddManagementProject,
    SddManagementProjectProduct,
    SddManagementProjectRelease,
    SddManagementProjectReleaseRepo,
    SddManagementRepository,
)
from app.domains.management.services import git_ref_service, product_service


class ProjectServiceError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# Delivery lifecycle state machine: adjacent forward/backward transitions.
# Backward transitions are allowed so a misclicked advancement can be reverted.
LIFECYCLE_TRANSITIONS: Dict[ProjectLifecycleStatus, ProjectLifecycleStatus] = {
    ProjectLifecycleStatus.INITIATED: ProjectLifecycleStatus.DEVELOPING,
    ProjectLifecycleStatus.DEVELOPING: ProjectLifecycleStatus.DELIVERING,
    ProjectLifecycleStatus.DELIVERING: ProjectLifecycleStatus.MAINTAINING,
    ProjectLifecycleStatus.MAINTAINING: ProjectLifecycleStatus.RETIRED,
}

# Full ordered flow, used to resolve the previous status of a given status.
LIFECYCLE_ORDER: List[ProjectLifecycleStatus] = [
    ProjectLifecycleStatus.INITIATED,
    ProjectLifecycleStatus.DEVELOPING,
    ProjectLifecycleStatus.DELIVERING,
    ProjectLifecycleStatus.MAINTAINING,
    ProjectLifecycleStatus.RETIRED,
]


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


def _normalize_ref_type(value: str) -> RepoRefType:
    normalized = str(value or "BRANCH").strip().upper()
    try:
        return RepoRefType(normalized)
    except ValueError as exc:
        raise ProjectServiceError("ref_type must be BRANCH or TAG", status_code=400) from exc


def _value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def next_lifecycle_status(current: ProjectLifecycleStatus) -> Optional[ProjectLifecycleStatus]:
    return LIFECYCLE_TRANSITIONS.get(current)


def previous_lifecycle_status(current: ProjectLifecycleStatus) -> Optional[ProjectLifecycleStatus]:
    try:
        index = LIFECYCLE_ORDER.index(current)
    except ValueError:
        return None
    return LIFECYCLE_ORDER[index - 1] if index > 0 else None


def _allowed_lifecycle_targets(current: ProjectLifecycleStatus) -> List[ProjectLifecycleStatus]:
    return [
        status
        for status in (
            previous_lifecycle_status(current),
            next_lifecycle_status(current),
        )
        if status is not None
    ]


def serialize_project(project: SddManagementProject) -> Dict[str, object]:
    return {
        "id": project.id,
        "name": project.name,
        "code": project.code,
        "customer": project.customer,
        "organization": project.organization,
        "lifecycle_status": _value(project.lifecycle_status),
        "description": project.description,
        "product_count": len(project.products) if project.products is not None else None,
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
    query = (
        db.query(SddManagementProject)
        .options(joinedload(SddManagementProject.products))
    )
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
            joinedload(SddManagementProject.products).joinedload(SddManagementProjectProduct.product),
            joinedload(SddManagementProject.products).joinedload(SddManagementProjectProduct.version),
        )
        .filter(SddManagementProject.id == project_id)
        .first()
    )


def serialize_project_product(link: SddManagementProjectProduct) -> Dict[str, object]:
    product = link.product
    version = link.version
    return {
        "id": link.id,
        "project_id": link.project_id,
        "product_id": link.product_id,
        "product_version_id": link.product_version_id,
        "product_name": product.name if product else None,
        "product_code": product.code if product else None,
        "product_version_no": version.version_no if version else None,
        "delivery_status": _value(link.delivery_status),
        "created_at": link.created_at,
    }


def serialize_release(release: SddManagementProjectRelease) -> Dict[str, object]:
    product = release.product
    return {
        "id": release.id,
        "project_id": release.project_id,
        "release_no": release.release_no,
        "name": release.name,
        "product_id": release.product_id,
        "product_name": product.name if product else None,
        "product_version_no": product.version_no if product else None,
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
                "ref_type": _value(repo.ref_type),
                "ref_name": repo.ref_name,
                "repo_kind": _value(repo.repo_kind),
            }
            for repo in release.repos
        ],
    }


def serialize_project_detail(project: SddManagementProject) -> Dict[str, object]:
    payload = serialize_project(project)
    payload["releases"] = [serialize_release(release) for release in project.releases]
    payload["products"] = [serialize_project_product(link) for link in project.products]
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
    product_count = len(project.products or [])
    release_count = len(project.releases or [])
    if product_count > 0 or release_count > 0:
        raise ProjectServiceError(
            "Cannot delete project '{name}' because it still contains {products} product(s) "
            "and {releases} release(s). Remove or detach them first.".format(
                name=project.name,
                products=product_count,
                releases=release_count,
            ),
            status_code=409,
        )
    db.delete(project)
    db.commit()


def transition_lifecycle(
    db: Session,
    project: SddManagementProject,
    target_status: str,
    actor_user_id: str,
) -> SddManagementProject:
    target = _normalize_lifecycle(target_status)
    if target == project.lifecycle_status:
        raise ProjectServiceError("Project is already in this lifecycle status", status_code=409)
    allowed = _allowed_lifecycle_targets(project.lifecycle_status)
    if target not in allowed:
        raise ProjectServiceError(
            f"Invalid lifecycle transition: {_value(project.lifecycle_status)} -> {_value(target)}. "
            f"Allowed transitions: {', '.join(_value(s) for s in allowed) or '(none)'}.",
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


# ── Project products (with per-product delivery progress) ─────────────────

def add_project_product(
    db: Session,
    project: SddManagementProject,
    *,
    product_id: str,
    product_version_id: Optional[str] = None,
    creator_id: Optional[str] = None,
) -> SddManagementProjectProduct:
    product = db.query(SddManagementProduct).filter(SddManagementProduct.id == product_id).first()
    if not product:
        raise ProjectServiceError("Product not found", status_code=404)
    existing = (
        db.query(SddManagementProjectProduct)
        .filter(
            SddManagementProjectProduct.project_id == project.id,
            SddManagementProjectProduct.product_id == product.id,
        )
        .first()
    )
    if existing:
        raise ProjectServiceError("This product is already in the project", status_code=409)
    # Resolve the bound version: explicit selection, otherwise the latest one.
    version = None
    if product_version_id:
        version = (
            db.query(SddManagementProductVersion)
            .filter(
                SddManagementProductVersion.id == product_version_id,
                SddManagementProductVersion.product_id == product.id,
            )
            .first()
        )
        if not version:
            raise ProjectServiceError("Product version not found", status_code=404)
    elif product.versions:
        version = product.versions[-1]
    else:
        raise ProjectServiceError(
            "Product has no versions yet; create a version before adding it to a project",
            status_code=409,
        )
    link = SddManagementProjectProduct(
        project_id=project.id,
        product_id=product.id,
        product_version_id=version.id if version else None,
        delivery_status=ProjectLifecycleStatus.INITIATED,
        created_by=creator_id,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def remove_project_product(db: Session, link: SddManagementProjectProduct) -> None:
    db.delete(link)
    db.commit()


def update_project_product_version(
    db: Session,
    link: SddManagementProjectProduct,
    *,
    product_version_id: str,
    actor_user_id: str,
) -> SddManagementProjectProduct:
    version = (
        db.query(SddManagementProductVersion)
        .filter(
            SddManagementProductVersion.id == product_version_id,
            SddManagementProductVersion.product_id == link.product_id,
        )
        .first()
    )
    if not version:
        raise ProjectServiceError("Product version not found", status_code=404)
    previous = link.product_version_id
    link.product_version_id = version.id
    db.commit()
    db.refresh(link)
    audit_log(
        action="update_project_product_version",
        outcome="success",
        resource_type="project_product",
        resource_id=link.id,
        user_id=actor_user_id,
        project_id=link.project_id,
        product_id=link.product_id,
        previous_version_id=previous,
        target_version_id=version.id,
        target_version_no=version.version_no,
    )
    return link


def transition_project_product_delivery(
    db: Session,
    link: SddManagementProjectProduct,
    target_status: str,
    actor_user_id: str,
) -> SddManagementProjectProduct:
    target = _normalize_lifecycle(target_status)
    if target == link.delivery_status:
        raise ProjectServiceError("Product is already in this delivery status", status_code=409)
    allowed = _allowed_lifecycle_targets(link.delivery_status)
    if target not in allowed:
        raise ProjectServiceError(
            f"Invalid delivery transition for product: {_value(link.delivery_status)} -> {_value(target)}. "
            f"Allowed transitions: {', '.join(_value(s) for s in allowed) or '(none)'}.",
            status_code=409,
        )
    previous = _value(link.delivery_status)
    link.delivery_status = target
    db.commit()
    db.refresh(link)
    audit_log(
        action="transition_project_product_delivery",
        outcome="success",
        resource_type="project_product",
        resource_id=link.id,
        user_id=actor_user_id,
        project_id=link.project_id,
        product_id=link.product_id,
        previous_status=previous,
        target_status=_value(target),
    )
    return link


def get_project_product(db: Session, project_id: str, product_id: str) -> Optional[SddManagementProjectProduct]:
    return (
        db.query(SddManagementProjectProduct)
        .options(
            joinedload(SddManagementProjectProduct.product),
            joinedload(SddManagementProjectProduct.version),
        )
        .filter(
            SddManagementProjectProduct.project_id == project_id,
            SddManagementProjectProduct.product_id == product_id,
        )
        .first()
    )


# ── Releases ───────────────────────────────────────────────────────────────

def create_release(
    db: Session,
    project: SddManagementProject,
    *,
    release_no: str,
    name: str,
    product_id: Optional[str],
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
    if product_id:
        product = db.query(SddManagementProduct).filter(SddManagementProduct.id == product_id).first()
        if not product:
            raise ProjectServiceError("Product not found", status_code=404)

    release = SddManagementProjectRelease(
        project_id=project.id,
        release_no=normalized_no,
        name=normalized_name,
        product_id=product.id if product else None,
        status=_normalize_release_status(status or "DRAFT"),
        release_date=release_date,
        notes=notes,
        created_by=creator_id,
    )
    db.add(release)
    db.flush()

    # OOTB repo set: snapshot the selected product version's repository bindings.
    if product:
        version = None
        for link in project.products:
            if link.product_id == product.id:
                version = link.version
                break
        if version is None and product.versions:
            version = product.versions[-1]
        if version is not None:
            bindings = product_service.resolve_effective_version_bindings(version)
            for binding in bindings:
                db.add(
                    SddManagementProjectReleaseRepo(
                        release_id=release.id,
                        repository_id=binding["repository_id"],
                        ref_type=binding["ref_type"],
                        ref_name=binding["ref_name"],
                        repo_kind=ReleaseRepoKind.OOTB,
                    )
                )

    # Custom repositories appended to the release.
    for item in custom_repos or []:
        repository_id = str((item or {}).get("repository_id") or "").strip()
        ref_name = str((item or {}).get("ref_name") or "").strip()
        ref_type = _normalize_ref_type(str((item or {}).get("ref_type") or "BRANCH"))
        if not repository_id:
            continue
        repository = db.query(SddManagementRepository).filter(SddManagementRepository.id == repository_id).first()
        if not repository:
            raise ProjectServiceError(f"Repository not found: {repository_id}", status_code=404)
        if not ref_name:
            ref_name = repository.default_branch
        git_ref_service.validate_ref_exists(repository.git_url, ref_type.value, ref_name)
        db.add(
            SddManagementProjectReleaseRepo(
                release_id=release.id,
                repository_id=repository.id,
                ref_type=ref_type,
                ref_name=ref_name,
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


# ── Workspace repo set resolution ──────────────────────────────────────────

def resolve_project_repo_set(
    db: Session,
    project: SddManagementProject,
    product_ids: Optional[List[str]] = None,
) -> List[Dict[str, object]]:
    """Resolve the effective repository set for a project and product selection.

    The repository set is the union of the tag/branch bindings of every
    selected product.
    """
    selected = {str(item).strip() for item in (product_ids or []) if str(item).strip()}
    repo_map: Dict[str, Dict[str, object]] = {}

    for link in project.products:
        if selected and link.product_id not in selected:
            continue
        # Use the version bound at project level; fall back to the latest one.
        version = link.version
        if version is None and link.product and link.product.versions:
            version = link.product.versions[-1]
        if version is None:
            continue
        bindings = product_service.resolve_effective_version_bindings(version)
        for binding in bindings:
            repo_id = binding["repository_id"]
            repo_map[repo_id] = {
                "repository_id": repo_id,
                "repository_name": binding["repository_name"],
                "git_url": binding["git_url"],
                "repo_type": binding["repo_type"],
                "default_branch": binding["default_branch"],
                "ref_type": binding["ref_type"],
                "ref_name": binding["ref_name"],
                "branch_name": binding["ref_name"],
                "repo_kind": "OOTB",
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
    "add_project_product",
    "remove_project_product",
    "update_project_product_version",
    "transition_project_product_delivery",
    "get_project_product",
    "create_release",
    "get_release",
    "update_release",
    "delete_release",
    "resolve_project_repo_set",
]
