"""
Asset API routes.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.dependencies import get_current_user, get_db
from app.domains.asset.models.asset import (
    AssetResolutionProposalStatus,
    AssetThreadMessageRole,
    AssetThreadStatus,
    SddAssetResolutionProposal,
)
from app.domains.task.models.task import TaskStatus
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.ai.schemas.ai_job import AiJobListResponse, AiJobResponse, AssetThreadAiJobCreateRequest
from app.domains.asset.schemas.asset import (
    AssetDocumentCapabilities,
    AssetDocumentResponse,
    AssetListResponse,
    AssetResolutionAnchorPrecheckRequest,
    AssetResolutionAnchorPrecheckResponse,
    AssetResolutionApplyRequest,
    AssetResolutionProposalCreateRequest,
    AssetResolutionProposalRewriteRequest,
    AssetResolutionProposalResponse,
    AssetResponse,
    AssetThreadCloseHintActionRequest,
    AssetThreadCreateRequest,
    AssetThreadListResponse,
    AssetThreadMarkerResponse,
    AssetThreadMessageCreateRequest,
    AssetThreadMessageResponse,
    AssetThreadResponse,
    AssetThreadStateUpdateRequest,
    AssetVersionListResponse,
    AssetVersionResponse,
)
from app.domains.workspace_asset.schemas.workspace_asset import DecisionCreateRequest
from app.domains.ai.services import ai_job_service
from app.domains.asset.services import asset_discussion_service, asset_document_service, asset_resolution_service, asset_service
from app.domains.auth.services import auth_service
from app.domains.task.services import task_cli_state_service, task_service
from app.domains.workspace.services import workspace_service
from app.domains.workspace_asset.services import workspace_task_detail_service
from app.domains.asset.ws.asset_discussion_manager import asset_discussion_ws_manager

router = APIRouter(prefix="/workspaces/{ws_id}/assets", tags=["Assets"])
logger = get_logger(__name__, category="ai_session")


def _verify_asset_access(ws_id: str, user: User, db: Session) -> None:
    member = workspace_service.get_workspace_member(db, ws_id, user.id)
    if not member:
        raise HTTPException(status_code=403, detail="No access to this workspace")
    if not workspace_service.user_has_permission(db, ws_id, user.id, WorkspacePermission.VIEW_ASSETS):
        raise HTTPException(status_code=403, detail="No permission to view assets")


def _verify_comment_permission(ws_id: str, user: User, db: Session) -> None:
    member = workspace_service.get_workspace_member(db, ws_id, user.id)
    if not member:
        raise HTTPException(status_code=403, detail="No access to this workspace")
    if not workspace_service.user_has_permission(db, ws_id, user.id, WorkspacePermission.VIEW_ASSETS):
        raise HTTPException(status_code=403, detail="No permission to view assets")


def _verify_expert_permission(ws_id: str, user: User, db: Session) -> None:
    _verify_comment_permission(ws_id, user, db)
    if not workspace_service.is_workspace_expert(db, ws_id, user.id):
        raise HTTPException(status_code=403, detail="Only workspace experts can apply resolutions")


def _ensure_spec_editable(asset) -> None:
    task = getattr(asset, "task", None)
    if not task:
        return
    if task.status != TaskStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail="Task engine already started, requirement document is read-only",
        )


def _serialize_asset(asset) -> AssetResponse:
    asset_type = asset.asset_type.value if hasattr(asset.asset_type, "value") else str(asset.asset_type)
    return AssetResponse(
        id=asset.id,
        task_id=asset.task_id,
        workspace_id=asset.workspace_id,
        asset_type=asset_type,
        name=asset.name,
        content_text=asset.content_text,
        content_json=asset.content_json,
        created_at=asset.created_at,
    )


def _serialize_version(version) -> AssetVersionResponse:
    return AssetVersionResponse(
        id=version.id,
        asset_id=version.asset_id,
        version_no=version.version_no,
        base_version_id=version.base_version_id,
        original_ext=version.original_ext,
        original_mime=version.original_mime,
        normalized_markdown=version.normalized_markdown,
        blocks_json=version.blocks_json,
        render_json=version.render_json,
        change_note=version.change_note,
        created_by=version.created_by,
        created_at=version.created_at,
    )


def _serialize_message(message) -> AssetThreadMessageResponse:
    creator_display_name = message.creator.display_name if message.creator else None
    creator_avatar_svg = auth_service.resolve_user_avatar_svg(message.creator) if message.creator else None
    role = message.role.value if hasattr(message.role, "value") else str(message.role)
    return AssetThreadMessageResponse(
        id=message.id,
        thread_id=message.thread_id,
        role=role,
        content=message.content,
        creator_id=message.creator_id,
        creator_display_name=creator_display_name,
        creator_avatar_svg=creator_avatar_svg,
        metadata_json=message.metadata_json,
        created_at=message.created_at,
    )


def _serialize_proposal(proposal) -> AssetResolutionProposalResponse:
    status = proposal.status.value if hasattr(proposal.status, "value") else str(proposal.status)
    return AssetResolutionProposalResponse(
        id=proposal.id,
        thread_id=proposal.thread_id,
        base_version_id=proposal.base_version_id,
        proposed_patch_json=proposal.proposed_patch_json,
        diff_text=proposal.diff_text,
        status=status,
        creator_id=proposal.creator_id,
        created_at=proposal.created_at,
        updated_at=proposal.updated_at,
    )


def _serialize_thread(thread) -> AssetThreadResponse:
    status = thread.status.value if hasattr(thread.status, "value") else str(thread.status)
    creator_display_name = thread.creator.display_name if thread.creator else None
    creator_avatar_svg = auth_service.resolve_user_avatar_svg(thread.creator) if thread.creator else None
    messages = sorted(list(thread.messages or []), key=lambda item: item.created_at)
    proposals = sorted(list(thread.proposals or []), key=lambda item: item.created_at, reverse=True)
    return AssetThreadResponse(
        id=thread.id,
        asset_id=thread.asset_id,
        version_id=thread.version_id,
        task_id=thread.task_id,
        workspace_id=thread.workspace_id,
        block_id=thread.block_id,
        selected_text=thread.selected_text,
        char_start=thread.char_start,
        char_end=thread.char_end,
        status=status,
        creator_id=thread.creator_id,
        creator_display_name=creator_display_name,
        creator_avatar_svg=creator_avatar_svg,
        resolved_by=thread.resolved_by,
        resolved_at=thread.resolved_at,
        resolved_version_id=thread.resolved_version_id,
        close_hint_state=str(thread.close_hint_state or "none"),
        close_hint_reason=thread.close_hint_reason,
        close_hint_version_id=thread.close_hint_version_id,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        messages=[_serialize_message(item) for item in messages],
        proposals=[_serialize_proposal(item) for item in proposals],
    )


def _serialize_thread_with_context(
    db: Session,
    *,
    thread,
    context_version=None,
) -> AssetThreadResponse:
    payload = _serialize_thread(thread).model_dump()
    anchor_eval = asset_discussion_service.resolve_thread_anchor_for_version(
        db,
        thread=thread,
        context_version=context_version,
    )
    payload["close_hint_state"] = str(thread.close_hint_state or "none")
    payload["close_hint_reason"] = thread.close_hint_reason
    payload["close_hint_version_id"] = thread.close_hint_version_id
    payload["anchor_status"] = str(anchor_eval.get("anchor_status") or "valid")
    payload["effective_anchor"] = anchor_eval.get("effective_anchor")
    return AssetThreadResponse(**payload)


def _ensure_thread_open(thread) -> None:
    status = thread.status.value if hasattr(thread.status, "value") else str(thread.status)
    if status == AssetThreadStatus.OPEN.value:
        return
    raise HTTPException(status_code=409, detail="Thread is not open")


def _ensure_active_version(db: Session, asset):
    before_active = asset.active_version_id
    version = asset_document_service.ensure_asset_has_version(db, asset)
    if version and asset.active_version_id != version.id:
        asset.active_version_id = version.id
    if version and asset.active_version_id != before_active:
        db.commit()
        db.refresh(asset)
    return version


def _is_latest_context_version(asset, context_version_id: Optional[str]) -> bool:
    active_id = str(asset.active_version_id or "").strip()
    context_id = str(context_version_id or "").strip()
    if not active_id or not context_id:
        return True
    return active_id == context_id


def _ensure_latest_context_version_for_mutation(asset, context_version_id: Optional[str]) -> None:
    if _is_latest_context_version(asset, context_version_id):
        return
    raise HTTPException(
        status_code=409,
        detail="Historical document versions are read-only",
    )


def _maybe_backfill_task_spec_asset(db: Session, ws_id: str, task_id: Optional[str]) -> None:
    if not task_id:
        return
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        return
    created = asset_document_service.ensure_spec_asset_backfilled(db, task)
    if created:
        db.commit()


@router.get("", response_model=AssetListResponse)
def search_assets(
    ws_id: str,
    task_id: Optional[str] = Query(None),
    asset_type: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    creator_id: Optional[str] = Query(None),
    include_unfinished_task_spec: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _verify_asset_access(ws_id, current_user, db)
    if include_unfinished_task_spec:
        _maybe_backfill_task_spec_asset(db, ws_id, task_id)
    items, total = asset_service.search_assets(
        db=db,
        workspace_id=ws_id,
        task_id=task_id,
        asset_type=asset_type,
        keyword=keyword,
        creator_id=creator_id,
        include_unfinished_task_spec=include_unfinished_task_spec,
        page=page,
        page_size=page_size,
    )
    # Extra fallback: if task-level SPEC query returned empty but asset exists,
    # return it explicitly to avoid enum/filter compatibility edge cases.
    if (
        total == 0
        and task_id
        and asset_type
        and str(asset_type).upper() == "SPEC"
        and include_unfinished_task_spec
    ):
        fallback_asset = asset_service.get_task_asset_by_type(
            db,
            task_id=task_id,
            asset_type="SPEC",
        )
        if fallback_asset and fallback_asset.workspace_id == ws_id:
            logger.warning(
                "SPEC asset fallback hit for ws={} task={} asset={}",
                ws_id,
                task_id,
                fallback_asset.id,
            )
            items = [fallback_asset]
            total = 1
    return AssetListResponse(items=[_serialize_asset(item) for item in items], total=total)


@router.get("/{asset_id}", response_model=AssetResponse)
def get_asset(
    ws_id: str,
    asset_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _verify_asset_access(ws_id, current_user, db)
    asset = asset_service.get_asset(db, asset_id, ws_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return _serialize_asset(asset)


@router.get("/{asset_id}/document", response_model=AssetDocumentResponse)
def get_asset_document(
    ws_id: str,
    asset_id: str,
    version_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _verify_asset_access(ws_id, current_user, db)
    asset = asset_document_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    active_version = None
    if version_id:
        active_version = asset_document_service.get_asset_version(db, asset.id, version_id)
    if not active_version:
        active_version = _ensure_active_version(db, asset)
    updated = False
    if active_version and asset_document_service.repair_docx_version_if_needed(db, asset, active_version):
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
    is_latest_context_version = _is_latest_context_version(asset, selected_version_id)
    can_comment = can_view and is_latest_context_version
    can_apply_resolution = (
        workspace_service.is_workspace_expert(db, ws_id, current_user.id)
        and is_latest_context_version
    )
    inline_review_enabled = asset_document_service.can_inline_review(asset.source_ext)
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
        asset=_serialize_asset(asset),
        active_version=_serialize_version(active_version) if active_version else None,
        blocks=blocks,
        thread_markers=markers,
        capabilities=AssetDocumentCapabilities(
            can_view=can_view,
            can_comment=can_comment,
            can_ai_reply=can_ai_reply,
            can_apply_resolution=can_apply_resolution,
            inline_review_enabled=inline_review_enabled,
            ai_available=ai_available,
            ai_unavailable_reason=ai_unavailable_reason,
        ),
    )


@router.get("/{asset_id}/versions", response_model=AssetVersionListResponse)
def list_asset_versions(
    ws_id: str,
    asset_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _verify_asset_access(ws_id, current_user, db)
    asset = asset_document_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    versions = asset_document_service.list_asset_versions(db, asset.id)
    return AssetVersionListResponse(
        items=[_serialize_version(version) for version in versions],
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
    _verify_asset_access(ws_id, current_user, db)
    asset = asset_document_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    version = asset_document_service.get_asset_version(db, asset.id, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    return _serialize_version(version)


@router.get("/{asset_id}/threads", response_model=AssetThreadListResponse)
def list_asset_threads(
    ws_id: str,
    asset_id: str,
    context_version_id: Optional[str] = Query(default=None),
    version_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _verify_asset_access(ws_id, current_user, db)
    asset = asset_document_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    resolved_context_version_id = context_version_id or version_id
    context_version = None
    if resolved_context_version_id:
        context_version = asset_document_service.get_asset_version(db, asset.id, resolved_context_version_id)
    if not context_version:
        context_version = _ensure_active_version(db, asset)
    items = asset_discussion_service.list_threads(db, asset_id=asset.id, version_id=None)
    return AssetThreadListResponse(
        items=[
            _serialize_thread_with_context(
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
    _verify_asset_access(ws_id, current_user, db)
    asset = asset_document_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    context_version = None
    if context_version_id:
        context_version = asset_document_service.get_asset_version(db, asset.id, context_version_id)
    if not context_version:
        context_version = _ensure_active_version(db, asset)
    return _serialize_thread_with_context(
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
    _verify_comment_permission(ws_id, current_user, db)
    asset = asset_document_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    version = None
    if data.version_id:
        version = asset_document_service.get_asset_version(db, asset.id, data.version_id)
    if not version:
        version = _ensure_active_version(db, asset)
    if not version:
        raise HTTPException(status_code=400, detail="Asset has no version to annotate")
    _ensure_latest_context_version_for_mutation(asset, version.id)

    try:
        thread = asset_discussion_service.create_thread(
            db,
            asset=asset,
            version=version,
            creator_id=current_user.id,
            block_id=data.block_id,
            body=data.body,
            selected_text=data.selected_text,
            char_start=data.char_start,
            char_end=data.char_end,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    db.commit()
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread.id)
    payload = _serialize_thread_with_context(
        db,
        thread=thread,
        context_version=version,
    )

    await asset_discussion_ws_manager.broadcast(
        asset.id,
        {
            "type": "thread_created",
            "asset_id": asset.id,
            "thread": payload.model_dump(mode="json"),
        },
    )
    task_cli_state_service.schedule_prepare_thread_workspace(thread.id)
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
    _verify_comment_permission(ws_id, current_user, db)
    asset = asset_document_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    _ensure_thread_open(thread)

    try:
        message = asset_discussion_service.add_thread_message(
            db,
            thread=thread,
            role=AssetThreadMessageRole.USER,
            content=data.content,
            creator_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    db.commit()
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread.id)
    created = next((item for item in (thread.messages or []) if item.id == message.id), None)
    response = _serialize_message(created or message)

    await asset_discussion_ws_manager.broadcast(
        asset.id,
        {
            "type": "message_created",
            "asset_id": asset.id,
            "thread_id": thread.id,
            "message": response.model_dump(mode="json"),
        },
    )
    return response


@router.post("/{asset_id}/threads/{thread_id}/ai-jobs", response_model=AiJobResponse)
async def create_asset_thread_ai_job(
    ws_id: str,
    asset_id: str,
    thread_id: str,
    data: AssetThreadAiJobCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _verify_comment_permission(ws_id, current_user, db)
    asset = asset_document_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    _ensure_thread_open(thread)
    if not thread.task_id:
        raise HTTPException(status_code=400, detail="Thread task is required")

    try:
        task_cli_state_service.ensure_bootstrap_ready(
            db,
            workspace_id=ws_id,
            task_id=thread.task_id,
        )
        await task_cli_state_service.ensure_thread_session(
            thread.id,
            require_ready=True,
        )
    except task_cli_state_service.BootstrapNotReadyError as exc:
        await task_cli_state_service.publish_bootstrap_snapshot(thread.task_id)
        raise HTTPException(status_code=409, detail=str(exc))

    prompt_text = (data.prompt or "").strip()
    if prompt_text:
        user_message = asset_discussion_service.add_thread_message(
            db,
            thread=thread,
            role=AssetThreadMessageRole.USER,
            content=prompt_text,
            creator_id=current_user.id,
            metadata_json={"source": "@AI", "kind": "manual_ai_job"},
        )
        db.commit()
        thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread.id)
        created = next((item for item in (thread.messages or []) if item.id == user_message.id), None)
        if created:
            await asset_discussion_ws_manager.broadcast(
                asset.id,
                {
                    "type": "message_created",
                    "asset_id": asset.id,
                    "thread_id": thread.id,
                    "message": _serialize_message(created).model_dump(mode="json"),
                },
            )

    job = ai_job_service.create_asset_thread_job(
        db,
        workspace_id=ws_id,
        task_id=thread.task_id,
        asset_id=asset.id,
        thread_id=thread.id,
        creator_id=current_user.id,
        prompt_text=prompt_text or None,
        job_kind=ai_job_service.JOB_KIND_THREAD_AI_REPLY,
    )
    payload = ai_job_service.serialize_job(job)
    await ai_job_service.enqueue_asset_thread_job(job.id)
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
    _verify_comment_permission(ws_id, current_user, db)
    asset = asset_document_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    jobs = ai_job_service.list_thread_jobs(
        db,
        thread_id=thread.id,
        active_only=active_only,
    )
    items = [AiJobResponse(**ai_job_service.serialize_job(item)) for item in jobs]
    return AiJobListResponse(items=items, total=len(items))


@router.post("/{asset_id}/threads/{thread_id}/resolution/proposals", response_model=AiJobResponse)
async def create_thread_resolution_proposal(
    ws_id: str,
    asset_id: str,
    thread_id: str,
    data: Optional[AssetResolutionProposalCreateRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _verify_comment_permission(ws_id, current_user, db)
    asset = asset_document_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    _ensure_thread_open(thread)
    if not thread.task_id:
        raise HTTPException(status_code=400, detail="Thread task is required")
    request_data = data or AssetResolutionProposalCreateRequest()
    overwrite_existing_draft = bool(request_data.overwrite_existing_draft)
    context_version_id = str(request_data.context_version_id or "").strip() or None
    _ensure_latest_context_version_for_mutation(asset, context_version_id or asset.active_version_id)

    existing_draft = (
        db.query(SddAssetResolutionProposal)
        .filter(
            SddAssetResolutionProposal.thread_id == thread.id,
            SddAssetResolutionProposal.status == AssetResolutionProposalStatus.DRAFT,
        )
        .order_by(SddAssetResolutionProposal.updated_at.desc(), SddAssetResolutionProposal.created_at.desc())
        .first()
    )
    if existing_draft and not overwrite_existing_draft:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Draft proposal already exists",
                "existing_draft_id": existing_draft.id,
            },
        )

    try:
        task_cli_state_service.ensure_bootstrap_ready(
            db,
            workspace_id=ws_id,
            task_id=thread.task_id,
        )
        await task_cli_state_service.ensure_thread_session(
            thread.id,
            require_ready=True,
        )
    except task_cli_state_service.BootstrapNotReadyError as exc:
        await task_cli_state_service.publish_bootstrap_snapshot(thread.task_id)
        raise HTTPException(status_code=409, detail=str(exc))

    job = ai_job_service.create_asset_thread_job(
        db,
        workspace_id=ws_id,
        task_id=thread.task_id,
        asset_id=asset.id,
        thread_id=thread.id,
        creator_id=current_user.id,
        prompt_text=None,
        job_kind=ai_job_service.JOB_KIND_RESOLUTION_PROPOSAL,
        context_json={
            "overwrite_existing_draft": overwrite_existing_draft,
            "existing_draft_id": existing_draft.id if existing_draft else None,
            "context_version_id": context_version_id or asset.active_version_id,
        },
    )
    payload = ai_job_service.serialize_job(job)
    await ai_job_service.enqueue_asset_thread_job(job.id)
    return AiJobResponse(**payload)


@router.post(
    "/{asset_id}/threads/{thread_id}/resolution/proposals/{proposal_id}/anchor-precheck",
    response_model=AssetResolutionAnchorPrecheckResponse,
)
def precheck_thread_resolution_anchor(
    ws_id: str,
    asset_id: str,
    thread_id: str,
    proposal_id: str,
    data: AssetResolutionAnchorPrecheckRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _verify_comment_permission(ws_id, current_user, db)
    asset = asset_document_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    _ensure_thread_open(thread)
    proposal = (
        db.query(SddAssetResolutionProposal)
        .filter(
            SddAssetResolutionProposal.id == proposal_id,
            SddAssetResolutionProposal.thread_id == thread.id,
        )
        .first()
    )
    if not proposal:
        raise HTTPException(status_code=404, detail="Resolution proposal not found")
    if proposal.status != AssetResolutionProposalStatus.DRAFT:
        raise HTTPException(status_code=409, detail="Only draft proposals can be checked")

    rewrite_scope = str(data.rewrite_scope or "anchor").strip().lower()
    if rewrite_scope != "anchor":
        return AssetResolutionAnchorPrecheckResponse(
            ok=True,
            requires_relocation=False,
            anchor_status="valid",
            effective_anchor=None,
        )

    resolved_context_version_id = str(data.context_version_id or "").strip() or asset.active_version_id
    _ensure_latest_context_version_for_mutation(asset, resolved_context_version_id)

    context_version = None
    if resolved_context_version_id:
        context_version = asset_document_service.get_asset_version(db, asset.id, resolved_context_version_id)
    if not context_version:
        context_version = _ensure_active_version(db, asset)

    anchor_eval = asset_discussion_service.resolve_thread_anchor_for_version(
        db,
        thread=thread,
        context_version=context_version,
    )
    anchor_status = str(anchor_eval.get("anchor_status") or "valid")
    requires_relocation = anchor_status == "missing"
    return AssetResolutionAnchorPrecheckResponse(
        ok=not requires_relocation,
        requires_relocation=requires_relocation,
        reason="anchor_missing" if requires_relocation else None,
        anchor_status=anchor_status,
        effective_anchor=anchor_eval.get("effective_anchor"),
    )


@router.post(
    "/{asset_id}/threads/{thread_id}/resolution/proposals/{proposal_id}/rewrite",
    response_model=AiJobResponse,
)
async def rewrite_thread_resolution_proposal(
    ws_id: str,
    asset_id: str,
    thread_id: str,
    proposal_id: str,
    data: AssetResolutionProposalRewriteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _verify_comment_permission(ws_id, current_user, db)
    asset = asset_document_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    _ensure_thread_open(thread)
    if not thread.task_id:
        raise HTTPException(status_code=400, detail="Thread task is required")

    proposal = (
        db.query(SddAssetResolutionProposal)
        .filter(
            SddAssetResolutionProposal.id == proposal_id,
            SddAssetResolutionProposal.thread_id == thread.id,
        )
        .first()
    )
    if not proposal:
        raise HTTPException(status_code=404, detail="Resolution proposal not found")
    if proposal.status != AssetResolutionProposalStatus.DRAFT:
        raise HTTPException(status_code=409, detail="Only draft proposals can be rewritten")

    proposal_text = (data.proposal_text or "").strip()
    if not proposal_text:
        raise HTTPException(status_code=422, detail="proposal_text is required")
    rewrite_scope = str(data.rewrite_scope or "anchor").strip().lower()
    if rewrite_scope not in {"anchor", "document"}:
        rewrite_scope = "anchor"
    context_version_id = str(data.context_version_id or "").strip() or asset.active_version_id
    _ensure_latest_context_version_for_mutation(asset, context_version_id)

    relocated_anchor = data.relocated_anchor if isinstance(data.relocated_anchor, dict) else None

    try:
        task_cli_state_service.ensure_bootstrap_ready(
            db,
            workspace_id=ws_id,
            task_id=thread.task_id,
        )
        await task_cli_state_service.ensure_thread_session(
            thread.id,
            require_ready=True,
        )
    except task_cli_state_service.BootstrapNotReadyError as exc:
        await task_cli_state_service.publish_bootstrap_snapshot(thread.task_id)
        raise HTTPException(status_code=409, detail=str(exc))

    job = ai_job_service.create_asset_thread_job(
        db,
        workspace_id=ws_id,
        task_id=thread.task_id,
        asset_id=asset.id,
        thread_id=thread.id,
        creator_id=current_user.id,
        prompt_text=None,
        job_kind=ai_job_service.JOB_KIND_RESOLUTION_REWRITE,
        context_json={
            "proposal_id": proposal.id,
            "proposal_text": proposal_text,
            "rewrite_scope": rewrite_scope,
            "context_version_id": context_version_id,
            "relocated_anchor": relocated_anchor,
        },
    )
    payload = ai_job_service.serialize_job(job)
    await ai_job_service.enqueue_asset_thread_job(job.id)
    return AiJobResponse(**payload)


@router.post("/{asset_id}/threads/{thread_id}/resolution/apply", response_model=AssetVersionResponse)
async def apply_thread_resolution(
    ws_id: str,
    asset_id: str,
    thread_id: str,
    data: AssetResolutionApplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _verify_expert_permission(ws_id, current_user, db)
    asset = asset_document_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    _ensure_spec_editable(asset)
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    _ensure_thread_open(thread)

    proposal = (
        db.query(SddAssetResolutionProposal)
        .filter(
            SddAssetResolutionProposal.id == data.proposal_id,
            SddAssetResolutionProposal.thread_id == thread.id,
        )
        .first()
    )
    if not proposal:
        raise HTTPException(status_code=404, detail="Resolution proposal not found")

    try:
        version = asset_resolution_service.apply_resolution_proposal(
            db,
            asset=asset,
            thread=thread,
            proposal=proposal,
            actor_user_id=current_user.id,
            final_block_ast=data.final_block_ast,
            final_blocks_ast=data.final_blocks_ast,
            change_note=data.change_note,
        )
    except asset_resolution_service.ResolutionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    if data.decision:
        if not thread.task_id:
            raise HTTPException(status_code=422, detail="Decision source requires a Task-bound Spec / Plan asset")
        try:
            workspace_task_detail_service.create_decision(
                db,
                ws_id,
                thread.task_id,
                current_user.id,
                DecisionCreateRequest(
                    requirement_id=data.decision.requirement_id,
                    status="ACCEPTED",
                    title=data.decision.title,
                    body=data.decision.body,
                    impact_scope=data.decision.impact_scope,
                    promote_candidate=data.decision.promote_candidate,
                    source_type="SPEC_PLAN_CHANGE",
                    source_asset_id=asset.id,
                    source_asset_version_id=version.id,
                    source_asset_thread_id=thread.id,
                    source_resolution_proposal_id=proposal.id,
                    source_metadata={
                        "asset_type": asset.asset_type.value if hasattr(asset.asset_type, "value") else str(asset.asset_type),
                        "asset_name": asset.name,
                        "thread_block_id": thread.block_id,
                        "resolution_applied": True,
                    },
                    change_reason="Recorded from Spec / Plan resolution apply.",
                ),
            )
        except workspace_task_detail_service.TaskDetailWriteError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    db.commit()
    if thread.task_id:
        task_cli_state_service.schedule_bootstrap(thread.task_id)
        await task_cli_state_service.publish_bootstrap_snapshot(thread.task_id)
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread.id)
    version_response = _serialize_version(version)

    await asset_discussion_ws_manager.broadcast(
        asset.id,
        {
            "type": "version_applied",
            "asset_id": asset.id,
            "thread_id": thread.id,
            "version": version_response.model_dump(mode="json"),
        },
    )
    await asset_discussion_ws_manager.broadcast(
        asset.id,
        {
            "type": "thread_updated",
            "asset_id": asset.id,
            "thread": _serialize_thread_with_context(
                db,
                thread=thread,
                context_version=version,
            ).model_dump(mode="json"),
        },
    )
    return version_response


@router.post("/{asset_id}/threads/{thread_id}/state", response_model=AssetThreadResponse)
async def update_thread_state(
    ws_id: str,
    asset_id: str,
    thread_id: str,
    data: AssetThreadStateUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _verify_expert_permission(ws_id, current_user, db)
    asset = asset_document_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    if data.status == "resolved":
        target_status = AssetThreadStatus.RESOLVED
    elif data.status == "closed":
        target_status = AssetThreadStatus.CLOSED
    else:
        target_status = AssetThreadStatus.OPEN
    asset_discussion_service.set_thread_status(
        db,
        thread=thread,
        status=target_status,
        actor_user_id=current_user.id,
        resolved_version_id=(asset.active_version_id if target_status != AssetThreadStatus.OPEN else None),
    )
    db.commit()
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread.id)
    response = _serialize_thread_with_context(
        db,
        thread=thread,
        context_version=asset_document_service.get_asset_version(db, asset.id, asset.active_version_id)
        if asset.active_version_id
        else None,
    )

    await asset_discussion_ws_manager.broadcast(
        asset.id,
        {
            "type": "thread_updated",
            "asset_id": asset.id,
            "thread": response.model_dump(mode="json"),
        },
    )
    return response


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
    _verify_comment_permission(ws_id, current_user, db)
    asset = asset_document_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    context_version = None
    resolved_context_id = str(context_version_id or "").strip() or asset.active_version_id
    if resolved_context_id:
        context_version = asset_document_service.get_asset_version(db, asset.id, resolved_context_id)

    if data.action == "mark_no_close_needed":
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
                actor_user_id=current_user.id,
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

    db.commit()
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread.id)
    response = _serialize_thread_with_context(
        db,
        thread=thread,
        context_version=context_version,
    )
    await asset_discussion_ws_manager.broadcast(
        asset.id,
        {
            "type": "thread_updated",
            "asset_id": asset.id,
            "thread": response.model_dump(mode="json"),
        },
    )
    return response
