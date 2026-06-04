"""Final summary draft, verification, and baseline orchestration."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.domains.workspace_asset.models.workspace_asset import (
    SddTaskFinalSummary,
    TaskFinalStatus,
    TaskProcessAuditAction,
    TaskProcessRecordType,
)
from app.domains.workspace_asset.schemas.task_final_workflow import (
    FinalSummaryDraftRequest,
    WorkflowFinalSummaryUpsertRequest,
)
from app.domains.workspace_asset.schemas.workspace_asset import TaskFinalSummaryUpsertRequest
from app.domains.workspace_asset.services.task_final_workflow import baseline_service
from app.domains.workspace_asset.services.workspace_task_detail_shared import (
    TaskDetailWriteError,
    _add_process_audit,
    _ensure_evidence,
    _ensure_final_summary_verified_allowed,
    _ensure_human_review,
    _get_task_or_error,
    clean_optional,
    final_summary_response,
    normalize_enum,
    normalize_list,
)


def draft_final_summary(
    db: Session,
    workspace_id: str,
    task_id: str,
    actor_id: Optional[str],
    payload: FinalSummaryDraftRequest,
) -> str:
    task = _get_task_or_error(db, workspace_id, task_id)
    baseline_service.ensure_task_mutable(task)
    evidence_ids = [item.id for item in (task.evidence_items or [])]
    review_count = len(task.human_reviews or [])
    clarification_count = len(task.clarifications or [])
    delta_count = len(task.human_deltas or [])
    decision_count = len(task.decisions or [])
    summary_text = (
        f"Task '{task.name}' is ready for final review with {len(evidence_ids)} evidence item(s), "
        f"{review_count} review(s), {clarification_count} clarification(s), "
        f"{delta_count} human delta(s), and {decision_count} decision record(s)."
    )
    return upsert_final_summary(
        db,
        workspace_id,
        task_id,
        actor_id,
        WorkflowFinalSummaryUpsertRequest(
            final_status="PARTIAL",
            summary=summary_text,
            remaining_risk="Review checklist items before marking the final summary VERIFIED.",
            next_steps="Resolve blocking clarifications, confirm evidence, then verify the final summary.",
            final_evidence_ids=evidence_ids,
            review_checklist={"review_count": review_count},
            clarification_summary={"clarification_count": clarification_count},
            delta_summary={"human_delta_count": delta_count},
            decision_summary={"decision_count": decision_count, "hard_blocking": False},
            change_reason=payload.change_reason or "Generated final summary draft.",
        ),
    )


def _coerce_workflow_payload(payload: TaskFinalSummaryUpsertRequest | WorkflowFinalSummaryUpsertRequest) -> WorkflowFinalSummaryUpsertRequest:
    if isinstance(payload, WorkflowFinalSummaryUpsertRequest):
        return payload
    return WorkflowFinalSummaryUpsertRequest(
        final_status=payload.final_status,
        summary=payload.summary,
        remaining_risk=payload.remaining_risk,
        next_steps=payload.next_steps,
        final_evidence_ids=payload.final_evidence_ids,
        review_checklist=payload.review_checklist,
        clarification_summary=payload.clarification_summary,
        delta_summary=payload.delta_summary,
        decision_summary=payload.decision_summary,
        human_confirmation_review_id=payload.human_confirmation_review_id,
        change_reason=payload.change_reason,
    )


def upsert_final_summary(
    db: Session,
    workspace_id: str,
    task_id: str,
    actor_id: Optional[str],
    payload: TaskFinalSummaryUpsertRequest | WorkflowFinalSummaryUpsertRequest,
) -> str:
    task = _get_task_or_error(db, workspace_id, task_id)
    baseline_service.ensure_task_mutable(task)
    workflow_payload = _coerce_workflow_payload(payload)
    status = normalize_enum(TaskFinalStatus, workflow_payload.final_status, TaskFinalStatus.PENDING, "Task final status")
    for evidence_id in workflow_payload.final_evidence_ids:
        _ensure_evidence(db, workspace_id, task_id, evidence_id)
    _ensure_human_review(db, workspace_id, task_id, workflow_payload.human_confirmation_review_id)
    if status == TaskFinalStatus.VERIFIED:
        _ensure_final_summary_verified_allowed(task)

    summary = task.final_summary
    before = final_summary_response(summary).model_dump(mode="json") if summary else None
    if not summary:
        summary = SddTaskFinalSummary(workspace_id=workspace_id, task_id=task_id)
        db.add(summary)
        db.flush()
        task.final_summary = summary
        action = TaskProcessAuditAction.CREATED
    else:
        action = TaskProcessAuditAction.FINALIZED if status == TaskFinalStatus.VERIFIED else TaskProcessAuditAction.UPDATED

    summary.author_id = actor_id
    summary.final_status = status
    summary.summary = clean_optional(workflow_payload.summary)
    summary.remaining_risk = clean_optional(workflow_payload.remaining_risk)
    summary.next_steps = clean_optional(workflow_payload.next_steps)
    summary.final_evidence_ids_json = normalize_list(workflow_payload.final_evidence_ids)
    summary.review_checklist_json = workflow_payload.review_checklist
    summary.clarification_summary_json = workflow_payload.clarification_summary
    summary.delta_summary_json = workflow_payload.delta_summary
    summary.decision_summary_json = workflow_payload.decision_summary
    summary.human_confirmation_review_id = workflow_payload.human_confirmation_review_id
    if status == TaskFinalStatus.VERIFIED:
        summary.verified_at = datetime.utcnow()
        summary.verified_by_id = actor_id
    db.flush()

    _add_process_audit(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        record_type=TaskProcessRecordType.FINAL_SUMMARY,
        record_id=summary.id,
        action=action,
        actor_id=actor_id,
        before=before,
        after=final_summary_response(summary).model_dump(mode="json"),
        reason=workflow_payload.change_reason,
    )

    if status == TaskFinalStatus.VERIFIED:
        baseline_service.baseline_task(db, task, actor_id)

    summary_id = summary.id
    db.commit()
    return summary_id


def baseline_task(db: Session, workspace_id: str, task_id: str, actor_id: Optional[str]) -> str:
    task = _get_task_or_error(db, workspace_id, task_id)
    baseline_service.ensure_task_mutable(task)
    baseline = baseline_service.baseline_task(db, task, actor_id)
    db.commit()
    return baseline.id
