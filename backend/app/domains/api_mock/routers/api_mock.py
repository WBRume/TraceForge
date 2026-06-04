"""
API MOCK routes.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Any, Dict, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.distributed_lock import LockAcquireTimeout, lock_api_mock_project
from app.core.logging import get_logger
from app.dependencies import get_current_user, get_db
from app.domains.api_mock.models.api_mock import ApiMockCollabEventType, ApiMockRuleMode, SddApiMockEndpoint, SddApiMockRule
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.api_mock.schemas.api_mock import (
    ApiMockActivateSourceRequest,
    ApiMockCollabEventCreate,
    ApiMockCollabEventListResponse,
    ApiMockCollabEventResponse,
    ApiMockContextResponse,
    ApiMockDocumentResponse,
    ApiMockDocumentUpdate,
    ApiMockEndpointListResponse,
    ApiMockEndpointResponse,
    ApiMockEndpointUpdate,
    ApiMockEntityCreate,
    ApiMockEntityListResponse,
    ApiMockEntityResponse,
    ApiMockEntityUpdate,
    ApiMockJobListResponse,
    ApiMockJobResponse,
    ApiMockMockCaseCreate,
    ApiMockMockCaseListResponse,
    ApiMockMockCaseResponse,
    ApiMockMockCaseUpdate,
    ApiMockPreviewRequest,
    ApiMockPreviewResponse,
    ApiMockProjectResponse,
    ApiMockProjectUpdate,
    ApiMockSourceVersionListResponse,
    ApiMockSourceVersionResponse,
    ApiMockSyncStartResponse,
)
from app.domains.api_mock.services import api_mock_service
from app.domains.workspace.services import workspace_service

router = APIRouter(prefix="/workspaces/{ws_id}/api-mock", tags=["API MOCK"])
gateway_router = APIRouter(tags=["API MOCK Gateway"])
logger = get_logger(__name__, category="api_mock")


def _ensure_workspace_permission(
    db: Session,
    ws_id: str,
    user: User,
    permission: WorkspacePermission,
    detail: str,
) -> None:
    member = workspace_service.get_workspace_member(db, ws_id, user.id)
    if not member:
        raise HTTPException(status_code=403, detail="No access to this workspace")
    if not workspace_service.user_has_permission(db, ws_id, user.id, permission):
        raise HTTPException(status_code=403, detail=detail)


def _require_view_permission(db: Session, ws_id: str, user: User) -> None:
    _ensure_workspace_permission(
        db,
        ws_id,
        user,
        WorkspacePermission.VIEW_API_MOCK,
        "No permission to view API MOCK",
    )


def _require_manage_permission(db: Session, ws_id: str, user: User) -> None:
    _ensure_workspace_permission(
        db,
        ws_id,
        user,
        WorkspacePermission.MANAGE_API_MOCK,
        "No permission to manage API MOCK",
    )


def _require_publish_permission(db: Session, ws_id: str, user: User) -> None:
    _ensure_workspace_permission(
        db,
        ws_id,
        user,
        WorkspacePermission.PUBLISH_API_MOCK,
        "No permission to publish API MOCK",
    )


def _get_or_create_project(db: Session, ws_id: str, task_id: str, user: User):
    try:
        return api_mock_service.ensure_project(db, ws_id, task_id, user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


def _get_project_by_id_or_404(db: Session, ws_id: str, project_id: str):
    project = api_mock_service.get_project_by_id(db, project_id)
    if not project or project.workspace_id != ws_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _build_mock_base_url(request: Request, ws_id: str, task_id: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/mock/{ws_id}/{task_id}"


def _raise_if_project_swagger_mutation_locked(db: Session, project_id: str) -> None:
    active_auto_job = api_mock_service.get_active_auto_mock_job(db, project_id)
    if not active_auto_job:
        return
    raise HTTPException(
        status_code=409,
        detail=api_mock_service.build_auto_mock_locked_detail(
            code="ai_auto_mock_locked_project_swagger_mutation",
            message="AI auto mock is running, Swagger mutation is temporarily locked for this project.",
            job=active_auto_job,
        ),
    )


def _raise_if_current_endpoint_create_case_locked(db: Session, project_id: str, endpoint_id: str) -> None:
    active_endpoint_job = api_mock_service.get_active_auto_mock_job(db, project_id, endpoint_id=endpoint_id)
    if not active_endpoint_job:
        return
    raise HTTPException(
        status_code=409,
        detail=api_mock_service.build_auto_mock_locked_detail(
            code="ai_auto_mock_locked_current_endpoint",
            message="AI auto mock is running for this endpoint, creating new mock case is temporarily locked.",
            job=active_endpoint_job,
            endpoint_id=endpoint_id,
        ),
    )


def _raise_auto_mock_start_locked(exc: LockAcquireTimeout, *, endpoint_id: str) -> None:
    _ = exc
    raise HTTPException(
        status_code=409,
        detail=api_mock_service.build_auto_mock_locked_detail(
            code="ai_auto_mock_start_busy",
            message="AI auto mock startup is busy. Please retry later.",
            endpoint_id=endpoint_id,
        ),
    )


@router.get("/projects/{task_id}", response_model=ApiMockProjectResponse)
def get_project(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_view_permission(db, ws_id, current_user)
    return _get_or_create_project(db, ws_id, task_id, current_user)


@router.get("/projects/{task_id}/context", response_model=ApiMockContextResponse)
def get_project_context(
    ws_id: str,
    task_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_view_permission(db, ws_id, current_user)
    project = _get_or_create_project(db, ws_id, task_id, current_user)

    endpoints = api_mock_service.list_endpoints(db, project)
    endpoint_ids = [item.id for item in endpoints]
    mock_case_count = 0
    endpoints_with_mock_cases = 0
    for endpoint_id in endpoint_ids:
        cases = api_mock_service.list_mock_cases_for_endpoint(db, project, endpoint_id)
        if cases:
            endpoints_with_mock_cases += 1
            mock_case_count += len(cases)

    endpoint_count = len(endpoint_ids)
    return ApiMockContextResponse(
        project_id=project.id,
        workspace_id=ws_id,
        task_id=task_id,
        source_version_id=project.active_source_version_id,
        mock_base_url=_build_mock_base_url(request, ws_id, task_id),
        endpoint_count=endpoint_count,
        endpoints_with_mock_cases=endpoints_with_mock_cases,
        endpoints_without_mock_cases=max(0, endpoint_count - endpoints_with_mock_cases),
        mock_case_count=mock_case_count,
    )


@router.put("/projects/{task_id}", response_model=ApiMockProjectResponse)
def update_project(
    ws_id: str,
    task_id: str,
    data: ApiMockProjectUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manage_permission(db, ws_id, current_user)
    if data.proxy_enabled is not None or data.proxy_base_url is not None:
        _require_publish_permission(db, ws_id, current_user)

    project = _get_or_create_project(db, ws_id, task_id, current_user)
    return api_mock_service.update_project_settings(
        db,
        project,
        proxy_enabled=data.proxy_enabled,
        proxy_base_url=data.proxy_base_url,
    )


@router.post("/projects/{task_id}/sync", response_model=ApiMockSyncStartResponse)
def start_sync(
    ws_id: str,
    task_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manage_permission(db, ws_id, current_user)
    project = _get_or_create_project(db, ws_id, task_id, current_user)
    _raise_if_project_swagger_mutation_locked(db, project.id)
    job = api_mock_service.create_job(
        db,
        project,
        creator_id=current_user.id,
        job_type="SYNC_TASK_SOURCE",
        message="Queued for sync",
    )

    background_tasks.add_task(
        api_mock_service.run_sync_job_background,
        job.id,
        ws_id,
        task_id,
        current_user.id,
    )
    return ApiMockSyncStartResponse(
        job_id=job.id,
        project_id=project.id,
        status=job.status.value if hasattr(job.status, "value") else str(job.status),
        message=job.message or "Sync queued",
    )


@router.post("/projects/{task_id}/swagger/import", response_model=ApiMockSyncStartResponse)
async def import_swagger(
    ws_id: str,
    task_id: str,
    background_tasks: BackgroundTasks,
    source_name: Optional[str] = Form(default=None),
    source_url: Optional[str] = Form(default=None),
    raw_content: Optional[str] = Form(default=None),
    file: Optional[UploadFile] = File(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manage_permission(db, ws_id, current_user)
    project = _get_or_create_project(db, ws_id, task_id, current_user)
    _raise_if_project_swagger_mutation_locked(db, project.id)

    logger.info(f"Swagger import request - source_name: {source_name}, source_url: {source_url}, raw_content length: {len(raw_content) if raw_content else 0}, file: {file}")
    
    body_content = (raw_content or "").strip()
    if file is not None:
        logger.info(f"File received: {file.filename}, size: {file.size if hasattr(file, 'size') else 'unknown'}")
        content_bytes = await file.read()
        body_content = content_bytes.decode("utf-8", errors="ignore").strip()
        if not source_name:
            source_name = file.filename
        logger.info(f"File content length: {len(body_content)}")
    else:
        logger.warning("No file in request")

    if not body_content and not source_url:
        logger.error("No content provided - body_content is empty and source_url is empty")
        raise HTTPException(status_code=400, detail="Provide file, raw_content, or source_url")

    job = api_mock_service.create_job(
        db,
        project,
        creator_id=current_user.id,
        job_type="IMPORT_SWAGGER",
        message="Queued for import",
    )
    background_tasks.add_task(
        api_mock_service.run_import_job_background,
        job.id,
        ws_id,
        task_id,
        current_user.id,
        source_name=source_name,
        source_url=source_url,
        raw_content=body_content,
    )

    return ApiMockSyncStartResponse(
        job_id=job.id,
        project_id=project.id,
        status=job.status.value if hasattr(job.status, "value") else str(job.status),
        message=job.message or "Import queued",
    )


@router.get("/projects/{task_id}/jobs/{job_id}", response_model=ApiMockJobResponse)
def get_job(
    ws_id: str,
    task_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_view_permission(db, ws_id, current_user)
    project = _get_or_create_project(db, ws_id, task_id, current_user)
    job = api_mock_service.get_job(db, project.id, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/projects/{task_id}/jobs", response_model=ApiMockJobListResponse)
def list_jobs(
    ws_id: str,
    task_id: str,
    job_type: Optional[str] = Query(default=None),
    active_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_view_permission(db, ws_id, current_user)
    project = _get_or_create_project(db, ws_id, task_id, current_user)
    items = api_mock_service.list_jobs(
        db,
        project.id,
        job_type=job_type,
        active_only=active_only,
        limit=limit,
    )
    return ApiMockJobListResponse(
        items=[ApiMockJobResponse.model_validate(item) for item in items],
        total=len(items),
    )


@router.post("/projects/{task_id}/jobs/{job_id}/cancel", response_model=ApiMockJobResponse)
def cancel_job(
    ws_id: str,
    task_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manage_permission(db, ws_id, current_user)
    project = _get_or_create_project(db, ws_id, task_id, current_user)
    try:
        return api_mock_service.request_job_cancel(db, project.id, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/projects/{task_id}/source-versions", response_model=ApiMockSourceVersionListResponse)
def list_source_versions(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_view_permission(db, ws_id, current_user)
    project = _get_or_create_project(db, ws_id, task_id, current_user)
    items = api_mock_service.list_source_versions(db, project)
    return ApiMockSourceVersionListResponse(
        items=[
            ApiMockSourceVersionResponse(
                id=item.id,
                project_id=item.project_id,
                source_type=item.source_type.value if hasattr(item.source_type, "value") else str(item.source_type),
                source_name=item.source_name,
                summary_json=item.summary_json,
                is_active=item.is_active,
                creator_id=item.creator_id,
                created_at=item.created_at,
            )
            for item in items
        ],
        total=len(items),
    )


@router.post("/projects/{task_id}/sources/activate", response_model=ApiMockSourceVersionResponse)
def activate_source(
    ws_id: str,
    task_id: str,
    data: ApiMockActivateSourceRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manage_permission(db, ws_id, current_user)
    project = _get_or_create_project(db, ws_id, task_id, current_user)
    _raise_if_project_swagger_mutation_locked(db, project.id)
    try:
        source = api_mock_service.activate_source_version(db, project, data.source_version_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return ApiMockSourceVersionResponse(
        id=source.id,
        project_id=source.project_id,
        source_type=source.source_type.value if hasattr(source.source_type, "value") else str(source.source_type),
        source_name=source.source_name,
        summary_json=source.summary_json,
        is_active=source.is_active,
        creator_id=source.creator_id,
        created_at=source.created_at,
    )


@router.get("/projects/{project_id}/document", response_model=ApiMockDocumentResponse)
def get_active_document(
    ws_id: str,
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_view_permission(db, ws_id, current_user)
    project = _get_project_by_id_or_404(db, ws_id, project_id)
    try:
        source = api_mock_service.get_active_document(db, project)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    content = ""
    if getattr(source, "storage_path", None):
        import os
        if os.path.exists(source.storage_path):
            with open(source.storage_path, "r", encoding="utf-8") as f:
                content = f.read()
    if not content and getattr(source, "raw_content", None):
        content = source.raw_content

    return ApiMockDocumentResponse(
        project_id=project.id,
        source_version_id=source.id,
        source_type=source.source_type.value if hasattr(source.source_type, "value") else str(source.source_type),
        source_name=source.source_name,
        content=content or "",
        created_at=source.created_at,
    )


@router.put("/projects/{project_id}/document", response_model=ApiMockDocumentResponse)
def save_active_document(
    ws_id: str,
    project_id: str,
    data: ApiMockDocumentUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manage_permission(db, ws_id, current_user)
    project = _get_project_by_id_or_404(db, ws_id, project_id)
    _raise_if_project_swagger_mutation_locked(db, project.id)
    try:
        source = api_mock_service.save_active_document(
            db,
            project,
            raw_content=data.content,
            creator_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    content = ""
    if getattr(source, "storage_path", None):
        import os
        if os.path.exists(source.storage_path):
            with open(source.storage_path, "r", encoding="utf-8") as f:
                content = f.read()
    if not content and getattr(source, "raw_content", None):
        content = source.raw_content

    return ApiMockDocumentResponse(
        project_id=project.id,
        source_version_id=source.id,
        source_type=source.source_type.value if hasattr(source.source_type, "value") else str(source.source_type),
        source_name=source.source_name,
        content=content or "",
        created_at=source.created_at,
    )


@router.get("/projects/{task_id}/endpoints", response_model=ApiMockEndpointListResponse)
def list_endpoints(
    ws_id: str,
    task_id: str,
    source_version_id: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_view_permission(db, ws_id, current_user)
    project = _get_or_create_project(db, ws_id, task_id, current_user)
    items = api_mock_service.list_endpoints(db, project, source_version_id=source_version_id, keyword=keyword)
    return ApiMockEndpointListResponse(
        items=[ApiMockEndpointResponse.model_validate(item) for item in items],
        total=len(items),
    )


@router.put("/projects/{task_id}/endpoints/{endpoint_id}", response_model=ApiMockEndpointResponse)
def update_endpoint(
    ws_id: str,
    task_id: str,
    endpoint_id: str,
    data: ApiMockEndpointUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manage_permission(db, ws_id, current_user)
    project = _get_or_create_project(db, ws_id, task_id, current_user)
    _raise_if_project_swagger_mutation_locked(db, project.id)
    try:
        endpoint = api_mock_service.update_endpoint(
            db,
            project,
            endpoint_id,
            row_version=data.row_version,
            method=data.method,
            path=data.path,
            operation_id=data.operation_id,
            tag=data.tag,
            summary=data.summary,
            parameters_json=data.parameters_json,
            request_schema_json=data.request_schema_json,
            responses_json=data.responses_json,
            response_schema_json=data.response_schema_json,
            entity_refs_json=data.entity_refs_json,
            updater_id=current_user.id,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 409 if "updated by another user" in detail else 404
        raise HTTPException(status_code=status_code, detail=detail)
    return endpoint


@router.get("/projects/{task_id}/entities", response_model=ApiMockEntityListResponse)
def list_entities(
    ws_id: str,
    task_id: str,
    source_version_id: Optional[str] = Query(default=None),
    endpoint_id: Optional[str] = Query(default=None),
    scope: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_view_permission(db, ws_id, current_user)
    project = _get_or_create_project(db, ws_id, task_id, current_user)
    items = api_mock_service.list_entities(
        db, project,
        source_version_id=source_version_id,
        endpoint_id=endpoint_id,
        scope=scope,
    )
    return ApiMockEntityListResponse(
        items=[ApiMockEntityResponse.model_validate(item) for item in items],
        total=len(items),
    )


@router.post("/projects/{task_id}/entities", response_model=ApiMockEntityResponse)
def create_entity(
    ws_id: str,
    task_id: str,
    data: ApiMockEntityCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manage_permission(db, ws_id, current_user)
    project = _get_or_create_project(db, ws_id, task_id, current_user)
    _raise_if_project_swagger_mutation_locked(db, project.id)
    try:
        entity = api_mock_service.create_entity(
            db, project,
            name=data.name,
            description=data.description,
            schema_json=data.schema_data,
            updater_id=current_user.id,
            endpoint_id=data.endpoint_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ApiMockEntityResponse.model_validate(entity)


@router.put("/projects/{task_id}/entities/{entity_id}", response_model=ApiMockEntityResponse)
def update_entity(
    ws_id: str,
    task_id: str,
    entity_id: str,
    data: ApiMockEntityUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manage_permission(db, ws_id, current_user)
    project = _get_or_create_project(db, ws_id, task_id, current_user)
    _raise_if_project_swagger_mutation_locked(db, project.id)
    try:
        entity = api_mock_service.update_entity(
            db, project, entity_id,
            row_version=data.row_version,
            name=data.name,
            description=data.description,
            schema_json=data.schema_data,
            updater_id=current_user.id,
            endpoint_id=data.endpoint_id,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 409 if "updated by another user" in detail else 404
        raise HTTPException(status_code=status_code, detail=detail)
    return ApiMockEntityResponse.model_validate(entity)


@router.delete("/projects/{task_id}/entities/{entity_id}")
def delete_entity(
    ws_id: str,
    task_id: str,
    entity_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manage_permission(db, ws_id, current_user)
    project = _get_or_create_project(db, ws_id, task_id, current_user)
    _raise_if_project_swagger_mutation_locked(db, project.id)
    try:
        api_mock_service.delete_entity(db, project, entity_id, updater_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@router.get("/endpoints/{endpoint_id}/mock-cases", response_model=ApiMockMockCaseListResponse)
def list_mock_cases(
    ws_id: str,
    endpoint_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_view_permission(db, ws_id, current_user)
    endpoint = db.query(SddApiMockEndpoint).filter(SddApiMockEndpoint.id == endpoint_id).first()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    project = _get_project_by_id_or_404(db, ws_id, endpoint.project_id)
    items = api_mock_service.list_mock_cases_for_endpoint(db, project, endpoint_id)
    return ApiMockMockCaseListResponse(
        items=[ApiMockMockCaseResponse.model_validate(item) for item in items],
        total=len(items),
    )


@router.post("/projects/{task_id}/endpoints/{endpoint_id}/auto-mock", response_model=ApiMockSyncStartResponse)
async def start_auto_mock(
    ws_id: str,
    task_id: str,
    endpoint_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manage_permission(db, ws_id, current_user)
    project = _get_or_create_project(db, ws_id, task_id, current_user)

    try:
        async with lock_api_mock_project(project.id):
            endpoint = api_mock_service.get_endpoint(db, project, endpoint_id)
            if not endpoint:
                raise HTTPException(status_code=404, detail="Endpoint not found")

            active_auto_job = api_mock_service.get_active_auto_mock_job(db, project.id)
            if active_auto_job:
                raise HTTPException(
                    status_code=409,
                    detail=api_mock_service.build_auto_mock_locked_detail(
                        code="ai_auto_mock_running",
                        message="AI auto mock is already running in this project.",
                        job=active_auto_job,
                        endpoint_id=endpoint_id,
                    ),
                )

            job = api_mock_service.create_job(
                db,
                project,
                creator_id=current_user.id,
                job_type=api_mock_service.AUTO_MOCK_JOB_TYPE,
                message="Queued for AI auto mock",
            )
            api_mock_service.set_auto_mock_job_target(
                db,
                project.id,
                job,
                endpoint_id=endpoint_id,
            )
    except LockAcquireTimeout as exc:
        _raise_auto_mock_start_locked(exc, endpoint_id=endpoint_id)

    background_tasks.add_task(
        api_mock_service.run_auto_mock_job_background,
        job.id,
        ws_id,
        task_id,
        current_user.id,
        endpoint_id=endpoint_id,
    )

    return ApiMockSyncStartResponse(
        job_id=job.id,
        project_id=project.id,
        status=job.status.value if hasattr(job.status, "value") else str(job.status),
        message=job.message or "Queued for AI auto mock",
    )


@router.post("/endpoints/{endpoint_id}/mock-cases", response_model=ApiMockMockCaseResponse)
def create_mock_case(
    ws_id: str,
    endpoint_id: str,
    data: ApiMockMockCaseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manage_permission(db, ws_id, current_user)
    endpoint = db.query(SddApiMockEndpoint).filter(SddApiMockEndpoint.id == endpoint_id).first()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    project = _get_project_by_id_or_404(db, ws_id, endpoint.project_id)
    _raise_if_current_endpoint_create_case_locked(db, project.id, endpoint_id)
    try:
        mock_case = api_mock_service.create_mock_case(
            db,
            project,
            endpoint_id=endpoint_id,
            updater_id=current_user.id,
            name=data.name,
            description=data.description,
            is_default=data.is_default,
            sort_order=data.sort_order,
            mode=ApiMockRuleMode(data.mode),
            request_path_params_json=data.request_path_params_json,
            request_query_json=data.request_query_json,
            request_body_json=data.request_body_json,
            status_code=data.status_code,
            enabled=data.enabled,
            delay_ms=data.delay_ms,
            static_body_json=data.static_body_json,
            mockjs_template=data.mockjs_template,
            headers_json=data.headers_json,
            cookies_json=data.cookies_json,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return ApiMockMockCaseResponse.model_validate(mock_case)


@router.put("/mock-cases/{mock_case_id}", response_model=ApiMockMockCaseResponse)
def update_mock_case(
    ws_id: str,
    mock_case_id: str,
    data: ApiMockMockCaseUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manage_permission(db, ws_id, current_user)
    mock_case = db.query(SddApiMockRule).filter(SddApiMockRule.id == mock_case_id).first()
    if not mock_case:
        raise HTTPException(status_code=404, detail="Mock case not found")
    project = _get_project_by_id_or_404(db, ws_id, mock_case.project_id)
    try:
        updated = api_mock_service.update_mock_case(
            db,
            project,
            mock_case_id=mock_case_id,
            updater_id=current_user.id,
            row_version=data.row_version,
            name=data.name,
            description=data.description,
            is_default=data.is_default,
            sort_order=data.sort_order,
            mode=ApiMockRuleMode(data.mode),
            request_path_params_json=data.request_path_params_json,
            request_query_json=data.request_query_json,
            request_body_json=data.request_body_json,
            status_code=data.status_code,
            enabled=data.enabled,
            delay_ms=data.delay_ms,
            static_body_json=data.static_body_json,
            mockjs_template=data.mockjs_template,
            headers_json=data.headers_json,
            cookies_json=data.cookies_json,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 409 if "updated by another user" in detail else 404
        raise HTTPException(status_code=status_code, detail=detail)
    return ApiMockMockCaseResponse.model_validate(updated)


@router.delete("/mock-cases/{mock_case_id}")
def delete_mock_case(
    ws_id: str,
    mock_case_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manage_permission(db, ws_id, current_user)
    mock_case = db.query(SddApiMockRule).filter(SddApiMockRule.id == mock_case_id).first()
    if not mock_case:
        raise HTTPException(status_code=404, detail="Mock case not found")
    project = _get_project_by_id_or_404(db, ws_id, mock_case.project_id)
    try:
        api_mock_service.delete_mock_case(db, project, mock_case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"success": True}


@router.post("/projects/{task_id}/preview", response_model=ApiMockPreviewResponse)
def preview(
    ws_id: str,
    task_id: str,
    data: ApiMockPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_view_permission(db, ws_id, current_user)
    project = _get_or_create_project(db, ws_id, task_id, current_user)
    try:
        result = api_mock_service.execute_preview(
            db,
            project,
            ws_id=ws_id,
            task_id=task_id,
            endpoint_id=data.endpoint_id,
            mock_case_id=data.mock_case_id,
            method=data.method,
            path=data.path,
            query=data.query,
            headers=data.headers,
            body=data.body,
        )
        status_code = int(result.get("status_code", 200))
        error_payload = result.get("body")
        if (
            status_code == 422
            and isinstance(error_payload, dict)
            and isinstance(error_payload.get("error"), dict)
            and str((error_payload.get("error") or {}).get("code", "")) == "mock_case_not_matched"
        ):
            return JSONResponse(status_code=422, content=error_payload)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/projects/{task_id}/collab/events", response_model=ApiMockCollabEventListResponse)
def list_collab_events(
    ws_id: str,
    task_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_view_permission(db, ws_id, current_user)
    project = _get_or_create_project(db, ws_id, task_id, current_user)
    items = api_mock_service.list_collab_events(db, project, limit=limit)
    return ApiMockCollabEventListResponse(
        items=[ApiMockCollabEventResponse.model_validate(item) for item in items],
        total=len(items),
    )


@router.post("/projects/{task_id}/collab/events", response_model=ApiMockCollabEventResponse)
def create_collab_event(
    ws_id: str,
    task_id: str,
    data: ApiMockCollabEventCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_manage_permission(db, ws_id, current_user)
    project = _get_or_create_project(db, ws_id, task_id, current_user)
    try:
        event = api_mock_service.create_collab_event(
            db,
            project,
            user_id=current_user.id,
            event_type=ApiMockCollabEventType(data.event_type),
            endpoint_id=data.endpoint_id,
            payload=data.payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return event


async def _parse_gateway_body(request: Request) -> Any:
    if request.method.upper() in {"GET", "HEAD"}:
        return None

    content_type = request.headers.get("content-type", "").lower()
    raw_body = await request.body()
    if not raw_body:
        return None

    if "application/json" in content_type:
        try:
            return json.loads(raw_body.decode("utf-8", errors="ignore"))
        except Exception:
            return raw_body.decode("utf-8", errors="ignore")

    if "application/x-www-form-urlencoded" in content_type:
        form = urllib.parse.parse_qs(raw_body.decode("utf-8", errors="ignore"))
        return {k: (v[0] if len(v) == 1 else v) for k, v in form.items()}

    return raw_body.decode("utf-8", errors="ignore")


@gateway_router.api_route(
    "/mock/{ws_id}/{task_id}/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
async def mock_gateway(
    ws_id: str,
    task_id: str,
    full_path: str,
    request: Request,
    db: Session = Depends(get_db),
):
    project = api_mock_service.get_project_by_task(db, ws_id, task_id)
    if not project:
        return JSONResponse(
            status_code=404,
            content={"message": "API MOCK project not found for this workspace/task"},
        )

    path = f"/{full_path}" if not full_path.startswith("/") else full_path
    query = dict(request.query_params)
    headers: Dict[str, str] = {k: v for k, v in request.headers.items()}
    body = await _parse_gateway_body(request)

    result = api_mock_service.execute_gateway(
        db,
        project,
        ws_id=ws_id,
        task_id=task_id,
        method=request.method,
        path=path,
        query=query,
        headers=headers,
        body=body,
    )

    response = JSONResponse(
        status_code=int(result.get("status_code", 200)),
        content=result.get("body"),
    )
    for key, value in (result.get("headers") or {}).items():
        if not key or value is None:
            continue
        response.headers[key] = str(value)

    for cookie in (result.get("cookies") or []):
        if not isinstance(cookie, dict):
            continue
        name = cookie.get("name")
        if not name:
            continue
        response.set_cookie(
            key=str(name),
            value=str(cookie.get("value", "")),
            path=str(cookie.get("path", "/")),
            httponly=bool(cookie.get("http_only", False)),
            secure=bool(cookie.get("secure", False)),
            samesite=str(cookie.get("same_site", "lax")).lower(),
        )

    response.headers["x-api-mock-mode"] = str(result.get("mode", "STATIC"))
    response.headers["x-api-mock-latency-ms"] = str(result.get("latency_ms", 0))
    return response
