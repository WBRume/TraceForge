"""
Decision write operations.

Extracted from workspace_task_detail_service.py.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.domains.workspace_asset.models.workspace_asset import (
    DecisionStatus,
    SddDecision,
    TaskProcessAuditAction,
    TaskProcessRecordType,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    DecisionCreateRequest,
    DecisionUpdateRequest,
)
from app.domains.workspace_asset.services.workspace_task_detail_shared import (
    TaskDetailWriteError,
    _ensure_task_not_baselined,
    clean_optional,
    decision_response,
    enum_value,
    json_dict,
    normalize_enum,
    payload_has_field,
    _add_process_audit,
    _ensure_evidence,
    _ensure_human_delta,
    _ensure_requirement,
    _get_task_or_error,
)
from app.domains.asset.services import decision_service


def create_decision(
    db: Session,
    workspace_id: str,
    task_id: str,
    actor_id: Optional[str],
    payload: DecisionCreateRequest,
) -> str:
    task = _get_task_or_error(db, workspace_id, task_id)
    _ensure_task_not_baselined(task)
    _ensure_requirement(db, workspace_id, payload.requirement_id)
    _ensure_human_delta(db, workspace_id, task_id, payload.human_delta_id)
    _ensure_evidence(db, workspace_id, task_id, payload.source_evidence_id)
    title = clean_optional(payload.title, limit=300)
    if not title:
        raise TaskDetailWriteError("Decision title is required.", status_code=422)
    try:
        source_type = decision_service.normalize_source_type(payload.source_type)
        decision_service.validate_decision_source(
            db,
            workspace_id=workspace_id,
            task_id=task_id,
            source_type=source_type,
            source_chat_message_id=payload.source_chat_message_id,
            source_asset_id=payload.source_asset_id,
            source_asset_version_id=payload.source_asset_version_id,
            source_asset_thread_id=payload.source_asset_thread_id,
            source_resolution_proposal_id=payload.source_resolution_proposal_id,
            source_final_summary_id=payload.source_final_summary_id,
        )
    except decision_service.DecisionSourceError as exc:
        raise TaskDetailWriteError(str(exc), status_code=exc.status_code) from exc
    decision = SddDecision(
        workspace_id=workspace_id,
        task_id=task_id,
        requirement_id=payload.requirement_id,
        human_delta_id=payload.human_delta_id,
        delta_region_id=payload.delta_region_id,
        decided_by_id=actor_id,
        source_evidence_id=payload.source_evidence_id,
        status=normalize_enum(DecisionStatus, payload.status, DecisionStatus.PROPOSED, "Decision status"),
        source_type=source_type,
        source_chat_message_id=payload.source_chat_message_id,
        source_asset_id=payload.source_asset_id,
        source_asset_version_id=payload.source_asset_version_id,
        source_asset_thread_id=payload.source_asset_thread_id,
        source_resolution_proposal_id=payload.source_resolution_proposal_id,
        source_final_summary_id=payload.source_final_summary_id,
        title=title,
        body=clean_optional(payload.body),
        rationale=clean_optional(payload.rationale),
        impact_scope=clean_optional(payload.impact_scope, limit=300),
        promote_candidate=bool(payload.promote_candidate),
        source_metadata_json=json_dict(payload.source_metadata),
        delta_line_refs_json=json_dict(payload.delta_line_refs),
    )
    db.add(decision)
    db.flush()
    _add_process_audit(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        record_type=TaskProcessRecordType.DECISION,
        record_id=decision.id,
        action=TaskProcessAuditAction.CREATED,
        actor_id=actor_id,
        after=decision_response(decision).model_dump(mode="json"),
        reason=payload.change_reason,
    )
    created_id = decision.id
    db.commit()
    db.refresh(decision)
    decision_service.safe_record_decision_context_segment(db, decision)
    return created_id


def update_decision(
    db: Session,
    workspace_id: str,
    task_id: str,
    decision_id: str,
    actor_id: Optional[str],
    payload: DecisionUpdateRequest,
) -> None:
    decision = (
        db.query(SddDecision)
        .filter(SddDecision.workspace_id == workspace_id, SddDecision.task_id == task_id, SddDecision.id == decision_id)
        .first()
    )
    if not decision:
        raise TaskDetailWriteError("Decision not found for this Task.", status_code=404)
    _ensure_task_not_baselined(decision.task)
    before = decision_response(decision).model_dump(mode="json")
    if payload_has_field(payload, "requirement_id"):
        _ensure_requirement(db, workspace_id, payload.requirement_id)
        decision.requirement_id = payload.requirement_id
    if payload_has_field(payload, "human_delta_id"):
        _ensure_human_delta(db, workspace_id, task_id, payload.human_delta_id)
        decision.human_delta_id = payload.human_delta_id
    if payload_has_field(payload, "delta_region_id"):
        decision.delta_region_id = payload.delta_region_id
    if payload_has_field(payload, "source_evidence_id"):
        _ensure_evidence(db, workspace_id, task_id, payload.source_evidence_id)
        decision.source_evidence_id = payload.source_evidence_id
    if payload_has_field(payload, "source_type") and payload.source_type is not None:
        decision.source_type = decision_service.normalize_source_type(payload.source_type)
    if payload_has_field(payload, "source_chat_message_id"):
        decision.source_chat_message_id = payload.source_chat_message_id
    if payload_has_field(payload, "source_asset_id"):
        decision.source_asset_id = payload.source_asset_id
    if payload_has_field(payload, "source_asset_version_id"):
        decision.source_asset_version_id = payload.source_asset_version_id
    if payload_has_field(payload, "source_asset_thread_id"):
        decision.source_asset_thread_id = payload.source_asset_thread_id
    if payload_has_field(payload, "source_resolution_proposal_id"):
        decision.source_resolution_proposal_id = payload.source_resolution_proposal_id
    if payload_has_field(payload, "source_final_summary_id"):
        decision.source_final_summary_id = payload.source_final_summary_id
    try:
        decision_service.validate_decision_source(
            db,
            workspace_id=workspace_id,
            task_id=task_id,
            source_type=decision_service.normalize_source_type(enum_value(decision.source_type)),
            source_chat_message_id=decision.source_chat_message_id,
            source_asset_id=decision.source_asset_id,
            source_asset_version_id=decision.source_asset_version_id,
            source_asset_thread_id=decision.source_asset_thread_id,
            source_resolution_proposal_id=decision.source_resolution_proposal_id,
            source_final_summary_id=decision.source_final_summary_id,
        )
    except decision_service.DecisionSourceError as exc:
        raise TaskDetailWriteError(str(exc), status_code=exc.status_code) from exc
    if payload_has_field(payload, "status") and payload.status is not None:
        decision.status = normalize_enum(DecisionStatus, payload.status, DecisionStatus.PROPOSED, "Decision status")
    if payload_has_field(payload, "title"):
        decision.title = clean_optional(payload.title, limit=300) or decision.title
    if payload_has_field(payload, "body"):
        decision.body = clean_optional(payload.body)
    if payload_has_field(payload, "rationale"):
        decision.rationale = clean_optional(payload.rationale)
    if payload_has_field(payload, "impact_scope"):
        decision.impact_scope = clean_optional(payload.impact_scope, limit=300)
    if payload_has_field(payload, "promote_candidate") and payload.promote_candidate is not None:
        decision.promote_candidate = bool(payload.promote_candidate)
    if payload_has_field(payload, "source_metadata"):
        decision.source_metadata_json = json_dict(payload.source_metadata)
    if payload_has_field(payload, "delta_line_refs"):
        decision.delta_line_refs_json = json_dict(payload.delta_line_refs)
    db.flush()
    _add_process_audit(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        record_type=TaskProcessRecordType.DECISION,
        record_id=decision.id,
        action=TaskProcessAuditAction.UPDATED,
        actor_id=actor_id,
        before=before,
        after=decision_response(decision).model_dump(mode="json"),
        reason=payload.change_reason,
    )
    db.commit()
    db.refresh(decision)
    decision_service.safe_record_decision_context_segment(db, decision)
