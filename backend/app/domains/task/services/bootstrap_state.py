"""Current baseline resource validity and its authoritative execution snapshot."""

from enum import StrEnum
from typing import Any, Literal

from app.agents.domain_tools.runtime import Milestone
from app.domains.ai.models.ai_job import AiJobStatus
from app.domains.task.models.task_cli_bootstrap import SddTaskCliBootstrap, TaskCliBootstrapStatus

MESSAGE_UNSET = object()


class BootstrapPhase(StrEnum):
    PREPARE = "SPEC_PREPARE"
    READ = "SPEC_READ"
    REFRESH = "SPEC_REFRESH"
    ANALYZE = "SPEC_ANALYZE"
    VERIFY = "SPEC_VERIFY"


PHASES: dict[str, tuple[Literal["started", "validating"], str]] = {
    BootstrapPhase.PREPARE: ("started", "Preparing the document and task context"),
    BootstrapPhase.READ: ("started", "Reading the specification"),
    BootstrapPhase.REFRESH: ("started", "Updating baseline context"),
    BootstrapPhase.ANALYZE: ("validating", "Building context for document review"),
    BootstrapPhase.VERIFY: ("validating", "Checking that review sessions can reuse the baseline"),
}


def status_text(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def resource_status(record):
    job = record.execution
    if job is None or record.status == TaskCliBootstrapStatus.STALE:
        return record.status
    if str((job.context_json or {}).get("input_revision") or "") != str(record.spec_version_id or "missing"):
        return record.status
    if job.status in {AiJobStatus.FAILED, AiJobStatus.CANCELLED, AiJobStatus.ORPHANED}:
        return TaskCliBootstrapStatus.FAILED
    if record.status == TaskCliBootstrapStatus.READY and job.status != AiJobStatus.SUCCESS:
        return TaskCliBootstrapStatus.RUNNING
    return record.status


def serialize_bootstrap(record: SddTaskCliBootstrap) -> dict[str, Any]:
    status = resource_status(record)
    job = record.execution
    context = (job.context_json or {}) if job else {}
    current = job and str(context.get("input_revision") or "") == str(record.spec_version_id or "missing")
    milestones = []
    if status == TaskCliBootstrapStatus.RUNNING and current:
        milestones = context.get("domain_milestones") or []
        phase = PHASES.get(job.stage)
        if not milestones and phase:
            stage, description = phase
            milestones = [
                Milestone(
                    run_id=job.id,
                    call_id=job.stage,
                    sequence=int(job.version or 1),
                    tool="spec_bootstrap",
                    stage=stage,
                    message=description,
                    timestamp=job.updated_at.timestamp() if job.updated_at else 0,
                ).model_dump()
            ]
    return {
        "task_id": record.task_id,
        "workspace_id": record.workspace_id,
        "spec_asset_id": record.spec_asset_id,
        "spec_version_id": record.spec_version_id,
        "job_id": record.execution_job_id,
        "job_version": int(record.execution.version or 1) if record.execution else None,
        "job_status": status_text(record.execution.status) if record.execution else None,
        "status": status_text(status),
        "progress": int(record.execution.progress or 0) if record.execution else 0,
        "message": record.execution.message if record.execution else record.message,
        "domain_milestones": milestones,
        "baseline_dir": record.baseline_dir,
        "baseline_session_id": record.baseline_session_id,
        "agent_backend": record.agent_backend,
        "error_message": record.execution.error_message if record.execution else record.error_message,
        "refresh_mode": str(record.refresh_mode or "FULL"),
        "refresh_context_json": record.refresh_context_json if isinstance(record.refresh_context_json, dict) else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def report_execution(db, record, status, progress, message, error_message, baseline_session_id, *, phase=None):
    from app.agents import current_agent_attempt
    from app.domains.ai.services.jobs import domain_jobs

    attempt = current_agent_attempt()
    if not attempt:
        return True
    if record.execution_job_id != attempt.job_id:
        return False
    mapped = {TaskCliBootstrapStatus.READY: "SUCCESS", TaskCliBootstrapStatus.FAILED: "FAILED"}.get(status)
    if phase is not None:
        message = PHASES[phase][1]
    domain_jobs.report(
        db,
        attempt.job_id,
        status=mapped,
        progress=progress,
        stage=phase,
        message=message if message is not MESSAGE_UNSET else None,
        error_message=error_message,
        result={"spec_version_id": record.spec_version_id, "baseline_session_id": baseline_session_id}
        if mapped == "SUCCESS"
        else None,
        artifacts=[{"kind": "baseline", "id": record.id, "version": record.spec_version_id}]
        if mapped == "SUCCESS"
        else [],
    )
    return True
