"""会话控制与状态路由：interrupt / resume / 撤销 / 消息受理 / 快照 / 作业与上下文查询 / 预输入。"""

from __future__ import annotations

from typing import Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.distributed_lock import LockAcquireTimeout, lock_task
from app.dependencies import get_current_user, get_db
from app.domains.ai.schemas.ai_job import AiJobListResponse, AiJobResponse
from app.domains.ai.services.jobs.store import list_task_jobs, serialize_job
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.task.routers.task.deps import (
    TASKS_ROUTE_PREFIX,
    ensure_task_not_baselined,
    get_db_bind,
    get_task_or_404,
    raise_session_control_error,
    raise_task_lock_conflict,
    run_route_db_txn,
    verify_workspace_access,
    verify_workspace_permission,
)
from app.domains.task.schemas.context_token import ContextWindowResponse
from app.domains.task.schemas.task import (
    TaskInterruptRequest,
    TaskResumeInterruptedRequest,
    TaskUndoMessageRequest,
)
from app.domains.task.services import (
    chat_submission_service,
    context_token_service,
    pre_input_service,
    task_service,
    task_session_control_service,
    task_session_service,
)

router = APIRouter(prefix=TASKS_ROUTE_PREFIX, tags=["Tasks"])


def _load_task_control_context_sync(db: Session, *, ws_id: str, task_id: str) -> Dict[str, str]:
    task = get_task_or_404(db, task_id, ws_id)
    ensure_task_not_baselined(task)
    return {"task_id": task.id, "workspace_id": task.workspace_id}


def _prepare_task_undo_context_sync(
    db: Session,
    *,
    ws_id: str,
    task_id: str,
    user_id: str,
) -> Dict[str, str]:
    verify_workspace_permission(
        ws_id,
        user_id,
        db,
        WorkspacePermission.MANAGE_TASK_STATUS,
        "No permission to undo task messages",
            task_id=task_id,
    )
    task = get_task_or_404(db, task_id, ws_id)
    try:
        chat_submission_service.assert_no_preparing_submission(db, task_id)
    except chat_submission_service.SubmissionError as exc:
        raise HTTPException(409, str(exc)) from exc
    ensure_task_not_baselined(task)
    return {"task_id": str(task.id)}


@router.post("/{task_id}/interrupt")
async def interrupt_task(
    ws_id: str,
    task_id: str,
    body: TaskInterruptRequest = Body(default=TaskInterruptRequest()),
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
            "No permission to interrupt tasks",
            task_id=task_id,
        ),
    )
    db.close()

    try:
        async with lock_task(task_id):
            state = await run_route_db_txn(
                db, db_bind,
                lambda session: _load_task_control_context_sync(
                    db=session, ws_id=ws_id, task_id=task_id
                ),
            )
            return await task_session_control_service.interrupt_task(
                db,
                task_id=state["task_id"],
                workspace_id=state["workspace_id"],
                actor_user_id=current_user.id,
                reason=body.reason,
            )
    except LockAcquireTimeout as exc:
        raise_task_lock_conflict(exc)
    except task_session_control_service.TaskSessionControlError as exc:
        raise_session_control_error(exc)


