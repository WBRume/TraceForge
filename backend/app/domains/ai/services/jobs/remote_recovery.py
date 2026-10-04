"""Durable ownership of ordinary OpenCode task executions.

All provider traffic stays in the adapter. This module only persists locators,
fences old observers and claims existing work without enqueuing another prompt.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import math
import uuid

from app.agents.errors import AgentExecutionDetached
from app.core.offload import run_db
from app.database import SessionLocal
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services.jobs.registry import WORKER_BOOT_ID, WORKER_ID, runtime
from app.domains.task.models.task import SddTask


def valid_checkpoint(value) -> bool:
    return bool(isinstance(value, dict) and value.get("version") == 1
                and value.get("session_id") and value.get("prompt_id")
                and isinstance(value.get("deadline"), (int, float))
                and math.isfinite(value["deadline"])
                and value.get("phase") in {"prepared", "submitting", "submitted", "stopping"})


def recoverable(job) -> bool:
    return bool(job and job.channel == AiJobChannel.TASK_CHAT
                and job.status == AiJobStatus.RUNNING and job.cancel_requested_at is None
                and job.agent_backend == "opencode" and job.process_execution_kind == "REMOTE_SESSION"
                and (job.context_json or {}).get("job_kind") not in {"TASK_BASELINE", "DIAGNOSIS_SUMMARY", "PLAYBOOK_PROMOTION"}
                and valid_checkpoint(job.provider_execution_json)
                and job.provider_execution_json["phase"] != "stopping"
                and job.session_id == job.provider_execution_json["session_id"])


def current_task(db, job) -> bool:
    task = db.get(SddTask, job.task_id)
    return bool(task and (job.session_revision is None or task.session_revision == job.session_revision)
                and (job.session_generation is None or task.session_generation == job.session_generation))


def save_checkpoint_sync(attempt, checkpoint):
    if not valid_checkpoint(checkpoint):
        raise ValueError("Invalid remote execution checkpoint")
    with SessionLocal() as db:
        db.query(SddTask).filter(SddTask.id == attempt.task_id).with_for_update().first()
        job = db.query(SddAiJob).filter(SddAiJob.id == attempt.job_id).with_for_update().first()
        if not (job and job.status == AiJobStatus.RUNNING and job.cancel_requested_at is None
                and job.run_token == attempt.run_token and job.worker_boot_id == attempt.worker_boot_id
                and current_task(db, job)):
            raise AgentExecutionDetached("Remote execution observer lost its ownership")
        old = job.provider_execution_json
        if valid_checkpoint(old) and any(old[key] != checkpoint[key] for key in ("session_id", "prompt_id", "deadline")):
            raise AgentExecutionDetached("Remote execution identity cannot change during an attempt")
        if valid_checkpoint(old) and old["phase"] == "stopping" and checkpoint["phase"] != "stopping":
            raise AgentExecutionDetached("Remote execution is already being stopped")
        job.provider_execution_json = dict(checkpoint)
        job.session_id = checkpoint["session_id"]
        job.agent_backend = "opencode"
        db.commit()


def claim_existing_sync(job_id, expected_token):
    from app.domains.ai.services.jobs.store import lease_ttl_seconds
    with SessionLocal() as db:
        task_id = db.query(SddAiJob.task_id).filter(SddAiJob.id == job_id).scalar()
        db.query(SddTask).filter(SddTask.id == task_id).with_for_update().first()
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).with_for_update().first()
        if not recoverable(job) or job.run_token != expected_token or not current_task(db, job):
            return None
        now = datetime.utcnow()
        if job.worker_boot_id == WORKER_BOOT_ID and job.lease_expires_at and job.lease_expires_at > now:
            return None
        job.run_token = str(uuid.uuid4())
        job.worker_id, job.worker_boot_id = WORKER_ID, WORKER_BOOT_ID
        job.attempt_count = int(job.attempt_count or 0) + 1
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=lease_ttl_seconds())
        job.next_reap_at = job.lease_expires_at
        job.message = "Reconnecting to existing OpenCode execution"
        job.failure_code = None
        queue_key = str(job.queue_key)
        db.commit()
        return queue_key


async def attach_reclaimable(row) -> bool:
    """True means this row belongs to recovery, even if a competing claim won."""
    if not row.get("recoverable_remote"):
        return False
    queue_key = str(row["queue_key"])
    running = runtime.queue_runners.get(queue_key)
    if running and not running.done():
        return True
    claimed_queue = await run_db(claim_existing_sync, row["job_id"], row.get("expected_run_token"))
    if claimed_queue:
        runtime.schedule_queue(claimed_queue, recovered_job_id=row["job_id"])
    return True


def defer_observation_sync(attempt):
    """Leave remote work intact and expose a retryable observation outage."""
    from app.domains.ai.services.jobs.store import serialize_job
    with SessionLocal() as db:
        job = db.query(SddAiJob).filter(SddAiJob.id == attempt.job_id).with_for_update().first()
        if not (recoverable(job) and job.run_token == attempt.run_token
                and job.worker_boot_id == attempt.worker_boot_id):
            return None
        job.message = "OpenCode 状态暂不可确认，正在重新接管原任务"
        job.failure_code = "REMOTE_OBSERVER_DETACHED"
        job.lease_expires_at = datetime.utcnow() + timedelta(seconds=10)
        job.next_reap_at = job.lease_expires_at
        db.commit()
        return serialize_job(job)


def detach_local_observer(attempt) -> bool:
    """A lost DB lease must stop the observer, never its new owner's provider."""
    from app.engine.session.registry import get_engine
    engine = get_engine(attempt.task_id) if attempt.task_id else None
    if not engine or not valid_checkpoint(getattr(engine, "remote_execution_checkpoint", None)):
        return False
    owner = getattr(engine, "attempt", None)
    if not owner or owner.job_id != attempt.job_id or owner.run_token != attempt.run_token:
        # A successor is already registered. Never cancel its queue runner.
        return True
    runner = runtime.queue_runners.get(attempt.queue_key)
    if runner and not runner.done():
        runtime.detached_jobs.add(attempt.job_id)
        runner.cancel()
    return True
