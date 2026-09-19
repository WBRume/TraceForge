"""Durable AI job ownership 状态机检查（原 test_ai_job_reliability.py）。

覆盖：claim 竞争、reaper 收敛 legacy RUNNING、task 范围恢复、
cancel 不误报 finished、迟到终止不可覆盖终态、TERMINATING 防降级。
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from tests.ai.jobs.reliability_helpers import _job, _owned_job, _session_factory
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.ai.services.jobs import attempts as ai_attempts
from app.domains.ai.services.jobs import fencing as ai_fencing
from app.domains.ai.services.jobs import reaper as ai_reaper
from app.domains.ai.services.jobs import registry as ai_registry
from app.domains.ai.services.jobs import store as ai_store
from tests.ai.jobs.ai_job_test_utils import patch_ai_job_db


def test_two_claims_only_one_gets_run_token(monkeypatch):
    factory = _session_factory()
    db = factory()
    _job(db)
    patch_ai_job_db(monkeypatch, factory)

    first = ai_store.take_next_pending_job_id_sync("TASK_CHAT:task-1")
    second = ai_store.take_next_pending_job_id_sync("TASK_CHAT:task-1")

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
    patch_ai_job_db(monkeypatch, factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)

    asyncio.run(ai_reaper.reap_stale_jobs())

    recovered = db.get(SddAiJob, "reliability-job")
    assert recovered.status == AiJobStatus.ORPHANED
    assert recovered.failure_code == "WORKER_RESTART"


def test_task_scoped_recovery_does_not_select_other_tasks(monkeypatch):
    factory = _session_factory()
    with factory() as db:
        job = _job(db, status=AiJobStatus.RUNNING, run_token="old-token")
        job.task_id = "target-task"
        db.commit()
    patch_ai_job_db(monkeypatch, factory)
    assert ai_reaper.list_reclaimable_jobs_sync("other-task") == []
    rows = ai_reaper.list_reclaimable_jobs_sync("target-task")
    assert [row["job_id"] for row in rows] == ["reliability-job"]


def test_cancel_running_job_is_not_reported_as_finished(monkeypatch):
    factory = _session_factory()
    db = factory()
    _job(
        db,
        status=AiJobStatus.RUNNING,
        run_token="run-1",
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
    )
    result = ai_attempts.cancel_job(db, workspace_id="ws-1", job_id="reliability-job")

    assert result is not None
    assert result.status == AiJobStatus.TERMINATING
    assert result.finished_at is None


def test_late_termination_cannot_overwrite_success(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.SUCCESS)
    patch_ai_job_db(monkeypatch, factory)

    result = ai_attempts.finish_termination_sync(
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
    patch_ai_job_db(monkeypatch, factory)

    result = ai_attempts.finish_termination_sync(
        "reliability-job",
        "run-1",
        confirmed_dead=True,
        reason="late callback",
        failure_code="LATE_CALLBACK",
    )

    assert result is None
    assert db.get(SddAiJob, "reliability-job").status == AiJobStatus.CANCELLED


def test_terminating_job_cannot_be_downgraded_by_engine_error(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.TERMINATING)
    patch_ai_job_db(monkeypatch, factory)

    result = ai_fencing.update_job_state_sync(
        "reliability-job",
        status=AiJobStatus.FAILED,
        finalize=True,
        run_token="run-1",
        termination_confirmed_dead=True,
        error_message="late engine error",
    )

    assert result["broadcast"] is False
    assert db.get(SddAiJob, "reliability-job").status == AiJobStatus.TERMINATING
