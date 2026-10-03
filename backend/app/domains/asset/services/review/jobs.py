"""Validate and create AI review reply, proposal and rewrite jobs."""

from __future__ import annotations
from sqlalchemy.orm import Session
from app.domains.asset.models.asset import AssetResolutionProposalStatus, AssetThreadMessageRole, SddAssetResolutionProposal
from app.domains.ai.services.jobs import constants as ai_job_constants
from app.domains.ai.services.jobs.store import create_asset_thread_job, serialize_job
from app.domains.asset.services import asset_discussion_service, asset_service
from app.domains.task.services import task_cli_state_service
from app.domains.asset.services.review.errors import ReviewError
from app.domains.asset.services.review import policy as asset_review_policy
from app.domains.asset.services.review import serialization as asset_review_serialization


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
    task_cli_state_service.ensure_bootstrap_ready_or_start(
        db, workspace_id=ws_id, task_id=thread.task_id
    )
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


def _create_asset_resolution_job_sync(
    db: Session,
    *,
    ws_id: str,
    asset_id: str,
    thread_id: str,
    creator_id: str,
    job_kind: str,
    context_json: dict,
    overwrite_existing_draft: bool = False,
) -> dict:
    asset = asset_service.get_asset_by_id(db, ws_id, asset_id)
    thread = asset_discussion_service.get_thread(db, asset_id=asset_id, thread_id=thread_id)
    if not asset or not thread:
        raise ReviewError(status_code=404, detail="Asset thread not found")
    asset_review_policy._ensure_thread_open(thread)
    if not thread.task_id:
        raise ReviewError(status_code=400, detail="Thread task is required")
    context_version_id = str(context_json.get("context_version_id") or "").strip() or None
    asset_review_policy._ensure_latest_context_version_for_mutation(
        asset, context_version_id or asset.active_version_id
    )
    proposal_id = str(context_json.get("proposal_id") or "").strip() or None
    if job_kind == ai_job_constants.JOB_KIND_RESOLUTION_REWRITE:
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
    task_cli_state_service.ensure_bootstrap_ready_or_start(
        db, workspace_id=ws_id, task_id=thread.task_id
    )
    if job_kind == ai_job_constants.JOB_KIND_RESOLUTION_PROPOSAL:
        existing_draft = (
            db.query(SddAssetResolutionProposal)
            .filter(
                SddAssetResolutionProposal.thread_id == thread.id,
                SddAssetResolutionProposal.status == AssetResolutionProposalStatus.DRAFT,
            )
            .order_by(
                SddAssetResolutionProposal.updated_at.desc(),
                SddAssetResolutionProposal.created_at.desc(),
            )
            .first()
        )
        if existing_draft and not overwrite_existing_draft:
            raise ReviewError(
                status_code=409,
                detail={
                    "message": "Draft proposal already exists",
                    "existing_draft_id": existing_draft.id,
                },
            )
    job = create_asset_thread_job(
        db,
        workspace_id=ws_id,
        task_id=thread.task_id,
        asset_id=asset.id,
        thread_id=thread.id,
        creator_id=creator_id,
        prompt_text=None,
        job_kind=job_kind,
        context_json=context_json,
    )
    return {"payload": serialize_job(job)}
