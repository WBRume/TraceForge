"""asset.routers.assets.jobs domain operations."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.domains.ai.schemas.ai_job import AiJobListResponse, AiJobResponse, AssetThreadAiJobCreateRequest
from app.domains.ai.services.jobs import publishing as ai_job_publishing
from app.domains.ai.services.jobs.store import list_thread_jobs, serialize_job
from app.domains.asset.routers.assets import transport as asset_assets_transport
from app.domains.asset.routers.assets.transport import ReviewRoute
from app.domains.asset.services import asset_discussion_service, asset_service
from app.domains.asset.services.review import jobs as asset_review_jobs
from app.domains.asset.services.review import policy as asset_review_policy
from app.domains.asset.ws.asset_discussion_manager import asset_discussion_ws_manager
from app.domains.auth.models.user import User
from app.domains.task.services import task_cli_state_service

router = APIRouter(route_class=ReviewRoute)


@router.post("/{asset_id}/threads/{thread_id}/ai-jobs", response_model=AiJobResponse)
async def create_asset_thread_ai_job(
    ws_id: str,
    asset_id: str,
    thread_id: str,
    data: AssetThreadAiJobCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_bind = asset_assets_transport._get_db_bind(db)
    context = await asset_assets_transport._run_asset_route_db_txn(
        db,
        db_bind,
        lambda session: asset_review_policy._load_asset_thread_action_context_sync(
            session,
            ws_id=ws_id,
            asset_id=asset_id,
            thread_id=thread_id,
            user_id=current_user.id,
        ),
    )
    db.close()
    resolved_task_id = context["task_id"]

    try:
        await task_cli_state_service.ensure_thread_session(
            thread_id,
            require_ready=True,
        )
    except task_cli_state_service.BootstrapNotReadyError as exc:
        await task_cli_state_service.publish_bootstrap_snapshot(resolved_task_id)
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    prompt_text = (data.prompt or "").strip()
    try:
        created = await asset_assets_transport._run_asset_route_db_txn(
            db,
            db_bind,
            lambda session: asset_review_jobs._create_asset_thread_ai_job_sync(
                session,
                ws_id=ws_id,
                asset_id=asset_id,
                thread_id=thread_id,
                creator_id=current_user.id,
                prompt_text=prompt_text,
            ),
        )
    except task_cli_state_service.BootstrapNotReadyError as exc:
        await task_cli_state_service.publish_bootstrap_snapshot(resolved_task_id)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if created["message"]:
        await asset_discussion_ws_manager.broadcast(
            asset_id,
            {
                "type": "message_created",
                "asset_id": asset_id,
                "thread_id": thread_id,
                "message": created["message"],
            },
        )
    payload = created["payload"]
    await ai_job_publishing.enqueue_asset_thread_job(payload["id"])
    return AiJobResponse(**payload)


@router.get("/{asset_id}/threads/{thread_id}/ai-jobs", response_model=AiJobListResponse)
def list_asset_thread_ai_jobs(
    ws_id: str,
    asset_id: str,
    thread_id: str,
    active_only: bool = Query(default=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset_review_policy._verify_comment_permission(ws_id, current_user, db)
    asset = asset_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    jobs = list_thread_jobs(
        db,
        thread_id=thread.id,
        active_only=active_only,
    )
    items = [AiJobResponse(**serialize_job(item)) for item in jobs]
    return AiJobListResponse(items=items, total=len(items))
