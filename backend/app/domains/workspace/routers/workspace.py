"""
Workspace API routes.
"""

import asyncio
import time
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
    WorkspaceAgentBackendResponse,
    WorkspaceAgentBackendUpdate,
    WorkspaceCreate,
    WorkspaceAgentBackendTestRequest,
    WorkspaceAgentBackendTestResponse,
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
    # 配置项：新建工作区时是否启用“项目管理/产品管理”选择功能。
    # 关闭时进入独立模式：不关联管理项目/产品，直接填写名称并手动选择仓库分支。
    from app.domains.system_config.services import system_config_service

    mgmt_selection_enabled = system_config_service.get_config_bool(
        db, system_config_service.CONFIG_PROJECT_PRODUCT_MANAGEMENT_ENABLED
    )
    try:
        if not mgmt_selection_enabled:
            if data.project_id or (data.product_ids or []):
                raise ValueError(
                    "Project/product selection is disabled by system config; "
                    "provide project_name/product_name with repositories instead"
                )
            if not str(data.project_name or "").strip() or not str(data.product_name or "").strip():
                raise ValueError("project_name and product_name are required")
            if not data.repositories:
                raise ValueError("At least one repository with branch is required")
            missing_branch = [
                item.repository_id
                for item in data.repositories
                if not str(item.branch_name or "").strip()
            ]
            if missing_branch:
                raise ValueError("branch_name is required for every selected repository")

        job = provision_job_service.create_job(
            db,
            job_type=provision_job_service.ProvisionJobType.CREATE_WORKSPACE,
            creator_id=current_user.id,
            context_json={
                "name": data.name,
                "description": data.description,
                "project_path": data.project_path,
                "git_repo_url": data.git_repo_url,
                "project_id": data.project_id,
                "product_ids": list(data.product_ids or []),
                "project_name": data.project_name,
                "product_name": data.product_name,
                "repositories": [
                    {"repository_id": item.repository_id, "branch_name": item.branch_name}
                    for item in (data.repositories or [])
                ],
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


@router.get("/agent-backends", response_model=WorkspaceAgentBackendResponse)
def list_agent_backends(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """可选 agent backend 列表 + 全局默认值（未指定工作区上下文）。"""
    from app.agents.selection import default_backend_name, list_agent_backends as list_backends

    return WorkspaceAgentBackendResponse(
        agent_backend=None,
        effective_agent_backend=default_backend_name(),
        default_agent_backend=default_backend_name(),
        options=list_backends(),
    )


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


@router.get("/{ws_id}/agent-backends", response_model=WorkspaceAgentBackendResponse)
def get_workspace_agent_backends(
    ws_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_workspace_member(db, ws_id, current_user.id)
    from app.agents.selection import (
        default_backend_name,
        list_agent_backends as list_backends,
        normalize_backend_name,
        resolve_workspace_backend,
    )

    ws = workspace_service.get_workspace(db, ws_id, current_user)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    configured = normalize_backend_name(ws.agent_backend)
    return WorkspaceAgentBackendResponse(
        agent_backend=configured,
        effective_agent_backend=resolve_workspace_backend(db, ws_id),
        default_agent_backend=default_backend_name(),
        options=list_backends(),
    )


@router.post("/{ws_id}/agent-backends/test", response_model=WorkspaceAgentBackendTestResponse)
async def test_workspace_agent_backend(
    ws_id: str,
    data: WorkspaceAgentBackendTestRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_workspace_member(db, ws_id, current_user.id)
    from app.agents.selection import (
        SELECTABLE_AGENT_BACKENDS,
        create_agent_backend_by_name,
        normalize_backend_name,
    )

    backend_name = normalize_backend_name(data.backend)
    if not backend_name or backend_name not in SELECTABLE_AGENT_BACKENDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported agent backend: {data.backend!r}; expected one of {list(SELECTABLE_AGENT_BACKENDS)}",
        )

    backend = None
    started = time.monotonic()
    try:
        backend = create_agent_backend_by_name(backend_name)
        probe = getattr(backend, "probe", None)
        if probe is None:
            message = f"{backend_name} backend created successfully"
        else:
            message = await asyncio.wait_for(probe(), timeout=15)
        return WorkspaceAgentBackendTestResponse(
            backend=backend_name,
            success=True,
            message=message,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except Exception as exc:
        return WorkspaceAgentBackendTestResponse(
            backend=backend_name,
            success=False,
            message=str(exc),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    finally:
        if backend is not None:
            close = getattr(backend, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    logger.exception("Agent backend close failed during test")


@router.put("/{ws_id}/agent-backend", response_model=WorkspaceAgentBackendResponse)
def update_workspace_agent_backend(
    ws_id: str,
    data: WorkspaceAgentBackendUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_member_manager(db, ws_id, current_user.id)
    from app.agents.selection import (
        default_backend_name,
        list_agent_backends as list_backends,
        normalize_backend_name,
        resolve_workspace_backend,
        SELECTABLE_AGENT_BACKENDS,
    )

    ws = workspace_service.get_workspace(db, ws_id, current_user)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    requested = str(data.agent_backend or "").strip() or None
    if requested is not None and requested not in SELECTABLE_AGENT_BACKENDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported agent backend: {requested!r}; expected one of {list(SELECTABLE_AGENT_BACKENDS)}",
        )
    ws.agent_backend = requested
    db.commit()
    db.refresh(ws)

    audit_log(
        action="update_workspace_agent_backend",
        outcome="success",
        resource_type="workspace",
        resource_id=ws_id,
        user_id=current_user.id,
        agent_backend=requested or "default",
    )
    configured = normalize_backend_name(ws.agent_backend)
    return WorkspaceAgentBackendResponse(
        agent_backend=configured,
        effective_agent_backend=resolve_workspace_backend(db, ws_id),
        default_agent_backend=default_backend_name(),
        options=list_backends(),
    )


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
