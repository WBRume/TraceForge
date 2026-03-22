"""
Dashboard API Router
"""
from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.services import dashboard_service
from app.schemas.asset import DashboardOverview, SuccessRateData, PhaseDurationData, RetryHeatmapData

router = APIRouter(prefix="/workspaces/{ws_id}/dashboard", tags=["Dashboard"])

@router.get("/overview", response_model=DashboardOverview)
def get_dashboard_overview(ws_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """获取工作区任务整体概览指标"""
    return dashboard_service.get_overview(db, ws_id)

@router.get("/success-rate", response_model=List[SuccessRateData])
def get_dashboard_success_rate(ws_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """获取工作区任务成功率聚合数据"""
    return dashboard_service.get_success_rate(db, ws_id)

@router.get("/phase-duration", response_model=List[PhaseDurationData])
def get_dashboard_phase_duration(ws_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """获取各阶段执行耗时聚合数据"""
    return dashboard_service.get_phase_duration(db, ws_id)

@router.get("/retry-heatmap", response_model=List[RetryHeatmapData])
def get_dashboard_retry_heatmap(ws_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """获取按日期分组的重试频率热力图数据"""
    return dashboard_service.get_retry_heatmap(db, ws_id)
