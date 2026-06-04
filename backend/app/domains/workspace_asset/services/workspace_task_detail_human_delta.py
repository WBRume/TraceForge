"""
Human Review and Human Delta write operations.

Extracted from workspace_task_detail_service.py.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.domains.workspace_asset.models.workspace_asset import (
    HumanReviewOutcome,
    HumanReviewStatus,
    SddHumanReview,
    SddHumanReviewComment,
    TaskProcessAuditAction,
    TaskProcessRecordType,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    HumanReviewCommentCreateRequest,
    HumanReviewCreateRequest,
    HumanReviewUpdateRequest,
    HumanDeltaCreateRequest,
    HumanDeltaUpdateRequest,
)
from app.domains.workspace_asset.services.workspace_task_detail_shared import (
    TaskDetailWriteError,
    _ensure_task_not_baselined,
    clean_optional,
    human_review_comment_response,
    human_review_response,
    human_delta_response,
    json_dict,
    normalize_enum,
    payload_has_field,
    _add_process_audit,
    _ensure_human_review,
    _ensure_human_delta,
    _get_task_or_error,
)


def create_human_review(
    db: Session,
    workspace_id: str,
    task_id: str,
    actor_id: Optional[str],
    payload: HumanReviewCreateRequest,
) -> None:
    task = _get_task_or_error(db, workspace_id, task_id)
    _ensure_task_not_baselined(task)
    review = SddHumanReview(
        workspace_id=workspace_id,
        task_id=task_id,
        reviewer_id=actor_id,
        status=normalize_enum(HumanReviewStatus, payload.status, HumanReviewStatus.OPEN, "Human Review status"),
        outcome=normalize_enum(HumanReviewOutcome, payload.outcome, None, "Human Review outcome"),
        review_type=clean_optional(payload.review_type, limit=80),
        review_scope=clean_optional(payload.review_scope, limit=80),
        priority=clean_optional(payload.priority, limit=40),
        title=clean_optional(payload.title, limit=300),
        body=clean_optional(payload.body),
        source_ref_json=json_dict(payload.source_ref),
        target_ref_json=json_dict(payload.target_ref),
        due_date=payload.due_date,
    )
    db.add(review)
    db.flush()
    _add_process_audit(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        record_type=TaskProcessRecordType.HUMAN_REVIEW,
        record_id=review.id,
        action=TaskProcessAuditAction.CREATED,
        actor_id=actor_id,
        after=human_review_response(review).model_dump(mode="json"),
        reason=payload.change_reason,
    )
    db.commit()


def update_human_review(
    db: Session,
    workspace_id: str,
    task_id: str,
    review_id: str,
    actor_id: Optional[str],
    payload: HumanReviewUpdateRequest,
) -> None:
    review = _ensure_human_review(db, workspace_id, task_id, review_id)
    assert review is not None
    _ensure_task_not_baselined(review.task)
    before = human_review_response(review).model_dump(mode="json")
    if payload_has_field(payload, "status") and payload.status is not None:
        review.status = normalize_enum(HumanReviewStatus, payload.status, HumanReviewStatus.OPEN, "Human Review status")
    if payload_has_field(payload, "outcome") and payload.outcome is not None:
        review.outcome = normalize_enum(HumanReviewOutcome, payload.outcome, None, "Human Review outcome")
    if payload_has_field(payload, "review_type"):
        review.review_type = clean_optional(payload.review_type, limit=80)
    if payload_has_field(payload, "review_scope"):
        review.review_scope = clean_optional(payload.review_scope, limit=80)
    if payload_has_field(payload, "priority"):
        review.priority = clean_optional(payload.priority, limit=40)
    if payload_has_field(payload, "title"):
        review.title = clean_optional(payload.title, limit=300)
    if payload_has_field(payload, "body"):
        review.body = clean_optional(payload.body)
    if payload_has_field(payload, "source_ref"):
        review.source_ref_json = json_dict(payload.source_ref)
    if payload_has_field(payload, "target_ref"):
        review.target_ref_json = json_dict(payload.target_ref)
    if payload_has_field(payload, "due_date"):
        review.due_date = payload.due_date
    db.flush()
    _add_process_audit(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        record_type=TaskProcessRecordType.HUMAN_REVIEW,
        record_id=review.id,
        action=TaskProcessAuditAction.UPDATED,
        actor_id=actor_id,
        before=before,
        after=human_review_response(review).model_dump(mode="json"),
        reason=payload.change_reason,
    )
    db.commit()


def create_human_review_comment(
    db: Session,
    workspace_id: str,
    task_id: str,
    review_id: str,
    actor_id: Optional[str],
    payload: HumanReviewCommentCreateRequest,
) -> None:
    _ensure_human_review(db, workspace_id, task_id, review_id)
    task = _get_task_or_error(db, workspace_id, task_id)
    _ensure_task_not_baselined(task)
    body = clean_optional(payload.body)
    if not body:
        raise TaskDetailWriteError("Review comment body is required.", status_code=422)
    comment = SddHumanReviewComment(
        workspace_id=workspace_id,
        task_id=task_id,
        review_id=review_id,
        author_id=actor_id,
        comment_type=clean_optional(payload.comment_type, limit=80),
        body=body,
        required_change_json=json_dict(payload.required_change),
    )
    db.add(comment)
    db.flush()
    _add_process_audit(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        record_type=TaskProcessRecordType.HUMAN_REVIEW_COMMENT,
        record_id=comment.id,
        action=TaskProcessAuditAction.COMMENTED,
        actor_id=actor_id,
        after=human_review_comment_response(comment).model_dump(mode="json"),
        reason=payload.change_reason,
    )
    db.commit()


def _ensure_proposal(
    db: Session,
    workspace_id: str,
    task_id: str,
    proposal_id: Optional[str],
) -> Optional["SddTaskChangeProposal"]:
    from app.domains.workflow.models.task_change import SddTaskChangeProposal

    if not proposal_id:
        return None
    proposal = (
        db.query(SddTaskChangeProposal)
        .filter(
            SddTaskChangeProposal.workspace_id == workspace_id,
            SddTaskChangeProposal.task_id == task_id,
            SddTaskChangeProposal.id == proposal_id,
        )
        .first()
    )
    if not proposal:
        raise TaskDetailWriteError("ChangeProposal not found for this Task.", status_code=404)
    return proposal


def create_human_delta(
    db: Session,
    workspace_id: str,
    task_id: str,
    actor_id: Optional[str],
    payload: HumanDeltaCreateRequest,
) -> str:
    from app.domains.workspace_asset.services.human_delta_compare_service import create_delta

    task = _get_task_or_error(db, workspace_id, task_id)
    _ensure_task_not_baselined(task)
    return create_delta(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        actor_id=actor_id,
        proposal_id=payload.proposal_id or "",
        final_evidence_id=payload.final_evidence_id or "",
    )


def update_human_delta(
    db: Session,
    workspace_id: str,
    task_id: str,
    delta_id: str,
    actor_id: Optional[str],
    payload: HumanDeltaUpdateRequest,
) -> None:
    delta = _ensure_human_delta(db, workspace_id, task_id, delta_id)
    assert delta is not None
    _ensure_task_not_baselined(delta.task)
    before = human_delta_response(delta).model_dump(mode="json")
    if payload_has_field(payload, "change_category"):
        delta.change_category = clean_optional(payload.change_category, limit=100)
    if payload_has_field(payload, "change_reason"):
        delta.change_reason = clean_optional(payload.change_reason)
    if payload_has_field(payload, "promote_candidate") and payload.promote_candidate is not None:
        delta.promote_candidate = bool(payload.promote_candidate)
    db.flush()
    _add_process_audit(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        record_type=TaskProcessRecordType.HUMAN_DELTA,
        record_id=delta.id,
        action=TaskProcessAuditAction.UPDATED,
        actor_id=actor_id,
        before=before,
        after=human_delta_response(delta).model_dump(mode="json"),
        reason=payload.audit_reason or payload.change_reason,
    )
    db.commit()
