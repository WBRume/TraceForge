"""Apply human discussion messages, status transitions and close hints."""

from __future__ import annotations
from typing import Any, Optional
from sqlalchemy.orm import Session
from app.domains.asset.models.asset import AssetThreadMessageRole, AssetThreadStatus
from app.domains.asset.schemas.asset import AssetThreadCreateRequest, AssetThreadMessageCreateRequest
from app.domains.asset.services import asset_discussion_service, asset_service
from app.domains.asset.services.document import repository as document_repository, versioning as document_versioning
from app.domains.asset.services.review.errors import ReviewError
from app.domains.asset.services.review import policy as asset_review_policy
from app.domains.asset.services.review import serialization as asset_review_serialization


def _create_asset_thread_sync(
    db: Session,
    *,
    ws_id: str,
    asset_id: str,
    creator_id: str,
    data: AssetThreadCreateRequest,
    user_id: str,
) -> dict[str, Any]:
    asset_review_policy._verify_comment_permission_by_id(ws_id, user_id, db)
    asset = asset_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise ReviewError(status_code=404, detail="Asset not found")
    version = None
    if data.version_id:
        version = document_repository.get_asset_version(db, asset.id, data.version_id)
    if not version:
        version = document_versioning.ensure_asset_has_version(db, asset)
        if version and asset.active_version_id != version.id:
            asset.active_version_id = version.id
    if not version:
        raise ReviewError(status_code=400, detail="Asset has no version to annotate")
    asset_review_policy._ensure_latest_context_version_for_mutation(asset, version.id)
    try:
        thread = asset_discussion_service.create_thread(
            db,
            asset=asset,
            version=version,
            creator_id=creator_id,
            block_id=data.block_id,
            body=data.body,
            selected_text=data.selected_text,
            char_start=data.char_start,
            char_end=data.char_end,
        )
    except ValueError as exc:
        raise ReviewError(status_code=400, detail=str(exc)) from exc
    db.flush()
    db.refresh(thread)
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread.id)
    payload = asset_review_serialization._serialize_thread_with_context(db, thread=thread, context_version=version)
    return {"asset_id": str(asset.id), "payload": payload.model_dump(mode="json")}


def _create_asset_thread_message_sync(
    db: Session,
    *,
    ws_id: str,
    asset_id: str,
    thread_id: str,
    creator_id: str,
    data: AssetThreadMessageCreateRequest,
    user_id: str,
) -> dict[str, Any]:
    context = asset_review_policy._load_asset_thread_action_context_sync(
        db,
        ws_id=ws_id,
        asset_id=asset_id,
        thread_id=thread_id,
        user_id=user_id,
    )
    thread = asset_discussion_service.get_thread(db, asset_id=asset_id, thread_id=thread_id)
    message = asset_discussion_service.add_thread_message(
        db,
        thread=thread,
        role=AssetThreadMessageRole.USER,
        content=data.content,
        creator_id=creator_id,
    )
    db.flush()
    db.refresh(message)
    return {
        "asset_id": context["asset_id"],
        "thread_id": context["thread_id"],
        "message": asset_review_serialization._serialize_message(message).model_dump(mode="json"),
    }


def _update_asset_thread_state_sync(
    db: Session,
    *,
    ws_id: str,
    asset_id: str,
    thread_id: str,
    status: str,
    actor_user_id: str,
    user_id: str,
) -> dict[str, Any]:
    asset_review_policy._verify_expert_permission_by_id(ws_id, user_id, db)
    asset = asset_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise ReviewError(status_code=404, detail="Asset not found")
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread_id)
    if not thread:
        raise ReviewError(status_code=404, detail="Thread not found")
    target_status = {
        "resolved": AssetThreadStatus.RESOLVED,
        "closed": AssetThreadStatus.CLOSED,
    }.get(status, AssetThreadStatus.OPEN)
    asset_discussion_service.set_thread_status(
        db,
        thread=thread,
        status=target_status,
        actor_user_id=actor_user_id,
        resolved_version_id=(asset.active_version_id if target_status != AssetThreadStatus.OPEN else None),
    )
    db.flush()
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread.id)
    context_version = (
        document_repository.get_asset_version(db, asset.id, asset.active_version_id)
        if asset.active_version_id
        else None
    )
    response = asset_review_serialization._serialize_thread_with_context(db, thread=thread, context_version=context_version)
    return {"asset_id": str(asset.id), "payload": response.model_dump(mode="json")}


def _update_asset_thread_close_hint_sync(
    db: Session,
    *,
    ws_id: str,
    asset_id: str,
    thread_id: str,
    action: str,
    context_version_id: Optional[str],
    actor_user_id: str,
    user_id: str,
) -> dict[str, Any]:
    context = asset_review_policy._load_asset_thread_action_context_sync(
        db,
        ws_id=ws_id,
        asset_id=asset_id,
        thread_id=thread_id,
        user_id=user_id,
        context_version_id=context_version_id,
        ensure_open=False,
        require_task=False,
        require_latest_context=False,
    )
    asset = asset_service.get_asset_by_id(db, ws_id, asset_id)
    thread = asset_discussion_service.get_thread(db, asset_id=asset_id, thread_id=thread_id)
    resolved_context_id = str(context_version_id or "").strip() or asset.active_version_id
    context_version = (
        document_repository.get_asset_version(db, asset.id, resolved_context_id)
        if resolved_context_id
        else None
    )
    if action == "mark_no_close_needed":
        asset_discussion_service.set_thread_close_hint(
            db,
            thread=thread,
            state="no_close_needed",
            reason="anchor_missing",
            version_id=(context_version.id if context_version else thread.close_hint_version_id),
        )
        if thread.status != AssetThreadStatus.OPEN:
            asset_discussion_service.set_thread_status(
                db,
                thread=thread,
                status=AssetThreadStatus.OPEN,
                actor_user_id=actor_user_id,
                resolved_version_id=None,
            )
    else:
        anchor_eval = asset_discussion_service.resolve_thread_anchor_for_version(
            db,
            thread=thread,
            context_version=context_version,
        )
        if anchor_eval.get("anchor_status") == "missing":
            asset_discussion_service.set_thread_close_hint(
                db,
                thread=thread,
                state="pending",
                reason="anchor_missing",
                version_id=(context_version.id if context_version else thread.close_hint_version_id),
            )
        else:
            asset_discussion_service.set_thread_close_hint(
                db,
                thread=thread,
                state="none",
                reason=None,
                version_id=None,
            )
    db.flush()
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread.id)
    response = asset_review_serialization._serialize_thread_with_context(db, thread=thread, context_version=context_version)
    return {"asset_id": context["asset_id"], "payload": response.model_dump(mode="json")}
