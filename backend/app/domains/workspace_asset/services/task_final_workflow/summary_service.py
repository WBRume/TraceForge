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
from app.domains.workspace_asset.services.common.primitives import (
    clean_optional,
    normalize_enum,
    normalize_list,
)
from app.domains.workspace_asset.services.common.process_presenters import final_summary_response
from app.domains.workspace_asset.services.task_process.writes_support import (
    add_process_audit,
    ensure_evidence,
    ensure_final_summary_verified_allowed,
    ensure_human_review,
    get_task_or_error,
)


def draft_final_summary(
    db: Session,
    workspace_id: str,
    task_id: str,
    actor_id: Optional[str],
    payload: FinalSummaryDraftRequest,
) -> str:
    task = get_task_or_error(db, workspace_id, task_id)
    baseline_service.ensure_task_mutable(task)
    evidence_ids = [item.id for item in (task.evidence_items or [])]
    review_count = len(task.human_reviews or [])
    clarification_count = len(task.clarifications or [])
    delta_count = len(task.human_deltas or [])
    decision_count = len(task.decisions or [])
    summary_text = (
        f"任务「{task.name}」已进入最终状态审查阶段。当前已累计归档 {len(evidence_ids)} 项有效测试证据、"
        f"{review_count} 项专家审查记录、{clarification_count} 项澄清会话、"
        f"{delta_count} 项人工代码修改差异及 {decision_count} 项关键决策记录。"
    )
    return upsert_final_summary(
        db,
        workspace_id,
        task_id,
        actor_id,
        WorkflowFinalSummaryUpsertRequest(
            final_status="PARTIAL",
            summary=summary_text,
            remaining_risk="请在核验最终摘要前复核各项前置检查条件，确保无阻断级质量隐患。",
            next_steps="解决所有阻塞澄清项，确认测试证据，随后完成最终摘要验证并冻结基线。",
            final_evidence_ids=evidence_ids,
            review_checklist={"review_count": review_count},
            clarification_summary={"clarification_count": clarification_count},
            delta_summary={"human_delta_count": delta_count},
            decision_summary={"decision_count": decision_count, "hard_blocking": False},
            change_reason=payload.change_reason or "生成最终状态摘要草稿。",
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
    task = get_task_or_error(db, workspace_id, task_id)
    baseline_service.ensure_task_mutable(task)
    workflow_payload = _coerce_workflow_payload(payload)
    status = normalize_enum(TaskFinalStatus, workflow_payload.final_status, TaskFinalStatus.PENDING, "Task final status")
    for evidence_id in workflow_payload.final_evidence_ids:
        ensure_evidence(db, workspace_id, task_id, evidence_id)
    ensure_human_review(db, workspace_id, task_id, workflow_payload.human_confirmation_review_id)
    if status == TaskFinalStatus.VERIFIED:
        ensure_final_summary_verified_allowed(task)

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

    add_process_audit(
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
    task = get_task_or_error(db, workspace_id, task_id)
    baseline_service.ensure_task_mutable(task)
    baseline = baseline_service.baseline_task(db, task, actor_id)
    db.commit()
    return baseline.id
