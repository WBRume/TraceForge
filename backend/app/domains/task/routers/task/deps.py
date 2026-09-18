"""Task API 路由层共享设施。

- 工作区访问 / 权限守卫（各子路由直接调用）；
- 任务读取与状态守卫（404 / BASELINED / 引擎运行中）；
- 分布式锁冲突 → HTTP 409/429 的统一映射（task_closeout 路由复用）；
- 依赖 Session → bind 桥接：路由在等待分布式锁前必须释放请求 Session，
  锁内短事务经 run_route_db_txn 在 DB 线程执行（bind 取自依赖 Session）。

业务规则不属于本模块：会话编排见 task_session_control_service，
诊断总结守卫见 diagnosis_result_service。
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.distributed_lock import LockAcquireTimeout, make_resource_busy_error
from app.core.offload import run_db_txn_with_bind
from app.domains.auth.models.user import WorkspacePermission
from app.domains.task.models.task import TaskStatus
from app.domains.task.services import task_service
from app.domains.task.services.task_session_control_service import (
    BASELINED_LOCKED_MSG,
    TASK_RUNNING_MSG,
)
from app.domains.workspace.services import workspace_service
from app.engine.workflow_engine import get_engine

T = TypeVar("T")

# 所有 task 子路由共用的挂载前缀（各子模块的 APIRouter 各自声明，聚合器不再叠加）
TASKS_ROUTE_PREFIX = "/workspaces/{ws_id}/tasks"

TASK_INITIALIZING_MSG = "Task is being initialized by another request. Please retry later."
WORKSPACE_BUSY_MSG = "Workspace repository is busy. Please retry later."
CHANGE_PROPOSAL_QUEUE_BUSY_MSG = "Change proposal generation queue is busy. Please retry later."


# ── 工作区访问 / 权限守卫 ──


def verify_workspace_access(ws_id: str, user_id: str, db: Session) -> None:
    if not workspace_service.get_workspace_member(db, ws_id, user_id):
        raise HTTPException(status_code=403, detail="No access to this workspace")


def verify_workspace_permission(
    ws_id: str,
    user_id: str,
    db: Session,
    permission: WorkspacePermission,
    detail: str,
) -> None:
    verify_workspace_access(ws_id, user_id, db)
    if not workspace_service.user_has_permission(db, ws_id, user_id, permission):
        raise HTTPException(status_code=403, detail=detail)


# ── 任务读取与状态守卫 ──


def get_task_or_404(db: Session, task_id: str, ws_id: str):
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def ensure_task_not_baselined(task) -> None:
    if task.status == TaskStatus.BASELINED:
        raise HTTPException(status_code=403, detail=BASELINED_LOCKED_MSG)


def ensure_task_session_idle(task_id: str) -> None:
    engine = get_engine(task_id)
    if engine and engine.running:
        raise HTTPException(status_code=409, detail=TASK_RUNNING_MSG)


# ── 分布式锁冲突 → HTTP 映射 ──


def raise_task_lock_conflict(exc: LockAcquireTimeout, *, message: str = TASK_INITIALIZING_MSG) -> None:
    busy = make_resource_busy_error(exc, message)
    raise HTTPException(status_code=busy.status_code, detail=str(busy))


def raise_workspace_lock_conflict(exc: LockAcquireTimeout) -> None:
    busy = make_resource_busy_error(exc, WORKSPACE_BUSY_MSG)
    raise HTTPException(status_code=busy.status_code, detail=str(busy))


def raise_change_proposal_queue_conflict(exc: LockAcquireTimeout) -> None:
    busy = make_resource_busy_error(exc, CHANGE_PROPOSAL_QUEUE_BUSY_MSG)
    raise HTTPException(status_code=busy.status_code, detail=str(busy))


def raise_session_control_error(exc) -> None:
    """TaskSessionControlError → HTTPException（detail 为纯文本）。"""
    raise HTTPException(status_code=int(exc.status_code), detail=str(exc))


# ── 依赖 Session → bind 桥接 ──


def get_db_bind(db: Session) -> Any:
    getter = getattr(db, "get_bind", None)
    return getter() if callable(getter) else None


async def run_route_db_txn(db: Session, db_bind: Any, body: Callable[[Session], T]) -> T:
    """Run route DB work on the dependency's bind without carrying its Session."""
    if db_bind is None:
        # 轻量测试替身没有 SQLAlchemy bind：退回依赖 Session 同步执行。
        return body(db)
    return await run_db_txn_with_bind(db_bind, body)
