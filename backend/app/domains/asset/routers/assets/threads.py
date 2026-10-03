"""asset.routers.assets.threads domain operations."""

from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User
from app.domains.asset.schemas.asset import AssetThreadCloseHintActionRequest, AssetThreadCreateRequest, AssetThreadListResponse, AssetThreadMessageCreateRequest, AssetThreadMessageResponse, AssetThreadResponse, AssetThreadStateUpdateRequest
from app.domains.asset.services import asset_discussion_service, asset_service
from app.domains.asset.services.document import repository as document_repository
from app.domains.task.services import task_cli_state_service
from app.domains.asset.ws.asset_discussion_manager import asset_discussion_ws_manager
from app.domains.asset.routers.assets.transport import ReviewRoute
from app.domains.asset.routers.assets import transport as asset_assets_transport
from app.domains.asset.services.review import documents as asset_review_documents
from app.domains.asset.services.review import policy as asset_review_policy
from app.domains.asset.services.review import serialization as asset_review_serialization
from app.domains.asset.services.review import threads as asset_review_threads


router = APIRouter(route_class=ReviewRoute)


@router.get("/{asset_id}/threads", response_model=AssetThreadListResponse)
def list_asset_threads(
    ws_id: str,
    asset_id: str,
    context_version_id: Optional[str] = Query(default=None),
    version_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset_review_policy._verify_asset_access(ws_id, current_user, db)
    asset = asset_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    resolved_context_version_id = context_version_id or version_id
    context_version = None
    if resolved_context_version_id:
        context_version = document_repository.get_asset_version(db, asset.id, resolved_context_version_id)
    if not context_version:
        context_version = asset_review_documents._ensure_active_version(db, asset)
    items = asset_discussion_service.list_threads(db, asset_id=asset.id, version_id=None)
    return AssetThreadListResponse(
        items=[
            asset_review_serialization._serialize_thread_with_context(
                db,
                thread=item,
                context_version=context_version,
            )
            for item in items
        ],
        total=len(items),
    )


@router.get("/{asset_id}/threads/{thread_id}", response_model=AssetThreadResponse)
def get_asset_thread(
    ws_id: str,
    asset_id: str,
    thread_id: str,
    context_version_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset_review_policy._verify_asset_access(ws_id, current_user, db)
    asset = asset_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    context_version = None
    if context_version_id:
        context_version = document_repository.get_asset_version(db, asset.id, context_version_id)
    if not context_version:
        context_version = asset_review_documents._ensure_active_version(db, asset)
    return asset_review_serialization._serialize_thread_with_context(
        db,
        thread=thread,
        context_version=context_version,
    )


@router.post("/{asset_id}/threads", response_model=AssetThreadResponse)
async def create_asset_thread(
    ws_id: str,
    asset_id: str,
    data: AssetThreadCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_bind = asset_assets_transport._get_db_bind(db)
    created = await asset_assets_transport._run_asset_route_db_txn(
        db,
        db_bind,
        lambda session: asset_review_threads._create_asset_thread_sync(
            session,
            ws_id=ws_id,
            asset_id=asset_id,
            creator_id=current_user.id,
            data=data,
            user_id=current_user.id,
        ),
    )
    db.close()
    payload = AssetThreadResponse(**created["payload"])

    await asset_discussion_ws_manager.broadcast(
        created["asset_id"],
        {
            "type": "thread_created",
            "asset_id": created["asset_id"],
            "thread": created["payload"],
        },
    )
    task_cli_state_service.schedule_prepare_thread_workspace(payload.id)
    return payload


@router.post("/{asset_id}/threads/{thread_id}/messages", response_model=AssetThreadMessageResponse)
async def create_asset_thread_message(
    ws_id: str,
    asset_id: str,
    thread_id: str,
    data: AssetThreadMessageCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        db_bind = asset_assets_transport._get_db_bind(db)
        created = await asset_assets_transport._run_asset_route_db_txn(
            db,
            db_bind,
            lambda session: asset_review_threads._create_asset_thread_message_sync(
                session,
                ws_id=ws_id,
                asset_id=asset_id,
                thread_id=thread_id,
                creator_id=current_user.id,
                data=data,
                user_id=current_user.id,
            ),
        )
        db.close()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response = AssetThreadMessageResponse(**created["message"])

    await asset_discussion_ws_manager.broadcast(
        created["asset_id"],
        {
            "type": "message_created",
            "asset_id": created["asset_id"],
            "thread_id": created["thread_id"],
            "message": created["message"],
        },
    )
    return response


@router.post("/{asset_id}/threads/{thread_id}/state", response_model=AssetThreadResponse)
async def update_thread_state(
    ws_id: str,
    asset_id: str,
    thread_id: str,
    data: AssetThreadStateUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_bind = asset_assets_transport._get_db_bind(db)
    updated = await asset_assets_transport._run_asset_route_db_txn(
        db,
        db_bind,
        lambda session: asset_review_threads._update_asset_thread_state_sync(
            session,
            ws_id=ws_id,
            asset_id=asset_id,
            thread_id=thread_id,
            status=data.status,
            actor_user_id=current_user.id,
            user_id=current_user.id,
        ),
    )
    db.close()

    await asset_discussion_ws_manager.broadcast(
        updated["asset_id"],
        {
            "type": "thread_updated",
            "asset_id": updated["asset_id"],
            "thread": updated["payload"],
        },
    )
    return AssetThreadResponse(**updated["payload"])


@router.post("/{asset_id}/threads/{thread_id}/close-hint", response_model=AssetThreadResponse)
async def update_thread_close_hint(
    ws_id: str,
    asset_id: str,
    thread_id: str,
    data: AssetThreadCloseHintActionRequest,
    context_version_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_bind = asset_assets_transport._get_db_bind(db)
    updated = await asset_assets_transport._run_asset_route_db_txn(
        db,
        db_bind,
        lambda session: asset_review_threads._update_asset_thread_close_hint_sync(
            session,
            ws_id=ws_id,
            asset_id=asset_id,
            thread_id=thread_id,
            action=data.action,
            context_version_id=context_version_id,
            actor_user_id=current_user.id,
            user_id=current_user.id,
        ),
    )
    db.close()
    await asset_discussion_ws_manager.broadcast(
        updated["asset_id"],
        {
            "type": "thread_updated",
            "asset_id": updated["asset_id"],
            "thread": updated["payload"],
        },
    )
    return AssetThreadResponse(**updated["payload"])
