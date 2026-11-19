"""asset.routers.assets.resolutions domain operations."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.offload import run_db_txn
from app.dependencies import get_current_user, get_db
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.schemas.ai_job import AiJobResponse
from app.domains.ai.services.jobs import constants as ai_job_constants
from app.domains.ai.services.jobs import publishing as ai_job_publishing
from app.domains.ai.services.jobs.store import serialize_job
from app.domains.asset.models.asset import AssetResolutionProposalStatus, SddAssetResolutionProposal
from app.domains.asset.routers.assets import transport as asset_assets_transport
from app.domains.asset.routers.assets.transport import ReviewRoute
from app.domains.asset.schemas.asset import (
    AssetJointProposalCreateRequest,
    AssetResolutionAnchorPrecheckRequest,
    AssetResolutionAnchorPrecheckResponse,
    AssetResolutionApplyRequest,
    AssetResolutionProposalRewriteRequest,
    AssetVersionResponse,
)
from app.domains.asset.schemas.revision import RevisionSelection
from app.domains.asset.services import asset_discussion_service, asset_resolution_service, asset_service
from app.domains.asset.services.document import repository as document_repository
from app.domains.asset.services.review import documents as asset_review_documents
from app.domains.asset.services.review import jobs as asset_review_jobs
from app.domains.asset.services.review import policy as asset_review_policy
from app.domains.asset.services.review import proposal_sources
from app.domains.asset.services.review import resolutions as resolution_commands
from app.domains.asset.ws.asset_discussion_manager import asset_discussion_ws_manager
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.task.services import task_cli_state_service
from app.domains.workspace.services import workspace_service

router = APIRouter(route_class=ReviewRoute)
background_router = APIRouter(prefix="/document-revision-jobs", route_class=ReviewRoute)


def _owned_revision_jobs(db: Session, user_id: str):
    kind = SddAiJob.context_json["job_kind"].as_string()
    return db.query(SddAiJob).filter(
        SddAiJob.creator_id == user_id,
        SddAiJob.channel == AiJobChannel.ASSET_THREAD,
        SddAiJob.task_id.is_not(None),
        SddAiJob.asset_id.is_not(None),
        SddAiJob.thread_id.is_not(None),
        or_(
            kind == ai_job_constants.JOB_KIND_RESOLUTION_REWRITE,
            and_(
                kind == ai_job_constants.JOB_KIND_RESOLUTION_PROPOSAL,
                SddAiJob.context_json["source_thread_ids"].as_string().is_not(None),
            ),
        ),
    )


@background_router.get("", response_model=list[AiJobResponse])
def list_revision_jobs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    job_ids: str = Query(default="", max_length=2000),
):
    tracked_ids = [job_id for job_id in job_ids.split(",") if job_id]
    in_progress = ai_job_constants.ACTIVE_STATUSES - {AiJobStatus.INTERRUPTED, AiJobStatus.ORPHANED}
    jobs = (
        _owned_revision_jobs(db, current_user.id)
        .filter(or_(SddAiJob.status.in_(in_progress), SddAiJob.id.in_(tracked_ids)))
        .order_by(SddAiJob.created_at.desc())
        .all()
    )
    accessible_workspaces = {
        workspace_id
        for workspace_id in {job.workspace_id for job in jobs}
        if workspace_service.user_has_permission(db, workspace_id, current_user.id, WorkspacePermission.VIEW_ASSETS)
    }
    return [serialize_job(job) for job in jobs if job.workspace_id in accessible_workspaces]


@background_router.get("/{job_id}", response_model=AiJobResponse)
def get_revision_job(job_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    job = _owned_revision_jobs(db, current_user.id).filter(SddAiJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Document revision job not found")
    asset_review_policy._verify_comment_permission(job.workspace_id, current_user, db)
    return serialize_job(job)


@router.post("/{asset_id}/resolution/proposals", response_model=AiJobResponse)
async def generate_resolution_comparison(
    ws_id: str,
    asset_id: str,
    data: AssetJointProposalCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db_bind = asset_assets_transport._get_db_bind(db)
    user_id = current_user.id
    try:
        result = await asset_assets_transport._run_asset_route_db_txn(
            db,
            db_bind,
            lambda session: asset_review_jobs.create_joint_comparison_job(
                session, ws_id=ws_id, asset_id=asset_id, user_id=user_id, data=data
            ),
        )
    except task_cli_state_service.BootstrapNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.close()
    if result["created"]:
        await ai_job_publishing.enqueue_asset_thread_job(result["payload"]["id"])
    return AiJobResponse(**result["payload"])


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
    asset_review_policy._verify_comment_permission(ws_id, current_user, db)
    asset = asset_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
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
    if proposal_sources.source_ids(proposal.proposed_patch_json):
        if rewrite_scope != "document":
            raise HTTPException(status_code=409, detail="Joint proposals use document-level rewrite")
    else:
        asset_review_policy._ensure_thread_open(thread)
    if rewrite_scope != "anchor":
        return AssetResolutionAnchorPrecheckResponse(
            ok=True,
            requires_relocation=False,
            anchor_status="valid",
            effective_anchor=None,
        )

    resolved_context_version_id = str(data.context_version_id or "").strip() or asset.active_version_id
    asset_review_policy._ensure_latest_context_version_for_mutation(asset, resolved_context_version_id)

    context_version = None
    if resolved_context_version_id:
        context_version = document_repository.get_asset_version(db, asset.id, resolved_context_version_id)
    if not context_version:
        context_version = asset_review_documents.ensure_active_version(db, asset)

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
    proposal_text = (data.proposal_text or "").strip()
    if not proposal_text:
        raise HTTPException(status_code=422, detail="proposal_text is required")
    rewrite_scope = str(data.rewrite_scope or "anchor").strip().lower()
    if rewrite_scope not in {"anchor", "document"}:
        rewrite_scope = "anchor"
    context_version_id = str(data.context_version_id or "").strip() or None

    relocated_anchor = data.relocated_anchor if isinstance(data.relocated_anchor, dict) else None
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
            context_version_id=context_version_id,
            proposal_id=proposal_id,
            ensure_open=False,
        ),
    )
    db.close()
    resolved_task_id = context["task_id"]
    context_version_id = context["context_version_id"]

    try:
        if not context.get("source_thread_ids"):
            await task_cli_state_service.ensure_thread_session(thread_id, require_ready=True)
    except task_cli_state_service.BootstrapNotReadyError as exc:
        await task_cli_state_service.publish_bootstrap_snapshot(resolved_task_id)
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        created = await asset_assets_transport._run_asset_route_db_txn(
            db,
            db_bind,
            lambda session: asset_review_jobs.create_resolution_rewrite_job(
                session,
                ws_id=ws_id,
                asset_id=asset_id,
                thread_id=thread_id,
                creator_id=current_user.id,
                context_json={
                    "proposal_id": proposal_id,
                    "proposal_text": proposal_text,
                    "rewrite_scope": rewrite_scope,
                    "context_version_id": context_version_id,
                    "relocated_anchor": relocated_anchor,
                },
            ),
        )
    except task_cli_state_service.BootstrapNotReadyError as exc:
        await task_cli_state_service.publish_bootstrap_snapshot(resolved_task_id)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    payload = created["payload"]
    await ai_job_publishing.enqueue_asset_thread_job(payload["id"])
    return AiJobResponse(**payload)


@router.post("/{asset_id}/threads/{thread_id}/resolution/proposals/{proposal_id}/docx-preview")
async def preview_resolution_docx(
    ws_id: str,
    asset_id: str,
    thread_id: str,
    proposal_id: str,
    data: RevisionSelection,
    response: Response,
    current_user: User = Depends(get_current_user),
):
    result = await run_db_txn(
        lambda db: resolution_commands.preview_docx_resolution(
            db,
            ws_id=ws_id,
            asset_id=asset_id,
            thread_id=thread_id,
            proposal_id=proposal_id,
            user_id=current_user.id,
            revision_id=data.revision_id,
            change_ids=data.change_ids,
        )
    )
    response.headers["Cache-Control"] = "private, no-store"
    return result


@router.post("/{asset_id}/threads/{thread_id}/resolution/apply", response_model=AssetVersionResponse)
async def apply_thread_resolution(
    ws_id: str,
    asset_id: str,
    thread_id: str,
    data: AssetResolutionApplyRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        result = await run_db_txn(
            lambda session: resolution_commands.apply_resolution(
                session, ws_id=ws_id, asset_id=asset_id, thread_id=thread_id, data=data, user_id=current_user.id
            )
        )
    except asset_resolution_service.ResolutionServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
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
            "thread_id": result["thread_id"],
            "version": version_response.model_dump(mode="json"),
        },
    )
    await asset_discussion_ws_manager.broadcast(
        result["asset_id"],
        {
            "type": "thread_updated",
            "asset_id": result["asset_id"],
            "thread": result["thread"],
        },
    )
    return version_response
