"""Business state projection for durable domain-job recovery."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob


def business_row(db: Session, receipt: SddAiJob):
    from app.domains.api_mock.models.api_mock import SddApiMockJob
    from app.domains.skill.models.skill import SddSkillAnalysis
    from app.domains.workflow.models.provision_job import SddProvisionJob

    model = {
        "SKILL_ANALYSIS": SddSkillAnalysis,
        "API_MOCK": SddApiMockJob,
        "PROVISION": SddProvisionJob,
    }.get((receipt.context_json or {}).get("job_kind"))
    return db.get(model, receipt.id) if model else None


def settle(db: Session, receipt: SddAiJob) -> None:
    row = business_row(db, receipt)
    if row is None:
        return
    # Business completion may commit just before its receipt finalizer. Recovery
    # must preserve that result instead of executing its side effects again.
    if row.status.value in {"SUCCESS", "FAILED"}:
        return
    if receipt.status == AiJobStatus.PENDING:
        row.status = type(row.status)("PENDING")
        row.progress = 0
        row.message = "Execution interrupted; queued for recovery"
        row.finished_at = None
        return
    if receipt.status not in {AiJobStatus.FAILED, AiJobStatus.CANCELLED}:
        return
    row.status = type(row.status)("FAILED")
    row.finished_at = datetime.utcnow()
    row.message = receipt.error_message or receipt.terminal_reason or "Execution interrupted"
    if hasattr(row, "error_message"):
        row.error_message = row.message
    if hasattr(row, "stage"):
        row.stage = "CANCELLED" if receipt.status == AiJobStatus.CANCELLED else "FAILED"
    if receipt.status == AiJobStatus.CANCELLED and hasattr(row, "result_json"):
        row.result_json = {**(row.result_json or {}), "cancel_requested": True, "cancelled": True}
