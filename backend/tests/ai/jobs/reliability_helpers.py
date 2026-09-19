"""reliability 系列拆分模块共享的 job 构造器（原 test_ai_job_reliability.py）。

与 :mod:`tests.ai.jobs.ai_job_test_utils` 中的 convergence 版构造器语义
不同：这里默认 ``PENDING`` + 过期 lease、不设置 execution_kind、job id 固定
为 ``reliability-job``，忠实保留原文件行为，故独立成模块。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services.jobs import registry as ai_registry
from app.domains.ai.services.jobs.executors import task_chat as ai_task_chat


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


def _owned_job(db, *, status=AiJobStatus.TERMINATING, token="run-1"):
    job = _job(
        db,
        status=status,
        run_token=token,
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
    )
    job.process_pid = 4242
    job.process_started_at = datetime.utcnow()
    job.process_group_id = 4242
    db.commit()
    return job


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
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
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
    return ai_task_chat._finalize_task_chat_job_sync(
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
