"""
Task Detail process asset write and aggregation helpers.

This module owns the mutable Task Detail process asset boundary so
workspace_asset_service can stay focused on read orchestration.

Re-export facade: shared utilities live in ``workspace_task_detail_shared``,
domain write operations live in ``workspace_task_detail_human_delta``,
``workspace_task_detail_evidence``, and ``workspace_task_detail_decision``.
Clarification and Final Summary write operations remain here.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.domains.workspace_asset.models.workspace_asset import (
    ClarificationBlockingLevel,
    ClarificationStatus,
    SddClarification,
    SddTaskFinalSummary,
    TaskFinalStatus,
    TaskProcessAuditAction,
    TaskProcessRecordType,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    ClarificationCreateRequest,
    ClarificationUpdateRequest,
    TaskFinalSummaryUpsertRequest,
)

# ---------------------------------------------------------------------------
# Re-exports from shared module
# ---------------------------------------------------------------------------
from app.domains.workspace_asset.services.workspace_task_detail_shared import (  # noqa: F401
    TaskDetailWriteError,
    clean_optional,
    clarification_response,
    decision_response,
    enum_value,
    evidence_response,
    external_evidence_ref,
    final_summary_response,
    human_delta_response,
    human_review_comment_response,
    human_review_response,
    json_dict,
    normalize_enum,
    normalize_list,
    payload_has_field,
    process_audit_response,
    short_text,
    task_file_items,
    _task_file_from_asset,
    _task_file_from_ai_output,
    _task_file_from_change_proposal,
    _task_file_from_change_file,
    _task_file_from_verification,
    _task_file_from_conflict,
    _get_task_or_error,
    _ensure_task_not_baselined,
    _ensure_requirement,
    _ensure_ai_job,
    _ensure_ai_output,
    _ensure_human_review,
    _ensure_human_delta,
    _ensure_evidence,
    _validate_evidence_source,
    _validate_evidence_for_phase,
    _add_process_audit,
    _has_accepting_review,
    _is_human_confirmation,
    _task_coverage_status,
    _has_open_blocking_clarification,
    _ensure_final_summary_verified_allowed,
)

# ---------------------------------------------------------------------------
# Re-exports from human_delta domain
# ---------------------------------------------------------------------------
from app.domains.workspace_asset.services.workspace_task_detail_human_delta import (  # noqa: F401
    create_human_review,
    update_human_review,
    create_human_review_comment,
    _ensure_proposal,
    create_human_delta,
    update_human_delta,
)

# ---------------------------------------------------------------------------
# Re-exports from evidence domain
# ---------------------------------------------------------------------------
from app.domains.workspace_asset.services.workspace_task_detail_evidence import (  # noqa: F401
    create_evidence,
    update_evidence,
)

# ---------------------------------------------------------------------------
# Re-exports from decision domain
# ---------------------------------------------------------------------------
from app.domains.workspace_asset.services.workspace_task_detail_decision import (  # noqa: F401
    create_decision,
    update_decision,
)


# ---------------------------------------------------------------------------
# Clarification write operations (remain here)
# ---------------------------------------------------------------------------


def create_clarification(
    db: Session,
    workspace_id: str,
    task_id: str,
    actor_id: Optional[str],
    payload: ClarificationCreateRequest,
) -> str:
    from app.domains.workspace_asset.services.task_final_workflow.clarification_service import create_workflow_clarification

    return create_workflow_clarification(db, workspace_id, task_id, actor_id, payload)


def _create_clarification_legacy(
    db: Session,
    workspace_id: str,
    task_id: str,
    actor_id: Optional[str],
    payload: ClarificationCreateRequest,
) -> str:
    task = _get_task_or_error(db, workspace_id, task_id)
    _ensure_task_not_baselined(task)
    _ensure_requirement(db, workspace_id, payload.requirement_id)
    _ensure_requirement(db, workspace_id, payload.converted_requirement_id)
    _ensure_evidence(db, workspace_id, task_id, payload.source_evidence_id)
    question = clean_optional(payload.question)
    if not question:
        raise TaskDetailWriteError("Clarification question is required.", status_code=422)
    answer = clean_optional(payload.answer)
    clarification = SddClarification(
        workspace_id=workspace_id,
        task_id=task_id,
        requirement_id=payload.requirement_id,
        requester_id=actor_id,
        responder_id=actor_id if answer else None,
        source_evidence_id=payload.source_evidence_id,
        source_review_id=payload.source_review_id,
        converted_requirement_id=payload.converted_requirement_id,
        status=normalize_enum(ClarificationStatus, payload.status, ClarificationStatus.OPEN, "Clarification status"),
        blocking_level=normalize_enum(
            ClarificationBlockingLevel,
            payload.blocking_level,
            ClarificationBlockingLevel.NON_BLOCKING,
            "Clarification blocking level",
        ),
        question=question,
        answer=answer,
        clarification_type=clean_optional(payload.clarification_type, limit=80),
        target_ref_json=json_dict(payload.target_ref),
        urgency=clean_optional(payload.urgency, limit=40),
        answered_at=None,
        promote_candidate=bool(payload.promote_candidate),
    )
    db.add(clarification)
    db.flush()
    _add_process_audit(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        record_type=TaskProcessRecordType.CLARIFICATION,
        record_id=clarification.id,
        action=TaskProcessAuditAction.CREATED,
        actor_id=actor_id,
        after=clarification_response(clarification).model_dump(mode="json"),
        reason=payload.change_reason,
    )
    created_id = clarification.id
    db.commit()
    return created_id


def update_clarification(
    db: Session,
    workspace_id: str,
    task_id: str,
    clarification_id: str,
    actor_id: Optional[str],
    payload: ClarificationUpdateRequest,
) -> None:
    clarification = (
        db.query(SddClarification)
        .filter(
            SddClarification.workspace_id == workspace_id,
            SddClarification.task_id == task_id,
            SddClarification.id == clarification_id,
        )
        .first()
    )
    if not clarification:
        raise TaskDetailWriteError("Clarification not found for this Task.", status_code=404)
    _ensure_task_not_baselined(clarification.task)
    before = clarification_response(clarification).model_dump(mode="json")
    if payload_has_field(payload, "requirement_id"):
        _ensure_requirement(db, workspace_id, payload.requirement_id)
        clarification.requirement_id = payload.requirement_id
    if payload_has_field(payload, "converted_requirement_id"):
        _ensure_requirement(db, workspace_id, payload.converted_requirement_id)
        clarification.converted_requirement_id = payload.converted_requirement_id
    if payload_has_field(payload, "source_evidence_id"):
        _ensure_evidence(db, workspace_id, task_id, payload.source_evidence_id)
        clarification.source_evidence_id = payload.source_evidence_id
    if payload_has_field(payload, "source_review_id"):
        _ensure_human_review(db, workspace_id, task_id, payload.source_review_id)
        clarification.source_review_id = payload.source_review_id
    if payload_has_field(payload, "status") and payload.status is not None:
        clarification.status = normalize_enum(
            ClarificationStatus,
            payload.status,
            ClarificationStatus.OPEN,
            "Clarification status",
        )
    if payload_has_field(payload, "blocking_level") and payload.blocking_level is not None:
        clarification.blocking_level = normalize_enum(
            ClarificationBlockingLevel,
            payload.blocking_level,
            ClarificationBlockingLevel.NON_BLOCKING,
            "Clarification blocking level",
        )
    if payload_has_field(payload, "question"):
        clarification.question = clean_optional(payload.question) or clarification.question
    if payload_has_field(payload, "answer"):
        clarification.answer = clean_optional(payload.answer)
        clarification.responder_id = actor_id if clarification.answer else None
        clarification.answered_at = None
        if clarification.answer:
            from datetime import datetime

            clarification.answered_at = datetime.utcnow()
            if clarification.status == ClarificationStatus.OPEN:
                clarification.status = ClarificationStatus.ANSWERED
    if payload_has_field(payload, "clarification_type"):
        clarification.clarification_type = clean_optional(payload.clarification_type, limit=80)
    if payload_has_field(payload, "target_ref"):
        clarification.target_ref_json = json_dict(payload.target_ref)
    if payload_has_field(payload, "urgency"):
        clarification.urgency = clean_optional(payload.urgency, limit=40)
    if payload_has_field(payload, "promote_candidate") and payload.promote_candidate is not None:
        clarification.promote_candidate = bool(payload.promote_candidate)
    db.flush()
    _add_process_audit(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        record_type=TaskProcessRecordType.CLARIFICATION,
        record_id=clarification.id,
        action=TaskProcessAuditAction.UPDATED,
        actor_id=actor_id,
        before=before,
        after=clarification_response(clarification).model_dump(mode="json"),
        reason=payload.change_reason,
    )
    db.commit()


# ---------------------------------------------------------------------------
# Final Summary write operation (remains here)
# ---------------------------------------------------------------------------


def upsert_final_summary(
    db: Session,
    workspace_id: str,
    task_id: str,
    actor_id: Optional[str],
    payload: TaskFinalSummaryUpsertRequest,
) -> str:
    from app.domains.workspace_asset.services.task_final_workflow.summary_service import upsert_final_summary as _upsert

    return _upsert(db, workspace_id, task_id, actor_id, payload)
