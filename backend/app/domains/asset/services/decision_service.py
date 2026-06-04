"""Decision source attribution and lightweight creation helpers."""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domains.asset.models.asset import SddAsset, SddAssetResolutionProposal, SddAssetThread, SddAssetVersion
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.context_token import ContextTokenCategory
from app.domains.workspace_asset.models.workspace_asset import DecisionSourceType, SddDecision, SddTaskFinalSummary
from app.domains.workspace_asset.schemas.workspace_asset import (
    ChatMessageDecisionCreateRequest,
    DecisionCreateRequest,
    DecisionResponse,
    DecisionSourceResponse,
)
from app.domains.task.services import context_token_service


logger = get_logger(__name__, category="ai_session")


class DecisionSourceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def clean_optional(value: Optional[str], *, limit: Optional[int] = None) -> Optional[str]:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return normalized[:limit] if limit else normalized


def normalize_source_type(value: Optional[str]) -> DecisionSourceType:
    raw = str(value or DecisionSourceType.TASK_DETAIL_BACKFILL.value).strip().upper()
    try:
        return DecisionSourceType(raw)
    except ValueError as exc:
        raise DecisionSourceError(f"Unsupported Decision source type: {value}", status_code=422) from exc


def decision_source_response(decision: SddDecision) -> DecisionSourceResponse:
    source_type = normalize_source_type(enum_value(decision.source_type))
    labels = {
        DecisionSourceType.CHAT_MESSAGE: "Chat message",
        DecisionSourceType.SPEC_PLAN_CHANGE: "Spec / Plan change",
        DecisionSourceType.TASK_CLOSEOUT: "Task closeout",
        DecisionSourceType.TASK_DETAIL_BACKFILL: "Task Detail backfill",
    }
    return DecisionSourceResponse(
        source_type=source_type.value,
        label=labels[source_type],
        chat_message_id=decision.source_chat_message_id,
        asset_id=decision.source_asset_id,
        asset_version_id=decision.source_asset_version_id,
        asset_thread_id=decision.source_asset_thread_id,
        resolution_proposal_id=decision.source_resolution_proposal_id,
        final_summary_id=decision.source_final_summary_id,
        metadata=decision.source_metadata_json if isinstance(decision.source_metadata_json, dict) else None,
    )


def _ensure_chat_message(db: Session, workspace_id: str, task_id: str, message_id: Optional[str]) -> ChatMessage:
    normalized = clean_optional(message_id)
    if not normalized:
        raise DecisionSourceError("Chat message source is required.", status_code=422)
    message = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.workspace_id == workspace_id,
            ChatMessage.task_id == task_id,
            ChatMessage.id == normalized,
        )
        .first()
    )
    if not message:
        raise DecisionSourceError("Chat message source not found for this Task.", status_code=404)
    return message


def _ensure_asset(db: Session, workspace_id: str, task_id: str, asset_id: Optional[str]) -> Optional[SddAsset]:
    normalized = clean_optional(asset_id)
    if not normalized:
        return None
    asset = (
        db.query(SddAsset)
        .filter(SddAsset.workspace_id == workspace_id, SddAsset.task_id == task_id, SddAsset.id == normalized)
        .first()
    )
    if not asset:
        raise DecisionSourceError("Spec / Plan asset source not found for this Task.", status_code=404)
    return asset


def _ensure_asset_version(
    db: Session,
    asset: Optional[SddAsset],
    version_id: Optional[str],
) -> Optional[SddAssetVersion]:
    normalized = clean_optional(version_id)
    if not normalized:
        return None
    query = db.query(SddAssetVersion).filter(SddAssetVersion.id == normalized)
    if asset:
        query = query.filter(SddAssetVersion.asset_id == asset.id)
    version = query.first()
    if not version:
        raise DecisionSourceError("Spec / Plan version source not found.", status_code=404)
    return version


def _ensure_asset_thread(
    db: Session,
    workspace_id: str,
    task_id: str,
    thread_id: Optional[str],
) -> Optional[SddAssetThread]:
    normalized = clean_optional(thread_id)
    if not normalized:
        return None
    thread = (
        db.query(SddAssetThread)
        .filter(
            SddAssetThread.workspace_id == workspace_id,
            SddAssetThread.task_id == task_id,
            SddAssetThread.id == normalized,
        )
        .first()
    )
    if not thread:
        raise DecisionSourceError("Spec / Plan thread source not found for this Task.", status_code=404)
    return thread


def _ensure_resolution_proposal(
    db: Session,
    thread: Optional[SddAssetThread],
    proposal_id: Optional[str],
) -> Optional[SddAssetResolutionProposal]:
    normalized = clean_optional(proposal_id)
    if not normalized:
        return None
    query = db.query(SddAssetResolutionProposal).filter(SddAssetResolutionProposal.id == normalized)
    if thread:
        query = query.filter(SddAssetResolutionProposal.thread_id == thread.id)
    proposal = query.first()
    if not proposal:
        raise DecisionSourceError("Spec / Plan resolution proposal source not found.", status_code=404)
    return proposal


