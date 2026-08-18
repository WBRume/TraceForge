"""
Task API routes.
"""

import asyncio
from contextlib import AsyncExitStack
import os
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.distributed_lock import (
    LockAcquireTimeout,
    lock_task,
    lock_workspace_repo,
    make_resource_busy_error,
    queue_change_proposal_jobs,
)
from app.core.logging import audit_log, bind_task_context, get_logger
from app.dependencies import get_current_user, get_db
from app.engine.workflow_engine import get_engine
from app.domains.task.models.task import TaskStatus
from app.domains.auth.models.user import User, Workspace, WorkspacePermission
from app.domains.ai.schemas.ai_job import AiJobListResponse, AiJobResponse
from app.domains.workflow.schemas.change_proposal import ChangeProposalCreateRequest, ChangeProposalResponse
from app.domains.task.schemas.context_token import ContextWindowResponse
from app.domains.asset.schemas.asset import AssetResponse
from app.domains.task.schemas.task import (
    InitializeRequest,
    SuperpowersDocContentResponse,
    SuperpowersDocSaveRequest,
    SuperpowersDocsListResponse,
    TaskRuntimeSkillsResponse,
    TaskSkillRuntimeEventsResponse,
    TaskSkillRuntimeFileContentResponse,
    TaskSkillRuntimeFileTreeResponse,
    TaskSkillRuntimeFileWriteRequest,
    TaskCliBootstrapResponse,
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    TaskInterruptRequest,
    TaskResumeInterruptedRequest,
    TaskStartRequest,
)
from app.domains.task.schemas.diagnosis import (
    DiagnosisResultResponse,
    DiagnosisResultUpsertRequest,
)
from app.domains.case_center.schemas.case import CaseDraftCreateRequest, CaseResponse
from app.domains.case_center.services import case_service
from app.domains.workflow.schemas.provision import ProvisionJobAcceptedResponse
from app.domains.ai.services import ai_job_service
from app.domains.asset.services import asset_document_service
from app.domains.skill.services import task_skill_runtime_service, skill_runtime_trace_service
from app.domains.task.services import git_patch_service, task_cli_state_service, task_service, context_token_service, task_session_control_service
from app.domains.task.services import diagnosis_result_service
from app.domains.workflow.services import change_proposal_service, provision_job_service
from app.domains.workspace.services import workspace_service

router = APIRouter(prefix="/workspaces/{ws_id}/tasks", tags=["Tasks"])
logger = get_logger(__name__, category="task_execution")

_TASK_INITIALIZING_MSG = "Task is being initialized by another request. Please retry later."
_TASK_RUNNING_MSG = "Task is currently running. Please wait or cancel it first."
_TASK_INTERRUPTED_MSG = "Task is interrupted. Resume it or initialize a fresh session."
_WORKSPACE_BUSY_MSG = "Workspace repository is busy. Please retry later."
_CHANGE_PROPOSAL_QUEUE_BUSY_MSG = "Change proposal generation queue is busy. Please retry later."


def verify_workspace_access(ws_id: str, current_user: User, db: Session):
    member = workspace_service.get_workspace_member(db, ws_id, current_user.id)
    if not member:
        raise HTTPException(status_code=403, detail="No access to this workspace")
    return member


def verify_workspace_permission(
    ws_id: str,
    current_user: User,
    db: Session,
    permission: WorkspacePermission,
    detail: str,
):
    verify_workspace_access(ws_id, current_user, db)
    if not workspace_service.user_has_permission(db, ws_id, current_user.id, permission):
        raise HTTPException(status_code=403, detail=detail)


def _workspace_uses_git_worktree(db: Session, ws_id: str) -> bool:
    from app.domains.workspace.models.workspace_repository import SddWorkspaceRepository

    workspace = db.query(Workspace).filter(Workspace.id == ws_id).first()
    if not workspace:
        return False
    if bool(str(workspace.project_path or "").strip() and str(workspace.git_repo_url or "").strip()):
        return True
    repo_count = (
        db.query(SddWorkspaceRepository)
        .filter(SddWorkspaceRepository.workspace_id == ws_id)
        .count()
    )
    return repo_count > 0


