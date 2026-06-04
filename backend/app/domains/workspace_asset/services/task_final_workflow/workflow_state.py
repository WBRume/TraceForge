"""Read model assembly for the Task final-state workflow."""

from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy.orm import Session, selectinload

from app.domains.asset.models.asset import AssetType
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.workspace_asset.models.workspace_asset import (
    ClarificationBlockingLevel,
    SddClarification,
    SddClarificationThread,
    SddHumanReview,
    TaskFinalStatus,
)
from app.domains.workspace_asset.schemas.task_final_workflow import (
    ClarificationThreadResponse,
    FinalWorkflowAction,
    FinalWorkflowReviewTarget,
    TaskFinalWorkflowResponse,
    TaskFinalWorkflowStep,
)
from app.domains.workspace_asset.services.task_final_workflow import baseline_service, review_service
from app.domains.workspace_asset.services.workspace_task_detail_query import _task_summary_from_counts
from app.domains.workspace_asset.services.workspace_task_detail_shared import (
    TaskDetailWriteError,
    clarification_response,
    enum_value,
    final_summary_response,
    human_review_response,
)


def _load_task(db: Session, workspace_id: str, task_id: str) -> SddTask:
    task = (
        db.query(SddTask)
        .options(
            selectinload(SddTask.requirement_links),
            selectinload(SddTask.assets),
            selectinload(SddTask.ai_outputs),
            selectinload(SddTask.human_reviews).selectinload(SddHumanReview.comments),
            selectinload(SddTask.human_reviews).selectinload(SddHumanReview.clarification_links),
            selectinload(SddTask.clarifications).selectinload(SddClarification.threads),
            selectinload(SddTask.evidence_items),
            selectinload(SddTask.human_deltas),
            selectinload(SddTask.decisions),
            selectinload(SddTask.final_summary),
            selectinload(SddTask.baselines),
        )
        .filter(SddTask.workspace_id == workspace_id, SddTask.id == task_id)
        .first()
    )
    if not task:
        raise TaskDetailWriteError("Task not found.", status_code=404)
    return task


def _thread_response(thread: SddClarificationThread) -> ClarificationThreadResponse:
    return ClarificationThreadResponse(
        id=thread.id,
        workspace_id=thread.workspace_id,
        task_id=thread.task_id,
        clarification_id=thread.clarification_id,
        author_id=thread.author_id,
        entry_type=thread.entry_type,
        body=thread.body,
        is_answer=bool(thread.is_answer),
        created_at=thread.created_at,
    )


def _workflow_reviews(task: SddTask) -> List[SddHumanReview]:
    return [
        item
        for item in (task.human_reviews or [])
        if item.review_type == review_service.EXPERT_REVIEW_TYPE
    ]


def _target(
    *,
    target_type: str,
    target_id: str,
    label: str,
    status: Optional[str] = None,
    subtitle: Optional[str] = None,
    source_ref: Optional[dict] = None,
) -> FinalWorkflowReviewTarget:
    return FinalWorkflowReviewTarget(
        target_type=target_type,
        target_id=target_id,
        label=label,
        status=status,
        subtitle=subtitle,
        source_ref=source_ref,
    )


def _review_targets(task: SddTask) -> Dict[str, List[FinalWorkflowReviewTarget]]:
    targets: Dict[str, List[FinalWorkflowReviewTarget]] = {
        "SPEC": [],
        "PLAN": [],
        "AI_CHANGE": [],
        "HUMAN_DELTA": [],
        "EVIDENCE": [],
        "DECISION": [],
        "TASK_FILE": [],
    }
    for asset in task.assets or []:
        asset_type = enum_value(asset.asset_type)
        source_ref = {"source_kind": "asset", "asset_type": asset_type, "asset_id": asset.id}
        if asset_type == AssetType.SPEC.value:
            targets["SPEC"].append(
                _target(
                    target_type="SPEC",
                    target_id=asset.id,
                    label=asset.name,
                    status="ACTIVE" if asset.active_version_id else "DRAFT",
                    subtitle=asset.source_file_name,
                    source_ref=source_ref,
                )
            )
        elif asset_type == AssetType.PLAN.value:
            targets["PLAN"].append(
                _target(
                    target_type="PLAN",
                    target_id=asset.id,
                    label=asset.name,
                    status="ACTIVE" if asset.active_version_id else "DRAFT",
                    subtitle=asset.source_file_name,
                    source_ref=source_ref,
                )
            )
        else:
            targets["TASK_FILE"].append(
                _target(
                    target_type="TASK_FILE",
                    target_id=asset.id,
                    label=asset.name,
                    status=asset_type,
                    subtitle=asset.source_file_name,
                    source_ref=source_ref,
                )
            )
    for output in task.ai_outputs or []:
        targets["AI_CHANGE"].append(
            _target(
                target_type="AI_CHANGE",
                target_id=output.id,
                label=output.title or enum_value(output.output_type) or output.id,
                status=enum_value(output.output_type),
                subtitle=output.ai_job_id,
                source_ref={"source_kind": "ai_output", "ai_job_id": output.ai_job_id},
            )
        )
    for delta in task.human_deltas or []:
        targets["HUMAN_DELTA"].append(
            _target(
                target_type="HUMAN_DELTA",
                target_id=delta.id,
                label=delta.change_category or delta.comparison_summary or delta.id,
                status=enum_value(delta.status),
                subtitle=f"{delta.changed_files_count or 0} file(s)",
                source_ref={"source_kind": "human_delta", "proposal_id": delta.proposal_id},
            )
        )
    for evidence in task.evidence_items or []:
        targets["EVIDENCE"].append(
            _target(
                target_type="EVIDENCE",
                target_id=evidence.id,
                label=evidence.title or evidence.source_ref or evidence.source_uri or evidence.id,
                status=enum_value(evidence.status),
                subtitle=enum_value(evidence.evidence_type),
                source_ref={
                    "source_kind": "evidence",
                    "source_type": enum_value(evidence.source_type),
                    "source_ref": evidence.source_ref,
                    "source_uri": evidence.source_uri,
                    "source_path": evidence.source_path,
                },
            )
        )
    for decision in task.decisions or []:
        targets["DECISION"].append(
            _target(
                target_type="DECISION",
                target_id=decision.id,
                label=decision.title,
                status=enum_value(decision.status),
                subtitle=decision.impact_scope,
                source_ref={"source_kind": "decision", "source_type": enum_value(decision.source_type)},
            )
        )
    return targets


