"""Durable AI job ownership 状态机检查（原 test_ai_job_reliability.py）。

覆盖：success/INTERRUPTED/ORPHANED 的 ownership 保留与清空语义、
旧 token finalize 拦截、用户 TERMINATING 状态防引擎错误覆盖。
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from tests.ai.jobs.reliability_helpers import (
    _assert_no_ownership,
    _finalize,
    _job,
    _owned_job,
    _owned_running_job,
    _session_factory,
)
from app.agents import bind_agent_attempt, reset_agent_attempt
from app.agents.contract import AgentAttemptContext
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.ai.services.jobs import attempts as ai_attempts
from app.domains.ai.services.jobs import fencing as ai_fencing
from app.domains.ai.services.jobs import registry as ai_registry
from app.domains.ai.services.jobs import reaper as ai_reaper
from app.domains.ai.services.jobs.executors import task_chat as ai_task_chat
from tests.ai.jobs.ai_job_test_utils import patch_ai_job_db


def test_task_chat_success_clears_active_process_ownership(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.RUNNING)
    patch_ai_job_db(monkeypatch, factory)

    result = ai_fencing.update_job_state_sync(
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
    patch_ai_job_db(monkeypatch, factory)

    orphaned = ai_attempts.finish_termination_sync(
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

    interrupted = ai_attempts.finish_termination_sync(
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
    patch_ai_job_db(monkeypatch, factory)

    result = ai_attempts.finish_termination_sync(
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
    patch_ai_job_db(monkeypatch, factory)

    attempt = AgentAttemptContext(
        job_id="reliability-job",
        task_id=None,
        queue_key="TASK_CHAT:task-1",
        run_token="run-1",
        worker_id="w",
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
        attempt_count=1,
    )
    token = bind_agent_attempt(attempt)
    try:
        asyncio.run(ai_task_chat.on_engine_error("late error", "reliability-job"))
    finally:
        reset_agent_attempt(token)

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

    patch_ai_job_db(_pytest.MonkeyPatch(), factory)

    result = ai_fencing.update_job_state_sync(
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
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
    )
    import pytest as _pytest

    patch_ai_job_db(_pytest.MonkeyPatch(), factory)

    result = ai_fencing.update_job_state_sync(
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
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
    )
    import pytest as _pytest

    patch_ai_job_db(_pytest.MonkeyPatch(), factory)

    result = ai_fencing.update_job_state_sync(
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
    assert saved.worker_boot_id == ai_registry.WORKER_BOOT_ID


def test_update_job_state_confirmed_dead_allows_terminal_and_clears_ownership():
    """doc 11.3: started=True + dead=True + DB PID=None => 终态 + 清 ownership。"""
    factory = _session_factory()
    db = factory()
    _job(
        db,
        status=AiJobStatus.RUNNING,
        run_token="run-1",
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
    )
    import pytest as _pytest

    patch_ai_job_db(_pytest.MonkeyPatch(), factory)

    result = ai_fencing.update_job_state_sync(
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
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
    )
    import pytest as _pytest

    patch_ai_job_db(_pytest.MonkeyPatch(), factory)

    result = ai_fencing.update_job_state_sync(
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
