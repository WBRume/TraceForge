"""Lightweight Task closeout orchestration.

This service records the key local-development facts produced when a user
finishes or fails a Task. It deliberately delegates process-asset writes to
workspace_task_detail_service and does not mutate Traceability directly.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.domains.dashboard.models.metric import SddDashboardMetric
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.schemas.task_closeout import (
    CloseoutEvidenceAttachment,
    CompleteTaskCloseoutRequest,
    FailTaskCloseoutRequest,
    TaskCloseoutResponse,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    EvidenceCreateRequest,
    TaskFinalSummaryUpsertRequest,
)
from app.domains.workspace_asset.services import workspace_task_detail_service


class TaskCloseoutError(Exception):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _clean(value: Optional[str]) -> Optional[str]:
    normalized = str(value or "").strip()
    return normalized or None


def _short(value: Optional[str], limit: int = 500) -> Optional[str]:
    cleaned = _clean(value)
    return cleaned[:limit] if cleaned else None


def _get_open_task(db: Session, workspace_id: str, task_id: str) -> SddTask:
    task = db.query(SddTask).filter(SddTask.id == task_id, SddTask.workspace_id == workspace_id).first()
    if not task:
        raise TaskCloseoutError("Task not found", status_code=404)
    if task.status == TaskStatus.BASELINED:
        raise TaskCloseoutError("Task is BASELINED and locked for changes", status_code=403)
    if task.status in {TaskStatus.DONE, TaskStatus.FAILED}:
        raise TaskCloseoutError("Task is already closed", status_code=409)
    return task


def _attachment_evidence(
    attachment: CloseoutEvidenceAttachment,
    *,
    title_prefix: str,
    evidence_type: str,
    change_reason: str,
) -> EvidenceCreateRequest:
    source_uri = _clean(attachment.source_uri)
    source_path = _clean(attachment.source_path)
    if not source_uri and not source_path:
        raise TaskCloseoutError("Evidence attachment must include source_uri or source_path.", status_code=422)
    filename = _clean(attachment.filename) or "Evidence attachment"
    return EvidenceCreateRequest(
        evidence_type=evidence_type,
        source_type="OTHER",
        source_uri=source_uri,
        source_label=_clean(attachment.source_label) or filename,
        source_path=source_path,
        source_metadata={
            "kind": "closeout_attachment",
            "filename": filename,
            "content_type": attachment.content_type,
            "size": attachment.size,
        },
        title=f"{title_prefix}: {filename}",
        summary="Evidence attachment uploaded during Task closeout.",
        change_reason=change_reason,
    )


def _complete_evidence_payloads(payload: CompleteTaskCloseoutRequest) -> List[EvidenceCreateRequest]:
    evidence: List[EvidenceCreateRequest] = []
    commit_id = _clean(payload.commit_id)
    pr_url = _clean(payload.pr_url)
    local_ref = _clean(payload.local_ref)
    if commit_id:
        evidence.append(
            EvidenceCreateRequest(
                evidence_type="CODE",
                source_type="COMMIT",
                source_ref=commit_id,
                source_label="Commit",
                source_metadata={"kind": "closeout_commit", "landing_method": payload.landing_method},
                title="Completion commit reference",
                summary=payload.completion_summary,
                change_reason="Task completion closeout.",
            )
        )
    if pr_url:
        evidence.append(
            EvidenceCreateRequest(
                evidence_type="CODE",
                source_type="MR",
                source_uri=pr_url,
                source_label="PR / MR",
                source_metadata={"kind": "closeout_pr", "landing_method": payload.landing_method},
                title="Completion PR / MR reference",
                summary=payload.completion_summary,
                change_reason="Task completion closeout.",
            )
        )
    if local_ref:
        evidence.append(
            EvidenceCreateRequest(
                evidence_type="CODE",
                source_type="OTHER",
                source_ref=local_ref,
                source_label="Local commit reference",
                source_metadata={"kind": "closeout_local_ref", "landing_method": payload.landing_method},
                title="Completion local reference",
                summary=payload.completion_summary,
                change_reason="Task completion closeout.",
            )
        )
    for attachment in payload.evidence_attachments:
        evidence.append(
            _attachment_evidence(
                attachment,
                title_prefix="Completion evidence",
                evidence_type="CODE",
                change_reason="Task completion closeout.",
            )
        )
    if not evidence:
        raise TaskCloseoutError("Task completion requires at least one commit, PR, local reference, or evidence attachment.", status_code=422)
    return evidence


def _failure_evidence_payloads(payload: FailTaskCloseoutRequest) -> List[EvidenceCreateRequest]:
    evidence = [
        _attachment_evidence(
            attachment,
            title_prefix="Failure evidence",
            evidence_type="FAILURE",
            change_reason="Task failure closeout.",
        )
        for attachment in payload.evidence_attachments
    ]
    if not evidence:
        raise TaskCloseoutError("Task failure requires at least one uploaded failure evidence attachment.", status_code=422)
    return evidence


def _finalize_task(db: Session, task: SddTask, *, status: TaskStatus, message: str, metric_value: float) -> None:
    task.status = status
    task.error_message = _short(message)
    task.session_id = None
    task.interrupt_reason = None
    task.interrupted_by_id = None
    task.interrupted_at = None
    task.dashboard_metrics.append(
        SddDashboardMetric(
            workspace_id=task.workspace_id,
            metric_type="TASK_RESULT",
            metric_value=metric_value,
        )
    )
    db.commit()
    db.refresh(task)


def complete_task_closeout(
    db: Session,
    workspace_id: str,
    task_id: str,
    actor_id: str,
    payload: CompleteTaskCloseoutRequest,
) -> TaskCloseoutResponse:
    task = _get_open_task(db, workspace_id, task_id)
    evidence_payloads = _complete_evidence_payloads(payload)

    evidence_ids = [
        workspace_task_detail_service.create_evidence(db, workspace_id, task_id, actor_id, evidence_payload, _skip_phase_check=True)
        for evidence_payload in evidence_payloads
    ]

    final_summary_id = workspace_task_detail_service.upsert_final_summary(
        db,
        workspace_id,
        task_id,
        actor_id,
        TaskFinalSummaryUpsertRequest(
            final_status="PARTIAL",
            summary=payload.completion_summary,
            remaining_risk="Task is marked DONE from local development closeout. Coverage Verified still depends on real Evidence and human confirmation.",
            next_steps="Review Task Detail evidence and promote reusable knowledge when needed.",
            final_evidence_ids=evidence_ids,
            change_reason="Task completion closeout.",
        ),
    )
    _finalize_task(db, task, status=TaskStatus.DONE, message=payload.completion_summary, metric_value=1.0)
    from app.domains.workspace_asset.services.task_final_workflow.review_service import ensure_expert_review_for_task

    ensure_expert_review_for_task(db, task, actor_id)
    db.commit()
    return TaskCloseoutResponse(
        task_id=task_id,
        workspace_id=workspace_id,
        status="DONE",
        evidence_ids=evidence_ids,
        final_summary_id=final_summary_id,
    )


def fail_task_closeout(
    db: Session,
    workspace_id: str,
    task_id: str,
    actor_id: str,
    payload: FailTaskCloseoutRequest,
) -> TaskCloseoutResponse:
    task = _get_open_task(db, workspace_id, task_id)
    evidence_payloads = _failure_evidence_payloads(payload)

    evidence_ids = [
        workspace_task_detail_service.create_evidence(db, workspace_id, task_id, actor_id, evidence_payload, _skip_phase_check=True)
        for evidence_payload in evidence_payloads
    ]

    final_summary_id = workspace_task_detail_service.upsert_final_summary(
        db,
        workspace_id,
        task_id,
        actor_id,
        TaskFinalSummaryUpsertRequest(
            final_status="REJECTED",
            summary=payload.failure_summary,
            remaining_risk=f"Failure stage: {payload.failure_stage}; reason: {payload.failure_reason}.",
            next_steps="Review failure evidence, clarify requirements or environment, then initialize a fresh session if needed.",
            final_evidence_ids=evidence_ids,
            change_reason="Task failure closeout.",
        ),
    )
    _finalize_task(db, task, status=TaskStatus.FAILED, message=payload.failure_summary, metric_value=0.0)
    return TaskCloseoutResponse(
        task_id=task_id,
        workspace_id=workspace_id,
        status="FAILED",
        evidence_ids=evidence_ids,
        final_summary_id=final_summary_id,
    )
