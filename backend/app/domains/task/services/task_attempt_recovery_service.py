"""Recover old attempts before starting a new task conversation turn."""

import asyncio

from app.config import settings
from app.core.offload import run_db_txn
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob

BLOCKING = [AiJobStatus.PENDING, AiJobStatus.RUNNING, AiJobStatus.WAITING_HITL,
            AiJobStatus.TERMINATING, AiJobStatus.ORPHANED]


def active_statuses(db, task_id):
    return [row[0] for row in db.query(SddAiJob.status).filter(
        SddAiJob.task_id == task_id,
        SddAiJob.channel == AiJobChannel.TASK_CHAT,
        SddAiJob.status.in_(BLOCKING),
    ).all()]


async def recover_task_attempts(task_id, *, run_txn=run_db_txn, wait_for_running=False):
    """Caller holds the task lock; never cancel a healthy attempt on ordinary send."""
    from app.domains.ai.services import ai_job_service

    if not await run_txn(lambda db: active_statuses(db, task_id)):
        return
    await ai_job_service.reap_stale_jobs(task_id=task_id)
    deadline = asyncio.get_running_loop().time() + settings.TASK_SESSION_REVERT_WAIT_SECONDS
    while statuses := await run_txn(lambda db: active_statuses(db, task_id)):
        # Queued/running/HITL turns still belong to the user. Ordinary chat
        # must reject these promptly, rather than request their cancellation.
        if not wait_for_running and any(status in {
            AiJobStatus.PENDING, AiJobStatus.RUNNING, AiJobStatus.WAITING_HITL,
        } for status in statuses):
            return
        if asyncio.get_running_loop().time() >= deadline:
            return
        await asyncio.sleep(0.1)
