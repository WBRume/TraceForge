"""Submission and fenced fact reporting for durable domain executions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.agents import current_agent_attempt
from app.agents.errors import AgentCancelledError
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services.jobs.fencing import AgentAttemptFencedError

QUEUE_PREFIX = "DOMAIN_JOB:"


def enqueue(
    db: Session,
    *,
    job_id: str,
    kind: str,
    creator_id: str,
    workspace_id: str | None,
    resource_id: str,
    inputs: dict[str, Any] | None = None,
    task_id: str | None = None,
    message: str | None = None,
    stage: str | None = None,
    result: dict[str, Any] | None = None,
    retry_of_job_id: str | None = None,
    command_key: str | None = None,
) -> SddAiJob:
    """Add a receipt without committing the caller's business transaction."""
    receipt = SddAiJob(
        id=job_id,
        workspace_id=workspace_id,
        task_id=task_id,
        channel=AiJobChannel.BACKGROUND,
        queue_key=f"{QUEUE_PREFIX}{kind}:{resource_id}",
        status=AiJobStatus.PENDING,
        creator_id=creator_id,
        max_attempts=3,
        queue_source={"SKILL_ANALYSIS": "skill_analysis", "API_MOCK": "api_mock", "PROVISION": "provision"}[kind],
        job_type=(inputs or {}).get("job_type", kind),
        resource_id=resource_id,
        message=message,
        stage=stage or "QUEUED",
        result_json=result,
        retry_of_job_id=retry_of_job_id,
        command_key=command_key,
        context_json={"job_kind": kind, "inputs": inputs or {}},
    )
    db.add(receipt)
    return receipt


def schedule(kind: str, resource_id: str) -> None:
    from app.domains.ai.services.jobs.registry import runtime

    # A sync route need not have a loop: the durable dispatcher also discovers
    # this receipt, including if the process exits before this wake-up.
    runtime.schedule_queue(f"{QUEUE_PREFIX}{kind}:{resource_id}")


def schedule_by_id(job_id: str) -> None:
    from app.database import SessionLocal
    from app.domains.ai.services.jobs.backends import dispatch

    with SessionLocal() as db:
        receipt = db.get(SddAiJob, job_id)
        if receipt:
            dispatch(receipt)


def check_ownership(db: Session, *, allow_cancel: bool = False, job_id: str | None = None) -> SddAiJob | None:
    from app.domains.ai.services.jobs.registry import runtime

    attempt = current_agent_attempt()
    if not attempt:
        if job_id:
            raise AgentAttemptFencedError("Domain execution requires a bound attempt")
        return None
    if job_id and attempt.job_id != job_id:
        raise AgentAttemptFencedError("Attempt belongs to another job")
    if runtime.shutdown_in_progress():
        raise AgentAttemptFencedError("Worker shutdown interrupted the domain job")
    with db.no_autoflush:
        # Read scalar fence values from the database without replacing staged
        # result changes in the identity map. SELECT FOR UPDATE serializes a
        # concurrent cancel with this transaction's artifact commit.
        fence = (
            db.query(
                SddAiJob.run_token,
                SddAiJob.worker_boot_id,
                SddAiJob.status,
                SddAiJob.lease_expires_at,
                SddAiJob.cancel_requested_at,
                SddAiJob.completion_json,
                SddAiJob.result_json,
                SddAiJob.execution_backend,
            )
            .filter(SddAiJob.id == attempt.job_id)
            .with_for_update()
            .first()
        )
    if (
        fence is None
        or fence.execution_backend != "durable"
        or fence.run_token != attempt.run_token
        or fence.worker_boot_id != attempt.worker_boot_id
        or fence.status not in {AiJobStatus.RUNNING, AiJobStatus.TERMINATING}
        or (fence.lease_expires_at is not None and fence.lease_expires_at <= datetime.utcnow())
    ):
        raise AgentAttemptFencedError("Domain job attempt no longer owns its execution receipt")
    if not allow_cancel and (fence.cancel_requested_at or fence.status == AiJobStatus.TERMINATING):
        raise AgentCancelledError("Domain job cancelled")
    receipt = db.get(SddAiJob, attempt.job_id)
    # A worker may have loaded the receipt before cancellation committed on
    # another connection. Completion must use the intent read under this lock.
    set_committed_value(receipt, "cancel_requested_at", fence.cancel_requested_at)
    if fence.completion_json:
        set_committed_value(receipt, "completion_json", fence.completion_json)
        set_committed_value(receipt, "result_json", fence.result_json)
    return receipt


