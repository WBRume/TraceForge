"""Project hydrated review records into transport-safe response values."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.asset.schemas.asset import (
    AssetResolutionProposalResponse,
    AssetResponse,
    AssetThreadMessageResponse,
    AssetThreadResponse,
    AssetVersionResponse,
)
from app.domains.asset.services import asset_discussion_service
from app.domains.asset.services.document import serializer as document_serializer
from app.domains.auth.services import auth_service


def _serialize_asset(asset) -> AssetResponse:
    return document_serializer.serialize_asset(asset)


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
    messages = sorted(thread.messages or [], key=lambda item: item.created_at)
    proposals = sorted(thread.proposals or [], key=lambda item: item.created_at, reverse=True)
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
