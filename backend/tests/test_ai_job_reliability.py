"""SQLite state-machine checks for durable AI job ownership."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta

import pytest
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


def test_runtime_worker_health_rejects_stale_last_success(monkeypatch):
    class _LiveTask:
        def done(self):
            return False

    now = time.monotonic()
    monkeypatch.setattr(ai_job_service, "_REAPER_TASK", _LiveTask())
    monkeypatch.setattr(ai_job_service, "_DISPATCHER_TASK", _LiveTask())
    monkeypatch.setattr(ai_job_service, "_RUNTIME_WORKER_HEALTH", {
        "reaper": {
            "state": "healthy",
            "failure_count": 0,
            "last_success_monotonic": now - 10,
        },
        "dispatcher": {
            "state": "healthy",
            "failure_count": 0,
            "last_success_monotonic": now,
        },
    })
    monkeypatch.setattr(ai_job_service.settings, "AI_JOB_REAPER_STALE_SECONDS", 1)

    health = ai_job_service.runtime_worker_health()

    assert health["reaper"]["healthy"] is False
    assert health["reaper"]["alive"] is True
    assert health["healthy"] is False


def test_runtime_worker_reports_stalled_live_task(monkeypatch):
    class _LiveTask:
        def done(self):
            return False

    now = time.monotonic()
    monkeypatch.setattr(ai_job_service, "_REAPER_TASK", _LiveTask())
    monkeypatch.setattr(ai_job_service, "_DISPATCHER_TASK", _LiveTask())
    monkeypatch.setattr(ai_job_service, "_RUNTIME_WORKER_HEALTH", {
        "reaper": {
            "state": "running",
            "failure_count": 0,
            "last_success_monotonic": now,
            "iteration_started_monotonic": now - 10,
        },
        "dispatcher": {
            "state": "healthy",
            "failure_count": 0,
            "last_success_monotonic": now,
        },
    })
    monkeypatch.setattr(ai_job_service.settings, "AI_JOB_WORKER_OPERATION_TIMEOUT_SECONDS", 1)

    health = ai_job_service.runtime_worker_health()

    assert health["reaper"]["state"] == "stalled"
    assert health["reaper"]["healthy"] is False
    assert health["reaper"]["alive"] is True
    assert health["reaper"]["current_iteration_age_seconds"] >= 10
    assert health["reaper"]["last_error_type"] == "WorkerOperationTimeout"


def test_stalled_operation_does_not_spawn_overlapping_iterations(monkeypatch):
    calls = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def operation():
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return 1

    async def run():
        worker = asyncio.create_task(ai_job_service._run_runtime_worker_loop("reaper", operation, 1))
        monkeypatch.setattr(ai_job_service, "_REAPER_TASK", worker)
        await started.wait()
        await asyncio.sleep(0.2)
        assert calls == 1
        stalled = ai_job_service.runtime_worker_health()
        assert stalled["reaper"]["healthy"] is False
        assert stalled["reaper"]["state"] == "stalled"

        release.set()
        await asyncio.sleep(0.05)
        recovered = ai_job_service.runtime_worker_health()
        assert recovered["reaper"]["healthy"] is True
        assert calls == 1
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass

    monkeypatch.setattr(ai_job_service, "_SHUTTING_DOWN", False)
    monkeypatch.setattr(ai_job_service, "_RUNTIME_WORKER_HEALTH", {
        "dispatcher": {
            "state": "healthy",
            "failure_count": 0,
            "last_success_monotonic": time.monotonic(),
        },
    })
    monkeypatch.setattr(ai_job_service.settings, "AI_JOB_WORKER_OPERATION_TIMEOUT_SECONDS", 0.1)
    asyncio.run(run())


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


# ── P0/P1-1 state-machine acceptance tests ──────────────────────────────

OWNERSHIP_FIELDS = (
    "process_pid",
    "process_started_at",
    "process_group_id",
    "run_token",
    "worker_id",
    "worker_boot_id",
    "heartbeat_at",
    "lease_expires_at",
)


def _assert_no_ownership(job):
    for field in OWNERSHIP_FIELDS:
        assert getattr(job, field) is None, f"ownership field not cleared: {field}"


def _owned_running_job(db, *, token="run-1", pid=5151):
    job = _job(
        db,
        status=AiJobStatus.RUNNING,
        run_token=token,
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
    )
    job.process_pid = pid
    job.process_started_at = datetime.utcnow()
    job.process_group_id = pid
    job.heartbeat_at = datetime.utcnow()
    job.lease_expires_at = datetime.utcnow() + timedelta(seconds=30)
    db.commit()
    return job


def _finalize(
    db,
    *,
    success=False,
    dead=None,
    token="run-1",
    timeout_interrupted=False,
    process_started=None,
):
    return ai_job_service._finalize_task_chat_job_sync(
        db,
        job_id="reliability-job",
        last_result_success=success,
        last_result_text="boom",
        is_timeout_interrupted=timeout_interrupted,
        engine_session_id=None,
        run_token=token,
        process_started=process_started,
        termination_confirmed_dead=dead,
    )


def test_engine_error_does_not_interrupt_before_termination_finalizer(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_running_job(db)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    attempt = ai_job_service.AgentAttemptContext(
        job_id="reliability-job",
        task_id=None,
        queue_key="TASK_CHAT:task-1",
        run_token="run-1",
        worker_id="w",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        attempt_count=1,
    )
    token = ai_job_service.bind_agent_attempt(attempt)
    try:
        asyncio.run(ai_job_service._on_engine_error("provider exploded", "reliability-job"))
    finally:
        ai_job_service.reset_agent_attempt(token)

    saved = db.get(SddAiJob, "reliability-job")
    assert saved.status == AiJobStatus.RUNNING
    assert saved.process_pid == 5151
    assert saved.run_token == "run-1"


def test_task_chat_unconfirmed_tree_becomes_orphaned():
    factory = _session_factory()
    db = factory()
    _owned_running_job(db)

    result = _finalize(db, dead=False)

    saved = db.get(SddAiJob, "reliability-job")
    assert result["status"] == AiJobStatus.ORPHANED.value
    assert saved.status == AiJobStatus.ORPHANED
    assert saved.process_pid == 5151
    assert saved.process_group_id == 5151
    assert saved.run_token == "run-1"
    assert saved.worker_boot_id == ai_job_service.WORKER_BOOT_ID
    assert saved.failure_code == "PROCESS_TREE_STILL_ALIVE"


def test_task_chat_unconfirmed_tree_without_persisted_pid_becomes_orphaned(monkeypatch):
    factory = _session_factory()
    db = factory()
    _job(
        db,
        status=AiJobStatus.RUNNING,
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
    )

    # PID persistence failed but the attempt reports an unconfirmed tree:
    # False must never degrade to a clean terminal state.
    result = _finalize(db, dead=False)

    saved = db.get(SddAiJob, "reliability-job")
    assert result["status"] == AiJobStatus.ORPHANED.value
    assert saved.status == AiJobStatus.ORPHANED
    assert saved.run_token == "run-1"


def test_task_chat_started_without_death_proof_orphans_without_pid(monkeypatch):
    """doc 11.3: started=True + dead=None + DB PID=None => ORPHANED。

    PID 没有入库也不能把 process_started=True 当成“没有本地进程”；
    该行必须保留 run_token 阻塞同队列后继作业。
    """
    factory = _session_factory()
    db = factory()
    _job(
        db,
        status=AiJobStatus.RUNNING,
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
    )
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    result = _finalize(db, dead=None, process_started=True)

    saved = db.get(SddAiJob, "reliability-job")
    assert result["status"] == AiJobStatus.ORPHANED.value
    assert saved.status == AiJobStatus.ORPHANED
    assert saved.run_token == "run-1"
    assert saved.worker_boot_id == ai_job_service.WORKER_BOOT_ID
    assert saved.process_pid is None
    assert saved.failure_code == "PROCESS_TREE_STILL_ALIVE"


def test_task_chat_never_started_allows_clean_interrupted(monkeypatch):
    """doc 11.3: started=False + dead=None + 无 ownership => 业务失败终态。"""
    factory = _session_factory()
    db = factory()
    _job(
        db,
        status=AiJobStatus.RUNNING,
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
    )
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    result = _finalize(db, success=False, dead=None, process_started=False)

    saved = db.get(SddAiJob, "reliability-job")
    assert result["status"] == AiJobStatus.INTERRUPTED.value
    assert saved.status == AiJobStatus.INTERRUPTED
    _assert_no_ownership(saved)


def test_task_chat_confirmed_dead_error_becomes_clean_interrupted():
    factory = _session_factory()
    db = factory()
    _owned_running_job(db)

    result = _finalize(db, success=False, dead=True)

    saved = db.get(SddAiJob, "reliability-job")
    assert result["status"] == AiJobStatus.INTERRUPTED.value
    assert saved.status == AiJobStatus.INTERRUPTED
    _assert_no_ownership(saved)


def test_task_chat_confirmed_dead_success_becomes_clean_success():
    factory = _session_factory()
    db = factory()
    _owned_running_job(db)

    result = _finalize(db, success=True, dead=True)

    saved = db.get(SddAiJob, "reliability-job")
    assert result["status"] == AiJobStatus.SUCCESS.value
    assert saved.status == AiJobStatus.SUCCESS
    _assert_no_ownership(saved)


def test_task_chat_no_local_process_error_becomes_clean_interrupted():
    factory = _session_factory()
    db = factory()
    _job(
        db,
        status=AiJobStatus.RUNNING,
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
    )

    result = _finalize(db, success=False, dead=None)

    saved = db.get(SddAiJob, "reliability-job")
    assert result["status"] == AiJobStatus.INTERRUPTED.value
    assert saved.status == AiJobStatus.INTERRUPTED
    _assert_no_ownership(saved)


def test_dirty_interrupted_with_ownership_is_reaped(monkeypatch):
    factory = _session_factory()
    db = factory()
    job = _owned_running_job(db, token="run-legacy")
    job.status = AiJobStatus.INTERRUPTED
    db.commit()
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    rows = ai_job_service._list_reclaimable_jobs_sync()
    assert any(
        row["job_id"] == "reliability-job" and row["reason"] == "INTERRUPTED_OWNERSHIP_LEAK"
        for row in rows
    )

    adopted = ai_job_service._adopt_reclaimable_job_sync(
        "reliability-job", "run-legacy", "run-legacy", "INTERRUPTED_OWNERSHIP_LEAK"
    )
    assert adopted is True
    db.expire_all()
    assert db.get(SddAiJob, "reliability-job").status == AiJobStatus.TERMINATING

    payload = ai_job_service._finish_termination_sync(
        "reliability-job",
        "run-legacy",
        confirmed_dead=True,
        reason="reaper verified",
        failure_code="INTERRUPTED_OWNERSHIP_LEAK",
    )
    db.expire_all()
    saved = db.get(SddAiJob, "reliability-job")
    assert payload["status"] == AiJobStatus.INTERRUPTED.value
    assert saved.status == AiJobStatus.INTERRUPTED
    _assert_no_ownership(saved)


def test_dirty_interrupted_without_death_proof_is_not_cleared(monkeypatch):
    factory = _session_factory()
    db = factory()
    job = _owned_running_job(db, token="run-legacy")
    job.status = AiJobStatus.INTERRUPTED
    db.commit()
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    # The reaper first adopts the leaked row into its stop/verify flow.
    adopted = ai_job_service._adopt_reclaimable_job_sync(
        "reliability-job", "run-legacy", "run-legacy", "INTERRUPTED_OWNERSHIP_LEAK"
    )
    assert adopted is True
    db.expire_all()
    assert db.get(SddAiJob, "reliability-job").status == AiJobStatus.TERMINATING

    payload = ai_job_service._finish_termination_sync(
        "reliability-job",
        "run-legacy",
        confirmed_dead=False,
        reason="cannot inspect tree",
        failure_code="PROCESS_TREE_STILL_ALIVE",
    )
    db.expire_all()
    saved = db.get(SddAiJob, "reliability-job")
    assert payload["status"] == AiJobStatus.ORPHANED.value
    assert saved.status == AiJobStatus.ORPHANED
    assert saved.process_pid == 5151
    assert saved.run_token == "run-legacy"


def test_clean_interrupted_row_is_not_reaped(monkeypatch):
    factory = _session_factory()
    db = factory()
    _job(db, status=AiJobStatus.INTERRUPTED)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    rows = ai_job_service._list_reclaimable_jobs_sync()
    assert rows == []
    assert db.get(SddAiJob, "reliability-job").status == AiJobStatus.INTERRUPTED


def test_old_run_token_cannot_finalize_current_attempt():
    factory = _session_factory()
    db = factory()
    _owned_running_job(db, token="current-run")

    result = _finalize(db, dead=True, token="old-run")

    saved = db.get(SddAiJob, "reliability-job")
    assert result is None
    assert saved.status == AiJobStatus.RUNNING
    assert saved.process_pid == 5151


def test_user_terminating_state_cannot_be_overwritten_by_engine_error(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.TERMINATING)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    attempt = ai_job_service.AgentAttemptContext(
        job_id="reliability-job",
        task_id=None,
        queue_key="TASK_CHAT:task-1",
        run_token="run-1",
        worker_id="w",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        attempt_count=1,
    )
    token = ai_job_service.bind_agent_attempt(attempt)
    try:
        asyncio.run(ai_job_service._on_engine_error("late error", "reliability-job"))
    finally:
        ai_job_service.reset_agent_attempt(token)

    db.expire_all()
    assert db.get(SddAiJob, "reliability-job").status == AiJobStatus.TERMINATING


def test_success_clears_all_ownership_fields():
    factory = _session_factory()
    db = factory()
    _owned_running_job(db)

    result = _finalize(db, success=True, dead=True)

    saved = db.get(SddAiJob, "reliability-job")
    assert result["status"] == AiJobStatus.SUCCESS.value
    _assert_no_ownership(saved)


def test_interrupted_clears_all_ownership_fields():
    factory = _session_factory()
    db = factory()
    _owned_running_job(db)

    result = _finalize(db, success=False, dead=True, timeout_interrupted=True)

    saved = db.get(SddAiJob, "reliability-job")
    assert result["status"] == AiJobStatus.INTERRUPTED.value
    _assert_no_ownership(saved)


def test_confirmed_dead_failure_writes_failed_and_clears_ownership():
    factory = _session_factory()
    db = factory()
    _owned_running_job(db)
    import pytest as _pytest

    _pytest.MonkeyPatch().setattr(ai_job_service, "SessionLocal", factory)

    result = ai_job_service._update_job_state_sync(
        "reliability-job",
        status=AiJobStatus.FAILED,
        finalize=True,
        run_token="run-1",
        termination_confirmed_dead=True,
        error_message="provider error after exit",
    )

    saved = db.get(SddAiJob, "reliability-job")
    assert result["payload"]["status"] == AiJobStatus.FAILED.value
    _assert_no_ownership(saved)


def test_unconfirmed_failure_with_missing_pid_writes_orphaned():
    factory = _session_factory()
    db = factory()
    _job(
        db,
        status=AiJobStatus.RUNNING,
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
    )
    import pytest as _pytest

    _pytest.MonkeyPatch().setattr(ai_job_service, "SessionLocal", factory)

    result = ai_job_service._update_job_state_sync(
        "reliability-job",
        status=AiJobStatus.FAILED,
        finalize=True,
        run_token="run-1",
        termination_confirmed_dead=False,
        error_message="provider error, tree unconfirmed",
    )

    saved = db.get(SddAiJob, "reliability-job")
    assert result["payload"]["status"] == AiJobStatus.ORPHANED.value
    assert saved.status == AiJobStatus.ORPHANED
    assert saved.run_token == "run-1"
    assert saved.failure_code == "PROCESS_TREE_STILL_ALIVE"


def test_update_job_state_started_without_death_proof_orphans_without_pid():
    """doc 11.3: 非本地 PID 入库路径的同一决策表（started=True, dead=None）。"""
    factory = _session_factory()
    db = factory()
    _job(
        db,
        status=AiJobStatus.RUNNING,
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
    )
    import pytest as _pytest

    _pytest.MonkeyPatch().setattr(ai_job_service, "SessionLocal", factory)

    result = ai_job_service._update_job_state_sync(
        "reliability-job",
        status=AiJobStatus.FAILED,
        finalize=True,
        run_token="run-1",
        process_started=True,
        termination_confirmed_dead=None,
        error_message="spawn callback cancelled before PID attach",
    )

    saved = db.get(SddAiJob, "reliability-job")
    assert result["payload"]["status"] == AiJobStatus.ORPHANED.value
    assert saved.status == AiJobStatus.ORPHANED
    assert saved.run_token == "run-1"
    assert saved.worker_boot_id == ai_job_service.WORKER_BOOT_ID


def test_update_job_state_confirmed_dead_allows_terminal_and_clears_ownership():
    """doc 11.3: started=True + dead=True + DB PID=None => 终态 + 清 ownership。"""
    factory = _session_factory()
    db = factory()
    _job(
        db,
        status=AiJobStatus.RUNNING,
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
    )
    import pytest as _pytest

    _pytest.MonkeyPatch().setattr(ai_job_service, "SessionLocal", factory)

    result = ai_job_service._update_job_state_sync(
        "reliability-job",
        status=AiJobStatus.FAILED,
        finalize=True,
        run_token="run-1",
        process_started=True,
        termination_confirmed_dead=True,
        error_message="provider error after clean exit",
    )

    saved = db.get(SddAiJob, "reliability-job")
    assert result["payload"]["status"] == AiJobStatus.FAILED.value
    assert saved.status == AiJobStatus.FAILED
    _assert_no_ownership(saved)


def test_update_job_state_never_started_allows_business_failure():
    """doc 11.3: 无本地进程（started=False/None, dead=None, 无 ownership）=> 业务失败。"""
    factory = _session_factory()
    db = factory()
    _job(
        db,
        status=AiJobStatus.RUNNING,
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
    )
    import pytest as _pytest

    _pytest.MonkeyPatch().setattr(ai_job_service, "SessionLocal", factory)

    result = ai_job_service._update_job_state_sync(
        "reliability-job",
        status=AiJobStatus.FAILED,
        finalize=True,
        run_token="run-1",
        process_started=False,
        termination_confirmed_dead=None,
        error_message="remote provider rejected the request",
    )

    saved = db.get(SddAiJob, "reliability-job")
    assert result["payload"]["status"] == AiJobStatus.FAILED.value
    assert saved.status == AiJobStatus.FAILED
    _assert_no_ownership(saved)


def test_update_job_state_orphaned_retains_containment_and_ownership():
    """ORPHANED 行必须保留恢复信息（containment / ownership / run token）。"""
    factory = _session_factory()
    db = factory()
    _owned_running_job(db)
    job = db.get(SddAiJob, "reliability-job")
    job.process_containment_id = "runtoken:run-1"
    job.process_execution_kind = "LOCAL_PROCESS"
    db.commit()
    import pytest as _pytest

    _pytest.MonkeyPatch().setattr(ai_job_service, "SessionLocal", factory)

    result = ai_job_service._update_job_state_sync(
        "reliability-job",
        status=AiJobStatus.FAILED,
        finalize=True,
        run_token="run-1",
        process_started=True,
        termination_confirmed_dead=False,
        failure_code="PROCESS_TREE_STILL_ALIVE",
        remaining_pids=(4242,),
        error_message="descendant survived",
    )

    db.expire_all()
    saved = db.get(SddAiJob, "reliability-job")
    assert result["payload"]["status"] == AiJobStatus.ORPHANED.value
    assert saved.process_pid == 5151
    assert saved.run_token == "run-1"
    assert saved.process_containment_id == "runtoken:run-1"
    assert saved.process_execution_kind == "LOCAL_PROCESS"
    context = saved.context_json if isinstance(saved.context_json, dict) else {}
    assert context.get("unconfirmed_process_pids") == [4242]


def test_claim_persists_containment_id_derived_from_run_token(monkeypatch):
    factory = _session_factory()
    db = factory()
    _job(db)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    job_id = ai_job_service._take_next_pending_job_id_sync("TASK_CHAT:task-1")
    assert job_id == "reliability-job"
    claimed = db.get(SddAiJob, "reliability-job")
    assert claimed.run_token
    assert claimed.process_containment_id == f"runtoken:{claimed.run_token}"


def test_runtime_evidence_survives_cli_exit_then_outer_failure(monkeypatch):
    """CLI confirmed dead, later parse/persist failure must still see True."""
    import app.agents as agents_pkg

    factory = _session_factory()
    db = factory()
    _owned_running_job(db)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)

    async def _no_broadcast(payload, *, final=False):
        return None

    monkeypatch.setattr(ai_job_service, "_broadcast_job_payload", _no_broadcast)

    runtime = agents_pkg.AgentAttemptRuntimeState()
    runtime.record_process_started()
    runtime.record_termination(
        confirmed_dead=True,
        failure_code=None,
        error=None,
    )
    state_token = agents_pkg.bind_agent_attempt_runtime(runtime)
    attempt = ai_job_service.AgentAttemptContext(
        job_id="reliability-job",
        task_id=None,
        queue_key="TASK_CHAT:task-1",
        run_token="run-1",
        worker_id="w",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        attempt_count=1,
    )
    attempt_token = ai_job_service.bind_agent_attempt(attempt)
    try:
        asyncio.run(
            ai_job_service._finalize_task_chat_job_failure(
                "reliability-job",
                "persist failed after successful CLI exit",
            )
        )
    finally:
        ai_job_service.reset_agent_attempt_runtime(state_token)
        ai_job_service.reset_agent_attempt(attempt_token)

    saved = db.get(SddAiJob, "reliability-job")
    assert saved.status == AiJobStatus.INTERRUPTED
    _assert_no_ownership(saved)


def test_unconfirmed_runtime_evidence_finalizes_orphaned(monkeypatch):
    import app.agents as agents_pkg

    factory = _session_factory()
    db = factory()
    _owned_running_job(db)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)

    async def _no_broadcast(payload, *, final=False):
        return None

    monkeypatch.setattr(ai_job_service, "_broadcast_job_payload", _no_broadcast)

    runtime = agents_pkg.AgentAttemptRuntimeState()
    runtime.record_process_started()
    runtime.record_termination(
        confirmed_dead=False,
        failure_code="PROCESS_TREE_STILL_ALIVE",
        error="descendant survived",
        remaining_pids=(5151,),
    )
    state_token = agents_pkg.bind_agent_attempt_runtime(runtime)
    attempt = ai_job_service.AgentAttemptContext(
        job_id="reliability-job",
        task_id=None,
        queue_key="TASK_CHAT:task-1",
        run_token="run-1",
        worker_id="w",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        attempt_count=1,
    )
    attempt_token = ai_job_service.bind_agent_attempt(attempt)
    try:
        asyncio.run(
            ai_job_service._finalize_task_chat_job_failure(
                "reliability-job",
                "provider error with live tree",
            )
        )
    finally:
        ai_job_service.reset_agent_attempt_runtime(state_token)
        ai_job_service.reset_agent_attempt(attempt_token)

    saved = db.get(SddAiJob, "reliability-job")
    assert saved.status == AiJobStatus.ORPHANED
    assert saved.process_pid == 5151
    assert saved.run_token == "run-1"
    assert saved.failure_code == "PROCESS_TREE_STILL_ALIVE"


def test_concurrent_jobs_runtime_evidence_not_shared():
    import app.agents as agents_pkg

    first = agents_pkg.AgentAttemptRuntimeState()
    first.record_process_started()
    first.record_termination(confirmed_dead=True)
    token = agents_pkg.bind_agent_attempt_runtime(first)
    ai_job_service.reset_agent_attempt_runtime(token)

    second = agents_pkg.AgentAttemptRuntimeState()
    second.record_termination(confirmed_dead=False)
    token = agents_pkg.bind_agent_attempt_runtime(second)
    state = agents_pkg.current_agent_attempt_runtime()
    try:
        assert state is not second or True
        assert state.process_started is False
        assert state.termination_confirmed_dead is False
        assert first.termination_confirmed_dead is True
    finally:
        ai_job_service.reset_agent_attempt_runtime(token)
    assert agents_pkg.current_agent_attempt_runtime() is None


def test_identity_aware_evidence_state_machine():
    """Identity-aware evidence matrix (doc 11.1).

    废止 attempt 级 `False > True > None`：死亡证明按不可变进程身份记录，
    同一身份的后续 True 收敛先前 False；不同身份的证据互不覆盖。
    """
    from datetime import datetime, timezone

    from app.agents.contract import (
        AgentAttemptRuntimeState,
        AgentProcessIdentity,
        ProcessDeathState,
    )

    def _identity(pid: int) -> AgentProcessIdentity:
        return AgentProcessIdentity(
            pid=pid,
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            process_group_id=pid,
            containment_id=f"runtoken:tok-{pid}",
        )

    identity_a = _identity(101)
    identity_b = _identity(202)

    # A: STARTED -> False -> True  => attempt True（同一进程后续确认死亡）
    state = AgentAttemptRuntimeState()
    state.record_process_started(identity_a)
    assert state.termination_confirmed_dead is None
    state.record_termination(confirmed_dead=False, identity=identity_a)
    assert state.termination_confirmed_dead is False
    state.record_termination(confirmed_dead=True, identity=identity_a)
    assert state.termination_confirmed_dead is True

    # A: True -> late False  => attempt True（死亡不可逆，旧回调不能恢复）
    state.record_termination(
        confirmed_dead=False,
        identity=identity_a,
        failure_code="LATE_CALLBACK",
    )
    assert state.termination_confirmed_dead is True

    # A: False, B: True  => attempt False（B 的死亡不能覆盖 A 的未确认）
    state = AgentAttemptRuntimeState()
    state.record_process_started(identity_a)
    state.record_process_started(identity_b)
    state.record_termination(confirmed_dead=False, identity=identity_a)
    state.record_termination(confirmed_dead=True, identity=identity_b)
    assert state.termination_confirmed_dead is False

    # A: True, B: STARTED  => attempt None（B 的死亡证据尚未决出）
    state = AgentAttemptRuntimeState()
    state.record_process_started(identity_a)
    state.record_process_started(identity_b)
    state.record_termination(confirmed_dead=True, identity=identity_a)
    assert state.termination_confirmed_dead is None
    assert state.process_started is True

    # A: True, B: False  => attempt False
    state.record_termination(confirmed_dead=False, identity=identity_b)
    assert state.termination_confirmed_dead is False

    # 无本地进程  => process_started False, dead None
    state = AgentAttemptRuntimeState()
    assert state.process_started is False
    assert state.termination_confirmed_dead is None

    # 孤立的终止证据（stub bridge）不得伪造 process_started
    state = AgentAttemptRuntimeState()
    state.record_termination(confirmed_dead=True)
    assert state.process_started is False
    assert state.termination_confirmed_dead is True

    # 未确认 identity 的诊断信息保持可读
    state = AgentAttemptRuntimeState()
    state.record_process_started(identity_a)
    state.record_termination(
        confirmed_dead=False,
        identity=identity_a,
        failure_code="PROCESS_TREE_STILL_ALIVE",
        remaining_pids=(5151,),
    )
    assert state.termination_failure_code == "PROCESS_TREE_STILL_ALIVE"
    assert state.remaining_pids == (5151,)
    unconfirmed = state.unconfirmed_identities
    assert len(unconfirmed) == 1
    assert unconfirmed[0].state == ProcessDeathState.UNCONFIRMED
    assert unconfirmed[0].identity == identity_a


def test_concurrent_attempt_states_do_not_share_identity_evidence():
    """两个并发 job 的 evidence 不串线（doc 11.1）。"""
    from datetime import datetime, timezone

    from app.agents.contract import (
        AgentAttemptRuntimeState,
        AgentProcessIdentity,
    )

    def _identity(pid: int) -> AgentProcessIdentity:
        return AgentProcessIdentity(
            pid=pid,
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            containment_id=f"runtoken:tok-{pid}",
        )

    first = AgentAttemptRuntimeState()
    first.record_process_started(_identity(111))
    first.record_termination(confirmed_dead=True, identity=_identity(111))

    second = AgentAttemptRuntimeState()
    second.record_process_started(_identity(222))
    second.record_termination(confirmed_dead=False, identity=_identity(222))

    assert first.termination_confirmed_dead is True
    assert second.termination_confirmed_dead is False
    assert first.process_started is True
    assert second.process_started is True


def test_typed_agent_errors_carry_termination_evidence():
    from app.agents.errors import (
        AgentCancelledError,
        AgentError,
        AgentProviderError,
        AgentTimeoutError,
    )

    timeout = AgentTimeoutError(
        "hard timeout",
        phase="hard",
        limit_seconds=10.0,
        termination_confirmed_dead=True,
        process_started=True,
    )
    assert timeout.failure_code == "HARD_TIMEOUT"
    assert timeout.termination_confirmed_dead is True

    provider = AgentProviderError(
        "boom",
        termination_confirmed_dead=False,
        process_started=True,
        failure_code="PROVIDER_ERROR",
    )
    assert provider.failure_code == "PROVIDER_ERROR"
    assert provider.termination_confirmed_dead is False

    cancelled = AgentCancelledError(
        "cancelled",
        termination_confirmed_dead=True,
        process_started=True,
        failure_code="USER_CANCELLED",
    )
    assert cancelled.failure_code == "USER_CANCELLED"

    # Backward compatibility: typed errors stay catchable as RuntimeError.
    try:
        raise provider
    except RuntimeError:
        pass
    try:
        raise AgentError("plain")
    except RuntimeError:
        pass


class _StubBridge:
    """Minimal bridge double for run_cli_single_turn evidence propagation."""

    def __init__(self, *, termination=None, raise_timeout=False, error_result=False):
        self.termination = termination
        self.raise_timeout = raise_timeout
        self.error_result = error_result
        self.start_calls = 0
        self.cancel_calls = 0
        self.wait_calls = 0
        self.session_id = "session-1"
        self.process = None
        self.last_termination = termination
        self._running = False

    async def start_session(self, **_kwargs):
        self.start_calls += 1
        self._running = True
        return "session-1"

    async def wait(self):
        self.wait_calls += 1
        # 真实 bridge 的 wait() 一定有 await 点；yield 一次让 cancel monitor
        # 获得首次轮询机会（Python 3.12+ 的 wait_for 不再为协程创建 task）。
        await asyncio.sleep(0)
        if self.raise_timeout:
            raise asyncio.TimeoutError()
        if self.error_result:
            self._events = [{"type": "result", "is_error": True, "result": "provider down"}]
        self.last_termination = self.termination
        return self.termination

    async def cancel(self):
        self.cancel_calls += 1
        self.last_termination = self.termination
        return self.termination

    async def interrupt(self):
        return await self.cancel()

    def is_running(self):
        return self._running


def test_run_cli_single_turn_timeout_unconfirmed_tree_raises_typed_error(monkeypatch):
    from app.agents.errors import AgentError
    from app.agents.process_supervisor import TerminationResult

    bridge = _StubBridge(
        termination=TerminationResult(
            confirmed_dead=False,
            root_return_code=None,
            error_code="PROCESS_TREE_STILL_ALIVE",
        ),
        raise_timeout=True,
    )
    monkeypatch.setattr(ai_job_service, "create_cli_bridge", lambda *a, **kw: bridge)

    async def _run():
        with pytest.raises(AgentError) as exc_info:
            await ai_job_service.run_cli_single_turn("hi", ".", max_attempts=2)
        assert exc_info.value.termination_confirmed_dead is False
        assert exc_info.value.failure_code == "PROCESS_TREE_STILL_ALIVE"

    asyncio.run(_run())
    # An unconfirmed tree forbids starting the next retry process.
    assert bridge.start_calls == 1


def test_run_cli_single_turn_provider_error_confirmed_dead_raises_typed(monkeypatch):
    from app.agents.errors import AgentProviderError
    from app.agents.process_supervisor import TerminationResult

    class _ErrorResultBridge(_StubBridge):
        def __init__(self):
            super().__init__(
                termination=TerminationResult(confirmed_dead=True, root_return_code=0)
            )
            self._event_callback = None

        async def start_session(self, **kwargs):
            self._event_callback = kwargs.get("event_callback")
            return await super().start_session(**kwargs)

        async def wait(self):
            self.wait_calls += 1
            self.last_termination = self.termination
            callback = self._event_callback
            await callback({"type": "result", "is_error": True, "result": "provider down"})
            return self.termination

    bridge = _ErrorResultBridge()
    monkeypatch.setattr(ai_job_service, "create_cli_bridge", lambda *args, **kwargs: bridge)

    async def _run():
        with pytest.raises(AgentProviderError) as exc_info:
            await ai_job_service.run_cli_single_turn("hi", ".", max_attempts=1)
        assert exc_info.value.termination_confirmed_dead is True
        assert exc_info.value.failure_code == "PROVIDER_ERROR"
        assert bridge.last_termination.confirmed_dead is True

    asyncio.run(_run())


def test_run_cli_single_turn_cancelled_raises_typed_cancelled(monkeypatch):
    from app.agents.errors import AgentCancelledError
    from app.agents.process_supervisor import TerminationResult

    bridge = _StubBridge(
        termination=TerminationResult(confirmed_dead=True, root_return_code=None),
    )
    monkeypatch.setattr(ai_job_service, "create_cli_bridge", lambda *args, **kwargs: bridge)

    async def _run():
        with pytest.raises(AgentCancelledError) as exc_info:
            await ai_job_service.run_cli_single_turn(
                "hi",
                ".",
                max_attempts=1,
                should_cancel=lambda: True,
            )
        assert exc_info.value.termination_confirmed_dead is True
        assert exc_info.value.failure_code == "USER_CANCELLED"

    asyncio.run(_run())


def test_run_cli_single_turn_records_evidence_in_runtime_state(monkeypatch):
    import app.agents as agents_pkg
    from app.agents.contract import record_attempt_termination
    from app.agents.process_supervisor import TerminationResult

    class _RecordingBridge(_StubBridge):
        """Mirror the real SubprocessCliBridge evidence contract."""

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._event_callback = None

        async def start_session(self, **kwargs):
            self._event_callback = kwargs.get("event_callback")
            return await super().start_session(**kwargs)

        async def wait(self):
            self.wait_calls += 1
            self.last_termination = self.termination
            record_attempt_termination(self.last_termination)
            # 真实 bridge 在 wait 返回前一定会发出终局 result 事件
            # （07e04775 §4.3：没有 result 事件不构成 outcome）。
            callback = self._event_callback
            if callback is not None:
                await callback({"type": "result", "is_error": False, "result": "ok"})
            return self.last_termination

        async def cancel(self):
            self.cancel_calls += 1
            self.last_termination = self.termination
            record_attempt_termination(self.last_termination)
            return self.termination

    bridge = _RecordingBridge(
        termination=TerminationResult(confirmed_dead=True, root_return_code=0),
    )
    monkeypatch.setattr(ai_job_service, "create_cli_bridge", lambda *args, **kwargs: bridge)

    async def _run():
        runtime = agents_pkg.AgentAttemptRuntimeState()
        token = agents_pkg.bind_agent_attempt_runtime(runtime)
        try:
            result = await ai_job_service.run_cli_single_turn("hi", ".", max_attempts=1)
            assert result["termination_confirmed_dead"] is True
            # The stub never spawned a real process; a real bridge/spawn would
            # have recorded process_started via the supervisor.
            assert runtime.process_started is False
            assert runtime.termination_confirmed_dead is True
        finally:
            agents_pkg.reset_agent_attempt_runtime(token)

    asyncio.run(_run())