def _workflow_step_status(task: SddTask) -> List[TaskFinalWorkflowStep]:
    reviews = _workflow_reviews(task)
    clarifications = list(task.clarifications or [])
    unresolved_blocking_count = sum(
        1
        for item in clarifications
        if enum_value(item.blocking_level) == ClarificationBlockingLevel.BLOCKING.value
        and enum_value(item.status) not in baseline_service.TERMINAL_CLARIFICATION_STATUSES
    )
    summary_verified = bool(
        task.final_summary and enum_value(task.final_summary.final_status) == TaskFinalStatus.VERIFIED.value
    )
    baselined = enum_value(task.status) == TaskStatus.BASELINED.value
    review_ready = bool(reviews) and unresolved_blocking_count == 0
    review_attention_count = sum(
        1
        for review in reviews
        if review_service.derive_review_status(review, task_is_baselined=baselined)
        in {"WAITING_ANSWER", "ANSWERED_REVIEWING"}
    )

    return [
        TaskFinalWorkflowStep(
            key="expert_review",
            title="Expert Review",
            status="complete" if baselined or review_ready else ("active" if reviews else "ready"),
            detail=f"{len(reviews)} review item(s), {review_attention_count} awaiting clarification flow.",
            blocking_count=review_attention_count,
        ),
        TaskFinalWorkflowStep(
            key="clarification",
            title="Clarification",
            status="complete" if unresolved_blocking_count == 0 else "blocked",
            detail=f"{unresolved_blocking_count} unresolved blocking clarification(s).",
            blocking_count=unresolved_blocking_count,
        ),
        TaskFinalWorkflowStep(
            key="final_summary",
            title="Final Summary",
            status="complete" if summary_verified else ("ready" if review_ready else "blocked"),
            detail="Final summary is verified." if summary_verified else "Verify after review and clarification are complete.",
            blocking_count=0 if review_ready else 1,
        ),
        TaskFinalWorkflowStep(
            key="baseline",
            title="Baseline",
            status="complete" if baselined else ("ready" if summary_verified else "blocked"),
            detail=f"Baseline version {task.baseline_version}." if baselined else "Freeze after final summary verification.",
            blocking_count=0 if baselined or summary_verified else 1,
        ),
    ]


def _actions(task: SddTask, checklist_blocked: bool) -> List[FinalWorkflowAction]:
    readonly = enum_value(task.status) == TaskStatus.BASELINED.value
    if readonly:
        return []
    summary_verified = bool(
        task.final_summary and enum_value(task.final_summary.final_status) == TaskFinalStatus.VERIFIED.value
    )
    return [
        FinalWorkflowAction(
            key="generate_summary_draft",
            label="Generate summary draft",
            enabled=not readonly,
            disabled_reason="Task is baselined." if readonly else None,
        ),
        FinalWorkflowAction(
            key="verify_summary",
            label="Verify final summary",
            enabled=not readonly and not checklist_blocked,
            disabled_reason=(
                "Resolve blocking checklist items first."
                if checklist_blocked
                else ("Task is baselined." if readonly else None)
            ),
        ),
        FinalWorkflowAction(
            key="baseline",
            label="Freeze baseline",
            enabled=not readonly and summary_verified and not checklist_blocked,
            disabled_reason=(
                "Final summary must be verified first."
                if not summary_verified
                else ("Task is baselined." if readonly else None)
            ),
        ),
    ]


def get_workflow_state(
    db: Session,
    workspace_id: str,
    task_id: str,
    *,
    can_write_final_workflow: bool = False,
    can_resolve_clarification: bool = False,
) -> TaskFinalWorkflowResponse:
    task = _load_task(db, workspace_id, task_id)
    checklist = baseline_service.build_baseline_checklist(db, task)
    latest = baseline_service.latest_baseline(db, task.id)
    threads: Dict[str, List[ClarificationThreadResponse]] = {
        item.id: [_thread_response(thread) for thread in (item.threads or [])]
        for item in (task.clarifications or [])
    }
    checklist_blocked = any(item.blocking for item in checklist)
    readonly = enum_value(task.status) == TaskStatus.BASELINED.value
    reviews = _workflow_reviews(task)
    for review in reviews:
        setattr(review, "_derived_status", review_service.derive_review_status(review, task_is_baselined=readonly))

    return TaskFinalWorkflowResponse(
        task=_task_summary_from_counts(db, task),
        steps=_workflow_step_status(task),
        reviews=[human_review_response(item) for item in reviews],
        review_targets=_review_targets(task),
        clarifications=[clarification_response(item) for item in (task.clarifications or [])],
        clarification_threads=threads,
        final_summary=final_summary_response(task.final_summary) if task.final_summary else None,
        baseline=baseline_service.baseline_response(latest),
        checklist=checklist,
        available_actions=_actions(task, checklist_blocked),
        readonly=readonly,
        can_write_final_workflow=can_write_final_workflow and not readonly,
        can_resolve_clarification=can_resolve_clarification and not readonly,
    )