def _ensure_final_summary(
    db: Session,
    workspace_id: str,
    task_id: str,
    summary_id: Optional[str],
) -> Optional[SddTaskFinalSummary]:
    normalized = clean_optional(summary_id)
    if not normalized:
        return None
    summary = (
        db.query(SddTaskFinalSummary)
        .filter(
            SddTaskFinalSummary.workspace_id == workspace_id,
            SddTaskFinalSummary.task_id == task_id,
            SddTaskFinalSummary.id == normalized,
        )
        .first()
    )
    if not summary:
        raise DecisionSourceError("Task closeout source not found for this Task.", status_code=404)
    return summary


def validate_decision_source(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    source_type: DecisionSourceType,
    source_chat_message_id: Optional[str] = None,
    source_asset_id: Optional[str] = None,
    source_asset_version_id: Optional[str] = None,
    source_asset_thread_id: Optional[str] = None,
    source_resolution_proposal_id: Optional[str] = None,
    source_final_summary_id: Optional[str] = None,
) -> None:
    if source_type == DecisionSourceType.CHAT_MESSAGE:
        _ensure_chat_message(db, workspace_id, task_id, source_chat_message_id)
        return
    if source_type == DecisionSourceType.SPEC_PLAN_CHANGE:
        asset = _ensure_asset(db, workspace_id, task_id, source_asset_id)
        thread = _ensure_asset_thread(db, workspace_id, task_id, source_asset_thread_id)
        _ensure_asset_version(db, asset, source_asset_version_id)
        _ensure_resolution_proposal(db, thread, source_resolution_proposal_id)
        if not any([asset, thread, source_asset_version_id, source_resolution_proposal_id]):
            raise DecisionSourceError("Spec / Plan Decision source is required.", status_code=422)
        return
    if source_type == DecisionSourceType.TASK_CLOSEOUT:
        _ensure_final_summary(db, workspace_id, task_id, source_final_summary_id)
        return


def record_decision_context_segment(db: Session, decision: SddDecision) -> None:
    content = "\n\n".join(
        text
        for text in [
            decision.title,
            clean_optional(decision.body),
            f"Impact Scope: {decision.impact_scope}" if clean_optional(decision.impact_scope) else None,
            clean_optional(decision.rationale),
        ]
        if text
    )
    if not content:
        return
    snapshot = context_token_service.ensure_snapshot(
        db,
        workspace_id=decision.workspace_id,
        task_id=decision.task_id,
        session_id="decision-ledger",
        status="READY",
    )
    context_token_service.record_segment(
        db,
        snapshot=snapshot,
        category=ContextTokenCategory.HISTORY,
        source_kind="decision",
        source_ref_id=decision.id,
        chat_message_id=decision.source_chat_message_id,
        asset_id=decision.source_asset_id,
        asset_version_id=decision.source_asset_version_id,
        content=content,
        title=f"Decision: {decision.title}",
        metadata_json={
            "decision_id": decision.id,
            "source_type": enum_value(decision.source_type),
            "impact_scope": decision.impact_scope,
            "promote_candidate": bool(decision.promote_candidate),
        },
        dedupe=True,
    )


def safe_record_decision_context_segment(db: Session, decision: SddDecision) -> None:
    try:
        record_decision_context_segment(db, decision)
    except Exception as exc:
        logger.warning("Failed to record Decision context segment: %s", exc)


def mark_chat_message_as_decision(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    message_id: str,
    actor_id: Optional[str],
    payload: ChatMessageDecisionCreateRequest,
) -> DecisionResponse:
    message = _ensure_chat_message(db, workspace_id, task_id, message_id)
    existing = (
        db.query(SddDecision)
        .filter(
            SddDecision.workspace_id == workspace_id,
            SddDecision.task_id == task_id,
            SddDecision.source_chat_message_id == message.id,
        )
        .first()
    )
    if existing:
        raise DecisionSourceError("This chat message is already marked as a Decision.", status_code=409)
    metadata: Dict[str, Any] = {
        "chat_message_role": enum_value(message.role),
        "chat_message_type": enum_value(message.message_type),
        "chat_message_created_at": message.created_at.isoformat() if message.created_at else None,
    }
    decision_payload = DecisionCreateRequest(
        requirement_id=payload.requirement_id,
        status="ACCEPTED",
        title=payload.title,
        body=payload.body,
        impact_scope=payload.impact_scope,
        promote_candidate=payload.promote_candidate,
        source_type=DecisionSourceType.CHAT_MESSAGE.value,
        source_chat_message_id=message.id,
        source_metadata=metadata,
        change_reason=payload.change_reason or "Marked chat message as Decision.",
    )
    from app.domains.workspace_asset.services import workspace_task_detail_service

    decision_id = workspace_task_detail_service.create_decision(
        db,
        workspace_id,
        task_id,
        actor_id,
        decision_payload,
    )
    decision = db.query(SddDecision).filter(SddDecision.id == decision_id).first()
    if not decision:
        raise DecisionSourceError("Decision was not created.", status_code=500)
    return workspace_task_detail_service.decision_response(decision)