def _raise_task_lock_conflict(exc: LockAcquireTimeout, *, message: str = _TASK_INITIALIZING_MSG) -> None:
    busy = make_resource_busy_error(exc, message)
    raise HTTPException(status_code=busy.status_code, detail=str(busy))


def _raise_workspace_lock_conflict(exc: LockAcquireTimeout) -> None:
    busy = make_resource_busy_error(exc, _WORKSPACE_BUSY_MSG)
    raise HTTPException(status_code=busy.status_code, detail=str(busy))


def _raise_change_proposal_queue_conflict(exc: LockAcquireTimeout) -> None:
    busy = make_resource_busy_error(exc, _CHANGE_PROPOSAL_QUEUE_BUSY_MSG)
    raise HTTPException(status_code=busy.status_code, detail=str(busy))


def _raise_session_control_error(exc: task_session_control_service.TaskSessionControlError) -> None:
    raise HTTPException(status_code=int(exc.status_code), detail=str(exc))


def _ensure_task_not_baselined(task) -> None:
    if task.status == TaskStatus.BASELINED:
        raise HTTPException(status_code=403, detail="Task is BASELINED and locked for changes")


def _serialize_asset(asset) -> AssetResponse:
    asset_type = asset.asset_type.value if hasattr(asset.asset_type, "value") else str(asset.asset_type)
    return AssetResponse(
        id=asset.id,
        task_id=asset.task_id,
        workspace_id=asset.workspace_id,
        asset_type=asset_type,
        name=asset.name,
        content_text=asset.content_text,
        content_json=asset.content_json,
        created_at=asset.created_at,
    )


def _diagnosis_prompt_suffix(task) -> str:
    """问题定位任务：把任务性质与工作契约注入 AI 会话 prompt（见 diagnosis_result_service）。"""
    return diagnosis_result_service.build_diagnosis_prompt_suffix(task)


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
        current_user,
        db,
        WorkspacePermission.CREATE_TASK,
        "No permission to create tasks",
    )

    desc = data.description or ""
    if data.use_brainstorm:
        desc += "\n\nUse `/brainstorm` from superpowers to run requirement and architecture brainstorming first."

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


