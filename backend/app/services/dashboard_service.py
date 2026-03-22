"""
看板聚合查询服务
"""

from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc, case

from app.models.task import SddTask, TaskStatus
from app.models.test_result import SddTestResult
from app.models.metric import SddDashboardMetric
from app.schemas.asset import (
    DashboardOverview, SuccessRateData, PhaseDurationData, RetryHeatmapData
)


def get_overview(db: Session, workspace_id: str) -> DashboardOverview:
    total = db.query(sqlfunc.count(SddTask.id)).filter(
        SddTask.workspace_id == workspace_id
    ).scalar() or 0

    done = db.query(sqlfunc.count(SddTask.id)).filter(
        SddTask.workspace_id == workspace_id,
        SddTask.status == TaskStatus.DONE,
    ).scalar() or 0

    active = db.query(sqlfunc.count(SddTask.id)).filter(
        SddTask.workspace_id == workspace_id,
        SddTask.status.notin_([TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.PENDING]),
    ).scalar() or 0

    success_rate = (done / total * 100) if total > 0 else 0.0

    return DashboardOverview(
        total_tasks=total,
        success_rate=round(success_rate, 1),
        active_tasks=active,
        avg_duration_minutes=0.0,  # 后续计算
    )


def get_success_rate(db: Session, workspace_id: str) -> List[SuccessRateData]:
    results = (
        db.query(SddTask.status, sqlfunc.count(SddTask.id))
        .filter(SddTask.workspace_id == workspace_id)
        .group_by(SddTask.status)
        .all()
    )
    return [SuccessRateData(status=r[0].value, count=r[1]) for r in results]


def get_phase_duration(db: Session, workspace_id: str) -> List[PhaseDurationData]:
    # 基于指标表聚合
    results = (
        db.query(
            SddDashboardMetric.metric_type,
            sqlfunc.avg(SddDashboardMetric.metric_value),
        )
        .filter(SddDashboardMetric.workspace_id == workspace_id)
        .group_by(SddDashboardMetric.metric_type)
        .all()
    )
    return [
        PhaseDurationData(phase=r[0], avg_minutes=round(r[1], 2))
        for r in results
    ]


def get_retry_heatmap(db: Session, workspace_id: str) -> List[RetryHeatmapData]:
    results = (
        db.query(
            sqlfunc.date(SddTask.created_at).label("date"),
            sqlfunc.sum(SddTask.retry_count).label("retry_count"),
            sqlfunc.count(SddTask.id).label("task_count"),
        )
        .filter(SddTask.workspace_id == workspace_id)
        .group_by(sqlfunc.date(SddTask.created_at))
        .order_by(sqlfunc.date(SddTask.created_at))
        .all()
    )
    return [
        RetryHeatmapData(
            date=str(r.date),
            retry_count=int(r.retry_count or 0),
            task_count=r.task_count,
        )
        for r in results
    ]
