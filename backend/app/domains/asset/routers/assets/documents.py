"""asset.routers.assets.documents domain operations."""

from __future__ import annotations
import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.domains.asset.services.review import resolutions as resolution_commands
from app.core.offload import run_db_txn
from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User
from app.domains.asset.schemas.asset import AssetDocumentResponse, AssetManualEditBlockRequest, AssetVersionListResponse, AssetVersionResponse
from app.domains.asset.services import asset_service
from app.domains.asset.services.document import repository as document_repository
from app.domains.task.services import task_cli_state_service
from app.domains.asset.ws.asset_discussion_manager import asset_discussion_ws_manager
from app.domains.asset.routers.assets.transport import ReviewRoute
from app.domains.asset.services.review import documents as asset_review_documents
from app.domains.asset.services.review import policy as asset_review_policy
from app.domains.asset.services.review import serialization as asset_review_serialization


router = APIRouter(route_class=ReviewRoute)


@router.get("/{asset_id}/file")
def get_asset_original_file(
    ws_id: str,
    asset_id: str,
    version_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """下载资产某个版本的原始文件字节(PDF 预览等场景)。"""
    asset_review_policy._verify_asset_access(ws_id, current_user, db)
    asset = asset_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    version = None
    if version_id:
        version = document_repository.get_asset_version(db, asset.id, version_id)
    if not version:
        version = asset_review_documents.ensure_active_version(db, asset)
    if not version or not str(version.original_path or "").strip():
        raise HTTPException(status_code=404, detail="Version file not found")
    path = os.path.abspath(version.original_path)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Version file missing on disk")
    return FileResponse(
        path,
        media_type=version.original_mime or "application/octet-stream",
        filename=os.path.basename(path),
    )


@router.get("/{asset_id}/document", response_model=AssetDocumentResponse)
def get_asset_document(
    ws_id: str,
    asset_id: str,
    version_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return asset_review_documents.read_document(db, ws_id=ws_id, asset_id=asset_id, version_id=version_id, current_user=current_user)


@router.get("/{asset_id}/versions", response_model=AssetVersionListResponse)
def list_asset_versions(
    ws_id: str,
    asset_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset_review_policy._verify_asset_access(ws_id, current_user, db)
    asset = asset_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    versions = document_repository.list_asset_versions(db, asset.id)
    return AssetVersionListResponse(
        items=[asset_review_serialization._serialize_version(version) for version in versions],
        total=len(versions),
        current_version_id=asset.active_version_id,
    )


@router.get("/{asset_id}/versions/{version_id}", response_model=AssetVersionResponse)
def get_asset_version(
    ws_id: str,
    asset_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset_review_policy._verify_asset_access(ws_id, current_user, db)
    asset = asset_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    version = document_repository.get_asset_version(db, asset.id, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    return asset_review_serialization._serialize_version(version)


@router.post("/{asset_id}/document/blocks/{block_id}", response_model=AssetVersionResponse)
async def manual_edit_asset_block(
    ws_id: str,
    asset_id: str,
    block_id: str,
    data: AssetManualEditBlockRequest,
    current_user: User = Depends(get_current_user),
):

    result = await run_db_txn(lambda session: resolution_commands.edit_document_block(session, ws_id=ws_id, asset_id=asset_id, block_id=block_id, data=data, user_id=current_user.id))
    version_response = AssetVersionResponse(**result["version"])
    if result["task_id"]:
        await task_cli_state_service.mark_bootstrap_stale_async(
            workspace_id=ws_id,
            task_id=result["task_id"],
            spec_version_id=version_response.id,
        )
        await task_cli_state_service.publish_bootstrap_snapshot(result["task_id"])

    await asset_discussion_ws_manager.broadcast(
        result["asset_id"],
        {
            "type": "version_applied",
            "asset_id": result["asset_id"],
            "version": version_response.model_dump(mode="json"),
        },
    )
    for thread_payload in result["threads"]:
        await asset_discussion_ws_manager.broadcast(
            result["asset_id"],
            {
                "type": "thread_updated",
                "asset_id": result["asset_id"],
                "thread": thread_payload,
            },
        )
    return version_response
