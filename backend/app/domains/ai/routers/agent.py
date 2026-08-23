"""
Agent-facing APIs for local Electron clients.
"""

from __future__ import annotations

import json
import os
from contextlib import AsyncExitStack
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.core.distributed_lock import LockAcquireTimeout, lock_task, make_resource_busy_error
from app.dependencies import get_current_user, get_db
from app.domains.task.models.task import SddTask
from app.domains.workflow.models.task_change import SddTaskChangeProposal
from app.domains.auth.models.user import User
from app.domains.workflow.schemas.change_proposal import (
    AgentTaskListResponse,
    AgentTaskResponse,
    ApplyResultRequest,
    ApplyResultResponse,
    ChangeProposalFileListResponse,
    ChangeProposalResponse,
    ConflictReportCreateRequest,
    ConflictReportResponse,
    VerificationRunCreateRequest,
    VerificationRunResponse,
)
from app.domains.workflow.services import change_proposal_service
from app.domains.workspace.services import workspace_service

router = APIRouter(prefix="/agent", tags=["Agent"])

_TASK_BUSY_MSG = "Task is being updated by another request. Please retry later."


def _as_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _raise_task_lock_conflict(exc: LockAcquireTimeout) -> None:
    busy = make_resource_busy_error(exc, _TASK_BUSY_MSG)
    raise HTTPException(status_code=busy.status_code, detail=str(busy))


def _verify_workspace_access(db: Session, workspace_id: str, user: User) -> None:
    member = workspace_service.get_workspace_member(db, workspace_id, user.id)
    if not member:
        raise HTTPException(status_code=403, detail="No access to this workspace")


