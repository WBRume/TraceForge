"""
Provision job routes.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User
from app.domains.workflow.schemas.provision import ProvisionJobResponse
from app.domains.workflow.services import provision_job_service
from app.domains.workspace.services import workspace_service

router = APIRouter(prefix="/provision-jobs", tags=["Provision Jobs"])


@router.get("/{job_id}", response_model=ProvisionJobResponse)
def get_provision_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = provision_job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Provision job not found")

    is_creator = str(job.creator_id or "") == str(current_user.id or "")
    if not is_creator:
        if not job.workspace_id:
            raise HTTPException(status_code=403, detail="No access to this provision job")
        member = workspace_service.get_workspace_member(db, str(job.workspace_id), current_user.id)
        if not member:
            raise HTTPException(status_code=403, detail="No access to this provision job")

    return ProvisionJobResponse(**provision_job_service.serialize_job(job))
