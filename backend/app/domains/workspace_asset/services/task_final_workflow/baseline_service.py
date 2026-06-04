"""Baseline readiness, snapshot, and lock helpers for Task final workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.workspace_asset.models.workspace_asset import (
    ClarificationBlockingLevel,
    ClarificationStatus,
    EvidenceStatus,
    HumanReviewStatus,
    SddClarification,
    SddDecision,
    SddEvidence,
    SddHumanDelta,
    SddHumanReview,
    SddTaskBaseline,
    SddTaskFinalSummary,
    TaskFinalStatus,
    TaskProcessAuditAction,
    TaskProcessRecordType,
)
from app.domains.workspace_asset.schemas.task_final_workflow import (
    BaselineCheckItem,
    TaskBaselineResponse,
)
from app.domains.workspace_asset.services.workspace_task_detail_shared import (
    TaskDetailWriteError,
    _add_process_audit,
    _ensure_task_not_baselined,
    _task_coverage_status,
    enum_value,
)


TERMINAL_CLARIFICATION_STATUSES = {
    ClarificationStatus.ACCEPTED.value,
    ClarificationStatus.CLOSED.value,
    ClarificationStatus.CANCELLED.value,
}


def ensure_task_mutable(task: SddTask) -> None:
    _ensure_task_not_baselined(task)


def latest_baseline(db: Session, task_id: str) -> Optional[SddTaskBaseline]:
    return (
        db.query(SddTaskBaseline)
        .filter(SddTaskBaseline.task_id == task_id)
        .order_by(SddTaskBaseline.version.desc())
        .first()
    )


def baseline_response(baseline: Optional[SddTaskBaseline]) -> Optional[TaskBaselineResponse]:
    if not baseline:
        return None
    return TaskBaselineResponse(
        id=baseline.id,
        workspace_id=baseline.workspace_id,
        task_id=baseline.task_id,
        summary_id=baseline.summary_id,
        version=int(baseline.version or 0),
        snapshot=baseline.snapshot_json if isinstance(baseline.snapshot_json, dict) else None,
        baselined_by_id=baseline.baselined_by_id,
        is_rollback=bool(baseline.is_rollback),
        rollback_from_version=baseline.rollback_from_version,
        created_at=baseline.created_at,
    )


def _confirmed_evidence_count(db: Session, workspace_id: str, task_id: str) -> int:
    return int(
        db.query(func.count(SddEvidence.id))
        .filter(
            SddEvidence.workspace_id == workspace_id,
            SddEvidence.task_id == task_id,
            SddEvidence.status == EvidenceStatus.CONFIRMED,
        )
        .scalar()
        or 0
    )


def _active_job_count(db: Session, workspace_id: str, task_id: str) -> int:
    active_statuses = {AiJobStatus.PENDING, AiJobStatus.RUNNING, AiJobStatus.WAITING_HITL, AiJobStatus.INTERRUPTED}
    return int(
        db.query(func.count(SddAiJob.id))
        .filter(
            SddAiJob.workspace_id == workspace_id,
            SddAiJob.task_id == task_id,
            SddAiJob.status.in_(active_statuses),
        )
        .scalar()
        or 0
    )


def _expert_reviews(task: SddTask) -> list[SddHumanReview]:
    from app.domains.workspace_asset.services.task_final_workflow import review_service

    return [
        item
        for item in (task.human_reviews or [])
        if item.review_type == review_service.EXPERT_REVIEW_TYPE
    ]


def _has_unresolved_blocking_clarification(task: SddTask) -> bool:
    return any(
        enum_value(item.blocking_level) == ClarificationBlockingLevel.BLOCKING.value
        and enum_value(item.status) not in TERMINAL_CLARIFICATION_STATUSES
        for item in (task.clarifications or [])
    )


def _all_reviews_closed(task: SddTask) -> bool:
    reviews = _expert_reviews(task)
    return bool(reviews) and all(enum_value(review.status) == HumanReviewStatus.CLOSED.value for review in reviews)


def _expert_reviews_clear(task: SddTask) -> bool:
    return bool(_expert_reviews(task)) and not _has_unresolved_blocking_clarification(task)


def build_baseline_checklist(db: Session, task: SddTask) -> List[BaselineCheckItem]:
    confirmed_evidence_count = _confirmed_evidence_count(db, task.workspace_id, task.id)
    coverage_status = _task_coverage_status(task)
    active_job_count = _active_job_count(db, task.workspace_id, task.id)
    final_status = enum_value(task.final_summary.final_status) if task.final_summary else None
    decision_count = len(task.decisions or [])
    task_status = enum_value(task.status)
    task_is_freeze_ready = task_status in {TaskStatus.DONE.value, TaskStatus.BASELINED.value}

    return [
        BaselineCheckItem(
            key="task_done",
            label="Task is marked DONE",
            status="pass" if task_is_freeze_ready else "block",
            detail=f"Current task status: {task_status}.",
            blocking=not task_is_freeze_ready,
        ),
        BaselineCheckItem(
            key="active_session",
            label="No active AI/session job",
            status="pass" if active_job_count == 0 else "block",
            detail=f"{active_job_count} active job(s) detected.",
            blocking=active_job_count > 0,
        ),
        BaselineCheckItem(
            key="confirmed_evidence",
            label="Confirmed evidence exists",
            status="pass" if confirmed_evidence_count > 0 else "block",
            detail=f"{confirmed_evidence_count} confirmed evidence item(s).",
            blocking=confirmed_evidence_count == 0,
        ),
        BaselineCheckItem(
            key="coverage_verified",
            label="Coverage has human confirmation",
            status="pass" if coverage_status == "verified" else "block",
            detail=f"Coverage status: {coverage_status}.",
            blocking=coverage_status != "verified",
        ),
        BaselineCheckItem(
            key="expert_review",
            label="Expert review items clear",
            status="pass" if _expert_reviews_clear(task) else "block",
            detail="At least one expert review item is required, and every blocking clarification must be confirmed.",
            blocking=not _expert_reviews_clear(task),
        ),
        BaselineCheckItem(
            key="clarifications",
            label="Blocking clarifications resolved",
            status="pass" if not _has_unresolved_blocking_clarification(task) else "block",
            detail="Blocking clarifications must be accepted, closed, or cancelled.",
            blocking=_has_unresolved_blocking_clarification(task),
        ),
        BaselineCheckItem(
            key="final_summary",
            label="Final summary verified",
            status="pass" if final_status == TaskFinalStatus.VERIFIED.value else "block",
            detail=f"Final summary status: {final_status or 'missing'}.",
            blocking=final_status != TaskFinalStatus.VERIFIED.value,
        ),
        BaselineCheckItem(
            key="reviews_closed",
            label="Reviews are closed for freeze",
            status="pass" if _all_reviews_closed(task) else "block",
            detail="Resolved reviews are auto-closed during final summary verification.",
            blocking=not _all_reviews_closed(task),
        ),
        BaselineCheckItem(
            key="decisions",
            label="Decision records reviewed",
            status="pass" if decision_count > 0 else "warning",
            detail=f"{decision_count} decision record(s). This is advisory in v1.",
            blocking=False,
        ),
    ]


def ensure_baseline_allowed(db: Session, task: SddTask) -> None:
    blockers = [item for item in build_baseline_checklist(db, task) if item.blocking]
    if blockers:
        first = blockers[0]
        raise TaskDetailWriteError(
            f"Task cannot be baselined: {first.label}. {first.detail or ''}".strip(),
            status_code=409,
        )


def close_resolved_reviews(task: SddTask) -> None:
    from app.domains.workspace_asset.services.task_final_workflow import review_service

    for review in _expert_reviews(task):
        if review_service.derive_review_status(review) == "CLEAR":
            review.status = HumanReviewStatus.CLOSED


def _snapshot_record(item: Any, fields: List[str]) -> Dict[str, Any]:
    return {field: getattr(item, field, None) for field in fields}


def build_baseline_snapshot(task: SddTask, *, version: int) -> Dict[str, Any]:
    summary = task.final_summary
    return {
        "version": version,
        "task": {
            "id": task.id,
            "workspace_id": task.workspace_id,
            "name": task.name,
            "status": enum_value(task.status),
            "current_phase": task.current_phase,
        },
        "summary": {
            "id": summary.id if summary else None,
            "final_status": enum_value(summary.final_status) if summary else None,
            "summary": summary.summary if summary else None,
            "remaining_risk": summary.remaining_risk if summary else None,
            "next_steps": summary.next_steps if summary else None,
            "final_evidence_ids": summary.final_evidence_ids_json if summary else [],
        },
        "review_ids": [review.id for review in (task.human_reviews or [])],
        "clarification_ids": [item.id for item in (task.clarifications or [])],
        "evidence_ids": [item.id for item in (task.evidence_items or [])],
        "human_delta_ids": [item.id for item in (task.human_deltas or [])],
        "decision_ids": [item.id for item in (task.decisions or [])],
        "counts": {
            "reviews": len(task.human_reviews or []),
            "clarifications": len(task.clarifications or []),
            "evidence": len(task.evidence_items or []),
            "human_deltas": len(task.human_deltas or []),
            "decisions": len(task.decisions or []),
        },
        "created_at": datetime.utcnow().isoformat(),
    }


def baseline_task(db: Session, task: SddTask, actor_id: Optional[str]) -> SddTaskBaseline:
    if enum_value(task.status) == TaskStatus.BASELINED.value:
        existing = latest_baseline(db, task.id)
        if existing:
            return existing
    close_resolved_reviews(task)
    db.flush()
    ensure_baseline_allowed(db, task)

    version = int(task.baseline_version or 0) + 1
    snapshot = build_baseline_snapshot(task, version=version)
    baseline = SddTaskBaseline(
        workspace_id=task.workspace_id,
        task_id=task.id,
        summary_id=task.final_summary.id if task.final_summary else None,
        version=version,
        snapshot_json=snapshot,
        baselined_by_id=actor_id,
        is_rollback=False,
    )
    db.add(baseline)
    db.flush()

    task.status = TaskStatus.BASELINED
    task.baseline_version = version
    task.baselined_at = datetime.utcnow()
    task.baselined_by_id = actor_id
    task.baseline_snapshot_json = snapshot
    task.session_id = None
    task.interrupt_reason = None
    task.interrupted_by_id = None
    task.interrupted_at = None

    _add_process_audit(
        db,
        workspace_id=task.workspace_id,
        task_id=task.id,
        record_type=TaskProcessRecordType.TASK_BASELINE,
        record_id=baseline.id,
        action=TaskProcessAuditAction.FINALIZED,
        actor_id=actor_id,
        after=baseline_response(baseline).model_dump(mode="json"),
        reason="Task final summary verified and baseline snapshot frozen.",
    )
    return baseline