def _get_agent_task_or_error(db: Session, task_id: str, user: User) -> SddTask:
    task = db.query(SddTask).filter(SddTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    _verify_workspace_access(db, task.workspace_id, user)
    return task


def _get_agent_proposal_or_error(db: Session, proposal_id: str, user: User) -> SddTaskChangeProposal:
    proposal = db.query(SddTaskChangeProposal).filter(SddTaskChangeProposal.id == proposal_id).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Change proposal not found")
    _verify_workspace_access(db, proposal.workspace_id, user)
    return proposal


async def _read_upload_with_limit(upload: Any, *, limit: int) -> bytes:
    chunks = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail="Uploaded log/report exceeds size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _safe_download_filename(filename: str) -> str:
    safe = os.path.basename(filename or "change-proposal.patch").replace('"', "")
    return safe or "change-proposal.patch"


@router.get("/tasks", response_model=AgentTaskListResponse)
def list_agent_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items, total = change_proposal_service.list_agent_tasks(
        db,
        user_id=current_user.id,
        page=page,
        page_size=page_size,
    )
    return AgentTaskListResponse(items=[AgentTaskResponse(**item) for item in items], total=total, page=page, page_size=page_size)


@router.get("/tasks/{task_id}", response_model=AgentTaskResponse)
def get_agent_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = _get_agent_task_or_error(db, task_id, current_user)
    return AgentTaskResponse(**change_proposal_service.serialize_agent_task(db, task))


@router.get("/tasks/{task_id}/change-proposals/latest", response_model=Optional[ChangeProposalResponse])
def get_latest_change_proposal(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = _get_agent_task_or_error(db, task_id, current_user)
    proposal = change_proposal_service.get_latest_task_proposal(db, task_id=task.id)
    if not proposal:
        return None
    return proposal


@router.get("/change-proposals/{proposal_id}", response_model=ChangeProposalResponse)
def get_change_proposal(
    proposal_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_agent_proposal_or_error(db, proposal_id, current_user)


@router.get("/change-proposals/{proposal_id}/files", response_model=ChangeProposalFileListResponse)
def list_change_proposal_files(
    proposal_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proposal = _get_agent_proposal_or_error(db, proposal_id, current_user)
    files = change_proposal_service.list_proposal_files(db, proposal_id=proposal.id)
    return ChangeProposalFileListResponse(items=files, total=len(files))


@router.get("/change-proposals/{proposal_id}/repo-patches")
def list_change_proposal_repo_patches(
    proposal_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proposal = _get_agent_proposal_or_error(db, proposal_id, current_user)
    repo_patches = change_proposal_service.list_proposal_repo_patches(db, proposal_id=proposal.id)
    try:
        items = [
            change_proposal_service.serialize_repo_patch(db, repo_patch, include_patch_text=True)
            for repo_patch in repo_patches
        ]
    except change_proposal_service.ChangeProposalError as exc:
        raise HTTPException(status_code=int(getattr(exc, "status_code", 400)), detail=str(exc))
    return {"proposal_id": proposal.id, "items": items, "total": len(items)}


@router.get("/change-proposals/{proposal_id}/patch")
def download_change_proposal_patch(
    proposal_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proposal = _get_agent_proposal_or_error(db, proposal_id, current_user)
    try:
        raw, filename = change_proposal_service.read_patch_file(db, proposal)
        change_proposal_service.mark_patch_downloaded(db, proposal)
    except change_proposal_service.ChangeProposalError as exc:
        raise HTTPException(status_code=int(getattr(exc, "status_code", 400)), detail=str(exc))
    safe_name = _safe_download_filename(filename)
    return Response(
        content=raw,
        media_type="text/x-patch",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


@router.post("/tasks/{task_id}/apply-results", response_model=ApplyResultResponse)
async def submit_apply_result(
    task_id: str,
    data: ApplyResultRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = _get_agent_task_or_error(db, task_id, current_user)
    try:
        async with lock_task(task.id):
            proposal = change_proposal_service.record_apply_result(
                db,
                task=task,
                user=current_user,
                proposal_id=data.proposal_id,
                status=data.status,
                base_commit_sha=data.base_commit_sha,
                local_head_sha=data.local_head_sha,
                message=data.message,
            )
            return ApplyResultResponse(proposal_id=proposal.id, status=_as_value(proposal.status))
    except LockAcquireTimeout as exc:
        _raise_task_lock_conflict(exc)
    except change_proposal_service.ChangeProposalError as exc:
        raise HTTPException(status_code=int(getattr(exc, "status_code", 400)), detail=str(exc))


@router.post("/tasks/{task_id}/verification-runs", response_model=VerificationRunResponse, status_code=201)
async def create_verification_run(
    task_id: str,
    data: VerificationRunCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = _get_agent_task_or_error(db, task_id, current_user)
    try:
        async with lock_task(task.id):
            return change_proposal_service.create_verification_run(
                db,
                task=task,
                user=current_user,
                proposal_id=data.proposal_id,
                agent_id=data.agent_id,
                machine_name=data.machine_name,
                os_name=data.os_name,
                command=data.command,
                status=data.status,
                duration_ms=data.duration_ms,
                base_commit_sha=data.base_commit_sha,
                local_head_sha=data.local_head_sha,
                log_excerpt=data.log_excerpt,
                started_at=data.started_at,
                finished_at=data.finished_at,
            )
    except LockAcquireTimeout as exc:
        _raise_task_lock_conflict(exc)
    except change_proposal_service.ChangeProposalError as exc:
        raise HTTPException(status_code=int(getattr(exc, "status_code", 400)), detail=str(exc))


@router.post("/tasks/{task_id}/verification-runs/{run_id}/logs", response_model=VerificationRunResponse)
async def upload_verification_run_log(
    task_id: str,
    run_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = _get_agent_task_or_error(db, task_id, current_user)
    form = await request.form()
    upload = form.get("file") or form.get("log_file")
    if not upload or not hasattr(upload, "read"):
        raise HTTPException(status_code=422, detail="Multipart file field 'file' is required")
    content = await _read_upload_with_limit(upload, limit=int(settings.TASK_CHANGE_MAX_UPLOAD_BYTES))
    filename = str(getattr(upload, "filename", "") or f"verification-run-{run_id}.log")
    log_excerpt = str(form.get("log_excerpt") or "").strip() or None

    try:
        async with lock_task(task.id):
            return change_proposal_service.attach_verification_log(
                db,
                task=task,
                run_id=run_id,
                user=current_user,
                file_name=filename,
                file_content=content,
                log_excerpt=log_excerpt,
            )
    except LockAcquireTimeout as exc:
        _raise_task_lock_conflict(exc)
    except change_proposal_service.ChangeProposalError as exc:
        raise HTTPException(status_code=int(getattr(exc, "status_code", 400)), detail=str(exc))


def _json_or_none(raw: Optional[str]) -> Any:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return json.loads(str(raw))
    except Exception:
        return [str(raw)]


async def _parse_conflict_request(request: Request) -> tuple[ConflictReportCreateRequest, Optional[str], Optional[bytes]]:
    content_type = str(request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in content_type:
        form = await request.form()
        payload: Dict[str, Any] = {
            "proposal_id": form.get("proposal_id"),
            "agent_id": form.get("agent_id"),
            "machine_name": form.get("machine_name"),
            "base_commit_sha": form.get("base_commit_sha"),
            "local_head_sha": form.get("local_head_sha"),
            "conflicted_files": _json_or_none(form.get("conflicted_files_json") or form.get("conflicted_files")),
            "git_apply_stderr": form.get("git_apply_stderr"),
            "conflict_excerpt": form.get("conflict_excerpt"),
        }
        upload = form.get("file") or form.get("report_file")
        file_name = None
        file_content = None
        if upload and hasattr(upload, "read"):
            file_content = await _read_upload_with_limit(upload, limit=int(settings.TASK_CHANGE_MAX_UPLOAD_BYTES))
            file_name = str(getattr(upload, "filename", "") or "conflict-report.log")
        return ConflictReportCreateRequest.model_validate(payload), file_name, file_content

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Request body must be JSON or multipart/form-data") from exc
    try:
        return ConflictReportCreateRequest.model_validate(payload), None, None
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/conflict-reports", response_model=ConflictReportResponse, status_code=201)
async def create_conflict_report(
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = _get_agent_task_or_error(db, task_id, current_user)
    try:
        data, file_name, file_content = await _parse_conflict_request(request)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        async with AsyncExitStack() as stack:
            try:
                await stack.enter_async_context(lock_task(task.id))
            except LockAcquireTimeout as exc:
                _raise_task_lock_conflict(exc)
            return change_proposal_service.create_conflict_report(
                db,
                task=task,
                user=current_user,
                proposal_id=data.proposal_id,
                agent_id=data.agent_id,
                machine_name=data.machine_name,
                base_commit_sha=data.base_commit_sha,
                local_head_sha=data.local_head_sha,
                conflicted_files=data.conflicted_files,
                git_apply_stderr=data.git_apply_stderr,
                conflict_excerpt=data.conflict_excerpt,
                report_file_name=file_name,
                report_file_content=file_content,
            )
    except change_proposal_service.ChangeProposalError as exc:
        raise HTTPException(status_code=int(getattr(exc, "status_code", 400)), detail=str(exc))
