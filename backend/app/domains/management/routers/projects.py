"""
Project management API routes.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.logging import audit_log
from app.dependencies import get_current_user, get_db, require_admin
from app.domains.auth.models.user import User
from app.domains.management.schemas.management import (
    LifecycleTransitionRequest,
    ProjectCreate,
    ProjectProductDepCreate,
    ProjectProductDepUpdate,
    ProjectReleaseCreate,
    ProjectReleaseUpdate,
    ProjectRepoAssociateCreate,
    ProjectUpdate,
)
from app.domains.management.services import project_service
from app.domains.management.services.git_ref_service import GitRefAccessError

router = APIRouter(prefix="/management/projects", tags=["Management Projects"])


@router.get("")
def list_projects(
    keyword: str = Query(default="", max_length=100),
    lifecycle_status: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items, total = project_service.list_projects(
        db,
        keyword=keyword,
        lifecycle_status=lifecycle_status,
        page=page,
        page_size=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("", status_code=201)
def create_project(
    data: ProjectCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        project = project_service.create_project(
            db,
            name=data.name,
            code=data.code,
            customer=data.customer,
            organization=data.organization,
            description=data.description,
            creator_id=current_user.id,
        )
        audit_log(
            action="create_project",
            outcome="success",
            resource_type="project",
            resource_id=project.id,
            user_id=current_user.id,
        )
        return project_service.serialize_project(project)
    except project_service.ProjectServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/{project_id}")
def get_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = project_service.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project_service.serialize_project_detail(project)


@router.put("/{project_id}")
def update_project(
    project_id: str,
    data: ProjectUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    project = project_service.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        updated = project_service.update_project(
            db,
            project,
            name=data.name,
            code=data.code,
            customer=data.customer,
            organization=data.organization,
            description=data.description,
        )
        return project_service.serialize_project(updated)
    except project_service.ProjectServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    project = project_service.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project_service.delete_project(db, project)
    audit_log(
        action="delete_project",
        outcome="success",
        resource_type="project",
        resource_id=project_id,
        user_id=current_user.id,
    )
    return {"msg": "Project deleted"}


@router.get("/{project_id}/repo-set")
def get_project_repo_set(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = project_service.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    repos = project_service.resolve_project_repo_set(db, project)
    return {"project_id": project.id, "repositories": repos}


@router.post("/{project_id}/lifecycle/transition")
def transition_project_lifecycle(
    project_id: str,
    data: LifecycleTransitionRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    project = project_service.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        updated = project_service.transition_lifecycle(
            db,
            project,
            target_status=data.target_status,
            actor_user_id=current_user.id,
        )
        return project_service.serialize_project(updated)
    except project_service.ProjectServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/{project_id}/releases", status_code=201)
def create_project_release(
    project_id: str,
    data: ProjectReleaseCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    project = project_service.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        release = project_service.create_release(
            db,
            project,
            release_no=data.release_no,
            name=data.name,
            product_id=data.product_id,
            product_version_id=data.product_version_id,
            status=data.status,
            release_date=data.release_date,
            notes=data.notes,
            custom_repos=[item.model_dump() for item in data.custom_repos],
            creator_id=current_user.id,
        )
        audit_log(
            action="create_project_release",
            outcome="success",
            resource_type="project_release",
            resource_id=release.id,
            user_id=current_user.id,
            project_id=project.id,
        )
        return project_service.serialize_release(release)
    except (project_service.ProjectServiceError, GitRefAccessError) as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 400), detail=str(exc))


@router.put("/{project_id}/releases/{release_id}")
def update_project_release(
    project_id: str,
    release_id: str,
    data: ProjectReleaseUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    release = project_service.get_release(db, project_id, release_id)
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")
    try:
        updated = project_service.update_release(
            db,
            release,
            release_no=data.release_no,
            name=data.name,
            status=data.status,
            release_date=data.release_date,
            notes=data.notes,
        )
        return project_service.serialize_release(updated)
    except project_service.ProjectServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.delete("/{project_id}/releases/{release_id}")
def delete_project_release(
    project_id: str,
    release_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    release = project_service.get_release(db, project_id, release_id)
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")
    project_service.delete_release(db, release)
    return {"msg": "Release deleted"}


@router.post("/{project_id}/product-deps", status_code=201)
def add_project_product_dep(
    project_id: str,
    data: ProjectProductDepCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    project = project_service.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        dep = project_service.add_product_dep(
            db,
            project,
            product_id=data.product_id,
            product_version_id=data.product_version_id,
            creator_id=current_user.id,
        )
        return {
            "id": dep.id,
            "project_id": dep.project_id,
            "product_id": dep.product_id,
            "product_version_id": dep.product_version_id,
        }
    except project_service.ProjectServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.put("/{project_id}/product-deps/{product_id}")
def update_project_product_dep(
    project_id: str,
    product_id: str,
    data: ProjectProductDepUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    project = project_service.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    dep = next(
        (item for item in project.product_deps if item.product_id == product_id),
        None,
    )
    if not dep:
        raise HTTPException(status_code=404, detail="Product dependency not found")
    try:
        updated = project_service.update_product_dep(
            db,
            dep,
            product_version_id=data.product_version_id,
        )
        return {
            "id": updated.id,
            "project_id": updated.project_id,
            "product_id": updated.product_id,
            "product_version_id": updated.product_version_id,
        }
    except project_service.ProjectServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.delete("/{project_id}/product-deps/{product_id}")
def remove_project_product_dep(
    project_id: str,
    product_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    project = project_service.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    dep = next(
        (item for item in project.product_deps if item.product_id == product_id),
        None,
    )
    if not dep:
        raise HTTPException(status_code=404, detail="Product dependency not found")
    project_service.remove_product_dep(db, dep)
    return {"msg": "Product dependency removed"}


@router.post("/{project_id}/repos", status_code=201)
def associate_project_repository(
    project_id: str,
    data: ProjectRepoAssociateCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    project = project_service.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        assoc = project_service.associate_repository(
            db,
            project,
            repository_id=data.repository_id,
            branch_name=data.branch_name,
            creator_id=current_user.id,
        )
        return {
            "id": assoc.id,
            "project_id": assoc.project_id,
            "repository_id": assoc.repository_id,
            "branch_name": assoc.branch_name,
        }
    except (project_service.ProjectServiceError, GitRefAccessError) as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 400), detail=str(exc))


@router.delete("/{project_id}/repos/{repository_id}")
def dissociate_project_repository(
    project_id: str,
    repository_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    project = project_service.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        project_service.dissociate_repository(db, project, repository_id)
        return {"msg": "Repository association removed"}
    except project_service.ProjectServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
