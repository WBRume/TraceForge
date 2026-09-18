"""任务 CRUD、关注、仓库、删除、导出与历史路由。"""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.distributed_lock import LockAcquireTimeout, lock_task, lock_workspace_repo
from app.core.logging import audit_log
from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.task.models.task import TaskStatus
from app.domains.task.routers.task.deps import (
    TASKS_ROUTE_PREFIX,
    ensure_task_not_baselined,
    get_task_or_404,
    raise_task_lock_conflict,
    raise_workspace_lock_conflict,
    verify_workspace_access,
    verify_workspace_permission,
)
from app.domains.task.schemas.task import (
    TaskCreate,
    TaskFollowResponse,
    TaskListResponse,
    TaskResponse,
)
from app.domains.task.services import task_cli_state_service, task_service
from app.domains.task.services.chat_submission_service import SubmissionError
from app.domains.task.services.task_session_control_service import TASK_RUNNING_MSG
from app.domains.workflow.schemas.provision import (
    ProvisionJobAcceptedResponse,
    ProvisionJobResponse,
)
from app.domains.workflow.services import provision_job_service
from app.domains.workspace.services import workspace_service
from app.engine.session import get_engine

router = APIRouter(prefix=TASKS_ROUTE_PREFIX, tags=["Tasks"])