def report(
    db: Session,
    job_id: str,
    *,
    status=None,
    progress: int | None = None,
    stage: str | None = None,
    message: str | None = None,
    error_message: str | None = None,
    result: dict[str, Any] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
) -> SddAiJob:
    """Stage execution facts with the caller's artifacts in one transaction.

    Completion is durable before process cleanup. Only convergence can expose
    a terminal status. Recovery consumes this evidence and never repeats work.
    """
    outcome = str(getattr(status, "value", status) or "")
    allow_cancel = outcome in {"FAILED", "CANCELLED"} or stage in {"CANCELLING", "CANCELLED"}
    job = check_ownership(db, allow_cancel=allow_cancel, job_id=job_id)
    if job.completion_json:
        return job
    if outcome == "SUCCESS" and (job.context_json or {}).get("job_kind") == "PROVISION":
        from app.domains.ai.schemas.job_result import PROVISION_RESULTS

        result = (
            PROVISION_RESULTS[job.job_type]
            .model_validate(
                result
                or {
                    "workspace_id": job.workspace_id,
                    "task_id": job.task_id,
                }
            )
            .model_dump(exclude_unset=True)
        )
    if progress is not None:
        job.progress = max(0, min(100, int(progress)))
    if stage is not None:
        job.stage = stage
    if message is not None:
        job.message = message
    if error_message is not None:
        job.error_message = error_message
    if result is not None:
        if (job.context_json or {}).get("job_kind") == "API_MOCK":
            from app.domains.api_mock.schemas.api_mock import ApiMockJobResult

            result = ApiMockJobResult.model_validate(result).model_dump(exclude_unset=True)
        job.result_json = result
    if outcome in {"SUCCESS", "FAILED", "CANCELLED"}:
        from app.domains.ai.schemas.job_result import JobCompletion

        job.completion_json = JobCompletion(
            schema_version=2,
            kind=job.job_type,
            outcome="CANCELLED" if job.cancel_requested_at else outcome,
            summary=message or error_message or outcome,
            artifacts=artifacts or [],
            attempt=int(job.attempt_count),
            committed_at=datetime.utcnow(),
        ).model_dump(mode="json")
        if outcome == "SUCCESS":
            job.stage = "RESULT_COMMITTED"
    return job


def business_session(factory, *, allow_cancel: bool = False) -> Session:
    """Fence every flush/commit of a worker's business transaction.

    The receipt lock and the business write share a transaction. This also
    protects helpers which commit internally, such as source-version imports.
    """
    db = factory()
    attempt = current_agent_attempt()
    if attempt and attempt.queue_key.startswith(QUEUE_PREFIX):
        db.info["domain_allow_cancel"] = allow_cancel

        def guard(session, *args):
            check_ownership(session, allow_cancel=session.info.get("domain_allow_cancel", False))

        event.listen(db, "before_flush", guard)
        event.listen(db, "before_commit", guard)
    return db


def request_cancel(db: Session, job_id: str) -> bool:
    with db.no_autoflush:
        receipt = db.query(SddAiJob).filter_by(id=job_id).populate_existing().with_for_update().first()
        if receipt and receipt.completion_json:
            return False
    if (
        receipt
        and receipt.channel == AiJobChannel.BACKGROUND
        and receipt.status
        in {
            AiJobStatus.PENDING,
            AiJobStatus.RUNNING,
        }
    ):
        # Domain cancellation includes cooperative cleanup. Keep the lease and
        # runner until that cleanup is complete, including for a queued task.
        receipt.cancel_requested_at = receipt.cancel_requested_at or datetime.utcnow()
        receipt.stage = "CANCELLING"
        return True
    return False


def begin_cancel_finalization(job_id: str) -> bool:
    from app.database import SessionLocal
    from app.domains.ai.services.ai_job_convergence_service import (
        AttemptTerminationRequest,
        request_attempt_termination_in_txn,
    )

    with SessionLocal() as db:
        receipt = db.get(SddAiJob, job_id)
        if receipt is None or not receipt.cancel_requested_at:
            return False
        attempt = current_agent_attempt()
        request_attempt_termination_in_txn(
            db,
            AttemptTerminationRequest(
                job_id=job_id,
                reason="USER_CANCEL",
                expected_run_token=attempt.run_token,
            ),
        )
        db.commit()
        if (receipt.context_json or {}).get("job_kind") == "API_MOCK":
            from app.domains.api_mock.services.api_mock.job_service import _clear_cancel_event

            _clear_cancel_event(job_id)
        return True


def should_cancel() -> bool:
    from app.database import SessionLocal

    try:
        with SessionLocal() as db:
            check_ownership(db)
    except (AgentCancelledError, AgentAttemptFencedError):
        return True
    return False
