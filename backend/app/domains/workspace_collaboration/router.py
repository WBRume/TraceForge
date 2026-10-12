"""Authenticated collaboration API; local paths never cross this boundary."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.distributed_lock import LockAcquireTimeout, lock_task
from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.workspace.services import workspace_service

from . import content, service, session
from .schemas import (
    DeliveryReceipt,
    DisableRequest,
    EnableRequest,
    Fence,
    HandoffRequest,
    LeaseRequest,
    MissingObjectsRequest,
)

router = APIRouter(prefix="/workspaces/{ws_id}/tasks/{task_id}/collaboration", tags=["Workspace collaboration"])


def _task(db: Session, ws_id: str, task_id: str, user: User | str, *, write: bool = False) -> SddTask:
    user_id = user if isinstance(user, str) else user.id
    if not workspace_service.get_workspace_member(db, ws_id, user_id):
        raise HTTPException(403, "No access to this workspace")
    task = db.query(SddTask).filter_by(id=task_id, workspace_id=ws_id).first()
    if task is None:
        raise HTTPException(404, "Task not found")
    if write:
        if not workspace_service.user_has_permission(db, ws_id, user_id, WorkspacePermission.START_TASK):
            raise HTTPException(403, "No permission to collaborate on this task")
        if task.status == TaskStatus.BASELINED:
            raise HTTPException(403, "Baselined task is read-only")
    return task


def _invoke(db: Session, function, *args, **kwargs):
    try:
        result = function(db, *args, **kwargs)
        db.commit()
        return result
    except service.CollaborationError as exc:
        if exc.code == "RECOVERY_REQUIRED":
            db.commit()
        else:
            db.rollback()
        raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)}) from exc
    except (ValueError, OSError) as exc:
        db.rollback()
        raise HTTPException(409, {"code": "COLLABORATION_CONTENT_ERROR", "message": str(exc)}) from exc


async def _locked(db: Session, ws_id: str, task_id: str, user: User, function, *args):
    user_id = user.id
    bind = db.get_bind()
    db.close()

    def execute():
        with Session(bind=bind) as transaction:
            task = _task(transaction, ws_id, task_id, user_id, write=True)
            return _invoke(transaction, function, task, user_id, *args)

    try:
        async with lock_task(task_id):
            return await run_in_threadpool(execute)
    except LockAcquireTimeout as exc:
        raise HTTPException(409, {"code": "TASK_BUSY", "message": "Task is being updated; retry shortly"}) from exc


@router.get("")
def state(ws_id: str, task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _invoke(db, service.get_state, _task(db, ws_id, task_id, user))


@router.post("/enable")
async def enable(
    ws_id: str, task_id: str, data: EnableRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return await _locked(db, ws_id, task_id, user, service.enable, data)


@router.post("/lease")
def lease(
    ws_id: str, task_id: str, data: LeaseRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return _invoke(db, service.renew_lease, _task(db, ws_id, task_id, user, write=True), user.id, data)


@router.post("/claim-driver")
async def claim_driver(
    ws_id: str, task_id: str, data: EnableRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return await _locked(db, ws_id, task_id, user, service.claim_driver, data)


@router.get("/handoffs")
def handoffs(ws_id: str, task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _task(db, ws_id, task_id, user)
    return _invoke(db, service.handoff_history, task_id)


class ReleaseRequest(LeaseRequest):
    operation_id: str = Field(min_length=1, max_length=128)


@router.post("/release-driver")
async def release_driver(
    ws_id: str,
    task_id: str,
    data: ReleaseRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await _locked(db, ws_id, task_id, user, session.release_driver, data)


class LatestSnapshotRequest(BaseModel):
    base_snapshot_id: str | None = Field(default=None, max_length=128)


@router.post("/latest-snapshot")
async def latest_snapshot(
    ws_id: str,
    task_id: str,
    data: LatestSnapshotRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await _locked(db, ws_id, task_id, user, session.download, data.base_snapshot_id)


@router.get("/snapshots/{snapshot_id}")
def snapshot(
    ws_id: str,
    task_id: str,
    snapshot_id: str,
    base_snapshot_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _task(db, ws_id, task_id, user)
    target = _invoke(db, service.get_snapshot, task_id, snapshot_id)
    if base_snapshot_id:
        from .delta import between

        try:
            base = service.get_snapshot(db, task_id, base_snapshot_id)
        except service.CollaborationError as exc:
            if exc.status_code != 404:
                raise
        else:
            return between(base, target)
    return target


@router.post("/objects/missing")
def missing(
    ws_id: str,
    task_id: str,
    data: MissingObjectsRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _task(db, ws_id, task_id, user)
    store = content.ObjectStore(task_id)
    try:
        available = store.has_many(data.hashes)
        return {"missing": [value for value in data.hashes if value not in available]}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _put_object(db: Session, ws_id: str, task_id: str, user: User, data: LeaseRequest, sha256: str, raw: bytes):
    _task(db, ws_id, task_id, user, write=True)
    active = service._state(db, task_id)
    if active is None:
        raise HTTPException(409, {"code": "COLLABORATION_DISABLED", "message": "Enable collaboration first"})
    try:
        service._check_driver(active, user.id, data)
        result = content.ObjectStore(task_id).put(raw, sha256)
        db.commit()
        return {"sha256": result, "size": len(raw)}
    except service.CollaborationError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)}) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc


@router.put("/objects/{sha256}")
async def upload_object(
    ws_id: str,
    task_id: str,
    sha256: str,
    request: Request,
    client_id: str,
    instance_id: str,
    lease_epoch: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > content.MAX_OBJECT_BYTES:
            raise HTTPException(413, "Collaboration file exceeds 64 MiB limit")
        chunks.extend(chunk)
    identity = LeaseRequest(client_id=client_id, instance_id=instance_id, lease_epoch=lease_epoch)
    return await run_in_threadpool(_put_object, db, ws_id, task_id, user, identity, sha256, bytes(chunks))


@router.get("/objects/{sha256}")
def download_object(
    ws_id: str, task_id: str, sha256: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    _task(db, ws_id, task_id, user)
    try:
        raw = content.ObjectStore(task_id).read(sha256)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Collaboration object not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(
        raw,
        media_type="application/octet-stream",
        headers={"ETag": '"' + sha256 + '"', "Cache-Control": "private, immutable"},
    )


@router.post("/handoff")
async def handoff(
    ws_id: str,
    task_id: str,
    data: HandoffRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = await _locked(db, ws_id, task_id, user, service.handoff, data)
    if data.submission_id:
        from app.domains.task.services.chat_submission_service import schedule

        schedule(data.submission_id)
    return result


@router.post("/receipt")
def receipt(
    ws_id: str,
    task_id: str,
    data: DeliveryReceipt,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _invoke(db, service.receipt, _task(db, ws_id, task_id, user, write=True), user.id, data)


@router.post("/disable")
def disable(
    ws_id: str,
    task_id: str,
    data: DisableRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _invoke(db, service.disable, _task(db, ws_id, task_id, user, write=True), user.id, data, data.operation_id)


class CancelRequest(Fence):
    operation_id: str = Field(min_length=1, max_length=128)
    submission_id: str


@router.post("/cancel-preparation")
async def cancel(
    ws_id: str, task_id: str, data: CancelRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return await _locked(db, ws_id, task_id, user, service.cancel_preparation, data, data.submission_id)


class RecoverRequest(Fence):
    operation_id: str = Field(min_length=1, max_length=128)


@router.post("/recover-input")
async def recover_input(
    ws_id: str,
    task_id: str,
    data: RecoverRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = await _locked(db, ws_id, task_id, user, service.recover_input, data, data.operation_id)
    if result.get("pending_submission_id"):
        from app.domains.task.services.chat_submission_service import schedule

        schedule(result["pending_submission_id"])
    return result


@router.post("/recover-output")
async def recover_output(
    ws_id: str,
    task_id: str,
    data: RecoverRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await _locked(db, ws_id, task_id, user, service.recover_output, data)