@router.post("", response_model=ProvisionJobAcceptedResponse, status_code=202)
async def create_task(
    ws_id: str,
    data: TaskCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_permission(
        ws_id,
        current_user.id,
        db,
        WorkspacePermission.CREATE_TASK,
        "No permission to create tasks",
    )

    desc = data.description or ""

    try:
        task = task_service.create_task_record_for_provision(
            db,
            current_user,
            ws_id,
            name=data.name,
            description=desc.strip(),
            spec_doc_path=data.spec_doc_path,
            requirement_duration_hours=data.requirement_duration_hours,
            skill_ids=data.skill_ids,
            task_type=data.task_type,
            phenomenon=data.phenomenon,
            priority=data.priority,
            repository_branches=[
                {"repository_id": item.repository_id, "branch_name": item.branch_name}
                for item in (data.repository_branches or [])
            ] or None,
            repository_ids=list(data.repository_ids or []) or None,
        )
        job = provision_job_service.create_job(
            db,
            job_type=provision_job_service.ProvisionJobType.CREATE_TASK,
            creator_id=current_user.id,
            workspace_id=ws_id,
            task_id=task.id,
            context_json={
                "workspace_id": ws_id,
                "task_id": task.id,
                "task_name": task.name,
            },
            stage="QUEUED",
            message="Task provisioning queued",
        )
        background_tasks.add_task(provision_job_service.run_create_task_job, job.id)
        audit_log(
            action="create_task",
            outcome="accepted",
            resource_type="task",
            resource_id=task.id,
            user_id=current_user.id,
            workspace_id=ws_id,
            task_name=task.name,
            job_id=job.id,
        )
        return provision_job_service.serialize_accepted(job)
    except ValueError as exc:
        audit_log(
            action="create_task",
            outcome="failed",
            resource_type="task",
            user_id=current_user.id,
            workspace_id=ws_id,
            reason=str(exc),
        )
        raise HTTPException(status_code=int(getattr(exc, "status_code", 400)), detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        audit_log(
            action="create_task",
            outcome="failed",
            resource_type="task",
            user_id=current_user.id,
            workspace_id=ws_id,
            reason=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{task_id}/provision-job/cancel", response_model=ProvisionJobResponse)
def cancel_task_provision_job(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建人取消任务进行中的资源准备：后台工作流在下一个检查点终止并回滚（清理目录/worktree + 删除任务记录）。"""
    verify_workspace_access(ws_id, current_user.id, db)
    task = get_task_or_404(db, task_id, ws_id)

    if str(task.creator_id or "") != str(current_user.id or ""):
        raise HTTPException(status_code=403, detail="Only the task creator can cancel provisioning")

    job = provision_job_service.get_latest_active_job_for_task(db, task_id)
    if not job:
        raise HTTPException(status_code=409, detail="No active provisioning job for this task")

    if not provision_job_service.request_cancel(db, job, message="Task creation cancelled by user"):
        raise HTTPException(status_code=409, detail="Provision job already finished")

    return ProvisionJobResponse(**provision_job_service.serialize_job(job))


@router.get("", response_model=TaskListResponse)
def list_tasks(
    ws_id: str,
    status: Optional[str] = None,
    task_type: Optional[str] = Query(default=None),
    relation: Optional[str] = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user.id, db)
    items, total = task_service.list_tasks(
        db,
        ws_id,
        status,
        page,
        page_size,
        task_type=task_type,
        relation=relation,
        current_user_id=current_user.id,
    )
    following_ids = task_service.list_following_task_ids(
        db,
        ws_id,
        current_user.id,
        [task.id for task in items],
    )
    serialized_items = []
    for task in items:
        payload = TaskResponse.model_validate(task).model_dump()
        payload["is_following"] = task.id in following_ids
        serialized_items.append(payload)
    return {
        "items": serialized_items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user.id, db)
    task = get_task_or_404(db, task_id, ws_id)
    payload = TaskResponse.model_validate(task).model_dump()
    payload["is_following"] = task.id in task_service.list_following_task_ids(
        db, ws_id, current_user.id, [task.id]
    )
    return payload


@router.get("/{task_id}/follow", response_model=TaskFollowResponse)
def get_task_following(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user.id, db)
    task = get_task_or_404(db, task_id, ws_id)
    following = task.id in task_service.list_following_task_ids(
        db, ws_id, current_user.id, [task.id]
    )
    return TaskFollowResponse(task_id=task.id, is_following=following)


@router.put("/{task_id}/follow", response_model=TaskFollowResponse)
def follow_task_messages(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user.id, db)
    task = get_task_or_404(db, task_id, ws_id)
    following = task_service.set_task_following(
        db, task=task, user_id=current_user.id, following=True
    )
    return TaskFollowResponse(task_id=task.id, is_following=following)


@router.delete("/{task_id}/follow", response_model=TaskFollowResponse)
def unfollow_task_messages(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user.id, db)
    task = get_task_or_404(db, task_id, ws_id)
    following = task_service.set_task_following(
        db, task=task, user_id=current_user.id, following=False
    )
    return TaskFollowResponse(task_id=task.id, is_following=following)


@router.get("/{task_id}/repositories")
def get_task_repositories(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user.id, db)
    task = get_task_or_404(db, task_id, ws_id)
    repos = task_service.get_task_repositories(db, task.id)
    return {
        "task_id": task.id,
        "primary_cli_dir": task_service.resolve_task_cli_dir(db, task),
        "items": [task_service.serialize_task_repository(repo) for repo in repos],
        "total": len(repos),
    }


@router.delete("/{task_id}")
async def delete_task(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_permission(
        ws_id,
        current_user.id,
        db,
        WorkspacePermission.DELETE_TASK,
        "No permission to delete tasks",
    )

    current_task = get_task_or_404(db, task_id, ws_id)
    ensure_task_not_baselined(current_task)
    use_workspace_lock = bool(str(current_task.git_repo_url or "").strip()) and (
        workspace_service.workspace_uses_git_worktree(db, ws_id)
    )

    try:
        async with AsyncExitStack() as stack:
            if use_workspace_lock:
                try:
                    await stack.enter_async_context(lock_workspace_repo(ws_id))
                except LockAcquireTimeout as exc:
                    raise_workspace_lock_conflict(exc)
            try:
                await stack.enter_async_context(lock_task(task_id))
            except LockAcquireTimeout as exc:
                raise_task_lock_conflict(exc)

            engine = get_engine(task_id)
            if engine:
                await engine.stop()

            success = task_service.delete_task(db, task_id, ws_id)
    except ValueError as exc:
        audit_log(
            action="delete_task",
            outcome="failed",
            resource_type="task",
            resource_id=task_id,
            user_id=current_user.id,
            workspace_id=ws_id,
            reason=str(exc),
        )
        raise HTTPException(status_code=int(getattr(exc, "status_code", 409)), detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        audit_log(
            action="delete_task",
            outcome="failed",
            resource_type="task",
            resource_id=task_id,
            user_id=current_user.id,
            workspace_id=ws_id,
            reason=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc))
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")
    task_cli_state_service.schedule_task_cli_state_cleanup(ws_id, task_id)
    audit_log(
        action="delete_task",
        outcome="success",
        resource_type="task",
        resource_id=task_id,
        user_id=current_user.id,
        workspace_id=ws_id,
    )
    return {"msg": "Task deleted successfully"}


@router.get("/{task_id}/export")
def export_task(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_permission(
        ws_id,
        current_user.id,
        db,
        WorkspacePermission.EXPORT_TASK,
        "No permission to export tasks",
    )

    session_data = task_service.export_task_session(db, task_id, ws_id)
    if not session_data:
        raise HTTPException(status_code=404, detail="Task not found")
    return session_data


@router.get("/{task_id}/history")
def get_task_history(
    ws_id: str,
    task_id: str,
    page: int = 1,
    page_size: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user.id, db)
    return task_service.get_task_history(db, task_id, ws_id, page=page, page_size=page_size)


@router.delete("/{task_id}/history")
async def clear_task_history(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_permission(
        ws_id,
        current_user.id,
        db,
        WorkspacePermission.MANAGE_TASK_STATUS,
        "No permission to clear task history",
    )
    try:
        async with lock_task(task_id):
            task = get_task_or_404(db, task_id, ws_id)
            ensure_task_not_baselined(task)
            engine = get_engine(task_id)
            if (engine and engine.running) or task.status == TaskStatus.CODING:
                raise HTTPException(status_code=409, detail=TASK_RUNNING_MSG)
            try:
                return task_service.clear_task_history(db, task_id, ws_id)
            except SubmissionError as exc:
                raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)}) from exc
    except LockAcquireTimeout as exc:
        raise_task_lock_conflict(exc)
