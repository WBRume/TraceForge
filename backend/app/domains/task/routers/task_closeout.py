"""Task closeout routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.distributed_lock import LockAcquireTimeout, lock_task
from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.local_resource.client import ResourceError
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.routers.task.deps import get_db_bind, raise_task_lock_conflict, run_route_db_txn
from app.domains.task.schemas.task_closeout import (
    CompleteTaskCloseoutRequest,
    FailTaskCloseoutRequest,
    TaskCloseoutResponse,
)
from app.domains.task.services import task_closeout_service
from app.domains.workspace_asset.schemas.workspace_asset import EvidenceAttachmentResponse
from app.domains.workspace_asset.services.common.errors import WorkspaceAssetError
from app.domains.workspace_asset.services.task_process import evidence_attachments

router = APIRouter(prefix="/workspaces/{ws_id}/tasks/{task_id}/closeout", tags=["Task Closeout"])


def _verify_manage_task_status(ws_id: str, current_user: User, db: Session, task_id: str) -> None:
    from app.domains.task.routers.task.deps import verify_workspace_permission

    verify_workspace_permission(
        ws_id,
        current_user.id,
        db,
        WorkspacePermission.MANAGE_TASK_STATUS,
        "No permission to manage tasks",
        task_id=task_id,
        operation="closeout",
    )


def _raise_closeout_error(exc: Exception) -> None:
    if isinstance(exc, ResourceError):
        raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)})
    if isinstance(exc, task_closeout_service.TaskCloseoutError):
        detail = {"code": exc.code, "message": str(exc)} if exc.code else str(exc)
        raise HTTPException(status_code=exc.status_code, detail=detail)
    if isinstance(exc, WorkspaceAssetError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    raise exc


@router.post("/attachments", response_model=EvidenceAttachmentResponse, status_code=201)
def upload_closeout_attachment(
    ws_id: str,
    task_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_status(ws_id, current_user, db, task_id)
    task = (
        db.query(SddTask).filter_by(id=task_id, workspace_id=ws_id).populate_existing().with_for_update().one_or_none()
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.baselined_at or task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.PROVISIONING}:
        raise HTTPException(status_code=409, detail="Task is not available for closeout attachments")
    try:
        return evidence_attachments.upload(db, task, current_user.id, file)
    except WorkspaceAssetError as exc:
        _raise_closeout_error(exc)


@router.post("/complete", response_model=TaskCloseoutResponse)
async def complete_task_closeout(
    ws_id: str,
    task_id: str,
    payload: CompleteTaskCloseoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db_bind = get_db_bind(db)
    db.close()
    await run_route_db_txn(
        db, db_bind, lambda session: _verify_manage_task_status(ws_id, current_user, session, task_id)
    )
    try:
        async with lock_task(task_id):
            try:
                result = await run_route_db_txn(
                    db,
                    db_bind,
                    lambda session: task_closeout_service.complete_task_closeout(
                        session, ws_id, task_id, current_user.id, payload
                    ),
                )
            except (task_closeout_service.TaskCloseoutError, WorkspaceAssetError, ResourceError) as exc:
                _raise_closeout_error(exc)
            from app.domains.task.services.task_event_publisher import wake

            wake()
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
    db.close()
    await run_route_db_txn(
        db, db_bind, lambda session: _verify_manage_task_status(ws_id, current_user, session, task_id)
    )
    try:
        async with lock_task(task_id):
            try:
                result = await run_route_db_txn(
                    db,
                    db_bind,
                    lambda session: task_closeout_service.fail_task_closeout(
                        session, ws_id, task_id, current_user.id, payload
                    ),
                )
            except (task_closeout_service.TaskCloseoutError, WorkspaceAssetError, ResourceError) as exc:
                _raise_closeout_error(exc)
            from app.domains.task.services.task_event_publisher import wake

            wake()
            return result
    except LockAcquireTimeout as exc:
        raise_task_lock_conflict(exc, message="Task is busy. Please retry later.")
