"""任务会话建立路由（start / initialize）。

路由层只保留鉴权、任务分布式锁与锁冲突映射；业务编排在
task_session_control_service.start_task_session / initialize_task_session。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.distributed_lock import LockAcquireTimeout, lock_task
from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.task.routers.task.deps import (
    TASKS_ROUTE_PREFIX,
    get_db_bind,
    raise_session_control_error,
    raise_task_lock_conflict,
    run_route_db_txn,
    verify_workspace_permission,
)
from app.domains.task.schemas.task import InitializeRequest, TaskStartRequest
from app.domains.task.services import task_session_control_service, task_session_service

router = APIRouter(prefix=TASKS_ROUTE_PREFIX, tags=["Tasks"])


@router.post("/{task_id}/start")
async def start_task(
    ws_id: str,
    task_id: str,
    start_req: Optional[TaskStartRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db_bind = get_db_bind(db)
    await run_route_db_txn(
        db,
        db_bind,
        lambda session: verify_workspace_permission(
            ws_id,
            current_user.id,
            session,
            WorkspacePermission.START_TASK,
            "No permission to start tasks",
        ),
    )
    # Permission checks are complete; no dependency Session is allowed to
    # remain open while distributed locks are awaited.
    db.close()

    try:
        async with lock_task(task_id):
            return await task_session_control_service.start_task_session(
                db,
                ws_id=ws_id,
                task_id=task_id,
                actor_user_id=current_user.id,
                requested_prompt=start_req.prompt if start_req else None,
                sop_auto_run=start_req.sop_auto_run if start_req else None,
            )
    except task_session_control_service.TaskSessionControlError as exc:
        raise_session_control_error(exc)
    except LockAcquireTimeout as exc:
        raise_task_lock_conflict(exc)


@router.post("/{task_id}/initialize")
async def initialize_task(
    ws_id: str,
    task_id: str,
    body: InitializeRequest = Body(default=InitializeRequest()),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db_bind = get_db_bind(db)
    await run_route_db_txn(
        db,
        db_bind,
        lambda session: verify_workspace_permission(
            ws_id,
            current_user.id,
            session,
            WorkspacePermission.MANAGE_TASK_STATUS,
            "No permission to initialize tasks",
        ),
    )
    db.close()

    try:
        async with lock_task(task_id):
            return await task_session_control_service.initialize_task_session(
                db,
                ws_id=ws_id,
                task_id=task_id,
                actor_user_id=current_user.id,
                skill_ids=body.skill_ids,
                keep_deleted_runtime_skills=body.keep_deleted_runtime_skills is not False,
                requested_prompt=body.prompt,
                reason=body.reason,
            )
    except task_session_service.TaskSessionUndoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except task_session_control_service.TaskSessionControlError as exc:
        raise_session_control_error(exc)
    except LockAcquireTimeout as exc:
        raise_task_lock_conflict(exc)
