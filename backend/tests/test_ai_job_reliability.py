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
