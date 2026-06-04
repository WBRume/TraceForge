"""
Workspace API routes.
"""

from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.distributed_lock import (
    LockAcquireTimeout,
    lock_workspace_repo,
    make_resource_busy_error,
)
from app.core.logging import audit_log, get_logger
from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User
from app.domains.ai.schemas.ai_job import AiJobResponse
from app.domains.asset.schemas.asset import (
    WorkspaceCreate,
    WorkspaceMemberAdd,
    WorkspaceMemberListResponse,
    WorkspaceMemberResponse,
    WorkspaceMemberUpdate,
    WorkspaceMyPermissionsResponse,
    WorkspaceResponse,
)
from app.domains.workflow.schemas.provision import ProvisionJobAcceptedResponse
from app.domains.ai.services import ai_job_service
from app.domains.workspace.services import workspace_service
from app.domains.workflow.services import provision_job_service

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])
logger = get_logger(__name__)
_WORKSPACE_BUSY_MSG = "Workspace repository is busy. Please retry later."


def _raise_workspace_lock_conflict(exc: LockAcquireTimeout) -> None:
    busy = make_resource_busy_error(exc, _WORKSPACE_BUSY_MSG)
    raise HTTPException(status_code=busy.status_code, detail=str(busy))


def _ensure_workspace_member(db: Session, ws_id: str, user_id: str):
    member = workspace_service.get_workspace_member(db, ws_id, user_id)
    if not member:
        raise HTTPException(status_code=403, detail="No access to this workspace")
    return member


def _ensure_member_manager(db: Session, ws_id: str, user_id: str):
    member = _ensure_workspace_member(db, ws_id, user_id)
    if not workspace_service.user_has_permission(db, ws_id, user_id, "MANAGE_MEMBERS"):
        raise HTTPException(status_code=403, detail="No permission to manage workspace members")
    return member


