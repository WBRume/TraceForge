"""任务 Skills 运行时路由：运行时 Skills 列表 / 事件追踪 / 运行文件树与读写。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.skill.services import skill_runtime_trace_service, task_skill_runtime_service
from app.domains.task.routers.task.deps import (
    TASKS_ROUTE_PREFIX,
    ensure_task_not_baselined,
    get_task_or_404,
    verify_workspace_access,
    verify_workspace_permission,
)
from app.domains.task.schemas.task import (
    TaskRuntimeSkillsResponse,
    TaskSkillRuntimeEventsResponse,
    TaskSkillRuntimeFileContentResponse,
    TaskSkillRuntimeFileTreeResponse,
    TaskSkillRuntimeFileWriteRequest,
)

router = APIRouter(prefix=TASKS_ROUTE_PREFIX, tags=["Tasks"])


@router.get("/{task_id}/skills/runtime", response_model=TaskRuntimeSkillsResponse)
def get_task_runtime_skills(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user.id, db)
    task = get_task_or_404(db, task_id, ws_id)
    payload = task_skill_runtime_service.list_task_runtime_skills(db, task)
    return TaskRuntimeSkillsResponse(**payload)


@router.get("/{task_id}/skills/runtime/events", response_model=TaskSkillRuntimeEventsResponse)
def get_task_runtime_skill_events(
    ws_id: str,
    task_id: str,
    skill_id: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    group_by_skill: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user.id, db)
    task = get_task_or_404(db, task_id, ws_id)
    payload = skill_runtime_trace_service.list_task_runtime_events(
        db,
        task,
        skill_id=skill_id,
        event_type=event_type,
        limit=limit,
        group_by_skill=group_by_skill,
    )
    return TaskSkillRuntimeEventsResponse(**payload)


@router.get("/{task_id}/skills/{skill_id}/files/tree", response_model=TaskSkillRuntimeFileTreeResponse)
def get_task_runtime_skill_file_tree(
    ws_id: str,
    task_id: str,
    skill_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user.id, db)
    task = get_task_or_404(db, task_id, ws_id)
    try:
        nodes = task_skill_runtime_service.build_task_runtime_skill_file_tree(
            db,
            task,
            skill_id=skill_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=int(getattr(exc, "status_code", 400)), detail=str(exc))
    return TaskSkillRuntimeFileTreeResponse(task_id=task.id, skill_id=skill_id, nodes=nodes)


@router.get("/{task_id}/skills/{skill_id}/files/content", response_model=TaskSkillRuntimeFileContentResponse)
def get_task_runtime_skill_file_content(
    ws_id: str,
    task_id: str,
    skill_id: str,
    path: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user.id, db)
    task = get_task_or_404(db, task_id, ws_id)
    try:
        payload = task_skill_runtime_service.read_task_runtime_skill_file(
            db,
            task,
            skill_id=skill_id,
            path=path,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=int(getattr(exc, "status_code", 400)), detail=str(exc))
    return TaskSkillRuntimeFileContentResponse(
        task_id=task.id,
        skill_id=skill_id,
        path=str(payload.get("path") or ""),
        content=payload.get("content"),
        is_binary=bool(payload.get("is_binary") or False),
        size=int(payload.get("size") or 0),
    )


@router.put("/{task_id}/skills/{skill_id}/files/content", response_model=TaskSkillRuntimeFileContentResponse)
def write_task_runtime_skill_file_content(
    ws_id: str,
    task_id: str,
    skill_id: str,
    body: TaskSkillRuntimeFileWriteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_permission(
        ws_id,
        current_user.id,
        db,
        WorkspacePermission.MANAGE_TASK_STATUS,
        "No permission to edit runtime task skills",
        task_id=task_id,
    )
    try:
        task = get_task_or_404(db, task_id, ws_id)
        ensure_task_not_baselined(task)
        payload = task_skill_runtime_service.write_task_runtime_skill_file(
            db,
            task,
            skill_id=skill_id,
            path=body.path,
            content=body.content,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=int(getattr(exc, "status_code", 400)), detail=str(exc))
    return TaskSkillRuntimeFileContentResponse(
        task_id=task.id,
        skill_id=skill_id,
        path=str(payload.get("path") or ""),
        content=payload.get("content"),
        is_binary=bool(payload.get("is_binary") or False),
        size=int(payload.get("size") or 0),
    )
