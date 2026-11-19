"""Validate and create AI review reply and document revision jobs."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.ai.models.ai_job import SddAiJob
from app.domains.ai.services.jobs import constants as ai_job_constants
from app.domains.ai.services.jobs.store import create_asset_thread_job, serialize_job
from app.domains.asset.models.asset import (
    AssetResolutionProposalStatus,
    AssetThreadMessageRole,
    SddAssetResolutionProposal,
)
from app.domains.asset.schemas.asset import AssetJointProposalCreateRequest
from app.domains.asset.services import asset_discussion_service, asset_service
from app.domains.asset.services.document.transactions import lock_asset
from app.domains.asset.services.review import policy as asset_review_policy
from app.domains.asset.services.review import proposal_sources
from app.domains.asset.services.review import serialization as asset_review_serialization
from app.domains.asset.services.review.errors import ReviewError
from app.domains.task.services import task_cli_state_service


def _revision_jobs_for_thread(db: Session, thread_id: str) -> list[SddAiJob]:
    return (
        db.query(SddAiJob)
        .filter(SddAiJob.thread_id == thread_id, SddAiJob.status.in_(ai_job_constants.ACTIVE_STATUSES))
        .populate_existing()
        .all()
    )


def create_joint_comparison_job(
    db: Session,
    *,
    ws_id: str,
    asset_id: str,
    user_id: str,
    data: AssetJointProposalCreateRequest,
) -> dict:
    """Queue a document revision from resolved discussions and the published version."""
    asset_review_policy._verify_comment_permission_by_id(ws_id, user_id, db)
    asset = asset_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise ReviewError(404, "Asset not found")
    sources = tuple(sorted(set(data.thread_ids)))
    version, threads = proposal_sources.validate_sources(db, asset, sources, data.context_version_id, lock=True)
    owner = threads[0]
    task_cli_state_service.ensure_bootstrap_ready(db, workspace_id=ws_id, task_id=owner.task_id)
    for job in _revision_jobs_for_thread(db, owner.id):
        context = job.context_json or {}
        if context.get("job_kind") not in {
            ai_job_constants.JOB_KIND_RESOLUTION_PROPOSAL,
            ai_job_constants.JOB_KIND_RESOLUTION_REWRITE,
        } or not proposal_sources.source_ids(context):
            continue
        if (
            context.get("context_version_id") == version.id
            and proposal_sources.source_ids(context) == sources
            and job.creator_id == user_id
        ):
            return {"payload": serialize_job(job), "created": False}
        raise ReviewError(409, "A revision is already being generated for these discussions")
    drafts = proposal_sources.matching_drafts(db, owner.id, sources, version.id)
    if drafts and not data.overwrite_existing_draft:
        raise ReviewError(409, {"message": "Draft proposal already exists", "existing_draft_id": drafts[0].id})
    job = create_asset_thread_job(
        db,
        workspace_id=ws_id,
        task_id=owner.task_id,
        asset_id=asset.id,
        thread_id=owner.id,
        creator_id=user_id,
        prompt_text=None,
        job_kind=ai_job_constants.JOB_KIND_RESOLUTION_REWRITE,
        context_json={
            "context_version_id": version.id,
            "source_thread_ids": list(sources),
            "overwrite_existing_draft": data.overwrite_existing_draft,
            "rewrite_scope": "document",
            "document_name": asset.name,
        },
    )
    return {"payload": serialize_job(job), "created": True}


def _create_asset_thread_ai_job_sync(
    db: Session,
    *,
    ws_id: str,
    asset_id: str,
    thread_id: str,
    creator_id: str,
    prompt_text: str,
) -> dict:
    asset = asset_service.get_asset_by_id(db, ws_id, asset_id)
    thread = asset_discussion_service.get_thread(db, asset_id=asset_id, thread_id=thread_id)
    if not asset or not thread:
        raise ReviewError(status_code=404, detail="Asset thread not found")
    asset_review_policy._ensure_thread_open(thread)
    if not thread.task_id:
        raise ReviewError(status_code=400, detail="Thread task is required")
    task_cli_state_service.ensure_bootstrap_ready_or_start(db, workspace_id=ws_id, task_id=thread.task_id)
    message_payload = None
    if prompt_text:
        message = asset_discussion_service.add_thread_message(
            db,
            thread=thread,
            role=AssetThreadMessageRole.USER,
            content=prompt_text,
            creator_id=creator_id,
            metadata_json={"source": "@AI", "kind": "manual_ai_job"},
        )
        # The AI job creation commits this message in the same short DB phase.
        message_payload = asset_review_serialization._serialize_message(message).model_dump(mode="json")
    job = create_asset_thread_job(
        db,
        workspace_id=ws_id,
        task_id=thread.task_id,
        asset_id=asset.id,
        thread_id=thread.id,
        creator_id=creator_id,
        prompt_text=prompt_text or None,
        job_kind=ai_job_constants.JOB_KIND_THREAD_AI_REPLY,
    )
    return {"payload": serialize_job(job), "message": message_payload}


def create_resolution_rewrite_job(
    db: Session,
    *,
    ws_id: str,
    asset_id: str,
    thread_id: str,
    creator_id: str,
    context_json: dict,
) -> dict:
    """Queue a rewrite for an existing saved draft."""
    asset = asset_service.get_asset_by_id(db, ws_id, asset_id)
    thread = asset_discussion_service.get_thread(db, asset_id=asset_id, thread_id=thread_id)
    if not asset or not thread:
        raise ReviewError(status_code=404, detail="Asset thread not found")
    if not thread.task_id:
        raise ReviewError(status_code=400, detail="Thread task is required")
    lock_asset(db, asset)
    context_version_id = str(context_json.get("context_version_id") or "").strip() or None
    asset_review_policy._ensure_latest_context_version_for_mutation(
        asset, context_version_id or asset.active_version_id
    )
    proposal_id = str(context_json.get("proposal_id") or "").strip() or None
    proposal = (
        db.query(SddAssetResolutionProposal)
        .filter(
            SddAssetResolutionProposal.id == proposal_id,
            SddAssetResolutionProposal.thread_id == thread.id,
        )
        .populate_existing()
        .first()
    )
    if not proposal:
        raise ReviewError(status_code=404, detail="Resolution proposal not found")
    if proposal.status != AssetResolutionProposalStatus.DRAFT:
        raise ReviewError(status_code=409, detail="Only draft proposals can be rewritten")
    sources = proposal_sources.source_ids(proposal.proposed_patch_json)
    if sources:
        if context_version_id != proposal.base_version_id or context_json.get("rewrite_scope") != "document":
            raise ReviewError(409, "Joint proposals require a document rewrite on their base version")
        proposal_sources.validate_sources(db, asset, sources, proposal.base_version_id)
        context_json = {**context_json, "source_thread_ids": list(sources), "relocated_anchor": None}
    else:
        asset_review_policy._ensure_thread_open(thread)
    for active in _revision_jobs_for_thread(db, thread.id):
        context = active.context_json or {}
        if context.get("job_kind") not in {
            ai_job_constants.JOB_KIND_RESOLUTION_PROPOSAL,
            ai_job_constants.JOB_KIND_RESOLUTION_REWRITE,
        }:
            continue
        if context.get("proposal_id") == proposal_id or (sources and proposal_sources.source_ids(context) == sources):
            raise ReviewError(
                status_code=409,
                detail={"message": "Document revision is already in progress", "job_id": active.id},
            )
    task_cli_state_service.ensure_bootstrap_ready_or_start(db, workspace_id=ws_id, task_id=thread.task_id)
    job = create_asset_thread_job(
        db,
        workspace_id=ws_id,
        task_id=thread.task_id,
        asset_id=asset.id,
        thread_id=thread.id,
        creator_id=creator_id,
        prompt_text=None,
        job_kind=ai_job_constants.JOB_KIND_RESOLUTION_REWRITE,
        context_json={**context_json, "document_name": asset.name},
    )
    return {"payload": serialize_job(job)}
