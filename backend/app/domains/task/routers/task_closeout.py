"""Task closeout routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.distributed_lock import LockAcquireTimeout, lock_task, make_resource_busy_error
from app.dependencies import get_current_user, get_db
from app.engine.workflow_engine import get_engine
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.task.schemas.task_closeout import CompleteTaskCloseoutRequest, FailTaskCloseoutRequest, TaskCloseoutResponse
from app.domains.ai.services import ai_job_service
from app.domains.task.services import task_cli_state_service, task_closeout_service, task_service
from app.domains.workspace.services import workspace_service
from app.domains.workspace_asset.services.workspace_task_detail_service import TaskDetailWriteError


router = APIRouter(prefix="/workspaces/{ws_id}/tasks/{task_id}/closeout", tags=["Task Closeout"])


def _verify_manage_task_status(ws_id: str, current_user: User, db: Session) -> None:
    member = workspace_service.get_workspace_member(db, ws_id, current_user.id)
    if not member:
        raise HTTPException(status_code=403, detail="No access to this workspace")
    if not workspace_service.user_has_permission(db, ws_id, current_user.id, WorkspacePermission.MANAGE_TASK_STATUS):
        raise HTTPException(status_code=403, detail="Missing MANAGE_TASK_STATUS permission")


async def _stop_active_task_session(db: Session, ws_id: str, task_id: str, message: str) -> None:
    cancelled_job_ids = ai_job_service.mark_task_chat_jobs_cancelled(
        db,
        workspace_id=ws_id,
        task_id=task_id,
        message=message,
    )
    engine = get_engine(task_id)
    if engine:
        await engine.stop()
    for job_id in cancelled_job_ids:
        await ai_job_service.publish_job(job_id, final=True)
    task_cli_state_service.schedule_task_cli_state_cleanup(ws_id, task_id)


def _raise_closeout_error(exc: Exception) -> None:
    if isinstance(exc, task_closeout_service.TaskCloseoutError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    if isinstance(exc, TaskDetailWriteError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    raise exc


def _raise_task_lock_conflict(exc: LockAcquireTimeout) -> None:
    busy = make_resource_busy_error(exc, "Task is busy. Please retry later.")
    raise HTTPException(status_code=busy.status_code, detail=str(busy))


@router.post("/complete", response_model=TaskCloseoutResponse)
async def complete_task_closeout(
    ws_id: str,
    task_id: str,
    payload: CompleteTaskCloseoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_status(ws_id, current_user, db)
    try:
        async with lock_task(task_id):
            task = task_service.get_task(db, task_id, ws_id)
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            try:
                result = task_closeout_service.complete_task_closeout(db, ws_id, task_id, current_user.id, payload)
            except (task_closeout_service.TaskCloseoutError, TaskDetailWriteError) as exc:
                _raise_closeout_error(exc)
            await _stop_active_task_session(db, ws_id, task_id, "Task completed through closeout")
            return result
    except LockAcquireTimeout as exc:
        _raise_task_lock_conflict(exc)


@router.post("/fail", response_model=TaskCloseoutResponse)
async def fail_task_closeout(
    ws_id: str,
    task_id: str,
    payload: FailTaskCloseoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_status(ws_id, current_user, db)
    try:
        async with lock_task(task_id):
            task = task_service.get_task(db, task_id, ws_id)
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            try:
                result = task_closeout_service.fail_task_closeout(db, ws_id, task_id, current_user.id, payload)
            except (task_closeout_service.TaskCloseoutError, TaskDetailWriteError) as exc:
                _raise_closeout_error(exc)
            await _stop_active_task_session(db, ws_id, task_id, "Task failed through closeout")
            return result
    except LockAcquireTimeout as exc:
        _raise_task_lock_conflict(exc)
