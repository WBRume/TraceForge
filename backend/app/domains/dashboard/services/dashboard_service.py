"""
看板聚合查询服务
"""

from datetime import datetime, timedelta
from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc, case

from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.models.test_result import SddTestResult
from app.domains.dashboard.models.metric import SddDashboardMetric
from app.domains.asset.schemas.asset import (
    DashboardOverview, SuccessRateData, PhaseDurationData, RetryHeatmapData
)


def get_overview(db: Session, workspace_id: str) -> DashboardOverview:
    # 0. 任务总数应覆盖工作区全部任务（包含 PENDING / 进行中 / 已完成）
    total_tasks = db.query(sqlfunc.count(SddTask.id)).filter(
        SddTask.workspace_id == workspace_id
    ).scalar() or 0

    # 1. 活跃任务数 (实时从 Task 表)
    active = db.query(sqlfunc.count(SddTask.id)).filter(
        SddTask.workspace_id == workspace_id,
        SddTask.status.notin_([TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.PENDING]),
    ).scalar() or 0

    # 2. 从指标表获取持久化统计 (即使任务删了也还在)
    # 采用“每个任务仅统计最近一次执行结果”的逻辑，避免重试导致虚高
    latest_stmt = (
        db.query(
            SddDashboardMetric.task_id,
            sqlfunc.max(SddDashboardMetric.recorded_at).label("latest_at")
        )
        .filter(
            SddDashboardMetric.workspace_id == workspace_id,
            SddDashboardMetric.metric_type == "TASK_RESULT"
        )
        .group_by(SddDashboardMetric.task_id)
        .subquery()
    )

    total_recorded = db.query(sqlfunc.count(latest_stmt.c.task_id)).scalar() or 0
    
    # 成功数 (最新结果为 1.0 的任务)
    done_recorded = (
        db.query(sqlfunc.count(SddDashboardMetric.id))
        .join(latest_stmt, 
            (SddDashboardMetric.task_id == latest_stmt.c.task_id) & 
            (SddDashboardMetric.recorded_at == latest_stmt.c.latest_at)
        )
        .filter(
            SddDashboardMetric.metric_type == "TASK_RESULT",
            SddDashboardMetric.metric_value == 1.0
        )
        .scalar() or 0
    )
    
    success_rate = (done_recorded / total_recorded) if total_recorded > 0 else 0.0

    # 3. 累计费用
    total_cost = db.query(sqlfunc.sum(SddDashboardMetric.metric_value)).filter(
        SddDashboardMetric.workspace_id == workspace_id,
        SddDashboardMetric.metric_type == "COST"
    ).scalar() or 0.0

    # 4. 累计节省时间 (小时)
    # Time Saved = SUM(REQUIREMENT_DURATION) - SUM(DURATION / 3600000)
    total_req_hours = db.query(sqlfunc.sum(SddDashboardMetric.metric_value)).filter(
        SddDashboardMetric.workspace_id == workspace_id,
        SddDashboardMetric.metric_type == "REQUIREMENT_DURATION"
    ).scalar() or 0.0
    
    total_exec_ms = db.query(sqlfunc.sum(SddDashboardMetric.metric_value)).filter(
        SddDashboardMetric.workspace_id == workspace_id,
        SddDashboardMetric.metric_type == "DURATION"
    ).scalar() or 0.0
    
    total_exec_hours = total_exec_ms / 3600000.0
    time_saved_hours = max(0.0, total_req_hours - total_exec_hours)

    return DashboardOverview(
        total_tasks=total_tasks,
        success_rate=round(success_rate, 3), # 返回 0-1 之间的值，由前端处理百分比
        active_tasks=active,
        avg_duration_minutes=round(time_saved_hours, 1), # 这里暂用这个字段返回节省的小时数，前端适配
        total_cost_usd=round(total_cost, 4)
    )


def get_success_rate(db: Session, workspace_id: str) -> List[SuccessRateData]:
    # 状态分布基于 Task 实时状态：
    # DONE / FAILED / PENDING 单独统计，其它状态归并为 RUNNING
    status_bucket = case(
        (SddTask.status == TaskStatus.DONE, "DONE"),
        (SddTask.status == TaskStatus.FAILED, "FAILED"),
        (SddTask.status == TaskStatus.PENDING, "PENDING"),
        else_="RUNNING",
    ).label("status_bucket")

    results = (
        db.query(status_bucket, sqlfunc.count(SddTask.id))
        .filter(SddTask.workspace_id == workspace_id)
        .group_by(status_bucket)
        .all()
    )

    stats = {str(bucket): int(count) for bucket, count in results}

    return [
        SuccessRateData(status="DONE", count=stats.get("DONE", 0)),
        SuccessRateData(status="FAILED", count=stats.get("FAILED", 0)),
        SuccessRateData(status="PENDING", count=stats.get("PENDING", 0)),
        SuccessRateData(status="RUNNING", count=stats.get("RUNNING", 0)),
    ]


def get_phase_duration(db: Session, workspace_id: str) -> List[PhaseDurationData]:
    # 基于指标表聚合，仅保留耗时相关指标并归一化为分钟
    relevant_types = ["REQUIREMENT_DURATION", "DURATION"]
    results = (
        db.query(
            SddDashboardMetric.metric_type,
            sqlfunc.avg(SddDashboardMetric.metric_value),
        )
        .filter(
            SddDashboardMetric.workspace_id == workspace_id,
            SddDashboardMetric.metric_type.in_(relevant_types)
        )
        .group_by(SddDashboardMetric.metric_type)
        .all()
    )
    
    data = []
    for r_type, r_val in results:
        minutes = 0.0
        if r_type == "REQUIREMENT_DURATION":
            minutes = r_val * 60.0  # 小时转分钟
        elif r_type == "DURATION":
            minutes = r_val / 60000.0  # 毫秒转分钟
        
        data.append(PhaseDurationData(phase=r_type, avg_minutes=round(minutes, 2)))
    
    return data


def get_retry_heatmap(db: Session, workspace_id: str) -> List[RetryHeatmapData]:
    seven_days_ago = datetime.now() - timedelta(days=6)
    
    # 1. 获取重试总计与总任务数 (按天)
    task_stats = (
        db.query(
            sqlfunc.date(SddTask.created_at).label("date"),
            sqlfunc.sum(SddTask.retry_count).label("retry_count"),
            sqlfunc.count(SddTask.id).label("task_count"),
        )
        .filter(
            SddTask.workspace_id == workspace_id,
            SddTask.created_at >= seven_days_ago
        )
        .group_by(sqlfunc.date(SddTask.created_at))
        .all()
    )
    
    # 2. 获取失败总计 (按天) - 从指标表统计 TASK_RESULT = 0.0
    failure_stats = (
        db.query(
            sqlfunc.date(SddDashboardMetric.recorded_at).label("date"),
            sqlfunc.count(SddDashboardMetric.id).label("failure_count")
        )
        .filter(
            SddDashboardMetric.workspace_id == workspace_id,
            SddDashboardMetric.metric_type == "TASK_RESULT",
            SddDashboardMetric.metric_value == 0.0,
            SddDashboardMetric.recorded_at >= seven_days_ago
        )
        .group_by(sqlfunc.date(SddDashboardMetric.recorded_at))
        .all()
    )
    
    # 映射失败数据
    fail_map = {str(r.date): r.failure_count for r in failure_stats}
    
    return [
        RetryHeatmapData(
            date=str(r.date),
            retry_count=int(r.retry_count or 0),
            failure_count=fail_map.get(str(r.date), 0),
            task_count=r.task_count,
        )
        for r in task_stats
    ]
