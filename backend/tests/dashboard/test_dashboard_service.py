"""看板聚合口径测试：成功率 / 进行中任务 / 热力图补零。"""

import os
import sys
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.auth.models.user import User, Workspace  # noqa: E402
from app.domains.dashboard.models.metric import SddDashboardMetric  # noqa: E402
from app.domains.dashboard.services import dashboard_service  # noqa: E402
from app.domains.task.models.task import SddTask, TaskStatus  # noqa: E402


def _make_workspace(db: Session) -> Workspace:
    user = User(id="user-1", email="dash@example.com", hashed_password="x", display_name="Dash")
    workspace = Workspace(id="ws-1", name="Dashboard WS", owner_id=user.id)
    db.add_all([user, workspace])
    db.commit()
    return workspace


def _add_task(
    db: Session,
    workspace_id: str,
    task_id: str,
    status: TaskStatus,
    *,
    retry_count: int = 0,
    created_at: datetime | None = None,
) -> SddTask:
    task = SddTask(
        id=task_id,
        workspace_id=workspace_id,
        creator_id="user-1",
        name=task_id,
        project_path=".",
        status=status,
        retry_count=retry_count,
        created_at=created_at or datetime.now(),
    )
    db.add(task)
    db.commit()
    return task


def test_overview_uses_live_task_status_for_success_rate(db: Session):
    workspace = _make_workspace(db)
    _add_task(db, workspace.id, "t-done", TaskStatus.DONE)
    _add_task(db, workspace.id, "t-baselined", TaskStatus.BASELINED)
    _add_task(db, workspace.id, "t-failed", TaskStatus.FAILED)
    _add_task(db, workspace.id, "t-coding", TaskStatus.CODING)
    _add_task(db, workspace.id, "t-suspended", TaskStatus.SUSPENDED)
    _add_task(db, workspace.id, "t-provisioning", TaskStatus.PROVISIONING)
    _add_task(db, workspace.id, "t-pending", TaskStatus.PENDING)

    overview = dashboard_service.get_overview(db, workspace.id)

    assert overview.total_tasks == 7
    # DONE + BASELINED 为成功，(DONE + BASELINED) / (DONE + BASELINED + FAILED)
    assert overview.success_rate == round(2 / 3, 3)
    # 进行中 = 已启动且未终结（PROVISIONING / PENDING / 终态都不算）
    assert overview.active_tasks == 2


def test_overview_ignores_historical_metrics_for_success_rate(db: Session):
    workspace = _make_workspace(db)
    task = _add_task(db, workspace.id, "t-failed", TaskStatus.FAILED)
    db.add_all([
        SddDashboardMetric(
            task_id=task.id, workspace_id=workspace.id,
            metric_type="TASK_RESULT", metric_value=1.0,
        ),
        SddDashboardMetric(
            task_id=task.id, workspace_id=workspace.id,
            metric_type="COST", metric_value=1.25,
        ),
        SddDashboardMetric(
            task_id=task.id, workspace_id=workspace.id,
            metric_type="REQUIREMENT_DURATION", metric_value=3.0,
        ),
        SddDashboardMetric(
            task_id=task.id, workspace_id=workspace.id,
            metric_type="DURATION", metric_value=1800000.0,
        ),
    ])
    db.commit()

    overview = dashboard_service.get_overview(db, workspace.id)

    # 历史 TASK_RESULT=1 不再影响成功率（口径改为实时状态）
    assert overview.success_rate == 0.0
    assert overview.total_cost_usd == 1.25
    assert overview.time_saved_hours == 2.5


def test_overview_empty_workspace_returns_zeros(db: Session):
    workspace = _make_workspace(db)

    overview = dashboard_service.get_overview(db, workspace.id)

    assert overview.total_tasks == 0
    assert overview.success_rate == 0.0
    assert overview.active_tasks == 0
    assert overview.time_saved_hours == 0.0
    assert overview.total_cost_usd == 0.0


def test_retry_heatmap_returns_dense_seven_day_series(db: Session):
    workspace = _make_workspace(db)
    now = datetime.now()
    task = _add_task(
        db, workspace.id, "t-today", TaskStatus.CODING,
        retry_count=2, created_at=now,
    )
    db.add(SddDashboardMetric(
        task_id=task.id, workspace_id=workspace.id,
        metric_type="TASK_RESULT", metric_value=0.0,
        recorded_at=now,
    ))
    db.commit()

    rows = dashboard_service.get_retry_heatmap(db, workspace.id)

    today = now.date()
    expected_dates = [str(today - timedelta(days=offset)) for offset in range(6, -1, -1)]
    assert [row.date for row in rows] == expected_dates
    assert len(rows) == 7

    today_row = rows[-1]
    assert today_row.retry_count == 2
    assert today_row.task_count == 1
    assert today_row.failure_count == 1

    for row in rows[:-1]:
        assert row.retry_count == 0
        assert row.task_count == 0
        assert row.failure_count == 0
