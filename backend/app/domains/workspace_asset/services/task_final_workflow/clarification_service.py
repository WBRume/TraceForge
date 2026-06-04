"""Clarification conversation operations for Task final workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.domains.workspace_asset.models.workspace_asset import (
    ClarificationBlockingLevel,
    ClarificationStatus,
    SddClarification,
    SddClarificationThread,
    SddHumanReview,
    SddReviewClarificationLink,
    TaskProcessAuditAction,
    TaskProcessRecordType,
)
from app.domains.workspace_asset.schemas.task_final_workflow import (
    ClarificationMessageCreateRequest,
)
from app.domains.workspace_asset.schemas.workspace_asset import ClarificationCreateRequest
from app.domains.workspace_asset.services.task_final_workflow import baseline_service
from app.domains.workspace_asset.services.workspace_task_detail_shared import (
    TaskDetailWriteError,
    _add_process_audit,
    _ensure_evidence,
    _ensure_human_review,
    _ensure_requirement,
    _get_task_or_error,
    clean_optional,
    clarification_response,
    json_dict,
    normalize_enum,
)


QUESTION_ENTRY_TYPES = {"QUESTION", "FOLLOW_UP", "REOPEN"}


def _ensure_clarification(db: Session, workspace_id: str, task_id: str, clarification_id: str) -> SddClarification:
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
    return clarification


def _link_review_clarification(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    review: Optional[SddHumanReview],
    clarification: SddClarification,
) -> None:
    if not review:
        return
    existing = (
        db.query(SddReviewClarificationLink)
        .filter(
            SddReviewClarificationLink.workspace_id == workspace_id,
            SddReviewClarificationLink.task_id == task_id,
            SddReviewClarificationLink.review_id == review.id,
            SddReviewClarificationLink.clarification_id == clarification.id,
        )
        .first()
    )
    if existing:
        return
    db.add(
        SddReviewClarificationLink(
            workspace_id=workspace_id,
            task_id=task_id,
            review_id=review.id,
            clarification_id=clarification.id,
            link_type="SOURCE_REVIEW",
        )
    )


def _sync_source_review(clarification: SddClarification) -> None:
    if not clarification.source_review:
        return
    from app.domains.workspace_asset.services.task_final_workflow import review_service

    review_service.sync_review_status_from_clarifications(clarification.source_review)


def create_clarification_for_review(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    review: Optional[SddHumanReview],
    actor_id: Optional[str],
    payload: ClarificationCreateRequest,
) -> SddClarification:
    task = _get_task_or_error(db, workspace_id, task_id)
    baseline_service.ensure_task_mutable(task)
    _ensure_requirement(db, workspace_id, payload.requirement_id)
    _ensure_evidence(db, workspace_id, task_id, payload.source_evidence_id)
    source_review = review or _ensure_human_review(db, workspace_id, task_id, payload.source_review_id)
    question = clean_optional(payload.question)
    if not question:
        raise TaskDetailWriteError("Clarification question is required.", status_code=422)

    clarification = SddClarification(
        workspace_id=workspace_id,
        task_id=task_id,
        requirement_id=payload.requirement_id,
        requester_id=actor_id,
        source_evidence_id=payload.source_evidence_id,
        source_review_id=source_review.id if source_review else None,
        converted_requirement_id=payload.converted_requirement_id,
        status=ClarificationStatus.OPEN,
        blocking_level=normalize_enum(
            ClarificationBlockingLevel,
            payload.blocking_level,
            ClarificationBlockingLevel.BLOCKING,
            "Clarification blocking level",
        ),
        question=question,
        answer=None,
        clarification_type=clean_optional(payload.clarification_type, limit=80),
        target_ref_json=json_dict(payload.target_ref),
        urgency=clean_optional(payload.urgency, limit=40),
        answered_at=None,
        accepted_at=None,
        promote_candidate=bool(payload.promote_candidate),
    )
    db.add(clarification)
    db.flush()
    _link_review_clarification(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        review=source_review,
        clarification=clarification,
    )

    db.add(
        SddClarificationThread(
            workspace_id=workspace_id,
            task_id=task_id,
            clarification_id=clarification.id,
            author_id=actor_id,
            entry_type="QUESTION",
            body=question,
            is_answer=False,
        )
    )
    db.flush()
    _sync_source_review(clarification)
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
    return clarification


def create_workflow_clarification(
    db: Session,
    workspace_id: str,
    task_id: str,
    actor_id: Optional[str],
    payload: ClarificationCreateRequest,
) -> str:
    clarification = create_clarification_for_review(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        review=None,
        actor_id=actor_id,
        payload=payload,
    )
    db.commit()
    return clarification.id


def _apply_message_status(
    clarification: SddClarification,
    *,
    entry_type: str,
    body: str,
    actor_id: Optional[str],
) -> None:
    if entry_type in QUESTION_ENTRY_TYPES:
        clarification.status = ClarificationStatus.OPEN
        clarification.accepted_at = None
    elif entry_type == "ANSWER":
        clarification.status = ClarificationStatus.ANSWERED
        clarification.answer = body
        clarification.responder_id = actor_id
        clarification.answered_at = datetime.utcnow()
        clarification.accepted_at = None
    elif entry_type == "CONFIRM_RESOLUTION":
        clarification.status = ClarificationStatus.ACCEPTED
        clarification.accepted_at = datetime.utcnow()
    elif entry_type == "SYSTEM":
        return
    else:
        raise TaskDetailWriteError(f"Unsupported clarification message type: {entry_type}", status_code=422)


def add_message(
    db: Session,
    workspace_id: str,
    task_id: str,
    clarification_id: str,
    actor_id: Optional[str],
    payload: ClarificationMessageCreateRequest,
) -> str:
    clarification = _ensure_clarification(db, workspace_id, task_id, clarification_id)
    baseline_service.ensure_task_mutable(clarification.task)
    body = clean_optional(payload.body)
    if not body:
        raise TaskDetailWriteError("Clarification message body is required.", status_code=422)
    before = clarification_response(clarification).model_dump(mode="json")
    entry_type = payload.entry_type
    thread = SddClarificationThread(
        workspace_id=workspace_id,
        task_id=task_id,
        clarification_id=clarification_id,
        author_id=actor_id,
        entry_type=entry_type,
        body=body,
        is_answer=entry_type == "ANSWER",
    )
    db.add(thread)
    _apply_message_status(clarification, entry_type=entry_type, body=body, actor_id=actor_id)
    db.flush()
    _sync_source_review(clarification)
    db.flush()
    _add_process_audit(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        record_type=TaskProcessRecordType.CLARIFICATION,
        record_id=clarification.id,
        action=(
            TaskProcessAuditAction.FINALIZED
            if entry_type == "CONFIRM_RESOLUTION"
            else TaskProcessAuditAction.UPDATED
        ),
        actor_id=actor_id,
        before=before,
        after=clarification_response(clarification).model_dump(mode="json"),
        reason=payload.change_reason,
    )
    created_id = thread.id
    db.commit()
    return created_id
