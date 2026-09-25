"""Task closeout routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.distributed_lock import LockAcquireTimeout, lock_task
from app.dependencies import get_current_user, get_db
from app.engine.session import get_engine
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.task.routers.task.deps import raise_task_lock_conflict, get_db_bind, run_route_db_txn
from app.domains.local_resource.client import ResourceError
from app.domains.task.schemas.task_closeout import CompleteTaskCloseoutRequest, FailTaskCloseoutRequest, TaskCloseoutResponse
from app.domains.ai.services.jobs import attempts as ai_job_attempts
from app.domains.ai.services.jobs import publishing as ai_job_publishing
from app.domains.task.services import task_cli_state_service, task_closeout_service, task_service
from app.domains.workspace.services import workspace_service
from app.domains.workspace_asset.services.common.errors import WorkspaceAssetError


router = APIRouter(prefix="/workspaces/{ws_id}/tasks/{task_id}/closeout", tags=["Task Closeout"])


def _verify_manage_task_status(ws_id: str, current_user: User, db: Session, task_id: str) -> None:
    from app.domains.task.routers.task.deps import verify_workspace_permission
    verify_workspace_permission(ws_id, current_user.id, db, WorkspacePermission.MANAGE_TASK_STATUS,
                                "No permission to manage tasks", task_id=task_id)



async def _stop_active_task_session(db: Session, ws_id: str, task_id: str, message: str) -> None:
    cancelled_job_ids = ai_job_attempts.mark_task_chat_jobs_cancelled(
        db,
        workspace_id=ws_id,
        task_id=task_id,
        message=message,
    )
    engine = get_engine(task_id)
    if engine:
        await engine.stop()
    for job_id in cancelled_job_ids:
        await ai_job_publishing.publish_job(job_id)
    task_cli_state_service.schedule_task_cli_state_cleanup(ws_id, task_id)


def _raise_closeout_error(exc: Exception) -> None:
    if isinstance(exc, ResourceError):
        raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)})
    if isinstance(exc, task_closeout_service.TaskCloseoutError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    if isinstance(exc, WorkspaceAssetError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    raise exc


@router.post("/complete", response_model=TaskCloseoutResponse)
async def complete_task_closeout(
    ws_id: str,
    task_id: str,
    payload: CompleteTaskCloseoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db_bind = get_db_bind(db)
    await run_route_db_txn(db, db_bind, lambda session: _verify_manage_task_status(ws_id, current_user, session, task_id))
    try:
        async with lock_task(task_id):
            task = task_service.get_task(db, task_id, ws_id)
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            try:
                db.close()
                result = await run_route_db_txn(db, db_bind, lambda session: task_closeout_service.complete_task_closeout(session, ws_id, task_id, current_user.id, payload))
            except (task_closeout_service.TaskCloseoutError, WorkspaceAssetError, ResourceError) as exc:
                _raise_closeout_error(exc)
            await _stop_active_task_session(db, ws_id, task_id, "Task completed through closeout")
            return result
    except LockAcquireTimeout as exc:
        raise_task_lock_conflict(exc, message="Task is busy. Please retry later.")


@router.post("/fail", response_model=TaskCloseoutResponse)
async def fail_task_closeout(
    ws_id: str,
    task_id: str,
    payload: FailTaskCloseoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db_bind = get_db_bind(db)
    await run_route_db_txn(db, db_bind, lambda session: _verify_manage_task_status(ws_id, current_user, session, task_id))
    try:
        async with lock_task(task_id):
            task = task_service.get_task(db, task_id, ws_id)
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            try:
                db.close()
                result = await run_route_db_txn(db, db_bind, lambda session: task_closeout_service.fail_task_closeout(session, ws_id, task_id, current_user.id, payload))
            except (task_closeout_service.TaskCloseoutError, WorkspaceAssetError, ResourceError) as exc:
                _raise_closeout_error(exc)
            await _stop_active_task_session(db, ws_id, task_id, "Task failed through closeout")
            return result
    except LockAcquireTimeout as exc:
        raise_task_lock_conflict(exc, message="Task is busy. Please retry later.")
