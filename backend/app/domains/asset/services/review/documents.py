"""Prepare a review document and project version-specific review capabilities."""

from typing import Optional
from sqlalchemy.orm import Session
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.asset.schemas.asset import AssetDocumentResponse, AssetDocumentCapabilities, AssetThreadMarkerResponse
from app.domains.asset.services import asset_service, asset_discussion_service
from app.domains.asset.services.document import payload as document_payload, repair as document_repair, repository as document_repository, versioning as document_versioning
from app.domains.task.services import task_cli_state_service
from app.domains.workspace.services import workspace_service
from app.domains.asset.services.review import policy as asset_review_policy, serialization as asset_review_serialization
from app.domains.asset.services.review.errors import ReviewError

def ensure_active_version(db: Session, asset):
    before_active = asset.active_version_id
    version = document_versioning.ensure_asset_has_version(db, asset)
    if version and asset.active_version_id != version.id:
        asset.active_version_id = version.id
    if version and asset.active_version_id != before_active:
        db.commit()
        db.refresh(asset)
    return version


def read_document(db: Session, *, ws_id: str, asset_id: str, version_id: Optional[str], current_user: User) -> AssetDocumentResponse:
    asset_review_policy._verify_asset_access(ws_id, current_user, db)
    asset = asset_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise ReviewError(status_code=404, detail="Asset not found")

    active_version = None
    if version_id:
        active_version = document_repository.get_asset_version(db, asset.id, version_id)
    if not active_version:
        active_version = ensure_active_version(db, asset)
    updated = False
    if active_version and document_repair.repair_docx_version_if_needed(db, asset, active_version):
        updated = True
    if active_version:
        imported = asset_discussion_service.sync_docx_comments_to_threads(
            db,
            asset=asset,
            version=active_version,
            actor_user_id=asset.creator_id,
        )
        if imported:
            updated = True
    if updated:
        db.commit()
        if active_version:
            db.refresh(active_version)
        db.refresh(asset)

    blocks = []
    markers: list[AssetThreadMarkerResponse] = []
    if active_version:
        blocks = active_version.blocks_json or []
        raw_markers = asset_discussion_service.list_thread_markers(
            db,
            asset_id=asset.id,
            version_id=active_version.id,
        )
        markers = [AssetThreadMarkerResponse(**item) for item in raw_markers]

    can_view = workspace_service.user_has_permission(db, ws_id, current_user.id, WorkspacePermission.VIEW_ASSETS)
    selected_version_id = active_version.id if active_version else asset.active_version_id
    is_latest_context_version = asset_review_policy._is_latest_context_version(asset, selected_version_id)
    can_comment = can_view and is_latest_context_version
    can_apply_resolution = (
        workspace_service.is_workspace_expert(db, ws_id, current_user.id)
        and is_latest_context_version
    )
    inline_review_enabled = document_payload.can_inline_review(asset.source_ext)
    can_manual_edit = can_apply_resolution and inline_review_enabled
    ai_available = True
    ai_unavailable_reason: Optional[str] = None
    if not is_latest_context_version:
        ai_available = False
        ai_unavailable_reason = "historical_version_readonly"
    elif asset.task_id:
        snapshot = task_cli_state_service.get_bootstrap_snapshot(
            db,
            workspace_id=ws_id,
            task_id=asset.task_id,
        )
        if not snapshot:
            ai_available = False
            ai_unavailable_reason = "baseline_not_initialized"
        else:
            bootstrap_status = str(snapshot.get("status") or "").strip().upper()
            if bootstrap_status != "READY":
                ai_available = False
                ai_unavailable_reason = f"baseline_{bootstrap_status.lower() or 'not_ready'}"
    can_ai_reply = can_comment and ai_available

    return AssetDocumentResponse(
        asset=asset_review_serialization._serialize_asset(asset),
        active_version=asset_review_serialization._serialize_version(active_version) if active_version else None,
        blocks=blocks,
        thread_markers=markers,
        capabilities=AssetDocumentCapabilities(
            can_view=can_view,
            can_comment=can_comment,
            can_ai_reply=can_ai_reply,
            can_apply_resolution=can_apply_resolution,
            can_manual_edit=can_manual_edit,
            inline_review_enabled=inline_review_enabled,
            ai_available=ai_available,
            ai_unavailable_reason=ai_unavailable_reason,
        ),
    )
