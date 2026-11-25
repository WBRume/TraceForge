"""Workspace workload routes."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.workspace.services import workspace_service
from app.domains.workspace_asset.routers.workspace_asset import _verify_manage_requirements, _verify_view_assets
from app.domains.workspace_asset.schemas.workload import WorkloadLimits, WorkspaceMemberWorkload, WorkspaceWorkload
from app.domains.workspace_asset.services.workload import get_workload
from app.domains.workspace_asset.services.workload_overview import get_workspace_member_workload

router = APIRouter(prefix="/workspaces/{ws_id}/workspace-assets", tags=["Workspace Assets"])


def _can_edit_limits(ws_id: str, current_user: User, db: Session) -> bool:
    return workspace_service.user_has_permission(db, ws_id, current_user.id, WorkspacePermission.MANAGE_REQUIREMENTS)


@router.get("/workload", response_model=WorkspaceWorkload)
def read_workspace_workload(
    ws_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    can_edit = _can_edit_limits(ws_id, current_user, db)
    return get_workload(db, ws_id, can_edit_limits=can_edit, as_of=datetime.now(timezone.utc).replace(tzinfo=None))


@router.get("/workload/members", response_model=WorkspaceMemberWorkload)
def read_workspace_member_workload(
    ws_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    can_edit = _can_edit_limits(ws_id, current_user, db)
    return get_workspace_member_workload(
        db, ws_id, current_user.id, can_edit_limits=can_edit, as_of=datetime.now(timezone.utc).replace(tzinfo=None)
    )


@router.put("/workload/members/{user_id}/limits", response_model=WorkloadLimits)
def update_workspace_workload_limits(
    ws_id: str,
    user_id: str,
    payload: WorkloadLimits,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_requirements(ws_id, current_user, db)
    membership = workspace_service.get_workspace_member(db, ws_id, user_id)
    if not membership:
        raise HTTPException(status_code=404, detail="Workspace member not found")
    membership.workload_limits = payload.model_dump()
    db.commit()
    return payload
