"""
Repository management API routes: registration, org placement, git ref sync/validation.
"""

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.logging import audit_log
from app.dependencies import get_current_user, get_db, require_admin
from app.domains.auth.models.user import User
from app.domains.management.schemas.management import (
    RepositoryCreate,
    RepositoryUpdate,
    ValidateAccessRequest,
    ValidateBranchRequest,
)
from app.domains.management.services import repository_service
from app.domains.management.services.git_ref_service import GitRefAccessError
from app.domains.workflow.services import provision_job_service

router = APIRouter(prefix="/management/repositories", tags=["Management Repositories"])


@router.get("")
def list_repositories(
    keyword: str = Query(default="", max_length=100),
    repo_type: Optional[str] = None,
    org_node_id: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items, total = repository_service.list_repositories(
        db,
        keyword=keyword,
        repo_type=repo_type,
        org_node_id=org_node_id,
        page=page,
        page_size=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("", status_code=201)
def create_repository(
    data: RepositoryCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        repository = repository_service.create_repository(
            db,
            name=data.name,
            git_url=data.git_url,
            repo_type=data.repo_type,
            default_branch=data.default_branch,
            org_node_id=data.org_node_id,
            description=data.description,
            creator_id=current_user.id,
        )
        audit_log(
            action="create_repository",
            outcome="success",
            resource_type="repository",
            resource_id=repository.id,
            user_id=current_user.id,
        )
        return repository_service.serialize_repository(repository)
    except repository_service.RepositoryServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.post("/validate-access")
def validate_repository_access(
    data: ValidateAccessRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        return repository_service.validate_repository_access(db, data.git_url)
    except GitRefAccessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/{repository_id}")
def get_repository(
    repository_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repository = repository_service.get_repository(db, repository_id)
    if not repository:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repository_service.serialize_repository(repository)


@router.put("/{repository_id}")
def update_repository(
    repository_id: str,
    data: RepositoryUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    repository = repository_service.get_repository(db, repository_id)
    if not repository:
        raise HTTPException(status_code=404, detail="Repository not found")
    try:
        updated = repository_service.update_repository(
            db,
            repository,
            name=data.name,
            git_url=data.git_url,
            repo_type=data.repo_type,
            default_branch=data.default_branch,
            org_node_id=data.org_node_id,
            description=data.description,
        )
        return repository_service.serialize_repository(updated)
    except repository_service.RepositoryServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.delete("/{repository_id}")
def delete_repository(
    repository_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    repository = repository_service.get_repository(db, repository_id)
    if not repository:
        raise HTTPException(status_code=404, detail="Repository not found")
    repository_service.delete_repository(db, repository)
    audit_log(
        action="delete_repository",
        outcome="success",
        resource_type="repository",
        resource_id=repository_id,
        user_id=current_user.id,
    )
    return {"msg": "Repository deleted"}


@router.get("/{repository_id}/refs")
def list_repository_refs(
    repository_id: str,
    ref_type: Optional[str] = Query(default=None, pattern="^(branch|tag|BRANCH|TAG)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.domains.management.services.git_ref_service import list_repo_refs

    repository = repository_service.get_repository(db, repository_id)
    if not repository:
        raise HTTPException(status_code=404, detail="Repository not found")
    refs = list_repo_refs(db, repository, ref_type=ref_type)
    items = [
        {
            "id": ref.id,
            "ref_type": ref.ref_type.value if hasattr(ref.ref_type, "value") else str(ref.ref_type),
            "ref_name": ref.ref_name,
            "ref_sha": ref.ref_sha,
            "synced_at": ref.synced_at,
        }
        for ref in refs
    ]
    return {"repository_id": repository.id, "items": items, "total": len(items), "last_synced_at": repository.last_synced_at}


@router.post("/{repository_id}/sync", status_code=202)
async def sync_repository_refs(
    repository_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    repository = repository_service.get_repository(db, repository_id)
    if not repository:
        raise HTTPException(status_code=404, detail="Repository not found")
    job = provision_job_service.create_job(
        db,
        job_type=provision_job_service.ProvisionJobType.SYNC_REPO_REFS,
        creator_id=current_user.id,
        context_json={"repository_id": repository.id, "repository_name": repository.name},
        stage="QUEUED",
        message="Repository ref sync queued",
    )
    background_tasks.add_task(provision_job_service.run_sync_repo_refs_job, job.id)
    audit_log(
        action="sync_repository_refs",
        outcome="accepted",
        resource_type="repository",
        resource_id=repository.id,
        user_id=current_user.id,
        job_id=job.id,
    )
    return provision_job_service.serialize_accepted(job)


@router.post("/{repository_id}/validate-branch")
def validate_repository_branch(
    repository_id: str,
    data: ValidateBranchRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    repository = repository_service.get_repository(db, repository_id)
    if not repository:
        raise HTTPException(status_code=404, detail="Repository not found")
    try:
        return repository_service.validate_repository_branch(db, repository, data.branch_name)
    except GitRefAccessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
