"""Durable execution receipts for jobs whose business state lives in another domain.

Receipts share the AI queue's claim, lease, attempt supervision and reaper. Inputs
and the business row commit together; result payloads stay in their owning tables.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

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
) -> SddAiJob:
    """Add a receipt without committing the caller's business transaction."""
    receipt = SddAiJob(
        id=job_id,
        workspace_id=workspace_id,
        channel=AiJobChannel.BACKGROUND,
        queue_key=f"{QUEUE_PREFIX}{kind}:{resource_id}",
        status=AiJobStatus.PENDING,
        creator_id=creator_id,
        max_attempts=3,
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
    from app.domains.ai.services.jobs.registry import runtime

    with SessionLocal() as db:
        receipt = db.get(SddAiJob, job_id)
        if receipt:
            runtime.schedule_queue(receipt.queue_key)


def check_ownership(db: Session, *, allow_cancel: bool = False) -> SddAiJob | None:
    from app.domains.ai.services.jobs.registry import runtime

    attempt = current_agent_attempt()
    if not attempt or not attempt.queue_key.startswith(QUEUE_PREFIX):
        return None
    if runtime.shutdown_in_progress():
        raise AgentAttemptFencedError("Worker shutdown interrupted the domain job")
    with db.no_autoflush:
        receipt = db.query(SddAiJob).filter(SddAiJob.id == attempt.job_id).populate_existing().with_for_update().first()
    if (
        receipt is None
        or receipt.run_token != attempt.run_token
        or receipt.worker_boot_id != attempt.worker_boot_id
        or receipt.status not in {AiJobStatus.RUNNING, AiJobStatus.TERMINATING}
        or (receipt.lease_expires_at is not None and receipt.lease_expires_at <= datetime.utcnow())
    ):
        raise AgentAttemptFencedError("Domain job attempt no longer owns its execution receipt")
    if not allow_cancel and (receipt.cancel_requested_at or receipt.status == AiJobStatus.TERMINATING):
        raise AgentCancelledError("Domain job cancelled")
    return receipt


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


def request_cancel(db: Session, job_id: str) -> None:
    from app.domains.ai.services.jobs.domain_job_results import business_row

    with db.no_autoflush:
        receipt = db.query(SddAiJob).filter_by(id=job_id).populate_existing().with_for_update().first()
        row = business_row(db, receipt) if receipt else None
        if row is not None:
            db.refresh(row, with_for_update=True)
            if row.status.value in {"SUCCESS", "FAILED"}:
                return
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


def settle_business_state(db: Session, receipt: SddAiJob) -> None:
    """Mirror recovery/cancellation outcomes in the same convergence transaction."""
    if receipt.channel != AiJobChannel.BACKGROUND:
        return
    from app.domains.ai.services.jobs.domain_job_results import settle

    settle(db, receipt)
