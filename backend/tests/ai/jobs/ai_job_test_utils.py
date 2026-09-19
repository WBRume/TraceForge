"""AI 作业（jobs 子包）测试工具。

旧 ``ai_job_service`` 单体测试通过「patch 模块级 SessionLocal / 广播函数 /
调度函数」控制副作用；拆包后这些名字分散在多个模块。这里提供等价的
聚合 patch 帮助函数，以及原 test_ai_job_convergence.py 拆分后共享的
job / identity / attempt 构造器（保持原名与语义不变）。
"""

from __future__ import annotations

import importlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.domains.task.models.task  # noqa: F401  补全 ORM mapper / FK 注册
from app.agents.contract import (
    EXECUTION_KIND_LOCAL_PROCESS,
    AgentAttemptContext,
    AgentProcessIdentity,
)
from app.database import Base
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services import ai_job_convergence_service as convergence
from app.domains.ai.services.ai_job_convergence_service import (
    AttemptConvergenceRequest,
    ConvergenceIntent,
)
from app.domains.ai.services.jobs import registry as ai_registry

# jobs 子包中直接导入 SessionLocal 的模块（随重构演进维护）。
AI_JOB_DB_MODULES = (
    "app.domains.ai.services.jobs.store",
    "app.domains.ai.services.jobs.fencing",
    "app.domains.ai.services.jobs.attempts",
    "app.domains.ai.services.jobs.publishing",
    "app.domains.ai.services.jobs.reaper",
    "app.domains.ai.services.jobs.queue_runner",
    "app.domains.ai.services.jobs.executors",
    "app.domains.ai.services.jobs.executors.task_chat",
)


def _db_modules() -> Iterator[Any]:
    for target in AI_JOB_DB_MODULES:
        module = importlib.import_module(target)
        if hasattr(module, "SessionLocal"):
            yield module


def patch_ai_job_db(monkeypatch, factory) -> None:
    """monkeypatch 风格：把 jobs 子包所有模块的 SessionLocal 换成测试工厂。

    注意：不改动 ``app.database.SessionLocal``——``run_db_txn`` 的惰性导入
    语义与旧单体外洋试图保持一致，需要时由测试显式 patch。
    """
    for module in _db_modules():
        monkeypatch.setattr(module, "SessionLocal", factory)


@contextmanager
def patched_ai_job_db(factory):
    """mock 风格上下文：等价于 :func:`patch_ai_job_db`。"""
    import unittest.mock
    from contextlib import ExitStack

    with ExitStack() as stack:
        for module in _db_modules():
            stack.enter_context(unittest.mock.patch.object(module, "SessionLocal", factory))
        yield


# ── 共享构造器（原 test_ai_job_convergence.py，拆分后各模块共用）──────────


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _identity(pid: int) -> AgentProcessIdentity:
    return AgentProcessIdentity(
        pid=pid,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        process_group_id=pid,
        containment_id=f"runtoken:tok-{pid}",
    )


def _job(
    db,
    *,
    status=AiJobStatus.RUNNING,
    run_token=None,
    worker_boot_id=None,
    execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
    pid=None,
    cancel_requested=False,
):
    job = SddAiJob(
        id="convergence-job",
        workspace_id="ws-1",
        channel=AiJobChannel.TASK_CHAT,
        queue_key="TASK_CHAT:task-1",
        status=status,
        creator_id="user-1",
        run_token=run_token,
        worker_boot_id=worker_boot_id,
        process_execution_kind=execution_kind,
        task_id="task-1",
        process_pid=pid,
        process_group_id=pid,
        cancel_requested_at=datetime.utcnow() if cancel_requested else None,
        lease_expires_at=(
            datetime.utcnow() + timedelta(seconds=30)
            if status == AiJobStatus.RUNNING
            else None
        ),
    )
    db.add(job)
    db.commit()
    return job


def _owned_job(db, *, status=AiJobStatus.RUNNING, token="run-1", kind=EXECUTION_KIND_LOCAL_PROCESS, pid=5151, cancel_requested=False):
    return _job(
        db,
        status=status,
        run_token=token,
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
        execution_kind=kind,
        pid=pid,
        cancel_requested=cancel_requested,
    )


def _make_attempt(*, token="run-1", kind=EXECUTION_KIND_LOCAL_PROCESS):
    return AgentAttemptContext(
        job_id="convergence-job",
        task_id="task-1",
        queue_key="TASK_CHAT:task-1",
        run_token=token,
        worker_id="w",
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
        attempt_count=1,
        execution_kind=kind,
    )


def _terminate_request(
    *,
    dead=None,
    kind=EXECUTION_KIND_LOCAL_PROCESS,
    intent=ConvergenceIntent.TERMINATION_FINALIZE,
    started=None,
    remote_ack=None,
):
    evidence = convergence.AttemptFinalizerEvidence(
        execution_kind=kind,
        process_started=bool(started) if started is not None else False,
        termination_confirmed_dead=dead,
        remote_stop_acknowledged=remote_ack,
        failure_code=None,
        error_message=None,
        remaining_pids=(),
        source="stop_result",
    )
    return AttemptConvergenceRequest(
        job_id="convergence-job",
        run_token="run-1",
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
        requested_status=None,
        reason="USER_CANCEL",
        evidence=evidence,
        intent=intent,
        reap_bookkeeping=True,
    )


async def _no_broadcast(payload, *args, **kwargs):
    return None
