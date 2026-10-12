"""Connect collaboration input/output barriers to the existing chat lifecycle."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from app.core.logging import get_logger
from app.core.offload import run_db_txn, run_file_job
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.task.models.task import SddTask

logger = get_logger(__name__, category="task_execution")
STOPPED_STATUSES = {AiJobStatus.SUCCESS, AiJobStatus.FAILED, AiJobStatus.CANCELLED, AiJobStatus.INTERRUPTED}
_settling_jobs: set[str] = set()


def request_input(db, task, submission) -> None:
    from app.domains.task.services.chat_submission_service import SubmissionError
    from app.domains.workspace_collaboration import service

    try:
        service.request_input(db, task, submission.id, submission.creator_id)
    except service.CollaborationError as exc:
        raise SubmissionError(str(exc), exc.code, exc.status_code) from exc


def input_ready(db, task_id: str, submission_id: str) -> bool:
    from app.domains.workspace_collaboration import service

    return service.input_ready(db, task_id, submission_id)


def advance_session(db, task, submission_id: str | None) -> None:
    from app.domains.task.services.task_session_service import TaskSessionUndoError
    from app.domains.workspace_collaboration import service

    try:
        service.advance_session(db, task, submission_id)
    except service.CollaborationError as exc:
        raise TaskSessionUndoError(str(exc), code=exc.code, status_code=exc.status_code) from exc


def authorize_job(db, job) -> None:
    from app.domains.workspace_collaboration import service

    task = db.get(SddTask, job.task_id)
    context = dict(job.context_json or {})
    # Caller-controlled metadata never authorizes the file input.
    context.pop("collaboration", None)
    accepted = service.authorize_execution(db, task, context.get("submission_id"), job.id)
    if accepted:
        context["collaboration"] = accepted
    job.context_json = context


def _validate_job(db, job_id: str, run_token: str | None):
    from app.domains.workspace_collaboration import service

    job = db.get(SddAiJob, job_id)
    if not job or not job.task_id:
        return None
    return service.validate_execution(db, db.get(SddTask, job.task_id), job.id, expected_run_token=run_token)


def _stage_progress(db, job_id: str, run_token: str | None):
    from app.domains.workspace_collaboration import service

    job = db.get(SddAiJob, job_id)
    if not job or job.status not in {AiJobStatus.RUNNING, AiJobStatus.WAITING_HITL}:
        return None
    return service.stage_progress(db, db.get(SddTask, job.task_id), job.id, expected_run_token=run_token)


def _publish_progress(db, job_id: str, run_token: str | None, staged, captured):
    from app.domains.workspace_collaboration import service

    job = db.get(SddAiJob, job_id)
    if not job or job.status not in {AiJobStatus.RUNNING, AiJobStatus.WAITING_HITL}:
        return None
    return service.publish_progress(
        db, db.get(SddTask, job.task_id), job.id, staged, captured, expected_run_token=run_token
    )


async def _progress_loop(job_id: str, stop: asyncio.Event, run_token: str | None) -> None:
    from app.domains.workspace_collaboration import service

    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=2.0)
        except TimeoutError:
            try:
                staged = await run_db_txn(lambda db: _stage_progress(db, job_id, run_token))
                if staged is None:
                    return
                # One collection at a time; filesystem work does not hold a
                # database transaction or enqueue an unbounded preview backlog.
                captured = await run_file_job(service.collect_progress, staged)
                if not stop.is_set():
                    await run_db_txn(
                        lambda db, staged=staged, captured=captured: _publish_progress(
                            db, job_id, run_token, staged, captured
                        )
                    )
            except service.CollaborationError as exc:
                if exc.code in {"EXECUTION_FENCED", "SESSION_CHANGED", "REPOSITORY_SET_CHANGED"}:
                    return
                logger.warning("Collaboration preview deferred: job_id={}, code={}", job_id, exc.code)
            except Exception:
                # Preview failure is separate from the provider outcome. The
                # final snapshot remains mandatory before another execution.
                logger.exception("Collaboration preview deferred: job_id={}", job_id)


@asynccontextmanager
async def execution(job_id: str):
    """Validate the authorized input and collect shell/tool changes off-loop."""
    from app.agents import current_agent_attempt

    attempt = current_agent_attempt()
    run_token = attempt.run_token if attempt else None
    accepted = await run_db_txn(lambda db: _validate_job(db, job_id, run_token))
    stop = asyncio.Event()
    collector = asyncio.create_task(_progress_loop(job_id, stop, run_token)) if accepted else None
    try:
        yield accepted
    finally:
        stop.set()
        if collector:
            # Finish the in-flight read instead of abandoning its file worker.
            # Publication independently rechecks job status and version fences;
            # a final result may already have converged inside the executor.
            await asyncio.shield(collector)


def _settle_job(db, job_id: str) -> None:
    from app.domains.workspace_collaboration import service
    from app.domains.workspace_collaboration.models import CollaborationState

    job = db.get(SddAiJob, job_id)
    if not job or job.channel != AiJobChannel.TASK_CHAT or not job.task_id:
        return
    if job.status not in {*STOPPED_STATUSES, AiJobStatus.ORPHANED}:
        return
    state = db.get(CollaborationState, job.task_id)
    if not state or not state.enabled or state.run_id != job.id:
        return
    task = db.get(SddTask, job.task_id)
    if task is not None:
        service.finish_execution(db, task, job.id, confirmed_stopped=job.status in STOPPED_STATUSES)


async def settle_job(job_id: str) -> None:
    """Use persisted convergence, never a provider result event, as stop proof."""
    from app.domains.workspace_collaboration import service

    # The publisher and recovery sweep may observe the same terminal job. The
    # database NOWAIT fence also defers a competing process without blocking a
    # worker or mistaking an in-flight capture for failed delivery.
    if job_id in _settling_jobs:
        return
    _settling_jobs.add(job_id)
    try:
        try:
            await run_db_txn(lambda db: _settle_job(db, job_id))
        except Exception as exc:
            if isinstance(exc, service.CollaborationError) and exc.code == "TASK_BUSY":
                return
            logger.exception("Collaboration final delivery requires recovery: job_id={}", job_id)

            def mark_failed(db):
                job = db.get(SddAiJob, job_id)
                if job and job.task_id:
                    service.mark_recovery(
                        db, job.task_id, "最终代码快照未完成，请重新核对后继续", expected_run_id=job_id
                    )

            try:
                await run_db_txn(mark_failed)
            except service.CollaborationError as recovery_error:
                if recovery_error.code != "TASK_BUSY":
                    raise
    finally:
        _settling_jobs.discard(job_id)


async def recover_deliveries() -> None:
    """Reconcile convergence committed before a process lost its broadcast."""
    from app.domains.workspace_collaboration.models import CollaborationState

    def pending(db):
        return [
            row[0]
            for row in db.query(SddAiJob.id)
            .join(CollaborationState, CollaborationState.run_id == SddAiJob.id)
            .filter(
                CollaborationState.enabled.is_(True),
                CollaborationState.sync_phase.in_(["RUNNING", "WAITING_HITL", "STOPPING"]),
                SddAiJob.status.in_([*STOPPED_STATUSES, AiJobStatus.ORPHANED]),
            )
            .limit(50)
            .all()
        ]

    for job_id in await run_db_txn(pending):
        await settle_job(job_id)


def begin_restore(db, task, operation_id: str) -> None:
    from app.domains.task.services.task_session_service import TaskSessionUndoError
    from app.domains.workspace_collaboration import service

    try:
        service.begin_restore(db, task, operation_id=operation_id)
    except service.CollaborationError as exc:
        raise TaskSessionUndoError(str(exc), code=exc.code, status_code=exc.status_code) from exc


async def finish_restore(task_id: str, run_txn) -> None:
    from app.domains.workspace_collaboration import service

    try:
        await run_txn(lambda db: service.finish_restore(db, db.get(SddTask, task_id)))
    except Exception:
        logger.exception("Restored server code still requires local delivery: task_id={}", task_id)
        await run_txn(lambda db: service.mark_recovery(db, task_id, "历史代码已恢复，等待重新捕获交付版本"))


def minimal_context(accepted) -> str:
    """Small deterministic metadata; source files stay in the task workspace."""
    if not accepted:
        return ""
    snapshot = accepted.get("input_snapshot_id") or accepted.get("snapshot_id") or ""
    revision = accepted.get("workspace_revision", "")
    return (
        "\n\n[TraceForge 本地协同输入]\n"
        f"输入版本: {snapshot}; 工作区版本: {revision}。\n"
        "任务工作目录已包含本轮确认的本地修改。请重新读取相关代码，不复用上一轮的文件内容；"
        "用户在执行期间新增的本地修改不会注入本轮。\n"
    )
