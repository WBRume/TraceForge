"""Apply document resolutions and decision records in the same database transaction."""

from sqlalchemy.orm import Session

from app.domains.asset.models.asset import SddAssetResolutionProposal
from app.domains.asset.schemas.asset import AssetManualEditBlockRequest, AssetResolutionApplyRequest
from app.domains.asset.services import asset_discussion_service, asset_resolution_service, asset_service
from app.domains.asset.services.review import policy as asset_review_policy
from app.domains.asset.services.review import serialization as asset_review_serialization
from app.domains.asset.services.review.errors import ReviewError
from app.domains.workspace_asset.schemas.workspace_asset import DecisionCreateRequest
from app.domains.workspace_asset.services.common.errors import WorkspaceAssetError
from app.domains.workspace_asset.services.task_process import decision_writes


def apply_resolution(
    db: Session, *, ws_id: str, asset_id: str, thread_id: str, data: AssetResolutionApplyRequest, user_id: str
):
    asset_review_policy._verify_expert_permission_by_id(ws_id, user_id, db)
    asset = asset_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise ReviewError(status_code=404, detail="Asset not found")
    asset_review_policy._ensure_spec_editable(asset)
    thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread_id)
    if not thread:
        raise ReviewError(status_code=404, detail="Thread not found")
    asset_review_policy._ensure_thread_open(thread)

    proposal = (
        db.query(SddAssetResolutionProposal)
        .filter(
            SddAssetResolutionProposal.id == data.proposal_id,
            SddAssetResolutionProposal.thread_id == thread.id,
        )
        .first()
    )
    if not proposal:
        raise ReviewError(status_code=404, detail="Resolution proposal not found")

    try:
        version = asset_resolution_service.apply_resolution_proposal(
            db,
            asset=asset,
            thread=thread,
            proposal=proposal,
            actor_user_id=user_id,
            final_block_ast=data.final_block_ast,
            final_blocks_ast=data.final_blocks_ast,
            change_note=data.change_note,
        )
    except asset_resolution_service.ResolutionServiceError as exc:
        raise ReviewError(status_code=exc.status_code, detail=str(exc)) from exc

    if data.decision:
        if not thread.task_id:
            raise ReviewError(status_code=422, detail="Decision source requires a Task-bound Spec / Plan asset")
        try:
            decision_writes.create_decision(
                db,
                ws_id,
                thread.task_id,
                user_id,
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
                        "asset_type": asset.asset_type.value
                        if hasattr(asset.asset_type, "value")
                        else str(asset.asset_type),
                        "asset_name": asset.name,
                        "thread_block_id": thread.block_id,
                        "resolution_applied": True,
                    },
                    change_reason="Recorded from Spec / Plan resolution apply.",
                ),
            )
        except WorkspaceAssetError as exc:
            raise ReviewError(status_code=exc.status_code, detail=str(exc)) from exc

    db.commit()
    return {
        "asset_id": asset.id,
        "thread_id": thread.id,
        "task_id": thread.task_id,
        "version": asset_review_serialization._serialize_version(version).model_dump(mode="json"),
        "thread": asset_review_serialization._serialize_thread_with_context(
            db,
            thread=thread,
            context_version=version,
        ).model_dump(mode="json"),
    }


def edit_document_block(
    db: Session, *, ws_id: str, asset_id: str, block_id: str, data: AssetManualEditBlockRequest, user_id: str
):
    asset_review_policy._verify_expert_permission_by_id(ws_id, user_id, db)
    asset = asset_service.get_asset_by_id(db, ws_id, asset_id)
    if not asset:
        raise ReviewError(status_code=404, detail="Asset not found")
    asset_review_policy._ensure_spec_editable(asset)
    asset_review_policy._ensure_latest_context_version_for_mutation(asset, data.context_version_id)
    try:
        version, affected_threads = asset_resolution_service.manual_edit_block(
            db,
            asset=asset,
            block_id=block_id,
            new_text=data.new_text,
            actor_user_id=user_id,
            context_version_id=data.context_version_id,
            change_note=data.change_note,
        )
    except asset_resolution_service.ResolutionServiceError as exc:
        raise ReviewError(status_code=exc.status_code, detail=str(exc)) from exc
    db.commit()
    return {
        "asset_id": asset.id,
        "task_id": asset.task_id,
        "version": asset_review_serialization._serialize_version(version).model_dump(mode="json"),
        "threads": [
            asset_review_serialization._serialize_thread_with_context(
                db,
                thread=thread,
                context_version=version,
            ).model_dump(mode="json")
            for thread in affected_threads
        ],
    }
