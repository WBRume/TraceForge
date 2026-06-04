"""
Dashboard API routes.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.asset.schemas.asset import DashboardOverview, PhaseDurationData, RetryHeatmapData, SuccessRateData
from app.domains.dashboard.services import dashboard_service
from app.domains.workspace.services import workspace_service

router = APIRouter(prefix="/workspaces/{ws_id}/dashboard", tags=["Dashboard"])


def _verify_dashboard_access(ws_id: str, user: User, db: Session) -> None:
    member = workspace_service.get_workspace_member(db, ws_id, user.id)
    if not member:
        raise HTTPException(status_code=403, detail="No access to this workspace")
    if not workspace_service.user_has_permission(db, ws_id, user.id, WorkspacePermission.VIEW_DASHBOARD):
        raise HTTPException(status_code=403, detail="No permission to view dashboard")


@router.get("/overview", response_model=DashboardOverview)
def get_dashboard_overview(
    ws_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _verify_dashboard_access(ws_id, current_user, db)
    return dashboard_service.get_overview(db, ws_id)


@router.get("/success-rate", response_model=List[SuccessRateData])
def get_dashboard_success_rate(
    ws_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _verify_dashboard_access(ws_id, current_user, db)
    return dashboard_service.get_success_rate(db, ws_id)


@router.get("/phase-duration", response_model=List[PhaseDurationData])
def get_dashboard_phase_duration(
    ws_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _verify_dashboard_access(ws_id, current_user, db)
    return dashboard_service.get_phase_duration(db, ws_id)


@router.get("/retry-heatmap", response_model=List[RetryHeatmapData])
def get_dashboard_retry_heatmap(
    ws_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _verify_dashboard_access(ws_id, current_user, db)
    return dashboard_service.get_retry_heatmap(db, ws_id)