@router.post("/{task_id}/resume-interrupted")
async def resume_interrupted_task(
    ws_id: str,
    task_id: str,
    body: TaskResumeInterruptedRequest = Body(default=TaskResumeInterruptedRequest()),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db_bind = get_db_bind(db)
    await run_route_db_txn(db, db_bind, lambda session: verify_workspace_permission(
        ws_id, current_user.id, session, WorkspacePermission.START_TASK,
        "No permission to resume tasks", task_id=task_id,
    ))
    db.close()

    try:
        async with lock_task(task_id):
            await run_route_db_txn(
                db, db_bind,
                lambda session: _load_task_control_context_sync(
                    db=session, ws_id=ws_id, task_id=task_id
                ),
            )
            return await task_session_control_service.resume_interrupted_task(
                task_id=task_id,
                actor_user_id=current_user.id,
                prompt=body.prompt,
                confirm_continue=body.confirm_continue,
                client_message_id=body.client_message_id,
            )
    except chat_submission_service.SubmissionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except task_session_service.TaskSessionUndoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except LockAcquireTimeout as exc:
        raise_task_lock_conflict(exc)
    except task_session_control_service.TaskSessionControlError as exc:
        raise_session_control_error(exc)


@router.post("/{task_id}/messages/{message_id}/undo")
async def undo_task_message(
    ws_id: str,
    task_id: str,
    message_id: str,
    body: TaskUndoMessageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db_bind = get_db_bind(db)
    context = await run_route_db_txn(
        db,
        db_bind,
        lambda session: _prepare_task_undo_context_sync(
            session,
            ws_id=ws_id,
            task_id=task_id,
            user_id=current_user.id,
        ),
    )
    db.close()
    try:
        return await task_session_service.undo_task_message(
            db,
            task_id=context["task_id"],
            message_id=message_id,
            actor_user_id=current_user.id,
            operation_id=body.operation_id,
        )
    except task_session_service.TaskSessionUndoError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except LockAcquireTimeout as exc:
        raise_task_lock_conflict(exc)


@router.post("/{task_id}/chat-submissions", status_code=202)
async def submit_chat(
    ws_id: str,
    task_id: str,
    payload: dict = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bind = get_db_bind(db)
    actor_id = str(current_user.id)

    def authorize(session: Session) -> None:
        verify_workspace_access(ws_id, actor_id, session)
        if not task_service.get_task(session, task_id, ws_id):
            raise HTTPException(404, "Task not found")

    await run_route_db_txn(db, bind, authorize)
    db.close()
    try:
        return await chat_submission_service.accept(
            task_id=task_id,
            actor_id=actor_id,
            client_message_id=payload.get("client_message_id"),
            content=payload.get("content"),
            metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        )
    except chat_submission_service.SubmissionError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)}) from exc


@router.get("/{task_id}/session-state")
def get_task_session_state(
    ws_id: str,
    task_id: str,
    client_message_ids: str = Query(default=""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Initialization and exception-recovery snapshot: active receipt, receipts for
    the caller's unconfirmed idempotency keys, active jobs and their messages."""
    verify_workspace_access(ws_id, current_user.id, db)
    if not task_service.get_task(db, task_id, ws_id):
        raise HTTPException(404, "Task not found")
    keys = [value for value in (client_message_ids or "").split(",") if value.strip()]
    state = chat_submission_service.build_session_state(
        db, task_id, actor_id=str(current_user.id), client_message_ids=keys)
    if state is None:
        raise HTTPException(404, "Task not found")
    return state


@router.get("/{task_id}/ai-jobs", response_model=AiJobListResponse)
def list_task_ai_jobs(
    ws_id: str,
    task_id: str,
    active_only: bool = Query(default=True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user.id, db)
    task = get_task_or_404(db, task_id, ws_id)

    jobs = list_task_jobs(
        db,
        task_id=task.id,
        active_only=active_only,
    )
    items = [AiJobResponse(**serialize_job(item)) for item in jobs]
    return AiJobListResponse(items=items, total=len(items))


@router.get("/{task_id}/context-window", response_model=ContextWindowResponse)
def get_task_context_window(
    ws_id: str,
    task_id: str,
    ai_job_id: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user.id, db)
    task = get_task_or_404(db, task_id, ws_id)
    try:
        payload = context_token_service.get_context_window(
            db,
            workspace_id=ws_id,
            task_id=task.id,
            ai_job_id=ai_job_id,
            category=category,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ContextWindowResponse(**payload)


@router.get("/{task_id}/pre-input/active")
def get_active_pre_input(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """预输入收集窗口冷启动/WS 重连恢复兜底。"""
    verify_workspace_access(ws_id, current_user.id, db)

    pre_input = pre_input_service.get_active_pre_input(db, task_id)
    if not pre_input:
        return {"pre_input": None}
    return {"pre_input": pre_input_service.serialize_pre_input(db, pre_input)}
