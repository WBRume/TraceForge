"""Job facts for the existing forward-only initialization executor.

The initialization journal owns resumable repository operation receipts and
human continuation; it never enters the generic dispatcher or automatic retry.
The caller holds the task operation lock and commits facts with that journal.
"""

from datetime import datetime
from uuid import uuid4

from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.schemas.job_result import JobCompletion


def report_initialization(db, task, operation):
    job_id = operation["id"]
    job = db.query(SddAiJob).filter_by(id=job_id).with_for_update().first()
    now = datetime.utcnow()
    if job is None:
        job = SddAiJob(
            id=job_id,
            workspace_id=task.workspace_id,
            task_id=task.id,
            creator_id=operation["actor_id"],
            channel=AiJobChannel.BACKGROUND,
            queue_key=f"TASK_INITIALIZATION:{task.id}",
            queue_source="bootstrap",
            job_type="TASK_INITIALIZATION",
            resource_id=task.id,
            execution_backend="initialization_journal",
            status=AiJobStatus.PENDING,
            context_json={"job_kind": "TASK_INITIALIZATION", "inputs": operation["request"]},
            max_attempts=1,
        )
        db.add(job)
    if job.status == AiJobStatus.SUCCESS:
        return job
    if job.creator_id != operation["actor_id"] or job.task_id != task.id:
        raise ValueError("Initialization executor identity changed")
    if job.status in {AiJobStatus.PENDING, AiJobStatus.INTERRUPTED} and not operation.get("error"):
        job.attempt_count = int(job.attempt_count or 0) + 1
        job.run_token = str(uuid4())
        job.worker_id = "initialization_journal"
        job.started_at = now
    job.stage = operation["state"]
    job.error_message = operation.get("error")
    job.manual_intervention_required = bool(operation.get("error"))
    if operation["state"] == "COMPLETED":
        job.completion_json = JobCompletion(
            kind="TASK_INITIALIZATION",
            outcome="SUCCESS",
            summary="Task initialization completed",
            artifacts=[{"kind": "task_chat_job", "id": operation["job_id"]}],
            attempt=int(job.attempt_count or 0),
            committed_at=now,
        ).model_dump(mode="json")
        job.status = AiJobStatus.SUCCESS
        job.progress = 100
        job.finished_at = now
        job.run_token = None
    elif operation.get("error"):
        job.status = AiJobStatus.INTERRUPTED
    elif operation["state"] == "WAITING_LOCAL":
        job.status = AiJobStatus.WAITING_HITL
    else:
        job.status = AiJobStatus.RUNNING
    return job
