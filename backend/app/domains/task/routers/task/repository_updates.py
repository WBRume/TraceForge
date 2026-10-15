"""Task-code updates share the task mutation lock and workspace permissions."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.distributed_lock import LockAcquireTimeout, lock_task
from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.task.models.task import TaskStatus
from app.domains.task.services.repository_updates import service
from app.domains.task.services.repository_updates.git import UpdateError
from app.domains.workspace.services import workspace_service
from app.domains.workspace_collaboration.router import _task

router = APIRouter(prefix="/workspaces/{ws_id}/tasks/{task_id}/repository-updates", tags=["Task code"])


class Fence(BaseModel):
    operation_id: str = Field(min_length=36, max_length=36)
    version: int = Field(ge=1)


class Resolution(Fence):
    repository_id: str = Field(max_length=36)
    path: str = Field(min_length=1, max_length=2000)
    choice: Literal["task", "remote", "delete", "edit"]
    text: str | None = Field(default=None, max_length=2 * 1024 * 1024)


class Adaptation(Fence):
    instruction: str = Field(min_length=1, max_length=20000)
    auto_apply: bool = False


async def locked(db, ws_id, task_id, user, function, *args, write=True, lock_read=False, **kwargs):
    bind, actor = db.get_bind(), user.id
    db.close()

    def execute():
        with Session(bind=bind) as transaction:
            task = _task(transaction, ws_id, task_id, actor, write=write)
            try:
                result = function(transaction, task, actor, *args, **kwargs)
                transaction.commit()
                return result
            except UpdateError as exc:
                transaction.rollback()
                raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)}) from exc
            except (ValueError, OSError) as exc:
                transaction.rollback()
                raise HTTPException(
                    409, {"code": "UPDATE_STORAGE_ERROR", "message": "代码更新存储不可用，请检查快照存储配置。"}
                ) from exc

    try:
        if not write and not lock_read:
            result = await run_in_threadpool(execute)
        else:
            async with lock_task(task_id, ttl=600, blocking_timeout=30):
                result = await run_in_threadpool(execute)
    except LockAcquireTimeout as exc:
        raise HTTPException(409, {"code": "TASK_BUSY", "message": "任务正在处理其他操作，请稍后重试。"}) from exc
    from app.domains.task.services.chat_submission_service import wake_event_publisher

    await wake_event_publisher()
    return result


@router.get("")
async def get(ws_id: str, task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    def summary(tx, task, actor):
        return {
            **service.summary(tx, task),
            "can_update": task.status != TaskStatus.BASELINED
            and workspace_service.user_has_permission(tx, ws_id, actor, WorkspacePermission.START_TASK),
        }

    # Summary also recovers completed adaptations after missed job events.
    return await locked(db, ws_id, task_id, user, summary, write=False, lock_read=True)


@router.post("/prepare")
async def prepare(ws_id: str, task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return await locked(db, ws_id, task_id, user, service.prepare)


@router.get("/file")
async def file(
    ws_id: str,
    task_id: str,
    operation_id: str,
    repository_id: str,
    path: str = Query(max_length=2000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await locked(
        db,
        ws_id,
        task_id,
        user,
        lambda tx, task, actor: service.file_detail(task, operation_id, repository_id, path),
        write=False,
    )


@router.post("/resolve")
async def resolve(
    ws_id: str, task_id: str, data: Resolution, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return await locked(
        db,
        ws_id,
        task_id,
        user,
        service.resolve,
        data.operation_id,
        data.version,
        data.repository_id,
        data.path,
        data.choice,
        data.text,
    )


@router.post("/apply")
async def apply(
    ws_id: str, task_id: str, data: Fence, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return await locked(db, ws_id, task_id, user, service.apply, data.operation_id, data.version)


@router.post("/recover")
async def recover(
    ws_id: str, task_id: str, data: Fence, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return await locked(db, ws_id, task_id, user, service.recover, data.operation_id, data.version)


@router.post("/discard")
async def discard(
    ws_id: str, task_id: str, data: Fence, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return await locked(db, ws_id, task_id, user, service.discard, data.operation_id, data.version)


@router.post("/adapt")
async def adapt(
    ws_id: str, task_id: str, data: Adaptation, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    from app.domains.ai.services.jobs.publishing import enqueue_task_chat_job
    from app.domains.task.services.repository_updates import adaptation

    result = await locked(
        db,
        ws_id,
        task_id,
        user,
        adaptation.create,
        data.operation_id,
        data.version,
        data.instruction,
        auto_apply=data.auto_apply,
    )
    await enqueue_task_chat_job(result["job_id"])
    return result


@router.post("/cancel-adaptation")
async def cancel_adaptation(
    ws_id: str, task_id: str, data: Fence, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    from app.domains.ai.services.jobs.attempts import cancel_job
    from app.domains.ai.services.jobs.publishing import publish_job_state

    def cancel(tx, task, actor):
        plan = service.current(task, data.operation_id, data.version, states=("ADAPTING",))
        cancel_job(tx, workspace_id=ws_id, job_id=plan["job_id"])
        return service.view(task, plan)

    result = await locked(db, ws_id, task_id, user, cancel)
    await publish_job_state(result["job_id"])
    return result
