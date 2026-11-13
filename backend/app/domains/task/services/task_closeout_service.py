"""Lightweight Task closeout orchestration.

This service records the key development or diagnosis facts produced when a user
finishes or fails a Task. It deliberately delegates process-asset writes to
workspace_asset task_process writes and does not mutate Traceability directly.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.domains.ai.models.ai_job import AiJobChannel, SddAiJob
from app.domains.ai.services.jobs.constants import SESSION_GUARD_STATUSES
from app.domains.dashboard.models.metric import SddDashboardMetric
from app.domains.task.models.task import SddTask, TaskStatus, TaskType
from app.domains.task.schemas.task_closeout import (
    TASK_CLOSEOUT_VALUES,
    CloseoutEvidenceAttachment,
    CompleteTaskCloseoutRequest,
    FailTaskCloseoutRequest,
    TaskCloseoutResponse,
)
from app.domains.task.services import status_machine as sm
from app.domains.workspace_asset.models.workspace_asset import (
    RequirementAuditAction,
    SddRequirement,
    SddTaskRequirement,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    EvidenceCreateRequest,
    TaskFinalSummaryUpsertRequest,
)
from app.domains.workspace_asset.services.requirements.presenters import add_requirement_audit
from app.domains.workspace_asset.services.task_final_workflow import summary_service
from app.domains.workspace_asset.services.task_process import evidence_writes
from app.domains.workspace_collaboration.models import CollaborationState
from app.domains.workspace_collaboration.session import disconnect_driver, driver_connected


class TaskCloseoutError(Exception):
    def __init__(self, message: str, *, status_code: int = 400, code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _clean(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _short(value: str | None, limit: int = 500) -> str | None:
    cleaned = _clean(value)
    return cleaned[:limit] if cleaned else None


def _validate_closeout_values(task: SddTask, payload: CompleteTaskCloseoutRequest | FailTaskCloseoutRequest) -> None:
    task_type = TaskType(task.task_type or TaskType.DEVELOPMENT)
    allowed = TASK_CLOSEOUT_VALUES[task_type]
    fields = (
        ("landing_method",) if isinstance(payload, CompleteTaskCloseoutRequest) else ("failure_stage", "failure_reason")
    )
    for field in fields:
        if getattr(payload, field) not in allowed[field]:
            raise TaskCloseoutError(f"{field} is not valid for {task_type.value} tasks.", status_code=422)


def _get_open_task(db: Session, workspace_id: str, task_id: str) -> SddTask:
    task = db.query(SddTask).filter_by(id=task_id, workspace_id=workspace_id).with_for_update().first()
    if not task:
        raise TaskCloseoutError("Task not found", status_code=404)
    if task.baselined_at is not None:
        raise TaskCloseoutError("Task is BASELINED and locked for changes", status_code=403)
    if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
        raise TaskCloseoutError("Task is already closed", status_code=409)
    if task.status == TaskStatus.PROVISIONING:
        raise TaskCloseoutError("Task resources are being prepared", status_code=409)
    return task


def _prepare_closeout(db: Session, task: SddTask, actor_id: str, lease_epoch: int | None) -> None:
    from app.domains.local_resource.service import require_operation
    from app.engine.session.registry import list_task_engines

    require_operation(db, task, actor_id, operation="closeout")
    active_job = (
        db.query(SddAiJob.id)
        .filter(
            SddAiJob.task_id == task.id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
            SddAiJob.status.in_(SESSION_GUARD_STATUSES),
        )
        .first()
    )
    if active_job or any(engine.running for engine in list_task_engines(task.id)):
        raise TaskCloseoutError(
            "Wait for the Agent to finish before closing this task.",
            status_code=409,
            code="CLOSEOUT_AGENT_ACTIVE",
        )

    state = db.query(CollaborationState).filter_by(task_id=task.id).with_for_update().first()
    if not driver_connected(state):
        return
    if state.driver_user_id != actor_id or state.lease_epoch != lease_epoch:
        raise TaskCloseoutError(
            "An active collaboration host must disconnect before closing this task.",
            status_code=409,
            code="CLOSEOUT_COLLABORATION_CONNECTED",
        )
    disconnect_driver(state)


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


def _complete_evidence_payloads(
    payload: CompleteTaskCloseoutRequest, task_type: TaskType
) -> list[EvidenceCreateRequest]:
    evidence: list[EvidenceCreateRequest] = []
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
    for item in evidence:
        item.source_metadata = {
            **(item.source_metadata or {}),
            "task_type": task_type.value,
            "landing_method": payload.landing_method,
        }
    return evidence


def _failure_evidence_payloads(payload: FailTaskCloseoutRequest, task_type: TaskType) -> list[EvidenceCreateRequest]:
    evidence = [
        _attachment_evidence(
            attachment,
            title_prefix="Failure evidence",
            evidence_type="FAILURE",
            change_reason="Task failure closeout.",
        )
        for attachment in payload.evidence_attachments
    ]
    for item in evidence:
        item.source_metadata = {
            **(item.source_metadata or {}),
            "task_type": task_type.value,
            "failure_stage": payload.failure_stage,
            "failure_reason": payload.failure_reason,
        }
    return evidence


def _finalize_task(
    db: Session,
    task: SddTask,
    *,
    trigger: sm.Trigger,
    actor_id: str,
    message: str,
    metric_value: float,
    content: dict,
    result_fields: dict,
) -> TaskCloseoutResponse:
    key = f"closeout:{trigger.value}"
    sm.dispatch(db, task, trigger, event_key=key, actor_id=actor_id, reason=message, content=content)
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
    result = TaskCloseoutResponse(**sm.snapshot(task), **result_fields)
    sm.remember_command_result(db, task.id, key, result.model_dump(mode="json"))
    return result


def _replay_closeout(
    db: Session,
    workspace_id: str,
    task_id: str,
    actor_id: str,
    trigger: sm.Trigger,
    message: str,
    content: dict,
    previous: dict,
) -> TaskCloseoutResponse:
    # Preserve the original fingerprint for requests already recorded by older versions.
    if "confirmed_server_snapshot_id" in previous:
        content["confirmed_server_snapshot_id"] = previous["confirmed_server_snapshot_id"]
    task = db.query(SddTask).filter_by(id=task_id, workspace_id=workspace_id).one()
    sm.dispatch(
        db, task, trigger, event_key=f"closeout:{trigger.value}", actor_id=actor_id, reason=message, content=content
    )
    return TaskCloseoutResponse(**previous)


def complete_task_closeout(
    db: Session,
    workspace_id: str,
    task_id: str,
    actor_id: str,
    payload: CompleteTaskCloseoutRequest,
) -> TaskCloseoutResponse:
    previous = sm.receipt(db, task_id, "closeout:COMPLETE")
    if previous:
        return _replay_closeout(
            db,
            workspace_id,
            task_id,
            actor_id,
            sm.Trigger.COMPLETE,
            payload.completion_summary,
            payload.model_dump(mode="json", exclude={"disconnect_collaboration_lease_epoch"}),
            previous,
        )
    task = _get_open_task(db, workspace_id, task_id)
    _prepare_closeout(db, task, actor_id, payload.disconnect_collaboration_lease_epoch)
    _validate_closeout_values(task, payload)
    task_type = TaskType(task.task_type or TaskType.DEVELOPMENT)
    is_diagnosis = task_type == TaskType.DIAGNOSIS
    evidence_payloads = _complete_evidence_payloads(payload, task_type)

    if payload.requirement_id:
        requirement = db.query(SddRequirement).filter_by(id=payload.requirement_id, workspace_id=workspace_id).first()
        if not requirement:
            raise TaskCloseoutError("Requirement not found in this workspace", status_code=404)
        if db.query(SddRequirement.id).filter_by(parent_requirement_id=requirement.id).first():
            raise TaskCloseoutError("Parent Requirement has children; select a child Requirement", status_code=409)
        existing_link = (
            db.query(SddTaskRequirement.id).filter_by(task_id=task_id, requirement_id=requirement.id).first()
        )
        if not existing_link:
            requirement.updated_at = datetime.now(timezone.utc)
            db.add(
                SddTaskRequirement(
                    workspace_id=workspace_id,
                    task_id=task_id,
                    requirement_id=requirement.id,
                    created_by_id=actor_id,
                )
            )
            add_requirement_audit(
                db,
                workspace_id=workspace_id,
                requirement_id=requirement.id,
                task_id=task_id,
                actor_id=actor_id,
                action=RequirementAuditAction.LINKED_TASK,
                after={"task_id": task_id, "relation_type": "RELATES_TO"},
                source_metadata={"created_from": "task_closeout"},
            )

    evidence_ids = [
        evidence_writes.create_evidence(
            db, workspace_id, task_id, actor_id, evidence_payload, _skip_phase_check=True, commit=False
        )
        for evidence_payload in evidence_payloads
    ]

    final_summary_id = summary_service.upsert_final_summary(
        db,
        workspace_id,
        task_id,
        actor_id,
        TaskFinalSummaryUpsertRequest(
            final_status="PARTIAL",
            summary=payload.completion_summary,
            remaining_risk=(
                "Task is marked DONE from diagnosis closeout. Root-cause and fix verification still depend on supporting evidence and human confirmation."
                if is_diagnosis
                else "Task is marked DONE from local development closeout. Coverage Verified still depends on real Evidence and human confirmation."
            ),
            next_steps=(
                "Review the root cause and diagnostic evidence, follow up on any unverified fix, and archive reusable investigation findings."
                if is_diagnosis
                else "Review Task Detail evidence and promote reusable knowledge when needed."
            ),
            final_evidence_ids=evidence_ids,
            change_reason=f"Task completion closeout. Method: {payload.landing_method}.",
        ),
        commit=False,
    )
    from app.domains.notification.services.task_awareness import capture_business

    capture_business(db, task, actor_id, "TASK_COMPLETED", payload.completion_summary)
    result = _finalize_task(
        db,
        task,
        trigger=sm.Trigger.COMPLETE,
        actor_id=actor_id,
        message=payload.completion_summary,
        metric_value=1.0,
        content=payload.model_dump(mode="json", exclude={"disconnect_collaboration_lease_epoch"}),
        result_fields={
            "business_state": "TASK_COMPLETED",
            "evidence_ids": evidence_ids,
            "final_summary_id": final_summary_id,
        },
    )
    from app.domains.workspace_asset.services.task_final_workflow.review_service import ensure_expert_review_for_task

    ensure_expert_review_for_task(db, task, actor_id)
    db.commit()
    return result


def fail_task_closeout(
    db: Session,
    workspace_id: str,
    task_id: str,
    actor_id: str,
    payload: FailTaskCloseoutRequest,
) -> TaskCloseoutResponse:
    previous = sm.receipt(db, task_id, "closeout:FAIL")
    if previous:
        return _replay_closeout(
            db,
            workspace_id,
            task_id,
            actor_id,
            sm.Trigger.FAIL,
            payload.failure_summary,
            payload.model_dump(mode="json", exclude={"disconnect_collaboration_lease_epoch"}),
            previous,
        )
    task = _get_open_task(db, workspace_id, task_id)
    _prepare_closeout(db, task, actor_id, payload.disconnect_collaboration_lease_epoch)
    _validate_closeout_values(task, payload)
    task_type = TaskType(task.task_type or TaskType.DEVELOPMENT)
    evidence_payloads = _failure_evidence_payloads(payload, task_type)

    evidence_ids = [
        evidence_writes.create_evidence(
            db, workspace_id, task_id, actor_id, evidence_payload, _skip_phase_check=True, commit=False
        )
        for evidence_payload in evidence_payloads
    ]

    final_summary_id = summary_service.upsert_final_summary(
        db,
        workspace_id,
        task_id,
        actor_id,
        TaskFinalSummaryUpsertRequest(
            final_status="REJECTED",
            summary=payload.failure_summary,
            remaining_risk=f"Failure stage: {payload.failure_stage}; reason: {payload.failure_reason}.",
            next_steps=(
                "Collect missing diagnostic evidence, revisit reproduction conditions and hypotheses, then resume investigation in a fresh session if needed."
                if task_type == TaskType.DIAGNOSIS
                else "Review failure evidence, clarify requirements or environment, then initialize a fresh session if needed."
            ),
            final_evidence_ids=evidence_ids,
            change_reason="Task failure closeout.",
        ),
        commit=False,
    )
    from app.domains.notification.services.task_awareness import capture_business

    capture_business(db, task, actor_id, "TASK_FAILED", payload.failure_summary)
    result = _finalize_task(
        db,
        task,
        trigger=sm.Trigger.FAIL,
        actor_id=actor_id,
        message=payload.failure_summary,
        metric_value=0.0,
        content=payload.model_dump(mode="json", exclude={"disconnect_collaboration_lease_epoch"}),
        result_fields={
            "business_state": "TASK_FAILED",
            "evidence_ids": evidence_ids,
            "final_summary_id": final_summary_id,
        },
    )
    db.commit()
    return result