@router.get("", response_model=TaskListResponse)
def list_tasks(
    ws_id: str,
    status: Optional[str] = None,
    task_type: Optional[str] = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user, db)
    items, total = task_service.list_tasks(db, ws_id, status, page, page_size, task_type=task_type)
    return {
        "items": items,
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
    verify_workspace_access(ws_id, current_user, db)
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{task_id}/repositories")
def get_task_repositories(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user, db)
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    repos = task_service.get_task_repositories(db, task.id)
    return {
        "task_id": task.id,
        "primary_cli_dir": task_service.resolve_task_cli_dir(db, task),
        "items": [task_service.serialize_task_repository(repo) for repo in repos],
        "total": len(repos),
    }


@router.post("/{task_id}/change-proposals", response_model=ChangeProposalResponse, status_code=201)
async def create_task_change_proposal(
    ws_id: str,
    task_id: str,
    data: ChangeProposalCreateRequest = Body(default=ChangeProposalCreateRequest()),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_permission(
        ws_id,
        current_user,
        db,
        WorkspacePermission.MANAGE_TASK_STATUS,
        "No permission to create change proposals",
    )

    try:
        async with queue_change_proposal_jobs(workspace_id=ws_id):
            async with AsyncExitStack() as stack:
                try:
                    await stack.enter_async_context(lock_workspace_repo(ws_id))
                except LockAcquireTimeout as exc:
                    _raise_workspace_lock_conflict(exc)
                try:
                    await stack.enter_async_context(lock_task(task_id))
                except LockAcquireTimeout as exc:
                    _raise_task_lock_conflict(exc)

                task = task_service.get_task(db, task_id, ws_id)
                if not task:
                    raise HTTPException(status_code=404, detail="Task not found")
                _ensure_task_not_baselined(task)
                engine = get_engine(task.id)
                if engine and engine.running:
                    raise HTTPException(status_code=409, detail=_TASK_RUNNING_MSG)

                workspace = db.query(Workspace).filter(Workspace.id == ws_id).first()
                proposal = change_proposal_service.create_change_proposal(
                    db,
                    task=task,
                    workspace=workspace,
                    creator_id=current_user.id,
                    summary=data.summary,
                    risk_notes=data.risk_notes,
                )
                audit_log(
                    action="create_change_proposal",
                    outcome="success",
                    resource_type="task_change_proposal",
                    resource_id=proposal.id,
                    user_id=current_user.id,
                    workspace_id=ws_id,
                    task_id=task.id,
                )
                return proposal
    except LockAcquireTimeout as exc:
        _raise_change_proposal_queue_conflict(exc)
    except (change_proposal_service.ChangeProposalError, git_patch_service.GitPatchError, ValueError) as exc:
        audit_log(
            action="create_change_proposal",
            outcome="failed",
            resource_type="task",
            resource_id=task_id,
            user_id=current_user.id,
            workspace_id=ws_id,
            reason=str(exc),
        )
        raise HTTPException(status_code=int(getattr(exc, "status_code", 400)), detail=str(exc))


@router.get("/{task_id}/spec-asset", response_model=AssetResponse)
def get_task_spec_asset(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user, db)
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    asset = asset_document_service.get_spec_asset_by_task(db, task.id)
    if not asset and task.spec_doc_path:
        asset = asset_document_service.ensure_spec_asset_backfilled(db, task)
        if asset:
            db.commit()
            db.refresh(asset)

    if not asset:
        raise HTTPException(status_code=404, detail="Task spec asset not found")

    return _serialize_asset(asset)


@router.post("/{task_id}/start")
async def start_task(
    ws_id: str,
    task_id: str,
    start_req: Optional[TaskStartRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_permission(
        ws_id,
        current_user,
        db,
        WorkspacePermission.START_TASK,
        "No permission to start tasks",
    )

    try:
        async with lock_task(task_id):
            task = task_service.get_task(db, task_id, ws_id)
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            _ensure_task_not_baselined(task)

            existing_engine = get_engine(task.id)
            if existing_engine and existing_engine.running:
                raise HTTPException(status_code=409, detail=_TASK_RUNNING_MSG)
            if task.status == TaskStatus.PROVISIONING:
                raise HTTPException(status_code=409, detail="Task is still being provisioned. Please wait until the workspace is ready.")
            if task.status == TaskStatus.CODING:
                raise HTTPException(status_code=409, detail=_TASK_RUNNING_MSG)
            if task.status == TaskStatus.INTERRUPTED:
                raise HTTPException(status_code=409, detail=_TASK_INTERRUPTED_MSG)
            if existing_engine and not existing_engine.running:
                await existing_engine.stop()

            if start_req and start_req.prompt:
                prompt = start_req.prompt
            elif task.description:
                prompt = task.description
            else:
                prompt = f"Please start task '{task.name}'."

            if task.spec_doc_path:
                abs_path = os.path.abspath(task.spec_doc_path)
                prompt += (
                    "\n\nPlease read and strictly implement all requirements in the specification file. "
                    f"Absolute path: {abs_path}"
                )

            prompt += _diagnosis_prompt_suffix(task)

            task.status = TaskStatus.CODING
            task.error_message = None
            task.session_id = None
            task.interrupt_reason = None
            task.interrupted_by_id = None
            task.interrupted_at = None
            db.commit()

            job = ai_job_service.create_task_chat_job(
                db,
                workspace_id=ws_id,
                task_id=task.id,
                creator_id=current_user.id,
                prompt_text=prompt,
                context_json={"source": "task_start", "fresh_session": True},
            )
            await ai_job_service.enqueue_task_chat_job(job.id)

            return {"msg": "Task started", "task_id": task.id, "job": ai_job_service.serialize_job(job)}
    except LockAcquireTimeout as exc:
        _raise_task_lock_conflict(exc)


@router.post("/{task_id}/initialize")
async def initialize_task(
    ws_id: str,
    task_id: str,
    body: InitializeRequest = Body(default=InitializeRequest()),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_permission(
        ws_id,
        current_user,
        db,
        WorkspacePermission.MANAGE_TASK_STATUS,
        "No permission to initialize tasks",
    )

    try:
        async with lock_task(task_id):
            task = task_service.get_task(db, task_id, ws_id)
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            _ensure_task_not_baselined(task)
            if task.status == TaskStatus.PROVISIONING:
                raise HTTPException(
                    status_code=409,
                    detail="Task is still being provisioned. Please wait until the workspace is ready.",
                )

            cancelled_job_ids = ai_job_service.mark_task_chat_jobs_cancelled(
                db,
                workspace_id=ws_id,
                task_id=task_id,
                message="Task initialized with a fresh session",
            )
            engine = get_engine(task_id)
            if engine:
                await engine.stop()
            for old_job_id in cancelled_job_ids:
                await ai_job_service.publish_job(old_job_id, final=True)

            if body.skill_ids is not None:
                try:
                    task_service.replace_task_skills_for_initialize(
                        db,
                        task,
                        workspace_id=ws_id,
                        skill_ids=body.skill_ids,
                        keep_deleted_runtime_skills=body.keep_deleted_runtime_skills is not False,
                    )
                    db.refresh(task)
                except ValueError as exc:
                    raise HTTPException(status_code=int(getattr(exc, "status_code", 400)), detail=str(exc))

            task.retry_count += 1
            task.status = TaskStatus.CODING
            task.error_message = None
            task.session_id = None
            task.interrupt_reason = None
            task.interrupted_by_id = None
            task.interrupted_at = None
            db.commit()
            db.refresh(task)

            prompt = task.description or f"Please start task '{task.name}'."
            if task.spec_doc_path:
                abs_path = os.path.abspath(task.spec_doc_path)
                prompt += (
                    "\n\nPlease read and strictly implement all requirements in the specification file. "
                    f"Absolute path: {abs_path}"
                )

            prompt += _diagnosis_prompt_suffix(task)

            init_reason_text = (body.reason or "").strip()
            task_service.save_chat_message(
                db,
                task_id,
                ws_id,
                current_user.id,
                role="system",
                content=init_reason_text,
                message_type="init_reason",
            )
            prompt_message = task_service.save_chat_message(
                db,
                task_id,
                ws_id,
                current_user.id,
                role="user",
                content=prompt,
            )

            job = ai_job_service.create_task_chat_job(
                db,
                workspace_id=ws_id,
                task_id=task.id,
                creator_id=current_user.id,
                prompt_text=prompt,
                context_json={
                    "source": "task_initialize",
                    "fresh_session": True,
                    "initialize_reason": init_reason_text,
                },
                chat_message_id=prompt_message.id,
            )
            await ai_job_service.enqueue_task_chat_job(job.id)

            return {"msg": "Task initialized", "job": ai_job_service.serialize_job(job)}
    except LockAcquireTimeout as exc:
        _raise_task_lock_conflict(exc)


@router.get("/{task_id}/skills/runtime", response_model=TaskRuntimeSkillsResponse)
def get_task_runtime_skills(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user, db)
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
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
    verify_workspace_access(ws_id, current_user, db)
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    payload = skill_runtime_trace_service.list_task_runtime_events(
        db,
        task,
        skill_id=skill_id,
        event_type=event_type,
        limit=limit,
        group_by_skill=group_by_skill,
    )
    return TaskSkillRuntimeEventsResponse(**payload)


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
    verify_workspace_access(ws_id, current_user, db)
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
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


@router.get("/{task_id}/skills/{skill_id}/files/tree", response_model=TaskSkillRuntimeFileTreeResponse)
def get_task_runtime_skill_file_tree(
    ws_id: str,
    task_id: str,
    skill_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user, db)
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
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
    verify_workspace_access(ws_id, current_user, db)
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
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
async def write_task_runtime_skill_file_content(
    ws_id: str,
    task_id: str,
    skill_id: str,
    body: TaskSkillRuntimeFileWriteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_permission(
        ws_id,
        current_user,
        db,
        WorkspacePermission.MANAGE_TASK_STATUS,
        "No permission to edit runtime task skills",
    )
    try:
        task = task_service.get_task(db, task_id, ws_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        _ensure_task_not_baselined(task)
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


@router.post("/{task_id}/interrupt")
async def interrupt_task(
    ws_id: str,
    task_id: str,
    body: TaskInterruptRequest = Body(default=TaskInterruptRequest()),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_permission(
        ws_id,
        current_user,
        db,
        WorkspacePermission.MANAGE_TASK_STATUS,
        "No permission to interrupt tasks",
    )

    try:
        async with lock_task(task_id):
            task = task_service.get_task(db, task_id, ws_id)
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            _ensure_task_not_baselined(task)
            return await task_session_control_service.interrupt_task(
                db,
                task=task,
                actor_user_id=current_user.id,
                reason=body.reason,
            )
    except LockAcquireTimeout as exc:
        _raise_task_lock_conflict(exc)
    except task_session_control_service.TaskSessionControlError as exc:
        _raise_session_control_error(exc)


@router.post("/{task_id}/resume-interrupted")
async def resume_interrupted_task(
    ws_id: str,
    task_id: str,
    body: TaskResumeInterruptedRequest = Body(default=TaskResumeInterruptedRequest()),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_permission(
        ws_id,
        current_user,
        db,
        WorkspacePermission.START_TASK,
        "No permission to resume tasks",
    )

    try:
        async with lock_task(task_id):
            task = task_service.get_task(db, task_id, ws_id)
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            _ensure_task_not_baselined(task)
            return await task_session_control_service.resume_interrupted_task(
                db,
                task=task,
                actor_user_id=current_user.id,
                prompt=body.prompt,
                confirm_continue=body.confirm_continue,
            )
    except LockAcquireTimeout as exc:
        _raise_task_lock_conflict(exc)
    except task_session_control_service.TaskSessionControlError as exc:
        _raise_session_control_error(exc)


@router.delete("/{task_id}")
async def delete_task(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_permission(
        ws_id,
        current_user,
        db,
        WorkspacePermission.DELETE_TASK,
        "No permission to delete tasks",
    )

    current_task = task_service.get_task(db, task_id, ws_id)
    if not current_task:
        raise HTTPException(status_code=404, detail="Task not found")
    _ensure_task_not_baselined(current_task)
    use_workspace_lock = bool(str(current_task.git_repo_url or "").strip()) and _workspace_uses_git_worktree(db, ws_id)

    try:
        async with AsyncExitStack() as stack:
            if use_workspace_lock:
                try:
                    await stack.enter_async_context(lock_workspace_repo(ws_id))
                except LockAcquireTimeout as exc:
                    _raise_workspace_lock_conflict(exc)
            try:
                await stack.enter_async_context(lock_task(task_id))
            except LockAcquireTimeout as exc:
                _raise_task_lock_conflict(exc)

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
        current_user,
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
    verify_workspace_access(ws_id, current_user, db)
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
        current_user,
        db,
        WorkspacePermission.MANAGE_TASK_STATUS,
        "No permission to clear task history",
    )
    try:
        async with lock_task(task_id):
            task = task_service.get_task(db, task_id, ws_id)
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            _ensure_task_not_baselined(task)
            engine = get_engine(task_id)
            if (engine and engine.running) or task.status == TaskStatus.CODING:
                raise HTTPException(status_code=409, detail=_TASK_RUNNING_MSG)
            return task_service.clear_task_history(db, task_id, ws_id)
    except LockAcquireTimeout as exc:
        _raise_task_lock_conflict(exc)


@router.get("/{task_id}/ai-jobs", response_model=AiJobListResponse)
def list_task_ai_jobs(
    ws_id: str,
    task_id: str,
    active_only: bool = Query(default=True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user, db)
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    jobs = ai_job_service.list_task_jobs(
        db,
        task_id=task.id,
        active_only=active_only,
    )
    items = [AiJobResponse(**ai_job_service.serialize_job(item)) for item in jobs]
    return AiJobListResponse(items=items, total=len(items))


@router.get("/{task_id}/spec-bootstrap", response_model=TaskCliBootstrapResponse)
def get_task_spec_bootstrap(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user, db)
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    snapshot = task_cli_state_service.get_bootstrap_snapshot(
        db,
        workspace_id=ws_id,
        task_id=task_id,
    )
    if not snapshot:
        raise HTTPException(status_code=404, detail="Specification baseline not initialized")
    return TaskCliBootstrapResponse(**snapshot)


@router.get("/{task_id}/superpowers-docs", response_model=SuperpowersDocsListResponse)
def list_task_superpowers_docs(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user, db)
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        payload = task_service.list_superpowers_docs(task)
    except ValueError as exc:
        raise HTTPException(status_code=int(getattr(exc, "status_code", 400)), detail=str(exc))

    return SuperpowersDocsListResponse(**payload)


@router.get("/{task_id}/superpowers-docs/content", response_model=SuperpowersDocContentResponse)
def get_task_superpowers_doc_content(
    ws_id: str,
    task_id: str,
    section: str = Query(...),
    name: Optional[str] = Query(default=None),
    path: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user, db)
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        payload = task_service.read_superpowers_doc(task, section=section, name=name, path=path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=int(getattr(exc, "status_code", 400)), detail=str(exc))

    return SuperpowersDocContentResponse(**payload)


@router.put("/{task_id}/superpowers-docs/content", response_model=SuperpowersDocContentResponse)
def save_task_superpowers_doc_content(
    ws_id: str,
    task_id: str,
    body: SuperpowersDocSaveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_permission(
        ws_id,
        current_user,
        db,
        WorkspacePermission.UPLOAD_TASK_SPEC,
        "No permission to edit superpowers documents",
    )

    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    _ensure_task_not_baselined(task)

    try:
        payload = task_service.save_superpowers_doc(
            task,
            section=body.section,
            content=body.content,
            name=body.name,
            path=body.path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=int(getattr(exc, "status_code", 400)), detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save document: {exc}")

    return SuperpowersDocContentResponse(**payload)


@router.post("/{task_id}/upload-spec", response_model=dict)
async def upload_task_spec(
    ws_id: str,
    task_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_permission(
        ws_id,
        current_user,
        db,
        WorkspacePermission.UPLOAD_TASK_SPEC,
        "No permission to upload task specification",
    )

    with bind_task_context(task_id=task_id, workspace_id=ws_id, user_id=current_user.id):
        try:
            async with lock_task(task_id):
                task = task_service.get_task(db, task_id, ws_id)
                if not task:
                    raise HTTPException(status_code=404, detail="Task not found")
                _ensure_task_not_baselined(task)
                content = await file.read()
                file_path, asset_id, version_id = task_service.upload_task_spec(db, task_id, file.filename, content)
                bootstrap = task_cli_state_service.upsert_bootstrap_for_upload(
                    db,
                    workspace_id=ws_id,
                    task_id=task_id,
                    spec_asset_id=asset_id,
                    spec_version_id=version_id,
                )
                db.commit()
                db.refresh(bootstrap)
                asyncio.create_task(task_cli_state_service.publish_bootstrap_snapshot(task_id))
                task_cli_state_service.schedule_bootstrap(task_id)
                return {
                    "status": "success",
                    "path": file_path,
                    "filename": file.filename,
                    "asset_id": asset_id,
                    "version_id": version_id,
                    "spec_bootstrap_status": bootstrap.status.value if hasattr(bootstrap.status, "value") else str(bootstrap.status),
                }
        except LockAcquireTimeout as exc:
            _raise_task_lock_conflict(exc)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception(f"Failed to upload spec for task {task_id}: {exc}")
            raise HTTPException(status_code=500, detail=str(exc))


# ─── 问题定位任务：定位结果与一键转案例 ───


def _require_diagnosis_task(db: Session, task_id: str, ws_id: str):
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if getattr(task, "task_type", None) != "DIAGNOSIS":
        raise HTTPException(status_code=403, detail="Only diagnosis tasks support diagnosis results")
    return task


@router.post("/{task_id}/upload-diagnosis-doc", response_model=dict)
async def upload_task_diagnosis_doc(
    ws_id: str,
    task_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """问题定位任务：上传需求/日志等辅助文档（供 AI 会话与诊断文档抽屉使用）。"""
    verify_workspace_permission(
        ws_id,
        current_user,
        db,
        WorkspacePermission.UPLOAD_TASK_SPEC,
        "No permission to upload diagnosis documents",
    )

    with bind_task_context(task_id=task_id, workspace_id=ws_id, user_id=current_user.id):
        try:
            async with lock_task(task_id):
                task = task_service.get_task(db, task_id, ws_id)
                if not task:
                    raise HTTPException(status_code=404, detail="Task not found")
                _ensure_task_not_baselined(task)
                if getattr(task, "task_type", None) != "DIAGNOSIS":
                    raise HTTPException(status_code=403, detail="Only diagnosis tasks support diagnosis documents")
                content = await file.read()
                if len(content) > 20 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="Diagnosis document is too large (max 20MB)")
                asset, version, cli_path = asset_document_service.create_diagnosis_doc_asset_version(
                    db,
                    task,
                    creator_id=current_user.id,
                    file_name=file.filename,
                    file_content=content,
                    change_note="Uploaded diagnosis document",
                )
                db.commit()
                db.refresh(asset)
                return {
                    "status": "success",
                    "path": cli_path,
                    "filename": file.filename,
                    "asset_id": asset.id,
                    "version_id": version.id,
                }
        except LockAcquireTimeout as exc:
            _raise_task_lock_conflict(exc)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception(f"Failed to upload diagnosis doc for task {task_id}: {exc}")
            raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{task_id}/diagnosis-result", response_model=Optional[DiagnosisResultResponse])
def get_diagnosis_result(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user, db)
    task = _require_diagnosis_task(db, task_id, ws_id)
    result = task.diagnosis_result
    if not result:
        # 尚无定位结果（AI 会话收敛后自动反填）：返回 200 + null，避免 404 噪音
        return None
    return diagnosis_result_service.serialize_diagnosis_result(result)


@router.put("/{task_id}/diagnosis-result", response_model=DiagnosisResultResponse)
def upsert_diagnosis_result(
    ws_id: str,
    task_id: str,
    data: DiagnosisResultUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_permission(
        ws_id,
        current_user,
        db,
        WorkspacePermission.MANAGE_TASK_STATUS,
        "No permission to update diagnosis results",
    )
    task = _require_diagnosis_task(db, task_id, ws_id)

    result = diagnosis_result_service.upsert_diagnosis_result_from_user(
        db,
        task=task,
        data=data,
        actor_user_id=current_user.id,
    )
    audit_log(
        action="diagnosis_result_upsert",
        outcome="success",
        resource_type="task_diagnosis_result",
        resource_id=result.id,
        user_id=current_user.id,
        workspace_id=ws_id,
        task_id=task.id,
    )
    return diagnosis_result_service.serialize_diagnosis_result(result)


@router.post("/{task_id}/case-draft", response_model=CaseResponse, status_code=201)
def create_case_draft_from_task(
    ws_id: str,
    task_id: str,
    data: CaseDraftCreateRequest = Body(default=CaseDraftCreateRequest()),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """问题定位任务：确认采纳 → 一键转案例（生成案例草稿，可一步提交专家评审）。"""
    verify_workspace_permission(
        ws_id,
        current_user,
        db,
        WorkspacePermission.CREATE_TASK,
        "No permission to create cases",
    )
    task = _require_diagnosis_task(db, task_id, ws_id)
    try:
        case = case_service.create_case_draft_from_task(
            db,
            task=task,
            creator=current_user,
            workspace_id=ws_id,
            data=data,
        )
    except case_service.CaseError as exc:
        raise HTTPException(status_code=int(getattr(exc, "status_code", 400)), detail=str(exc))
    member = workspace_service.get_workspace_member(db, ws_id, current_user.id)
    payload = case_service.serialize_case(case)
    payload["my_can_manage"] = True
    payload["my_can_review"] = bool(member.is_expert) if member else False
    return payload


@router.post("/{task_id}/diagnosis-summary", response_model=dict)
async def trigger_diagnosis_summary(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """问题定位任务：一键总结问题案例。

    创建一次性的「诊断总结」后台 AI 任务：汇总问题定位会话过程，按原定位结果
    JSON 契约生成结构化结果，完成后原位刷新「定位结果」卡片并广播到任务房间。
    同任务已有进行中的总结任务时直接返回既有任务（幂等）。
    """
    verify_workspace_permission(
        ws_id,
        current_user,
        db,
        WorkspacePermission.MANAGE_TASK_STATUS,
        "No permission to summarize diagnosis cases",
    )
    task = _require_diagnosis_task(db, task_id, ws_id)

    active_job = (
        db.query(ai_job_service.SddAiJob)
        .filter(
            ai_job_service.SddAiJob.task_id == task.id,
            ai_job_service.SddAiJob.channel == ai_job_service.AiJobChannel.TASK_CHAT,
            ai_job_service.SddAiJob.status.in_(
                [
                    ai_job_service.AiJobStatus.PENDING.value,
                    ai_job_service.AiJobStatus.RUNNING.value,
                ]
            ),
        )
        .order_by(ai_job_service.SddAiJob.created_at.desc())
        .first()
    )
    if active_job is not None:
        active_context = (
            active_job.context_json
            if isinstance(active_job.context_json, dict)
            else {}
        )
        if str(active_context.get("job_kind") or "").strip().upper() == "DIAGNOSIS_SUMMARY":
            return {
                "job_id": active_job.id,
                "status": ai_job_service.serialize_job(active_job).get("status"),
                "task_id": task.id,
            }

    job = ai_job_service.create_diagnosis_summary_job(
        db,
        workspace_id=ws_id,
        task_id=task.id,
        creator_id=current_user.id,
    )
    audit_log(
        action="diagnosis_summary_triggered",
        outcome="success",
        resource_type="ai_job",
        resource_id=job.id,
        user_id=current_user.id,
        workspace_id=ws_id,
        task_id=task.id,
    )
    await ai_job_service.enqueue_task_chat_job(job.id)
    return {"job_id": job.id, "status": "PENDING", "task_id": task.id}


@router.get("/{task_id}/diagnosis-summary/{job_id}", response_model=dict)
def get_diagnosis_summary_status(
    ws_id: str,
    task_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """问题定位任务：查询「一键总结问题案例」后台任务状态（供前端轮询收敛）。"""
    verify_workspace_access(ws_id, current_user, db)
    job = (
        db.query(ai_job_service.SddAiJob)
        .filter(
            ai_job_service.SddAiJob.id == job_id,
            ai_job_service.SddAiJob.task_id == task_id,
        )
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Diagnosis summary job not found")
    payload = ai_job_service.serialize_job(job)
    return {
        "job_id": job.id,
        "task_id": task_id,
        "status": str(payload.get("status") or ""),
        "message": payload.get("message"),
    }
