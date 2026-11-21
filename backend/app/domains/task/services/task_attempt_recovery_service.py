"""Recover old attempts before starting a new task conversation turn."""

import asyncio
from datetime import datetime

from sqlalchemy import func

from app.config import settings
from app.core.distributed_lock import lock_task
from app.core.offload import run_db_txn
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services.jobs.store import blocking_attempt_predicate, lease_ttl_seconds


def interrupt_lock_ttl_seconds() -> int:
    return max(1, min(settings.TASK_LOCK_TTL_SECONDS, settings.TASK_INTERRUPT_LOCK_TTL_SECONDS))


def lock_task_for_resume(task_id: str):
    # A killed stop handler cannot release its Redis lock. Wait through one
    # full stop lease plus the polling interval without bypassing live holders.
    wait = max(
        settings.DISTRIBUTED_LOCK_BLOCKING_TIMEOUT_SECONDS,
        interrupt_lock_ttl_seconds() + max(1.0, 2 * settings.DISTRIBUTED_LOCK_SLEEP_SECONDS),
    )
    return lock_task(task_id, blocking_timeout=wait)


def active_statuses(db, task_id):
    return [
        row[0]
        for row in db.query(SddAiJob.status)
        .filter(
            SddAiJob.task_id == task_id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
            blocking_attempt_predicate(),
        )
        .all()
    ]


def _interrupt_lease_remaining(db, task_id: str) -> float:
    expires_at = (
        db.query(func.max(SddAiJob.lease_expires_at))
        .filter(
            SddAiJob.task_id == task_id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
            SddAiJob.status == AiJobStatus.TERMINATING,
            SddAiJob.cancel_requested_at.isnot(None),
            SddAiJob.context_json["termination_mode"].as_string() == "INTERRUPT",
        )
        .scalar()
    )
    if expires_at is None:
        return 0.0
    return min(lease_ttl_seconds(), max(0.0, (expires_at - datetime.utcnow()).total_seconds()))


async def recover_task_attempts(task_id, *, run_txn=run_db_txn, wait_for_running=False, wait_for_interrupt_lease=False):
    """Caller holds the task lock; never cancel a healthy attempt on ordinary send."""
    from app.domains.ai.services.jobs.reaper import reap_stale_jobs

    if not await run_txn(lambda db: active_statuses(db, task_id)):
        return
    await reap_stale_jobs(task_id=task_id)
    remaining = await run_txn(lambda db: _interrupt_lease_remaining(db, task_id)) if wait_for_interrupt_lease else 0
    loop = asyncio.get_running_loop()
    deadline = loop.time() + remaining + settings.TASK_SESSION_REVERT_WAIT_SECONDS
    reap_at = loop.time() + remaining if remaining else None
    while statuses := await run_txn(lambda db: active_statuses(db, task_id)):
        # Queued/running/HITL turns still belong to the user. Ordinary chat
        # must reject these promptly, rather than request their cancellation.
        if not wait_for_running and any(
            status
            in {
                AiJobStatus.PENDING,
                AiJobStatus.RUNNING,
                AiJobStatus.WAITING_HITL,
            }
            for status in statuses
        ):
            return
        now = loop.time()
        if reap_at is not None and now >= reap_at:
            await reap_stale_jobs(task_id=task_id)
            reap_at = None
            continue
        if now >= deadline:
            return
        delay = 0.25 if wait_for_interrupt_lease else 0.1
        await asyncio.sleep(min(delay, (reap_at or deadline) - now))
