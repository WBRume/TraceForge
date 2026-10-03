"""Validate review authorization, version mutability and discussion context."""

from __future__ import annotations
from typing import Any, Optional
from sqlalchemy.orm import Session
from app.domains.asset.models.asset import AssetResolutionProposalStatus, AssetThreadStatus, SddAssetResolutionProposal
from app.domains.task.models.task import TaskStatus
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.asset.services import asset_discussion_service, asset_service
from app.domains.asset.services.document import repository as document_repository
from app.domains.workspace.services import workspace_service
from app.domains.asset.services.review.errors import ReviewError


def _verify_asset_access(ws_id: str, user: User, db: Session) -> None:
    member = workspace_service.get_workspace_member(db, ws_id, user.id)
    if not member:
        raise ReviewError(status_code=403, detail="No access to this workspace")
    if not workspace_service.user_has_permission(db, ws_id, user.id, WorkspacePermission.VIEW_ASSETS):
        raise ReviewError(status_code=403, detail="No permission to view assets")


def _verify_comment_permission(ws_id: str, user: User, db: Session) -> None:
    _verify_comment_permission_by_id(ws_id, user.id, db)


def _verify_comment_permission_by_id(ws_id: str, user_id: str, db: Session) -> None:
    member = workspace_service.get_workspace_member(db, ws_id, user_id)
    if not member:
        raise ReviewError(status_code=403, detail="No access to this workspace")
    if not workspace_service.user_has_permission(db, ws_id, user_id, WorkspacePermission.VIEW_ASSETS):
        raise ReviewError(status_code=403, detail="No permission to view assets")


def _verify_expert_permission(ws_id: str, user: User, db: Session) -> None:
    _verify_expert_permission_by_id(ws_id, user.id, db)


def _verify_expert_permission_by_id(ws_id: str, user_id: str, db: Session) -> None:
    _verify_comment_permission_by_id(ws_id, user_id, db)
    if not workspace_service.is_workspace_expert(db, ws_id, user_id):
        raise ReviewError(status_code=403, detail="Only workspace experts can apply resolutions")


def _ensure_spec_editable(asset) -> None:
    task = getattr(asset, "task", None)
    if not task:
        return
    if task.status != TaskStatus.PENDING:
        raise ReviewError(
            status_code=409,
            detail="Task engine already started, requirement document is read-only",
        )


def _ensure_thread_open(thread) -> None:
    status = thread.status.value if hasattr(thread.status, "value") else str(thread.status)
    if status == AssetThreadStatus.OPEN.value:
        return
    raise ReviewError(status_code=409, detail="Thread is not open")


def _is_latest_context_version(asset, context_version_id: Optional[str]) -> bool:
    active_id = str(asset.active_version_id or "").strip()
    context_id = str(context_version_id or "").strip()
    if not active_id or not context_id:
        return True
    return active_id == context_id


def _ensure_latest_context_version_for_mutation(asset, context_version_id: Optional[str]) -> None:
    if _is_latest_context_version(asset, context_version_id):
        return
    raise ReviewError(
        status_code=409,
        detail="Historical document versions are read-only",
    )


def _load_asset_thread_action_context_sync(
    db: Session,
    *,
    ws_id: str,
    asset_id: str,
    thread_id: str,
    user_id: str,
    context_version_id: Optional[str] = None,
    proposal_id: Optional[str] = None,
    ensure_open: bool = True,
    require_task: bool = True,
    require_latest_context: bool = True,
) -> dict[str, Any]:
    """Authorize and validate an asset-thread action off the event loop."""
    _verify_comment_permission_by_id(ws_id, user_id, db)
    asset = asset_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise ReviewError(status_code=404, detail="Asset not found")
    thread = asset_discussion_service.get_thread(
        db,
        asset_id=asset.id,
        thread_id=thread_id,
    )
    if not thread:
        raise ReviewError(status_code=404, detail="Thread not found")
    if ensure_open:
        _ensure_thread_open(thread)
    if require_task and not thread.task_id:
        raise ReviewError(status_code=400, detail="Thread task is required")
    resolved_context_id = str(context_version_id or "").strip() or asset.active_version_id
    context_version = None
    if resolved_context_id:
        context_version = document_repository.get_asset_version(
            db,
            asset.id,
            resolved_context_id,
        )
    if require_latest_context:
        _ensure_latest_context_version_for_mutation(
            asset,
            context_version.id if context_version else resolved_context_id,
        )
    if proposal_id:
        proposal = (
            db.query(SddAssetResolutionProposal)
            .filter(
                SddAssetResolutionProposal.id == proposal_id,
                SddAssetResolutionProposal.thread_id == thread.id,
            )
            .first()
        )
        if not proposal:
            raise ReviewError(status_code=404, detail="Resolution proposal not found")
        if proposal.status != AssetResolutionProposalStatus.DRAFT:
            raise ReviewError(status_code=409, detail="Only draft proposals can be rewritten")
    return {
        "asset_id": str(asset.id),
        "thread_id": str(thread.id),
        "task_id": str(thread.task_id),
        "active_version_id": str(asset.active_version_id or "") or None,
        "context_version_id": str(context_version.id if context_version else resolved_context_id or "") or None,
    }
