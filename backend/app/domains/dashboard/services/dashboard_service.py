"""
看板聚合查询服务
"""

from datetime import datetime, timedelta
from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc, case

from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.dashboard.models.metric import SddDashboardMetric
from app.domains.asset.schemas.asset import (
    DashboardOverview, SuccessRateData, PhaseDurationData, RetryHeatmapData
)

# 成功率口径：DONE 与 BASELINED 视为完成
SUCCESS_STATUSES = (TaskStatus.DONE, TaskStatus.BASELINED)
FAILURE_STATUSES = (TaskStatus.FAILED,)
# 进行中口径：已启动且未终结（PROVISIONING 资源准备中、PENDING 未启动、终态均不算）
ACTIVE_EXCLUDED_STATUSES = (
    TaskStatus.PROVISIONING,
    TaskStatus.PENDING,
    TaskStatus.DONE,
    TaskStatus.FAILED,
    TaskStatus.BASELINED,
)
HEATMAP_DAYS = 7


def get_overview(db: Session, workspace_id: str) -> DashboardOverview:
    # 0. 任务总数应覆盖工作区全部任务（包含 PENDING / 进行中 / 已完成）
    total_tasks = db.query(sqlfunc.count(SddTask.id)).filter(
        SddTask.workspace_id == workspace_id
    ).scalar() or 0

    # 1. 活跃任务数：已启动且未终结 (实时从 Task 表)
    active = db.query(sqlfunc.count(SddTask.id)).filter(
        SddTask.workspace_id == workspace_id,
        SddTask.status.notin_(ACTIVE_EXCLUDED_STATUSES),
    ).scalar() or 0

    # 2. 成功率：与状态分布同源的实时任务状态口径（不回看历史指标）
    done_count = db.query(sqlfunc.count(SddTask.id)).filter(
        SddTask.workspace_id == workspace_id,
        SddTask.status.in_(SUCCESS_STATUSES),
    ).scalar() or 0

    failed_count = db.query(sqlfunc.count(SddTask.id)).filter(
        SddTask.workspace_id == workspace_id,
        SddTask.status.in_(FAILURE_STATUSES),
    ).scalar() or 0

    finished_count = done_count + failed_count
    success_rate = (done_count / finished_count) if finished_count > 0 else 0.0

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
        success_rate=round(success_rate, 3),  # 返回 0-1 之间的值，由前端处理百分比
        active_tasks=active,
        time_saved_hours=round(time_saved_hours, 1),
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
    today = datetime.now().date()
    first_day = today - timedelta(days=HEATMAP_DAYS - 1)
    window_start = datetime.combine(first_day, datetime.min.time())

    # 1. 获取重试总计与总任务数 (按天)
    task_stats = (
        db.query(
            sqlfunc.date(SddTask.created_at).label("date"),
            sqlfunc.sum(SddTask.retry_count).label("retry_count"),
            sqlfunc.count(SddTask.id).label("task_count"),
        )
        .filter(
            SddTask.workspace_id == workspace_id,
            SddTask.created_at >= window_start
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
            SddDashboardMetric.recorded_at >= window_start
        )
        .group_by(sqlfunc.date(SddDashboardMetric.recorded_at))
        .all()
    )

    retry_map = {str(r.date): int(r.retry_count or 0) for r in task_stats}
    task_map = {str(r.date): int(r.task_count or 0) for r in task_stats}
    fail_map = {str(r.date): int(r.failure_count or 0) for r in failure_stats}

    # 3. 补齐连续 HEATMAP_DAYS 天序列，前端直接消费，避免自行计算日期产生时区偏差
    return [
        RetryHeatmapData(
            date=str(day),
            retry_count=retry_map.get(str(day), 0),
            failure_count=fail_map.get(str(day), 0),
            task_count=task_map.get(str(day), 0),
        )
        for day in (first_day + timedelta(days=offset) for offset in range(HEATMAP_DAYS))
    ]