@router.post("", response_model=ProvisionJobAcceptedResponse, status_code=202)
async def create_workspace(
    data: WorkspaceCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        job = provision_job_service.create_job(
            db,
            job_type=provision_job_service.ProvisionJobType.CREATE_WORKSPACE,
            creator_id=current_user.id,
            context_json={
                "name": data.name,
                "description": data.description,
                "project_path": data.project_path,
                "git_repo_url": data.git_repo_url,
            },
            stage="QUEUED",
            message="Workspace provisioning queued",
        )
        audit_log(
            action="create_workspace",
            outcome="accepted",
            resource_type="workspace",
            user_id=current_user.id,
            workspace_name=data.name,
            job_id=job.id,
        )
        background_tasks.add_task(provision_job_service.run_create_workspace_job, job.id)
        return provision_job_service.serialize_accepted(job)
    except ValueError as exc:
        audit_log(
            action="create_workspace",
            outcome="failed",
            resource_type="workspace",
            user_id=current_user.id,
            workspace_name=data.name,
            job_id=None,
            reason=str(exc),
        )
        logger.warning(
            "Create workspace rejected: user_id={}, name={}, project_path={}, git_repo_url={}, reason={}",
            current_user.id,
            data.name,
            data.project_path,
            data.git_repo_url,
            str(exc),
        )
        raise HTTPException(status_code=int(getattr(exc, "status_code", 400)), detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        audit_log(
            action="create_workspace",
            outcome="failed",
            resource_type="workspace",
            user_id=current_user.id,
            workspace_name=data.name,
            job_id=None,
            reason=str(exc),
        )
        logger.exception(
            "Create workspace failed unexpectedly: user_id={}, name={}, project_path={}, git_repo_url={}",
            current_user.id,
            data.name,
            data.project_path,
            data.git_repo_url,
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("", response_model=List[WorkspaceResponse])
def get_workspaces(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return workspace_service.list_user_workspace_summaries(db, current_user)


@router.get("/{ws_id}", response_model=WorkspaceResponse)
def get_workspace(
    ws_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    summary = workspace_service.get_workspace_summary(db, ws_id, current_user)
    if not summary:
        raise HTTPException(status_code=404, detail="Workspace not found or no access")
    return summary


@router.delete("/{ws_id}")
async def delete_workspace(
    ws_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_workspace_member(db, ws_id, current_user.id)
    if not workspace_service.can_delete_workspace(db, ws_id, current_user.id):
        raise HTTPException(status_code=403, detail="Only owner can delete workspace")

    try:
        async with lock_workspace_repo(ws_id):
            success = workspace_service.delete_workspace(db, ws_id)
    except LockAcquireTimeout as exc:
        _raise_workspace_lock_conflict(exc)
    except ValueError as exc:
        audit_log(
            action="delete_workspace",
            outcome="failed",
            resource_type="workspace",
            resource_id=ws_id,
            user_id=current_user.id,
            reason=str(exc),
        )
        logger.warning(
            "Delete workspace rejected: ws_id={}, user_id={}, reason={}",
            ws_id,
            current_user.id,
            str(exc),
        )
        raise HTTPException(status_code=int(getattr(exc, "status_code", 409)), detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        audit_log(
            action="delete_workspace",
            outcome="failed",
            resource_type="workspace",
            resource_id=ws_id,
            user_id=current_user.id,
            reason=str(exc),
        )
        logger.exception(
            "Delete workspace failed unexpectedly: ws_id={}, user_id={}",
            ws_id,
            current_user.id,
        )
        raise HTTPException(status_code=500, detail=str(exc))
    if not success:
        raise HTTPException(status_code=404, detail="Workspace not found")
    audit_log(
        action="delete_workspace",
        outcome="success",
        resource_type="workspace",
        resource_id=ws_id,
        user_id=current_user.id,
    )
    return {"msg": "Workspace deleted successfully"}


@router.get("/{ws_id}/permissions/me", response_model=WorkspaceMyPermissionsResponse)
def get_my_workspace_permissions(
    ws_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payload = workspace_service.get_user_permission_payload(db, ws_id, current_user.id)
    if not payload:
        raise HTTPException(status_code=403, detail="No access to this workspace")
    return payload


@router.post("/{ws_id}/ai-jobs/{job_id}/cancel", response_model=AiJobResponse)
async def cancel_ai_job(
    ws_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_workspace_member(db, ws_id, current_user.id)
    job = ai_job_service.get_job(db, job_id=job_id)
    if not job or str(job.workspace_id) != str(ws_id):
        raise HTTPException(status_code=404, detail="AI job not found")
    can_manage = workspace_service.user_has_permission(db, ws_id, current_user.id, "MANAGE_TASK_STATUS")
    is_owner = str(job.creator_id or "") == str(current_user.id)
    if not (can_manage or is_owner):
        raise HTTPException(status_code=403, detail="No permission to cancel AI jobs")

    try:
        job = ai_job_service.cancel_job(
            db,
            workspace_id=ws_id,
            job_id=job_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not job:
        raise HTTPException(status_code=404, detail="AI job not found")

    await ai_job_service.publish_job(job.id, final=True)
    return AiJobResponse(**ai_job_service.serialize_job(job))


@router.get("/{ws_id}/members", response_model=WorkspaceMemberListResponse)
def list_workspace_members(
    ws_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=5, ge=1, le=100),
    keyword: str = Query(default="", max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_workspace_member(db, ws_id, current_user.id)

    owner_member, members, total = workspace_service.list_workspace_members_paginated(
        db,
        ws_id,
        page=page,
        page_size=page_size,
        keyword=keyword,
    )
    return WorkspaceMemberListResponse(
        owner=(WorkspaceMemberResponse(**workspace_service.member_to_response(owner_member)) if owner_member else None),
        items=[WorkspaceMemberResponse(**workspace_service.member_to_response(member)) for member in members],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/{ws_id}/members", response_model=WorkspaceMemberResponse)
def add_workspace_member(
    ws_id: str,
    data: WorkspaceMemberAdd,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_member_manager(db, ws_id, current_user.id)

    try:
        member = workspace_service.add_member(
            db,
            ws_id,
            data.user_email,
            data.role,
            permissions_flags=(data.permissions.model_dump() if data.permissions else None),
            is_expert=data.is_expert,
        )
        reloaded = workspace_service.get_workspace_member_by_id(db, ws_id, member.id)
        if not reloaded:
            raise HTTPException(status_code=500, detail="Failed to load new member")
        audit_log(
            action="update_workspace_member",
            outcome="success",
            resource_type="workspace_member",
            resource_id=member.id,
            user_id=current_user.id,
            workspace_id=ws_id,
            operation="add_member",
            member_email=data.user_email,
            member_role=data.role,
        )
        return WorkspaceMemberResponse(**workspace_service.member_to_response(reloaded))
    except ValueError as exc:
        audit_log(
            action="update_workspace_member",
            outcome="failed",
            resource_type="workspace_member",
            user_id=current_user.id,
            workspace_id=ws_id,
            operation="add_member",
            member_email=data.user_email,
            reason=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{ws_id}/members/{member_id}", response_model=WorkspaceMemberResponse)
def update_workspace_member(
    ws_id: str,
    member_id: str,
    data: WorkspaceMemberUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_member_manager(db, ws_id, current_user.id)

    try:
        member = workspace_service.update_member(
            db,
            ws_id,
            member_id,
            role=data.role,
            permissions_flags=(data.permissions.model_dump() if data.permissions else None),
            is_expert=data.is_expert,
        )
        reloaded = workspace_service.get_workspace_member_by_id(db, ws_id, member.id)
        if not reloaded:
            raise HTTPException(status_code=500, detail="Failed to load member")
        audit_log(
            action="update_workspace_member",
            outcome="success",
            resource_type="workspace_member",
            resource_id=member.id,
            user_id=current_user.id,
            workspace_id=ws_id,
            operation="edit_member",
            member_role=data.role,
        )
        return WorkspaceMemberResponse(**workspace_service.member_to_response(reloaded))
    except ValueError as exc:
        audit_log(
            action="update_workspace_member",
            outcome="failed",
            resource_type="workspace_member",
            resource_id=member_id,
            user_id=current_user.id,
            workspace_id=ws_id,
            operation="edit_member",
            reason=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        audit_log(
            action="update_workspace_member",
            outcome="failed",
            resource_type="workspace_member",
            resource_id=member_id,
            user_id=current_user.id,
            workspace_id=ws_id,
            operation="edit_member",
            reason=str(exc),
        )
        raise HTTPException(status_code=403, detail=str(exc))


@router.delete("/{ws_id}/members/{member_id}", response_model=dict)
def remove_workspace_member(
    ws_id: str,
    member_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_member_manager(db, ws_id, current_user.id)

    try:
        workspace_service.remove_member(db, ws_id, member_id, operator_user_id=current_user.id)
    except ValueError as exc:
        audit_log(
            action="update_workspace_member",
            outcome="failed",
            resource_type="workspace_member",
            resource_id=member_id,
            user_id=current_user.id,
            workspace_id=ws_id,
            operation="remove_member",
            reason=str(exc),
        )
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        audit_log(
            action="update_workspace_member",
            outcome="failed",
            resource_type="workspace_member",
            resource_id=member_id,
            user_id=current_user.id,
            workspace_id=ws_id,
            operation="remove_member",
            reason=str(exc),
        )
        raise HTTPException(status_code=403, detail=str(exc))

    audit_log(
        action="update_workspace_member",
        outcome="success",
        resource_type="workspace_member",
        resource_id=member_id,
        user_id=current_user.id,
        workspace_id=ws_id,
        operation="remove_member",
    )
    return {"msg": "Member removed"}
