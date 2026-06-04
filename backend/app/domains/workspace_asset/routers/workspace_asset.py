"""
Workspace Assets API routes.
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.workspace_asset.schemas.workspace_asset import (
    ClarificationCreateRequest,
    ClarificationUpdateRequest,
    ClarificationResponse,
    DecisionCreateRequest,
    DecisionUpdateRequest,
    DecisionResponse,
    EvidenceCreateRequest,
    EvidenceUpdateRequest,
    EvidenceResponse,
    HumanDeltaCreateRequest,
    HumanDeltaUpdateRequest,
    HumanDeltaResponse,
    HumanDeltaSuggestionsResponse,
    HumanReviewCommentCreateRequest,
    HumanReviewCreateRequest,
    HumanReviewUpdateRequest,
    HumanReviewResponse,
    RequirementCreateRequest,
    RequirementDetailResponse,
    RequirementImportBatchResponse,
    RequirementImportConfirmRequest,
    RequirementPreviewJobResponse,
    RequirementSplitRequest,
    RequirementSplitPreviewRequest,
    RequirementTaskLinkRequest,
    RequirementUpdateRequest,
    TaskClarificationsSectionResponse,
    TaskDecisionsSectionResponse,
    TaskDetailResponse,
    TaskDetailSummaryResponse,
    TaskEvidenceSectionResponse,
    TaskFileDiffResponse,
    TaskFileItemResponse,
    TaskFilesSectionResponse,
    TaskFinalSummaryResponse,
    TaskFinalSummaryUpsertRequest,
    TaskHumanDeltasSectionResponse,
    TaskHumanReviewsSectionResponse,
    TaskProcessAuditLogResponse,
    TaskProcessAuditSectionResponse,
    WorkspaceAssetsKnowledgeResponse,
    WorkspaceAssetsOverviewResponse,
    WorkspaceAssetsRequirementsResponse,
    WorkspaceAssetsTasksResponse,
    WorkspaceAssetsTraceabilityResponse,
    WorkbenchDeltaResponse,
)
from app.domains.workspace_asset.schemas.task_final_workflow import (
    ClarificationMessageCreateRequest,
    FinalSummaryDraftRequest,
    FinalWorkflowReviewUpsertRequest,
    FinalWorkflowReviewTargetPreviewResponse,
    TaskFinalWorkflowResponse,
    WorkflowClarificationCreateRequest,
    WorkflowFinalSummaryUpsertRequest,
)
from app.domains.workspace.services import workspace_service
from app.domains.workspace_asset.services import workspace_asset_service, workspace_asset_task_query, workspace_task_detail_service
from app.domains.workspace_asset.services import workspace_task_detail_query, workspace_task_detail_section
from app.domains.workspace_asset.services.task_final_workflow import (
    clarification_service,
    review_service,
    summary_service,
    target_preview_service,
    workflow_state,
)


router = APIRouter(prefix="/workspaces/{ws_id}/workspace-assets", tags=["Workspace Assets"])


def _verify_view_assets(ws_id: str, current_user: User, db: Session) -> None:
    member = workspace_service.get_workspace_member(db, ws_id, current_user.id)
    if not member:
        raise HTTPException(status_code=403, detail="No access to this workspace")
    if not workspace_service.user_has_permission(db, ws_id, current_user.id, WorkspacePermission.VIEW_ASSETS):
        raise HTTPException(status_code=403, detail="Missing VIEW_ASSETS permission")


def _verify_manage_requirements(ws_id: str, current_user: User, db: Session) -> None:
    _verify_view_assets(ws_id, current_user, db)
    if not workspace_service.user_has_permission(db, ws_id, current_user.id, WorkspacePermission.MANAGE_REQUIREMENTS):
        raise HTTPException(status_code=403, detail="Missing MANAGE_REQUIREMENTS permission")


def _verify_manage_task_process_assets(ws_id: str, current_user: User, db: Session) -> None:
    _verify_view_assets(ws_id, current_user, db)
    if not workspace_service.user_has_permission(db, ws_id, current_user.id, WorkspacePermission.MANAGE_TASK_STATUS):
        raise HTTPException(status_code=403, detail="Missing MANAGE_TASK_STATUS permission")


def _can_manage_task_process_assets(ws_id: str, current_user: User, db: Session) -> bool:
    return workspace_service.user_has_permission(db, ws_id, current_user.id, WorkspacePermission.MANAGE_TASK_STATUS)


def _workflow_state_for_user(
    db: Session,
    ws_id: str,
    task_id: str,
    current_user: User,
    *,
    can_manage: Optional[bool] = None,
) -> TaskFinalWorkflowResponse:
    allowed = _can_manage_task_process_assets(ws_id, current_user, db) if can_manage is None else can_manage
    return workflow_state.get_workflow_state(
        db,
        ws_id,
        task_id,
        can_write_final_workflow=allowed,
        can_resolve_clarification=allowed,
    )


def _raise_write_error(exc: workspace_asset_service.WorkspaceAssetWriteError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc))


def _raise_task_detail_write_error(exc: workspace_task_detail_service.TaskDetailWriteError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc))


def _task_detail_or_404(db: Session, ws_id: str, task_id: str) -> TaskDetailResponse:
    result = workspace_asset_service.get_task_detail(db, ws_id, task_id)
    if not result:
        raise HTTPException(status_code=404, detail="Task not found")
    return result


@router.get("/overview", response_model=WorkspaceAssetsOverviewResponse)
def get_workspace_assets_overview(
    ws_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    return workspace_asset_service.get_overview(db, ws_id)


@router.get("/requirements", response_model=WorkspaceAssetsRequirementsResponse)
def list_workspace_asset_requirements(
    ws_id: str,
    q: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    priority: Optional[str] = Query(default=None),
    source_kind: Optional[str] = Query(default=None),
    parent_id: Optional[str] = Query(default=None),
    scope: str = Query(default="tree", pattern="^(tree|flat|children)$"),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    return workspace_asset_service.list_requirements(
        db,
        ws_id,
        q=q,
        status=status,
        priority=priority,
        source_kind=source_kind,
        parent_id=parent_id,
        scope=scope,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )


@router.post("/requirements", response_model=RequirementDetailResponse, status_code=status.HTTP_201_CREATED)
def create_workspace_asset_requirement(
    ws_id: str,
    payload: RequirementCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_requirements(ws_id, current_user, db)
    try:
        return workspace_asset_service.create_requirement(db, ws_id, current_user.id, payload)
    except workspace_asset_service.WorkspaceAssetWriteError as exc:
        _raise_write_error(exc)


@router.post(
    "/requirements/imports",
    response_model=RequirementPreviewJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_workspace_asset_requirement_import_preview(
    ws_id: str,
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(default=None),
    text: Optional[str] = Form(default=None),
    source_kind: Optional[str] = Form(default="document"),
    source_uri: Optional[str] = Form(default=None),
    source_ref: Optional[str] = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_requirements(ws_id, current_user, db)
    if file is not None:
        file_name = file.filename or "requirements.md"
        raw = await file.read()
    else:
        file_name = "requirements.md"
        raw = (text or "").encode("utf-8")
    if not raw:
        raise HTTPException(status_code=422, detail="Requirement import content is required")
    try:
        response = workspace_asset_service.create_requirement_import_preview_job(
            db,
            ws_id,
            current_user.id,
            file_name=file_name,
            raw=raw,
            source_kind=source_kind,
            source_uri=source_uri,
            source_ref=source_ref,
        )
        background_tasks.add_task(
            workspace_asset_service.run_requirement_import_preview_job,
            response.job_id,
            file_name=file_name,
            raw=raw,
            source_kind=source_kind,
            source_uri=source_uri,
            source_ref=source_ref,
        )
        return response
    except workspace_asset_service.WorkspaceAssetWriteError as exc:
        _raise_write_error(exc)


@router.post(
    "/requirements/imports/direct",
    response_model=RequirementDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_asset_requirement_direct_import(
    ws_id: str,
    file: Optional[UploadFile] = File(default=None),
    text: Optional[str] = Form(default=None),
    source_kind: Optional[str] = Form(default="document"),
    source_uri: Optional[str] = Form(default=None),
    source_ref: Optional[str] = Form(default=None),
    change_reason: Optional[str] = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_requirements(ws_id, current_user, db)
    if file is not None:
        file_name = file.filename or "requirements.md"
        raw = await file.read()
    else:
        file_name = "requirements.md"
        raw = (text or "").encode("utf-8")
    if not raw:
        raise HTTPException(status_code=422, detail="Requirement import content is required")
    try:
        return workspace_asset_service.create_requirement_direct_import(
            db,
            ws_id,
            current_user.id,
            file_name=file_name,
            raw=raw,
            source_kind=source_kind,
            source_uri=source_uri,
            source_ref=source_ref,
            change_reason=change_reason,
        )
    except workspace_asset_service.WorkspaceAssetWriteError as exc:
        _raise_write_error(exc)


@router.get("/requirements/preview-jobs/{job_id}", response_model=RequirementPreviewJobResponse)
def get_workspace_asset_requirement_preview_job(
    ws_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_requirements(ws_id, current_user, db)
    result = workspace_asset_service.get_requirement_preview_job(db, ws_id, job_id)
    if not result:
        raise HTTPException(status_code=404, detail="Requirement preview job not found")
    return result


@router.post("/requirements/imports/{batch_id}/confirm", response_model=RequirementImportBatchResponse)
def confirm_workspace_asset_requirement_import(
    ws_id: str,
    batch_id: str,
    payload: RequirementImportConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_requirements(ws_id, current_user, db)
    try:
        result = workspace_asset_service.confirm_requirement_import(db, ws_id, batch_id, current_user.id, payload)
    except workspace_asset_service.WorkspaceAssetWriteError as exc:
        _raise_write_error(exc)
    if not result:
        raise HTTPException(status_code=404, detail="Requirement import batch not found")
    return result


@router.get("/requirements/{requirement_id}", response_model=RequirementDetailResponse)
def get_workspace_asset_requirement_detail(
    ws_id: str,
    requirement_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    result = workspace_asset_service.get_requirement_detail(db, ws_id, requirement_id)
    if not result:
        raise HTTPException(status_code=404, detail="Requirement not found")
    return result


@router.patch("/requirements/{requirement_id}", response_model=RequirementDetailResponse)
def update_workspace_asset_requirement(
    ws_id: str,
    requirement_id: str,
    payload: RequirementUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_requirements(ws_id, current_user, db)
    try:
        result = workspace_asset_service.update_requirement(db, ws_id, requirement_id, current_user.id, payload)
    except workspace_asset_service.WorkspaceAssetWriteError as exc:
        _raise_write_error(exc)
    if not result:
        raise HTTPException(status_code=404, detail="Requirement not found")
    return result


@router.post("/requirements/{requirement_id}/tasks", response_model=RequirementDetailResponse)
def link_workspace_asset_requirement_task(
    ws_id: str,
    requirement_id: str,
    payload: RequirementTaskLinkRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_requirements(ws_id, current_user, db)
    try:
        result = workspace_asset_service.link_requirement_task(db, ws_id, requirement_id, current_user.id, payload)
    except workspace_asset_service.WorkspaceAssetWriteError as exc:
        _raise_write_error(exc)
    if not result:
        raise HTTPException(status_code=404, detail="Requirement not found")
    return result


@router.delete("/requirements/{requirement_id}/tasks/{task_id}", response_model=RequirementDetailResponse)
def unlink_workspace_asset_requirement_task(
    ws_id: str,
    requirement_id: str,
    task_id: str,
    change_reason: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_requirements(ws_id, current_user, db)
    try:
        result = workspace_asset_service.unlink_requirement_task(
            db,
            ws_id,
            requirement_id,
            task_id,
            current_user.id,
            change_reason=change_reason,
        )
    except workspace_asset_service.WorkspaceAssetWriteError as exc:
        _raise_write_error(exc)
    if not result:
        raise HTTPException(status_code=404, detail="Requirement not found")
    return result


@router.post(
    "/requirements/{requirement_id}/split-preview",
    response_model=RequirementPreviewJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_workspace_asset_requirement_split_preview(
    ws_id: str,
    requirement_id: str,
    payload: RequirementSplitPreviewRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_requirements(ws_id, current_user, db)
    try:
        result = workspace_asset_service.create_requirement_split_preview_job(
            db,
            ws_id,
            requirement_id,
            current_user.id,
            change_reason=payload.change_reason,
        )
    except workspace_asset_service.WorkspaceAssetWriteError as exc:
        _raise_write_error(exc)
    if not result:
        raise HTTPException(status_code=404, detail="Requirement not found")
    background_tasks.add_task(workspace_asset_service.run_requirement_split_preview_job, result.job_id)
    return result


@router.post("/requirements/{requirement_id}/split", response_model=RequirementImportBatchResponse)
def confirm_workspace_asset_requirement_split(
    ws_id: str,
    requirement_id: str,
    payload: RequirementSplitRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_requirements(ws_id, current_user, db)
    try:
        result = workspace_asset_service.confirm_requirement_split(db, ws_id, requirement_id, current_user.id, payload)
    except workspace_asset_service.WorkspaceAssetWriteError as exc:
        _raise_write_error(exc)
    if not result:
        raise HTTPException(status_code=404, detail="Requirement not found")
    return result


@router.get("/tasks", response_model=WorkspaceAssetsTasksResponse)
def list_workspace_asset_tasks(
    ws_id: str,
    q: Optional[str] = Query(None, description="Search task name or description"),
    requirement_q: Optional[str] = Query(None, description="Search associated requirement title"),
    status: Optional[str] = Query(None, description="Filter by status"),
    current_phase: Optional[str] = Query(None, description="Filter by current phase"),
    sort_by: str = Query("created_at", description="Sort field"),
    sort_order: str = Query("desc", description="Sort order (asc/desc)"),
    page: int = Query(1, description="Page number, 1-indexed"),
    page_size: int = Query(50, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    return workspace_asset_task_query.list_tasks(
        db,
        ws_id,
        q=q,
        requirement_q=requirement_q,
        status=status,
        current_phase=current_phase,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )


def _task_summary_or_404(db: Session, ws_id: str, task_id: str) -> TaskDetailSummaryResponse:
    result = workspace_task_detail_query.get_task_detail_summary(db, ws_id, task_id)
    if not result:
        raise HTTPException(status_code=404, detail="Task not found")
    return result


@router.get("/tasks/{task_id}/summary", response_model=TaskDetailSummaryResponse)
def get_workspace_asset_task_summary(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    return _task_summary_or_404(db, ws_id, task_id)


@router.get("/tasks/{task_id}/files", response_model=TaskFilesSectionResponse)
def list_workspace_asset_task_files(
    ws_id: str,
    task_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    return workspace_task_detail_section.get_task_files(db, ws_id, task_id, page=page, page_size=page_size)


@router.get("/tasks/{task_id}/files/{file_id}", response_model=TaskFileItemResponse)
def get_workspace_asset_task_file_detail(
    ws_id: str,
    task_id: str,
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    result = workspace_task_detail_section.get_task_file_detail(db, ws_id, task_id, file_id)
    if not result:
        raise HTTPException(status_code=404, detail="File not found")
    return result


@router.get("/tasks/{task_id}/files/{file_id}/diff", response_model=TaskFileDiffResponse)
def get_workspace_asset_task_file_diff(
    ws_id: str,
    task_id: str,
    file_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    result = workspace_task_detail_section.get_task_file_diff(db, ws_id, task_id, file_id)
    if not result:
        raise HTTPException(status_code=404, detail="Diff not available for this file")
    return result


@router.get("/tasks/{task_id}/human-reviews", response_model=TaskHumanReviewsSectionResponse)
def list_workspace_asset_task_human_reviews(
    ws_id: str,
    task_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    return workspace_task_detail_section.get_task_human_reviews(db, ws_id, task_id, page=page, page_size=page_size)


@router.get("/tasks/{task_id}/human-reviews/{review_id}", response_model=HumanReviewResponse)
def get_workspace_asset_task_human_review_detail(
    ws_id: str,
    task_id: str,
    review_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    result = workspace_task_detail_section.get_task_human_review_detail(db, ws_id, task_id, review_id)
    if not result:
        raise HTTPException(status_code=404, detail="Review not found")
    return result


@router.get("/tasks/{task_id}/human-deltas", response_model=TaskHumanDeltasSectionResponse)
def list_workspace_asset_task_human_deltas(
    ws_id: str,
    task_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    return workspace_task_detail_section.get_task_human_deltas(db, ws_id, task_id, page=page, page_size=page_size)


@router.get("/tasks/{task_id}/human-deltas/suggestions", response_model=HumanDeltaSuggestionsResponse)
def get_workspace_asset_task_human_delta_suggestions(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    from app.domains.workspace_asset.services.human_delta_compare_service import suggest_deltas

    items = suggest_deltas(db, ws_id, task_id)
    return HumanDeltaSuggestionsResponse(items=items)


@router.get("/tasks/{task_id}/human-deltas/{delta_id}", response_model=HumanDeltaResponse)
def get_workspace_asset_task_human_delta_detail(
    ws_id: str,
    task_id: str,
    delta_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    result = workspace_task_detail_section.get_task_human_delta_detail(db, ws_id, task_id, delta_id)
    if not result:
        raise HTTPException(status_code=404, detail="Delta not found")
    return result


@router.get("/tasks/{task_id}/human-deltas/{delta_id}/workbench", response_model=WorkbenchDeltaResponse)
def get_workspace_asset_task_delta_workbench(
    ws_id: str,
    task_id: str,
    delta_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    result = workspace_task_detail_section.get_task_delta_workbench(db, ws_id, task_id, delta_id)
    if not result:
        raise HTTPException(status_code=404, detail="Delta not found")
    return result


@router.post("/tasks/{task_id}/human-deltas/{delta_id}/compare", response_model=TaskDetailSummaryResponse)
async def compare_workspace_asset_task_human_delta(
    ws_id: str,
    task_id: str,
    delta_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_process_assets(ws_id, current_user, db)
    from app.core.distributed_lock import LockAcquireTimeout, make_resource_busy_error, queue_workspace_compare_jobs
    from app.domains.workspace_asset.services.human_delta_compare_service import HumanDeltaError, compare_patches

    try:
        async with queue_workspace_compare_jobs(workspace_id=ws_id):
            await asyncio.to_thread(compare_patches, db, ws_id, task_id, delta_id, current_user.id)
    except HumanDeltaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except LockAcquireTimeout as exc:
        busy = make_resource_busy_error(exc, "Compare queue busy, please retry later.")
        raise HTTPException(status_code=busy.status_code, detail=str(busy)) from exc
    return _task_summary_or_404(db, ws_id, task_id)


@router.get("/tasks/{task_id}/evidence", response_model=TaskEvidenceSectionResponse)
def list_workspace_asset_task_evidence(
    ws_id: str,
    task_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    return workspace_task_detail_section.get_task_evidence(db, ws_id, task_id, page=page, page_size=page_size)


@router.get("/tasks/{task_id}/evidence/{evidence_id}", response_model=EvidenceResponse)
def get_workspace_asset_task_evidence_detail(
    ws_id: str,
    task_id: str,
    evidence_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    result = workspace_task_detail_section.get_task_evidence_detail(db, ws_id, task_id, evidence_id)
    if not result:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return result


@router.get("/tasks/{task_id}/decisions", response_model=TaskDecisionsSectionResponse)
def list_workspace_asset_task_decisions(
    ws_id: str,
    task_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    return workspace_task_detail_section.get_task_decisions(db, ws_id, task_id, page=page, page_size=page_size)


@router.get("/tasks/{task_id}/decisions/{decision_id}", response_model=DecisionResponse)
def get_workspace_asset_task_decision_detail(
    ws_id: str,
    task_id: str,
    decision_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    result = workspace_task_detail_section.get_task_decision_detail(db, ws_id, task_id, decision_id)
    if not result:
        raise HTTPException(status_code=404, detail="Decision not found")
    return result


@router.get("/tasks/{task_id}/clarifications", response_model=TaskClarificationsSectionResponse)
def list_workspace_asset_task_clarifications(
    ws_id: str,
    task_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    return workspace_task_detail_section.get_task_clarifications(db, ws_id, task_id, page=page, page_size=page_size)


@router.get("/tasks/{task_id}/clarifications/{clarification_id}", response_model=ClarificationResponse)
def get_workspace_asset_task_clarification_detail(
    ws_id: str,
    task_id: str,
    clarification_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    result = workspace_task_detail_section.get_task_clarification_detail(db, ws_id, task_id, clarification_id)
    if not result:
        raise HTTPException(status_code=404, detail="Clarification not found")
    return result


@router.get("/tasks/{task_id}/final-summary", response_model=TaskFinalSummaryResponse)
def get_workspace_asset_task_final_summary(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    result = workspace_task_detail_section.get_task_final_summary(db, ws_id, task_id)
    if not result:
        raise HTTPException(status_code=404, detail="Final summary not found")
    return result


@router.get("/tasks/{task_id}/final-workflow", response_model=TaskFinalWorkflowResponse)
def get_workspace_asset_task_final_workflow(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    try:
        return _workflow_state_for_user(db, ws_id, task_id, current_user)
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        _raise_task_detail_write_error(exc)


@router.get(
    "/tasks/{task_id}/final-workflow/review-targets/{target_type}/{target_id}/preview",
    response_model=FinalWorkflowReviewTargetPreviewResponse,
)
def get_workspace_asset_task_final_workflow_review_target_preview(
    ws_id: str,
    task_id: str,
    target_type: str,
    target_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    try:
        return target_preview_service.get_review_target_preview(db, ws_id, task_id, target_type, target_id)
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        _raise_task_detail_write_error(exc)


@router.post(
    "/tasks/{task_id}/final-workflow/reviews",
    response_model=TaskFinalWorkflowResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace_asset_task_final_workflow_review(
    ws_id: str,
    task_id: str,
    payload: FinalWorkflowReviewUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_process_assets(ws_id, current_user, db)
    try:
        review_service.create_review(db, ws_id, task_id, current_user.id, payload)
        return _workflow_state_for_user(db, ws_id, task_id, current_user, can_manage=True)
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        _raise_task_detail_write_error(exc)


@router.put("/tasks/{task_id}/final-workflow/reviews/{review_id}", response_model=TaskFinalWorkflowResponse)
def update_workspace_asset_task_final_workflow_review(
    ws_id: str,
    task_id: str,
    review_id: str,
    payload: FinalWorkflowReviewUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_process_assets(ws_id, current_user, db)
    try:
        review_service.update_review(db, ws_id, task_id, review_id, current_user.id, payload)
        return _workflow_state_for_user(db, ws_id, task_id, current_user, can_manage=True)
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        _raise_task_detail_write_error(exc)


@router.post("/tasks/{task_id}/final-workflow/clarifications", response_model=TaskFinalWorkflowResponse, status_code=status.HTTP_201_CREATED)
def create_workspace_asset_task_final_workflow_clarification(
    ws_id: str,
    task_id: str,
    payload: WorkflowClarificationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_process_assets(ws_id, current_user, db)
    try:
        clarification_service.create_workflow_clarification(
            db,
            ws_id,
            task_id,
            current_user.id,
            ClarificationCreateRequest(
                requirement_id=payload.requirement_id,
                source_review_id=payload.source_review_id,
                source_evidence_id=payload.source_evidence_id,
                blocking_level=payload.blocking_level,
                question=payload.question,
                clarification_type=payload.clarification_type,
                target_ref=payload.target_ref,
                urgency=payload.urgency,
                change_reason=payload.change_reason,
            ),
        )
        return _workflow_state_for_user(db, ws_id, task_id, current_user, can_manage=True)
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        _raise_task_detail_write_error(exc)


@router.post(
    "/tasks/{task_id}/final-workflow/clarifications/{clarification_id}/messages",
    response_model=TaskFinalWorkflowResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace_asset_task_final_workflow_clarification_message(
    ws_id: str,
    task_id: str,
    clarification_id: str,
    payload: ClarificationMessageCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_process_assets(ws_id, current_user, db)
    try:
        clarification_service.add_message(db, ws_id, task_id, clarification_id, current_user.id, payload)
        return _workflow_state_for_user(db, ws_id, task_id, current_user, can_manage=True)
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        _raise_task_detail_write_error(exc)


@router.post("/tasks/{task_id}/final-workflow/final-summary/draft", response_model=TaskFinalWorkflowResponse)
def create_workspace_asset_task_final_summary_draft(
    ws_id: str,
    task_id: str,
    payload: FinalSummaryDraftRequest = FinalSummaryDraftRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_process_assets(ws_id, current_user, db)
    try:
        summary_service.draft_final_summary(db, ws_id, task_id, current_user.id, payload)
        return _workflow_state_for_user(db, ws_id, task_id, current_user, can_manage=True)
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        _raise_task_detail_write_error(exc)


@router.put("/tasks/{task_id}/final-workflow/final-summary", response_model=TaskFinalWorkflowResponse)
def upsert_workspace_asset_task_final_workflow_summary(
    ws_id: str,
    task_id: str,
    payload: WorkflowFinalSummaryUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_process_assets(ws_id, current_user, db)
    try:
        summary_service.upsert_final_summary(db, ws_id, task_id, current_user.id, payload)
        return _workflow_state_for_user(db, ws_id, task_id, current_user, can_manage=True)
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        _raise_task_detail_write_error(exc)


@router.post("/tasks/{task_id}/final-workflow/baseline", response_model=TaskFinalWorkflowResponse)
def baseline_workspace_asset_task_final_workflow(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_process_assets(ws_id, current_user, db)
    try:
        summary_service.baseline_task(db, ws_id, task_id, current_user.id)
        return _workflow_state_for_user(db, ws_id, task_id, current_user, can_manage=True)
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        _raise_task_detail_write_error(exc)


@router.get("/tasks/{task_id}/process-audit", response_model=TaskProcessAuditSectionResponse)
def list_workspace_asset_task_process_audit(
    ws_id: str,
    task_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    return workspace_task_detail_section.get_task_process_audit(db, ws_id, task_id, page=page, page_size=page_size)


@router.get("/tasks/{task_id}/process-audit/{log_id}", response_model=TaskProcessAuditLogResponse)
def get_workspace_asset_task_process_audit_detail(
    ws_id: str,
    task_id: str,
    log_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    result = workspace_task_detail_section.get_task_process_audit_detail(db, ws_id, task_id, log_id)
    if not result:
        raise HTTPException(status_code=404, detail="Audit log not found")
    return result


@router.get("/tasks/{task_id}", response_model=TaskDetailResponse)
def get_workspace_asset_task_detail(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    return _task_detail_or_404(db, ws_id, task_id)


@router.post("/tasks/{task_id}/human-reviews", response_model=TaskDetailSummaryResponse, status_code=status.HTTP_201_CREATED)
def create_workspace_asset_task_human_review(
    ws_id: str,
    task_id: str,
    payload: HumanReviewCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_process_assets(ws_id, current_user, db)
    try:
        workspace_task_detail_service.create_human_review(db, ws_id, task_id, current_user.id, payload)
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        _raise_task_detail_write_error(exc)
    return _task_summary_or_404(db, ws_id, task_id)


@router.patch("/tasks/{task_id}/human-reviews/{review_id}", response_model=TaskDetailSummaryResponse)
def update_workspace_asset_task_human_review(
    ws_id: str,
    task_id: str,
    review_id: str,
    payload: HumanReviewUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_process_assets(ws_id, current_user, db)
    try:
        workspace_task_detail_service.update_human_review(db, ws_id, task_id, review_id, current_user.id, payload)
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        _raise_task_detail_write_error(exc)
    return _task_summary_or_404(db, ws_id, task_id)


@router.post(
    "/tasks/{task_id}/human-reviews/{review_id}/comments",
    response_model=TaskDetailSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace_asset_task_human_review_comment(
    ws_id: str,
    task_id: str,
    review_id: str,
    payload: HumanReviewCommentCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_process_assets(ws_id, current_user, db)
    try:
        workspace_task_detail_service.create_human_review_comment(db, ws_id, task_id, review_id, current_user.id, payload)
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        _raise_task_detail_write_error(exc)
    return _task_summary_or_404(db, ws_id, task_id)


@router.post("/tasks/{task_id}/human-deltas", response_model=TaskDetailSummaryResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace_asset_task_human_delta(
    ws_id: str,
    task_id: str,
    payload: HumanDeltaCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_process_assets(ws_id, current_user, db)
    from app.core.distributed_lock import LockAcquireTimeout, make_resource_busy_error, queue_workspace_compare_jobs

    try:
        async with queue_workspace_compare_jobs(workspace_id=ws_id):
            await asyncio.to_thread(
                workspace_task_detail_service.create_human_delta,
                db, ws_id, task_id, current_user.id, payload,
            )
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        _raise_task_detail_write_error(exc)
    except LockAcquireTimeout as exc:
        busy = make_resource_busy_error(exc, "Compare queue busy, please retry later.")
        raise HTTPException(status_code=busy.status_code, detail=str(busy)) from exc
    return _task_summary_or_404(db, ws_id, task_id)


@router.patch("/tasks/{task_id}/human-deltas/{delta_id}", response_model=TaskDetailSummaryResponse)
def update_workspace_asset_task_human_delta(
    ws_id: str,
    task_id: str,
    delta_id: str,
    payload: HumanDeltaUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_process_assets(ws_id, current_user, db)
    try:
        workspace_task_detail_service.update_human_delta(db, ws_id, task_id, delta_id, current_user.id, payload)
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        _raise_task_detail_write_error(exc)
    return _task_summary_or_404(db, ws_id, task_id)


@router.post("/tasks/{task_id}/evidence", response_model=TaskDetailSummaryResponse, status_code=status.HTTP_201_CREATED)
def create_workspace_asset_task_evidence(
    ws_id: str,
    task_id: str,
    payload: EvidenceCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_process_assets(ws_id, current_user, db)
    try:
        workspace_task_detail_service.create_evidence(db, ws_id, task_id, current_user.id, payload)
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        _raise_task_detail_write_error(exc)
    return _task_summary_or_404(db, ws_id, task_id)


@router.patch("/tasks/{task_id}/evidence/{evidence_id}", response_model=TaskDetailSummaryResponse)
def update_workspace_asset_task_evidence(
    ws_id: str,
    task_id: str,
    evidence_id: str,
    payload: EvidenceUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_process_assets(ws_id, current_user, db)
    try:
        workspace_task_detail_service.update_evidence(db, ws_id, task_id, evidence_id, current_user.id, payload)
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        _raise_task_detail_write_error(exc)
    return _task_summary_or_404(db, ws_id, task_id)


@router.post("/tasks/{task_id}/decisions", response_model=TaskDetailSummaryResponse, status_code=status.HTTP_201_CREATED)
def create_workspace_asset_task_decision(
    ws_id: str,
    task_id: str,
    payload: DecisionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_process_assets(ws_id, current_user, db)
    try:
        workspace_task_detail_service.create_decision(db, ws_id, task_id, current_user.id, payload)
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        _raise_task_detail_write_error(exc)
    return _task_summary_or_404(db, ws_id, task_id)


@router.patch("/tasks/{task_id}/decisions/{decision_id}", response_model=TaskDetailSummaryResponse)
def update_workspace_asset_task_decision(
    ws_id: str,
    task_id: str,
    decision_id: str,
    payload: DecisionUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_process_assets(ws_id, current_user, db)
    try:
        workspace_task_detail_service.update_decision(db, ws_id, task_id, decision_id, current_user.id, payload)
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        _raise_task_detail_write_error(exc)
    return _task_summary_or_404(db, ws_id, task_id)


@router.post("/tasks/{task_id}/clarifications", response_model=TaskDetailSummaryResponse, status_code=status.HTTP_201_CREATED)
def create_workspace_asset_task_clarification(
    ws_id: str,
    task_id: str,
    payload: ClarificationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_process_assets(ws_id, current_user, db)
    try:
        workspace_task_detail_service.create_clarification(db, ws_id, task_id, current_user.id, payload)
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        _raise_task_detail_write_error(exc)
    return _task_summary_or_404(db, ws_id, task_id)


@router.patch("/tasks/{task_id}/clarifications/{clarification_id}", response_model=TaskDetailSummaryResponse)
def update_workspace_asset_task_clarification(
    ws_id: str,
    task_id: str,
    clarification_id: str,
    payload: ClarificationUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_process_assets(ws_id, current_user, db)
    try:
        workspace_task_detail_service.update_clarification(
            db,
            ws_id,
            task_id,
            clarification_id,
            current_user.id,
            payload,
        )
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        _raise_task_detail_write_error(exc)
    return _task_summary_or_404(db, ws_id, task_id)


@router.put("/tasks/{task_id}/final-summary", response_model=TaskDetailSummaryResponse)
def upsert_workspace_asset_task_final_summary(
    ws_id: str,
    task_id: str,
    payload: TaskFinalSummaryUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_process_assets(ws_id, current_user, db)
    try:
        workspace_task_detail_service.upsert_final_summary(db, ws_id, task_id, current_user.id, payload)
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        _raise_task_detail_write_error(exc)
    return _task_summary_or_404(db, ws_id, task_id)


@router.get("/traceability", response_model=WorkspaceAssetsTraceabilityResponse)
def get_workspace_assets_traceability(
    ws_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    return workspace_asset_service.get_traceability(db, ws_id)


@router.get("/knowledge-assets", response_model=WorkspaceAssetsKnowledgeResponse)
def list_workspace_assets_knowledge_assets(
    ws_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_view_assets(ws_id, current_user, db)
    return workspace_asset_service.list_knowledge_assets(db, ws_id)
