"""Validate and create AI review reply, proposal and rewrite jobs."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.ai.services.jobs import constants as ai_job_constants
from app.domains.ai.services.jobs.store import create_asset_thread_job, serialize_job
from app.domains.asset.models.asset import (
    AssetResolutionProposalStatus,
    AssetThreadMessageRole,
    SddAssetResolutionProposal,
)
from app.domains.asset.schemas.asset import AssetJointProposalCreateRequest
from app.domains.asset.services import asset_discussion_service, asset_service
from app.domains.asset.services.review import policy as asset_review_policy
from app.domains.asset.services.review import proposal_sources
from app.domains.asset.services.review import serialization as asset_review_serialization
from app.domains.asset.services.review.errors import ReviewError
from app.domains.task.services import task_cli_state_service


def create_joint_proposal_job(
    db: Session,
    *,
    ws_id: str,
    asset_id: str,
    user_id: str,
    data: AssetJointProposalCreateRequest,
) -> dict:
    asset_review_policy._verify_comment_permission_by_id(ws_id, user_id, db)
    asset = asset_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise ReviewError(404, "Asset not found")
    sources = tuple(sorted(set(data.thread_ids)))
    version, threads = proposal_sources.validate_sources(db, asset, sources, data.context_version_id, lock=True)
    owner = threads[0]
    task_cli_state_service.ensure_bootstrap_ready(db, workspace_id=ws_id, task_id=owner.task_id)
    active = (
        db.query(SddAiJob)
        .filter(
            SddAiJob.thread_id == owner.id,
            SddAiJob.status.in_([AiJobStatus.PENDING, AiJobStatus.RUNNING, AiJobStatus.WAITING_HITL]),
        )
        .all()
    )
    for job in active:
        context = job.context_json or {}
        if context.get("job_kind") != ai_job_constants.JOB_KIND_RESOLUTION_PROPOSAL:
            continue
        if (
            context.get("context_version_id") == version.id
            and proposal_sources.source_ids(context) == sources
            and job.creator_id == user_id
        ):
            return {"payload": serialize_job(job), "created": False}
        raise ReviewError(409, "A proposal is already being generated for these discussions")
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
        job_kind=ai_job_constants.JOB_KIND_RESOLUTION_PROPOSAL,
        context_json={
            "context_version_id": version.id,
            "source_thread_ids": list(sources),
            "overwrite_existing_draft": data.overwrite_existing_draft,
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
            .populate_existing()
            .with_for_update()
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
        # Hold the proposal lock while checking for active jobs and creating the next one.
        active_jobs = (
            db.query(SddAiJob)
            .filter(
                SddAiJob.thread_id == thread.id,
                SddAiJob.status.in_(
                    [
                        AiJobStatus.PENDING,
                        AiJobStatus.RUNNING,
                        AiJobStatus.WAITING_HITL,
                        AiJobStatus.TERMINATING,
                        AiJobStatus.ORPHANED,
                    ]
                ),
            )
            .populate_existing()
            .with_for_update()
            .all()
        )
        for active in active_jobs:
            context = active.context_json or {}
            if context.get("job_kind") == job_kind and context.get("proposal_id") == proposal_id:
                raise ReviewError(
                    status_code=409,
                    detail={"message": "Proposal rewrite is already in progress", "job_id": active.id},
                )
    if job_kind == ai_job_constants.JOB_KIND_RESOLUTION_PROPOSAL:
        asset_review_policy._ensure_thread_open(thread)
        drafts = proposal_sources.matching_drafts(db, thread.id, (), context_version_id or asset.active_version_id)
        existing_draft = drafts[0] if drafts else None
        if existing_draft and not overwrite_existing_draft:
            raise ReviewError(
                status_code=409,
                detail={
                    "message": "Draft proposal already exists",
                    "existing_draft_id": existing_draft.id,
                },
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
        job_kind=job_kind,
        context_json=context_json,
    )
    return {"payload": serialize_job(job)}
