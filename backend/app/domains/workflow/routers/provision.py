"""
Provision job routes.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User
from app.domains.workflow.models.provision_job import ProvisionJobType
from app.domains.workflow.schemas.provision import ProvisionJobResponse
from app.domains.workflow.services import provision_job_service
from app.domains.workspace.services import workspace_service

router = APIRouter(prefix="/provision-jobs", tags=["Provision Jobs"])


@router.get("/active", response_model=List[ProvisionJobResponse])
def list_active_provision_jobs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """当前用户（仅创建人）名下未终态的任务创建 job，用于前端准备浮窗状态恢复。"""
    jobs = provision_job_service.list_active_jobs_for_creator(db, current_user.id)
    return [
        ProvisionJobResponse(**provision_job_service.serialize_active_job(db, job))
        for job in jobs
    ]


@router.post("/{job_id}/cancel", response_model=ProvisionJobResponse)
def cancel_provision_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建人取消任务创建 job：后台工作流在下一个检查点终止并回滚（清理目录 + 删除任务）。"""
    job = provision_job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Provision job not found")

    if str(job.creator_id or "") != str(current_user.id or ""):
        raise HTTPException(status_code=403, detail="Only the provision job creator can cancel it")

    if str(getattr(job.job_type, "value", job.job_type)) != str(ProvisionJobType.CREATE_TASK.value):
        raise HTTPException(status_code=400, detail="Only task provisioning jobs can be cancelled")

    if not provision_job_service.request_cancel(db, job, message="Task creation cancelled by user"):
        raise HTTPException(status_code=409, detail="Provision job already finished")

    return ProvisionJobResponse(**provision_job_service.serialize_job(job))


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
