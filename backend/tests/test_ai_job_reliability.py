"""SQLite state-machine checks for durable AI job ownership."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.domains.api_mock.models.api_mock  # noqa: F401
import app.domains.task.models.task  # noqa: F401
import app.domains.workspace_asset.models.workspace_asset  # noqa: F401
from app.database import Base
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services import ai_job_service


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _job(db, *, status=AiJobStatus.PENDING, run_token=None, worker_boot_id=None):
    job = SddAiJob(
        id="reliability-job",
        workspace_id="ws-1",
        channel=AiJobChannel.TASK_CHAT,
        queue_key="TASK_CHAT:task-1",
        status=status,
        creator_id="user-1",
        run_token=run_token,
        worker_boot_id=worker_boot_id,
        lease_expires_at=datetime.utcnow() - timedelta(seconds=1) if status == AiJobStatus.RUNNING else None,
    )
    db.add(job)
    db.commit()
    return job


def test_two_claims_only_one_gets_run_token(monkeypatch):
    factory = _session_factory()
    db = factory()
    _job(db)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    first = ai_job_service._take_next_pending_job_id_sync("TASK_CHAT:task-1")
    second = ai_job_service._take_next_pending_job_id_sync("TASK_CHAT:task-1")

    assert first == "reliability-job"
    assert second is None
    claimed = db.get(SddAiJob, "reliability-job")
    assert claimed.status == AiJobStatus.RUNNING
    assert claimed.run_token
    assert claimed.attempt_count == 1


def test_reaper_converges_legacy_running_without_in_memory_state(monkeypatch):
    factory = _session_factory()
    db = factory()
    _job(db, status=AiJobStatus.RUNNING)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)

    asyncio.run(ai_job_service.reap_stale_jobs())

    recovered = db.get(SddAiJob, "reliability-job")
    assert recovered.status == AiJobStatus.ORPHANED
    assert recovered.failure_code == "WORKER_RESTART"


def test_cancel_running_job_is_not_reported_as_finished(monkeypatch):
    factory = _session_factory()
    db = factory()
    _job(
        db,
        status=AiJobStatus.RUNNING,
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
    )
    result = ai_job_service.cancel_job(db, workspace_id="ws-1", job_id="reliability-job")

    assert result is not None
    assert result.status == AiJobStatus.TERMINATING
    assert result.finished_at is None


def _owned_job(db, *, status=AiJobStatus.TERMINATING, token="run-1"):
    job = _job(
        db,
        status=status,
        run_token=token,
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
    )
    job.process_pid = 4242
    job.process_started_at = datetime.utcnow()
    job.process_group_id = 4242
    db.commit()
    return job


def test_late_termination_cannot_overwrite_success(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.SUCCESS)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    result = ai_job_service._finish_termination_sync(
        "reliability-job",
        "run-1",
        confirmed_dead=True,
        reason="late callback",
        failure_code="LATE_CALLBACK",
    )

    assert result is None
    assert db.get(SddAiJob, "reliability-job").status == AiJobStatus.SUCCESS


def test_late_termination_cannot_overwrite_cancelled(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.CANCELLED)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    result = ai_job_service._finish_termination_sync(
        "reliability-job",
        "run-1",
        confirmed_dead=True,
        reason="late callback",
        failure_code="LATE_CALLBACK",
    )

    assert result is None
    assert db.get(SddAiJob, "reliability-job").status == AiJobStatus.CANCELLED


def test_old_run_token_cannot_interrupt_current_attempt(monkeypatch):
    factory = _session_factory()
    db = factory()
    _job(
        db,
        status=AiJobStatus.RUNNING,
        run_token="current-run",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
    )
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)

    result = ai_job_service._mark_task_chat_job_interrupted_sync(
        db,
        job_id="reliability-job",
        reason="old attempt",
        message=None,
        session_id=None,
        context_patch=None,
        result_patch=None,
        run_token="old-run",
    )

    assert result is None
    assert db.get(SddAiJob, "reliability-job").status == AiJobStatus.RUNNING


def test_terminating_job_cannot_be_downgraded_by_engine_error(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.TERMINATING)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    result = ai_job_service._update_job_state_sync(
        "reliability-job",
        status=AiJobStatus.FAILED,
        finalize=True,
        run_token="run-1",
        termination_confirmed_dead=True,
        error_message="late engine error",
    )

    assert result["broadcast"] is False
    assert db.get(SddAiJob, "reliability-job").status == AiJobStatus.TERMINATING


def test_task_chat_success_clears_active_process_ownership(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.RUNNING)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    result = ai_job_service._update_job_state_sync(
        "reliability-job",
        status=AiJobStatus.SUCCESS,
        finalize=True,
        run_token="run-1",
        termination_confirmed_dead=True,
    )

    assert result["payload"]["status"] == AiJobStatus.SUCCESS.value
    saved = db.get(SddAiJob, "reliability-job")
    assert saved.process_pid is None
    assert saved.process_started_at is None
    assert saved.process_group_id is None
    assert saved.run_token is None


def test_interrupted_job_clears_ownership_only_after_confirmed_death(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.TERMINATING)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    orphaned = ai_job_service._finish_termination_sync(
        "reliability-job",
        "run-1",
        confirmed_dead=False,
        reason="tree still alive",
        failure_code="PROCESS_TREE_STILL_ALIVE",
    )
    saved = db.get(SddAiJob, "reliability-job")
    assert orphaned["status"] == AiJobStatus.ORPHANED.value
    assert saved.process_pid == 4242
    assert saved.run_token == "run-1"

    interrupted = ai_job_service._finish_termination_sync(
        "reliability-job",
        "run-1",
        confirmed_dead=True,
        reason="tree dead",
        failure_code="OK",
    )
    saved = db.get(SddAiJob, "reliability-job")
    db.refresh(saved)
    assert interrupted["status"] == AiJobStatus.INTERRUPTED.value
    assert saved.process_pid is None
    assert saved.run_token is None


def test_orphaned_job_retains_process_identity(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.TERMINATING)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    result = ai_job_service._finish_termination_sync(
        "reliability-job",
        "run-1",
        confirmed_dead=False,
        reason="cannot inspect tree",
        failure_code="PROCESS_TREE_UNKNOWN",
    )

    saved = db.get(SddAiJob, "reliability-job")
    assert result["status"] == AiJobStatus.ORPHANED.value
    assert saved.process_pid == 4242
    assert saved.process_group_id == 4242


def test_runtime_worker_survives_one_iteration_failure_and_honors_cancel(monkeypatch):
    calls = 0
    holder = {}
    monkeypatch.setattr(ai_job_service, "_RUNTIME_WORKER_HEALTH", {})
    monkeypatch.setattr(ai_job_service, "_SHUTTING_DOWN", False)

    async def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary database outage")
        asyncio.get_running_loop().call_soon(holder["task"].cancel)

    async def run():
        task = asyncio.create_task(ai_job_service._run_runtime_worker_loop("test", operation, 1))
        holder["task"] = task
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())

    health = ai_job_service._RUNTIME_WORKER_HEALTH["test"]
    assert calls == 2
    assert health["consecutive_failures"] == 0
    assert health["last_success_at"]
    assert health["iteration_duration_ms"] >= 0
    assert health["last_scan_count"] == 0


def test_start_runtime_workers_is_idempotent(monkeypatch):
    stop = asyncio.Event()

    async def idle_loop():
        await stop.wait()

    async def recover():
        return 0

    monkeypatch.setattr(ai_job_service, "_REAPER_TASK", None)
    monkeypatch.setattr(ai_job_service, "_DISPATCHER_TASK", None)
    monkeypatch.setattr(ai_job_service, "_SHUTTING_DOWN", False)
    monkeypatch.setattr(ai_job_service, "_reaper_loop", idle_loop)
    monkeypatch.setattr(ai_job_service, "_dispatcher_loop", idle_loop)
    monkeypatch.setattr(ai_job_service, "recover_pending_queues", recover)
    monkeypatch.setattr(ai_job_service, "_mark_worker_jobs_terminating_sync", lambda reason: [])

    async def run():
        await ai_job_service.start_runtime_workers()
        first = (ai_job_service._REAPER_TASK, ai_job_service._DISPATCHER_TASK)
        await ai_job_service.start_runtime_workers()
        second = (ai_job_service._REAPER_TASK, ai_job_service._DISPATCHER_TASK)
        assert first == second
        await ai_job_service.shutdown_runtime_workers()

    asyncio.run(run())
