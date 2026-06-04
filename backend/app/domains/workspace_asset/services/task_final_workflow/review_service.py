"""Expert review item operations for the Task final workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.workspace_asset.models.workspace_asset import (
    ClarificationBlockingLevel,
    ClarificationStatus,
    HumanReviewStatus,
    SddClarification,
    SddHumanReview,
    TaskProcessAuditAction,
    TaskProcessRecordType,
)
from app.domains.workspace_asset.schemas.task_final_workflow import (
    FinalWorkflowReviewTargetRef,
    FinalWorkflowReviewUpsertRequest,
    ReviewDerivedStatus,
)
from app.domains.workspace_asset.schemas.workspace_asset import ClarificationCreateRequest
from app.domains.workspace_asset.services.task_final_workflow import baseline_service
from app.domains.workspace_asset.services.workspace_task_detail_shared import (
    TaskDetailWriteError,
    _add_process_audit,
    _ensure_human_review,
    _get_task_or_error,
    clean_optional,
    enum_value,
    human_review_response,
)


EXPERT_REVIEW_TYPE = "EXPERT_FINAL_REVIEW"
DEFAULT_REVIEW_MARKER = "final_state_default"
TERMINAL_CLARIFICATION_STATUSES = {
    ClarificationStatus.ACCEPTED.value,
    ClarificationStatus.CLOSED.value,
    ClarificationStatus.CANCELLED.value,
}
WAITING_CLARIFICATION_STATUSES = {
    ClarificationStatus.OPEN.value,
    ClarificationStatus.REJECTED.value,
}


def _review_clarifications(review: SddHumanReview) -> List[SddClarification]:
    linked = [
        link.clarification
        for link in (review.clarification_links or [])
        if getattr(link, "clarification", None) is not None
    ]
    source_linked = [
        item
        for item in (review.task.clarifications or [])
        if item.source_review_id == review.id and item not in linked
    ]
    return [*linked, *source_linked]


def _blocking_clarifications(review: SddHumanReview) -> List[SddClarification]:
    return [
        item
        for item in _review_clarifications(review)
        if enum_value(item.blocking_level) == ClarificationBlockingLevel.BLOCKING.value
    ]


def derive_review_status(
    review: SddHumanReview,
    *,
    task_is_baselined: Optional[bool] = None,
) -> ReviewDerivedStatus:
    """Derive final-workflow review status from linked blocking clarifications."""
    baselined = (
        enum_value(review.task.status) == TaskStatus.BASELINED.value
        if task_is_baselined is None and review.task is not None
        else bool(task_is_baselined)
    )
    if baselined or enum_value(review.status) == HumanReviewStatus.CLOSED.value:
        return "CLOSED"

    blocking = [
        item
        for item in _blocking_clarifications(review)
        if enum_value(item.status) not in TERMINAL_CLARIFICATION_STATUSES
    ]
    if not blocking:
        return "CLEAR"
    if any(enum_value(item.status) in WAITING_CLARIFICATION_STATUSES for item in blocking):
        return "WAITING_ANSWER"
    if any(enum_value(item.status) == ClarificationStatus.ANSWERED.value for item in blocking):
        return "ANSWERED_REVIEWING"
    return "WAITING_ANSWER"


def sync_review_status_from_clarifications(review: SddHumanReview) -> HumanReviewStatus:
    derived = derive_review_status(review)
    if derived == "CLOSED":
        review.status = HumanReviewStatus.CLOSED
    elif derived == "WAITING_ANSWER":
        review.status = HumanReviewStatus.NEED_CLARIFICATION
        review.resolved_at = None
    elif derived == "ANSWERED_REVIEWING":
        review.status = HumanReviewStatus.IN_REVIEW
        review.resolved_at = None
    else:
        review.status = HumanReviewStatus.RESOLVED
        if not review.resolved_at:
            review.resolved_at = datetime.utcnow()
    review.outcome = None
    return review.status


def _serialize_target_ref(ref: FinalWorkflowReviewTargetRef) -> dict:
    return {
        "target_type": ref.target_type,
        "target_id": ref.target_id,
        "label": ref.label,
        "source_ref": ref.source_ref,
    }


def _normalize_target_refs(refs: Iterable[FinalWorkflowReviewTargetRef]) -> list[dict]:
    normalized: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        target_id = clean_optional(ref.target_id, limit=300)
        if not target_id:
            continue
        key = (ref.target_type, target_id)
        if key in seen:
            continue
        seen.add(key)
        item = _serialize_target_ref(ref)
        item["target_id"] = target_id
        normalized.append(item)
    if not normalized:
        raise TaskDetailWriteError("At least one review target is required.", status_code=422)
    return normalized


def _review_clarification_question(title: str, body: Optional[str]) -> str:
    normalized_body = clean_optional(body)
    if normalized_body:
        return f"{title}\n\n{normalized_body}"
    return title


def _evidence_target_refs(task: SddTask) -> list[dict]:
    return [
        {
            "target_type": "EVIDENCE",
            "target_id": item.id,
            "label": item.title or item.source_ref or item.source_uri or item.id,
            "source_ref": {
                "source_type": enum_value(item.source_type),
                "source_ref": item.source_ref,
                "source_uri": item.source_uri,
                "source_path": item.source_path,
            },
        }
        for item in (task.evidence_items or [])
    ]


def ensure_expert_review_for_task(
    db: Session,
    task: SddTask,
    actor_id: Optional[str],
) -> Optional[SddHumanReview]:
    """Create only the default seed review; users can add more review items."""
    if enum_value(task.status) != TaskStatus.DONE.value:
        return None
    if not task.evidence_items:
        return None

    existing_reviews = (
        db.query(SddHumanReview)
        .filter(
            SddHumanReview.workspace_id == task.workspace_id,
            SddHumanReview.task_id == task.id,
            SddHumanReview.review_type == EXPERT_REVIEW_TYPE,
        )
        .order_by(SddHumanReview.created_at.asc())
        .all()
    )
    existing_default = next(
        (
            item
            for item in existing_reviews
            if isinstance(item.source_ref_json, dict) and item.source_ref_json.get("seed") == DEFAULT_REVIEW_MARKER
        ),
        None,
    )
    if existing_default:
        return existing_default

    review = SddHumanReview(
        workspace_id=task.workspace_id,
        task_id=task.id,
        reviewer_id=actor_id or task.creator_id,
        status=HumanReviewStatus.RESOLVED,
        outcome=None,
        review_type=EXPERT_REVIEW_TYPE,
        review_scope="TASK_FINAL_STATE",
        priority="NORMAL",
        title="Expert final-state review",
        body="Review completed task evidence and final-state readiness.",
        source_ref_json={"seed": DEFAULT_REVIEW_MARKER},
        target_ref_json={"targets": _evidence_target_refs(task)},
        resolved_at=datetime.utcnow(),
    )
    db.add(review)
    db.flush()
    setattr(review, "_derived_status", derive_review_status(review))
    _add_process_audit(
        db,
        workspace_id=task.workspace_id,
        task_id=task.id,
        record_type=TaskProcessRecordType.HUMAN_REVIEW,
        record_id=review.id,
        action=TaskProcessAuditAction.CREATED,
        actor_id=actor_id,
        after=human_review_response(review).model_dump(mode="json"),
        reason="Task reached DONE with evidence; seeded an expert review item.",
    )
    return review


def create_review(
    db: Session,
    workspace_id: str,
    task_id: str,
    actor_id: Optional[str],
    payload: FinalWorkflowReviewUpsertRequest,
) -> SddHumanReview:
    task = _get_task_or_error(db, workspace_id, task_id)
    baseline_service.ensure_task_mutable(task)
    title = clean_optional(payload.title, limit=300)
    if not title:
        raise TaskDetailWriteError("Review title is required.", status_code=422)
    target_refs = _normalize_target_refs(payload.target_refs)

    review = SddHumanReview(
        workspace_id=workspace_id,
        task_id=task_id,
        reviewer_id=actor_id,
        status=HumanReviewStatus.RESOLVED,
        outcome=None,
        review_type=EXPERT_REVIEW_TYPE,
        review_scope="TASK_FINAL_STATE",
        priority=clean_optional(payload.priority, limit=40) or "NORMAL",
        title=title,
        body=clean_optional(payload.body),
        target_ref_json={"targets": target_refs},
        resolved_at=datetime.utcnow(),
    )
    db.add(review)
    db.flush()
    from app.domains.workspace_asset.services.task_final_workflow import clarification_service

    clarification_service.create_clarification_for_review(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        review=review,
        actor_id=actor_id,
        payload=ClarificationCreateRequest(
            source_review_id=review.id,
            blocking_level=ClarificationBlockingLevel.BLOCKING.value,
            question=_review_clarification_question(title, payload.body),
            clarification_type="REVIEW_QUESTION",
            target_ref={"targets": target_refs},
            urgency=clean_optional(payload.priority, limit=40) or "NORMAL",
            change_reason=payload.change_reason,
        ),
    )
    db.flush()
    setattr(review, "_derived_status", derive_review_status(review))
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
    return review


def update_review(
    db: Session,
    workspace_id: str,
    task_id: str,
    review_id: str,
    actor_id: Optional[str],
    payload: FinalWorkflowReviewUpsertRequest,
) -> SddHumanReview:
    review = _ensure_human_review(db, workspace_id, task_id, review_id)
    assert review is not None
    baseline_service.ensure_task_mutable(review.task)
    title = clean_optional(payload.title, limit=300)
    if not title:
        raise TaskDetailWriteError("Review title is required.", status_code=422)
    before = human_review_response(review).model_dump(mode="json")

    review.title = title
    review.body = clean_optional(payload.body)
    review.priority = clean_optional(payload.priority, limit=40) or "NORMAL"
    review.review_scope = "TASK_FINAL_STATE"
    review.target_ref_json = {"targets": _normalize_target_refs(payload.target_refs)}
    sync_review_status_from_clarifications(review)
    db.flush()
    setattr(review, "_derived_status", derive_review_status(review))
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
    return review
