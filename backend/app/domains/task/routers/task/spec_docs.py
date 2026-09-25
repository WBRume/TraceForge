"""任务规格文档路由：spec 资产 / 上传 / spec 基线（bootstrap）/ superpowers 文档。"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.distributed_lock import LockAcquireTimeout, lock_task
from app.core.logging import bind_task_context, get_logger
from app.core.offload import run_db_txn
from app.dependencies import get_current_user, get_db
from app.domains.asset.schemas.asset import AssetResponse
from app.domains.asset.services import asset_service
from app.domains.asset.services.document import serializer as document_serializer
from app.domains.asset.services.document import versioning as document_versioning
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.ai.services.jobs import publishing as ai_job_publishing
from app.domains.task.routers.task.deps import (
    TASKS_ROUTE_PREFIX,
    ensure_task_not_baselined,
    get_task_or_404,
    raise_task_lock_conflict,
    verify_workspace_access,
    verify_workspace_permission,
)
from app.domains.task.schemas.task import (
    SuperpowersDocContentResponse,
    SuperpowersDocSaveRequest,
    SuperpowersDocsListResponse,
    TaskCliBootstrapResponse,
)
from app.domains.task.services import task_cli_state_service, task_service

router = APIRouter(prefix=TASKS_ROUTE_PREFIX, tags=["Tasks"])
logger = get_logger(__name__, category="task_execution")


@router.get("/{task_id}/spec-asset", response_model=AssetResponse)
def get_task_spec_asset(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user.id, db)
    task = get_task_or_404(db, task_id, ws_id)

    asset = asset_service.get_spec_asset_by_task(db, task.id)
    if not asset and task.spec_doc_path:
        asset = document_versioning.ensure_spec_asset_backfilled(db, task)
        if asset:
            db.commit()
            db.refresh(asset)

    if not asset:
        raise HTTPException(status_code=404, detail="Task spec asset not found")

    return document_serializer.serialize_asset(asset)


@router.post("/{task_id}/upload-spec", response_model=dict)
async def upload_task_spec(
    ws_id: str,
    task_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    with bind_task_context(task_id=task_id, workspace_id=ws_id, user_id=current_user.id):
        try:
            async with lock_task(task_id):
                content = await file.read()
                ext = os.path.splitext(file.filename or "")[1].lower()
                if ext == ".doc":
                    raise HTTPException(
                        status_code=415,
                        detail="Legacy .doc is not supported; please convert to .docx or upload a PDF",
                    )
                bootstrap_enabled = task_service.spec_bootstrap_enabled_for_ext(ext)

                def persist_task_spec_upload(db: Session):
                    verify_workspace_permission(
                        ws_id,
                        current_user.id,
                        db,
                        WorkspacePermission.UPLOAD_TASK_SPEC,
                        "No permission to upload task specification",
                        task_id=task_id,
                    )
                    task = get_task_or_404(db, task_id, ws_id)
                    ensure_task_not_baselined(task)
                    file_path, asset_id, version_id = task_service.upload_task_spec(
                        db, task_id, file.filename, content
                    )
                    if bootstrap_enabled:
                        bootstrap = task_cli_state_service.upsert_bootstrap_for_upload(
                            db,
                            workspace_id=ws_id,
                            task_id=task_id,
                            spec_asset_id=asset_id,
                            spec_version_id=version_id,
                        )
                        bootstrap_status = (
                            bootstrap.status.value
                            if hasattr(bootstrap.status, "value")
                            else str(bootstrap.status)
                        )
                    else:
                        bootstrap_status = "DISABLED"
                    return {
                        "path": file_path,
                        "asset_id": asset_id,
                        "version_id": version_id,
                        "spec_bootstrap_status": bootstrap_status,
                    }

                upload = await run_db_txn(persist_task_spec_upload)
                await task_cli_state_service.publish_bootstrap_snapshot(task_id)
                # 基线构建改为手动触发，
                # 避免批量上传 spec 时 CLI 资源被大量并发 bootstrap 抢占。
                return {
                    "status": "success",
                    "path": upload["path"],
                    "filename": file.filename,
                    "asset_id": upload["asset_id"],
                    "version_id": upload["version_id"],
                    "spec_bootstrap_status": upload["spec_bootstrap_status"],
                }
        except LockAcquireTimeout as exc:
            raise_task_lock_conflict(exc)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=415, detail=str(exc))
        except Exception as exc:
            logger.exception(f"Failed to upload spec for task {task_id}: {exc}")
            raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{task_id}/spec-bootstrap", response_model=TaskCliBootstrapResponse)
def get_task_spec_bootstrap(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user.id, db)
    get_task_or_404(db, task_id, ws_id)

    snapshot = task_cli_state_service.get_bootstrap_snapshot(
        db,
        workspace_id=ws_id,
        task_id=task_id,
    )
    if not snapshot:
        raise HTTPException(status_code=404, detail="Specification baseline not initialized")
    return TaskCliBootstrapResponse(**snapshot)


@router.post("/{task_id}/spec-bootstrap/run", response_model=TaskCliBootstrapResponse)
async def run_task_spec_bootstrap(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """手动触发 spec 基线构建（PENDING/FAILED/STALE 可触发；RUNNING 幂等；READY 返回 409）。"""
    with bind_task_context(task_id=task_id, workspace_id=ws_id, user_id=current_user.id):
        try:
            def prepare_baseline_request(db: Session):
                verify_workspace_permission(
                    ws_id,
                    current_user.id,
                    db,
                    WorkspacePermission.UPLOAD_TASK_SPEC,
                    "No permission to run task specification baseline",
                    task_id=task_id,
                )
                get_task_or_404(db, task_id, ws_id)
                task_cli_state_service.request_bootstrap_run(
                    db,
                    workspace_id=ws_id,
                    task_id=task_id,
                )
                snapshot = task_cli_state_service.get_bootstrap_snapshot(
                    db,
                    workspace_id=ws_id,
                    task_id=task_id,
                )
                if not snapshot:
                    raise HTTPException(status_code=404, detail="Specification baseline not initialized")
                return snapshot

            snapshot = await run_db_txn(prepare_baseline_request)
        except KeyError:
            raise HTTPException(status_code=404, detail="Specification baseline not initialized")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        await task_cli_state_service.publish_bootstrap_snapshot(task_id)
        baseline_job = await ai_job_publishing.enqueue_task_baseline_job(
            workspace_id=ws_id,
            task_id=task_id,
            creator_id=current_user.id,
        )
        if baseline_job:
            snapshot["job_id"] = baseline_job.get("id")
        return TaskCliBootstrapResponse(**snapshot)


@router.get("/{task_id}/superpowers-docs", response_model=SuperpowersDocsListResponse)
def list_task_superpowers_docs(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user.id, db)
    task = get_task_or_404(db, task_id, ws_id)

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
    verify_workspace_access(ws_id, current_user.id, db)
    task = get_task_or_404(db, task_id, ws_id)

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
        current_user.id,
        db,
        WorkspacePermission.UPLOAD_TASK_SPEC,
        "No permission to edit plan documents",
        task_id=task_id,
    )

    task = get_task_or_404(db, task_id, ws_id)
    ensure_task_not_baselined(task)

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
