"""Task 过程资产写侧的实体校验、phase 门禁与审计写入。

本模块是过程资产写操作（Review / Delta / Evidence / Decision /
Clarification / Final Summary）共用的前置校验与审计工具；展示器统一在
``common.process_presenters``。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.domains.ai.models.ai_job import SddAiJob
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.workspace_asset.models.workspace_asset import (
    ClarificationBlockingLevel,
    ClarificationStatus,
    EvidenceSourceType,
    EvidenceType,
    HumanReviewOutcome,
    HumanReviewStatus,
    SddAiOutput,
    SddEvidence,
    SddHumanDelta,
    SddHumanReview,
    SddRequirement,
    SddTaskProcessAuditLog,
    TaskProcessAuditAction,
    TaskProcessRecordType,
)
from app.domains.workspace_asset.services.common.errors import WorkspaceAssetError
from app.domains.workspace_asset.services.common.primitives import (
    clean_optional,
    enum_value,
    is_human_confirmation,
)


def get_task_or_error(db: Session, workspace_id: str, task_id: str) -> SddTask:
    task = db.query(SddTask).filter(SddTask.workspace_id == workspace_id, SddTask.id == task_id).first()
    if not task:
        raise WorkspaceAssetError("Task not found.", status_code=404)
    return task


def ensure_task_not_baselined(task: SddTask) -> None:
    if enum_value(task.status) == TaskStatus.BASELINED.value:
        raise WorkspaceAssetError(
            "Task is BASELINED and locked for process changes.",
            status_code=403,
        )


def ensure_requirement(db: Session, workspace_id: str, requirement_id: Optional[str]) -> Optional[SddRequirement]:
    if not requirement_id:
        return None
    requirement = (
        db.query(SddRequirement)
        .filter(SddRequirement.workspace_id == workspace_id, SddRequirement.id == requirement_id)
        .first()
    )
    if not requirement:
        raise WorkspaceAssetError("Requirement not found.", status_code=404)
    return requirement


def ensure_ai_job(db: Session, workspace_id: str, task_id: str, ai_job_id: Optional[str]) -> Optional[SddAiJob]:
    if not ai_job_id:
        return None
    job = (
        db.query(SddAiJob)
        .filter(SddAiJob.workspace_id == workspace_id, SddAiJob.task_id == task_id, SddAiJob.id == ai_job_id)
        .first()
    )
    if not job:
        raise WorkspaceAssetError("AI Run not found for this Task.", status_code=404)
    return job


def ensure_ai_output(db: Session, workspace_id: str, task_id: str, output_id: Optional[str]) -> Optional[SddAiOutput]:
    if not output_id:
        return None
    output = (
        db.query(SddAiOutput)
        .filter(SddAiOutput.workspace_id == workspace_id, SddAiOutput.task_id == task_id, SddAiOutput.id == output_id)
        .first()
    )
    if not output:
        raise WorkspaceAssetError("AI Output not found for this Task.", status_code=404)
    return output


def ensure_human_review(
    db: Session,
    workspace_id: str,
    task_id: str,
    review_id: Optional[str],
) -> Optional[SddHumanReview]:
    if not review_id:
        return None
    review = (
        db.query(SddHumanReview)
        .filter(
            SddHumanReview.workspace_id == workspace_id,
            SddHumanReview.task_id == task_id,
            SddHumanReview.id == review_id,
        )
        .first()
    )
    if not review:
        raise WorkspaceAssetError("Human Review not found for this Task.", status_code=404)
    return review


def ensure_human_delta(
    db: Session,
    workspace_id: str,
    task_id: str,
    delta_id: Optional[str],
) -> Optional[SddHumanDelta]:
    if not delta_id:
        return None
    delta = (
        db.query(SddHumanDelta)
        .filter(
            SddHumanDelta.workspace_id == workspace_id,
            SddHumanDelta.task_id == task_id,
            SddHumanDelta.id == delta_id,
        )
        .first()
    )
    if not delta:
        raise WorkspaceAssetError("Human Delta not found for this Task.", status_code=404)
    return delta


def ensure_evidence(db: Session, workspace_id: str, task_id: str, evidence_id: Optional[str]) -> Optional[SddEvidence]:
    if not evidence_id:
        return None
    evidence = (
        db.query(SddEvidence)
        .filter(SddEvidence.workspace_id == workspace_id, SddEvidence.task_id == task_id, SddEvidence.id == evidence_id)
        .first()
    )
    if not evidence:
        raise WorkspaceAssetError("Evidence not found for this Task.", status_code=404)
    return evidence


def validate_evidence_source(
    *,
    source_type: EvidenceSourceType,
    source_uri: Optional[str],
    source_ref: Optional[str],
    source_path: Optional[str],
    source_metadata: Optional[Dict[str, Any]],
) -> None:
    # All attachment fields are optional; source_type alone is sufficient.
    return


_RUNNING_STATUSES = {
    TaskStatus.PENDING,
    TaskStatus.BRAINSTORMING,
    TaskStatus.PLANNING,
    TaskStatus.CODING,
    TaskStatus.TESTING,
    TaskStatus.REVIEWING,
    TaskStatus.DEPLOYING,
    TaskStatus.SUSPENDED,
    TaskStatus.INTERRUPTED,
}


def validate_evidence_for_phase(task_status: TaskStatus, evidence_type: EvidenceType) -> None:
    """Running tasks cannot have evidence; DONE allows CODE/BUSINESS/HUMAN_CONFIRMATION; FAILED allows FAILURE/RUNTIME/AI."""
    if task_status == TaskStatus.BASELINED:
        raise WorkspaceAssetError("Task is BASELINED and locked for process changes.", status_code=403)
    if task_status in _RUNNING_STATUSES:
        raise WorkspaceAssetError(
            "Evidence can only be created after task reaches DONE or FAILED status.",
            status_code=422,
        )
    if task_status == TaskStatus.FAILED and evidence_type not in (
        EvidenceType.FAILURE,
        EvidenceType.RUNTIME,
        EvidenceType.AI,
    ):
        raise WorkspaceAssetError(
            f"Evidence type '{evidence_type.value}' is not applicable for a failed task.",
            status_code=422,
        )


def add_process_audit(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    record_type: TaskProcessRecordType,
    record_id: str,
    action: TaskProcessAuditAction,
    actor_id: Optional[str] = None,
    before: Optional[Dict[str, Any]] = None,
    after: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
) -> None:
    db.add(
        SddTaskProcessAuditLog(
            workspace_id=workspace_id,
            task_id=task_id,
            actor_id=actor_id,
            record_type=record_type,
            record_id=record_id,
            action=action,
            before_json=before,
            after_json=after,
            reason=clean_optional(reason),
        )
    )


def has_accepting_review(task: SddTask) -> bool:
    accepting = {
        HumanReviewOutcome.ACCEPT.value,
        HumanReviewOutcome.ACCEPT_WITH_MODIFICATION.value,
    }
    return any(
        enum_value(review.outcome) in accepting
        and enum_value(review.status) in {HumanReviewStatus.RESOLVED.value, HumanReviewStatus.CLOSED.value}
        for review in (task.human_reviews or [])
    )


def task_coverage_status(task: SddTask) -> str:
    if not task.requirement_links:
        return "not_available"
    evidence_items = list(task.evidence_items or [])
    if not evidence_items:
        return "waiting_evidence"
    if not any(is_human_confirmation(item) for item in evidence_items):
        return "waiting_human_confirmation"
    return "verified"


def has_open_blocking_clarification(task: SddTask) -> bool:
    terminal_statuses = {
        ClarificationStatus.ACCEPTED.value,
        ClarificationStatus.CLOSED.value,
        ClarificationStatus.CANCELLED.value,
    }
    return any(
        enum_value(item.status) not in terminal_statuses
        and enum_value(item.blocking_level) == ClarificationBlockingLevel.BLOCKING.value
        for item in (task.clarifications or [])
    )


def ensure_final_summary_verified_allowed(task: SddTask) -> None:
    if task_coverage_status(task) != "verified":
        raise WorkspaceAssetError(
            "Final Summary cannot be VERIFIED until Coverage is backed by human confirmation Evidence.",
            status_code=409,
        )
    from app.domains.workspace_asset.services.task_final_workflow import review_service

    expert_reviews = [
        review
        for review in (task.human_reviews or [])
        if review.review_type == review_service.EXPERT_REVIEW_TYPE
    ]
    if not expert_reviews:
        raise WorkspaceAssetError(
            "Final Summary cannot be VERIFIED without at least one expert review item.",
            status_code=409,
        )
    if has_open_blocking_clarification(task):
        raise WorkspaceAssetError(
            "Final Summary cannot be VERIFIED while a blocking Clarification is unresolved.",
            status_code=409,
        )
