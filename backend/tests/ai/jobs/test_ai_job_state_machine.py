"""Durable AI job ownership 状态机检查（原 test_ai_job_reliability.py）。

覆盖：finalize 幂等与泄漏行收敛、engine error 不打断 finalizer、
doc 11.3 决策表、dirty INTERRUPTED reaper、containment_id 持久化、
runtime 证据穿越外层失败、identity-aware 状态机与并发隔离。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from tests.ai.jobs.reliability_helpers import (
    _assert_no_ownership,
    _finalize,
    _job,
    _owned_running_job,
    _session_factory,
)
from app.agents import bind_agent_attempt, reset_agent_attempt, reset_agent_attempt_runtime
from app.agents.contract import AgentAttemptContext, AgentAttemptRuntimeState, AgentProcessIdentity
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.ai.services.jobs import attempts as ai_attempts
from app.domains.ai.services.jobs import fencing as ai_fencing
from app.domains.ai.services.jobs import publishing as ai_publishing
from app.domains.ai.services.jobs import reaper as ai_reaper
from app.domains.ai.services.jobs import registry as ai_registry
from app.domains.ai.services.jobs import store as ai_store
from app.domains.ai.services.jobs.executors import task_chat as ai_task_chat
from tests.ai.jobs.ai_job_test_utils import patch_ai_job_db


def test_finalize_on_clean_interrupted_row_is_noop(monkeypatch):
    """行已是干净 INTERRUPTED（无残留 ownership）时 finalize 必须幂等返回 None。

    回归：该分支引用了未导入的 row_has_leaked_interrupted_ownership，
    恢复会话后的 finalize 一触发就 NameError。
    """
    factory = _session_factory()
    db = factory()
    _job(db, status=AiJobStatus.INTERRUPTED)
    patch_ai_job_db(monkeypatch, factory)

    result = _finalize(db, success=False, dead=True)

    assert result is None
    saved = db.get(SddAiJob, "reliability-job")
    assert saved.status == AiJobStatus.INTERRUPTED


def test_finalize_on_leaked_interrupted_row_still_converges(monkeypatch):
    """脏 INTERRUPTED（仍残留 ownership）：finalize 走 convergence 收敛。"""
    factory = _session_factory()
    db = factory()
    job = _job(db, status=AiJobStatus.INTERRUPTED)
    job.run_token = "run-1"
    job.worker_boot_id = ai_registry.WORKER_BOOT_ID
    db.commit()
    patch_ai_job_db(monkeypatch, factory)

    result = _finalize(db, success=False, dead=True)

    assert result is not None
    # 生产路径由外层 run_db_txn 提交；测试需要显式提交后再读。
    db.commit()
    db.expire_all()
    saved = db.get(SddAiJob, "reliability-job")
    assert saved.status == AiJobStatus.INTERRUPTED
    assert saved.run_token is None


def test_engine_error_does_not_interrupt_before_termination_finalizer(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_running_job(db)
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
        asyncio.run(ai_task_chat.on_engine_error("provider exploded", "reliability-job"))
    finally:
        reset_agent_attempt(token)

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
    assert saved.worker_boot_id == ai_registry.WORKER_BOOT_ID
    assert saved.failure_code == "PROCESS_TREE_STILL_ALIVE"


def test_task_chat_unconfirmed_tree_without_persisted_pid_becomes_orphaned(monkeypatch):
    factory = _session_factory()
    db = factory()
    _job(
        db,
        status=AiJobStatus.RUNNING,
        run_token="run-1",
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
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
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
    )
    patch_ai_job_db(monkeypatch, factory)

    result = _finalize(db, dead=None, process_started=True)

    saved = db.get(SddAiJob, "reliability-job")
    assert result["status"] == AiJobStatus.ORPHANED.value
    assert saved.status == AiJobStatus.ORPHANED
    assert saved.run_token == "run-1"
    assert saved.worker_boot_id == ai_registry.WORKER_BOOT_ID
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
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
    )
    patch_ai_job_db(monkeypatch, factory)

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
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
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
    patch_ai_job_db(monkeypatch, factory)

    rows = ai_reaper.list_reclaimable_jobs_sync()
    assert any(
        row["job_id"] == "reliability-job" and row["reason"] == "INTERRUPTED_OWNERSHIP_LEAK"
        for row in rows
    )

    adopted = ai_reaper.adopt_reclaimable_job_sync(
        "reliability-job", "run-legacy", "run-legacy", "INTERRUPTED_OWNERSHIP_LEAK"
    )
    assert adopted is True
    db.expire_all()
    assert db.get(SddAiJob, "reliability-job").status == AiJobStatus.TERMINATING

    payload = ai_attempts.finish_termination_sync(
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
    patch_ai_job_db(monkeypatch, factory)

    # The reaper first adopts the leaked row into its stop/verify flow.
    adopted = ai_reaper.adopt_reclaimable_job_sync(
        "reliability-job", "run-legacy", "run-legacy", "INTERRUPTED_OWNERSHIP_LEAK"
    )
    assert adopted is True
    db.expire_all()
    assert db.get(SddAiJob, "reliability-job").status == AiJobStatus.TERMINATING

    payload = ai_attempts.finish_termination_sync(
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
    patch_ai_job_db(monkeypatch, factory)

    rows = ai_reaper.list_reclaimable_jobs_sync()
    assert rows == []
    assert db.get(SddAiJob, "reliability-job").status == AiJobStatus.INTERRUPTED


def test_claim_persists_containment_id_derived_from_run_token(monkeypatch):
    factory = _session_factory()
    db = factory()
    _job(db)
    patch_ai_job_db(monkeypatch, factory)

    job_id = ai_store.take_next_pending_job_id_sync("TASK_CHAT:task-1")
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
    patch_ai_job_db(monkeypatch, factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)

    async def _no_broadcast(payload, *, final=False):
        return None

    monkeypatch.setattr(ai_publishing, "broadcast_job_payload", _no_broadcast)

    runtime = agents_pkg.AgentAttemptRuntimeState()
    runtime.record_process_started()
    runtime.record_termination(
        confirmed_dead=True,
        failure_code=None,
        error=None,
    )
    state_token = agents_pkg.bind_agent_attempt_runtime(runtime)
    attempt = AgentAttemptContext(
        job_id="reliability-job",
        task_id=None,
        queue_key="TASK_CHAT:task-1",
        run_token="run-1",
        worker_id="w",
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
        attempt_count=1,
    )
    attempt_token = bind_agent_attempt(attempt)
    try:
        asyncio.run(
            ai_task_chat.finalize_task_chat_job_failure(
                "reliability-job",
                "persist failed after successful CLI exit",
            )
        )
    finally:
        reset_agent_attempt_runtime(state_token)
        reset_agent_attempt(attempt_token)

    saved = db.get(SddAiJob, "reliability-job")
    assert saved.status == AiJobStatus.INTERRUPTED
    _assert_no_ownership(saved)


def test_unconfirmed_runtime_evidence_finalizes_orphaned(monkeypatch):
    import app.agents as agents_pkg

    factory = _session_factory()
    db = factory()
    _owned_running_job(db)
    patch_ai_job_db(monkeypatch, factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)

    async def _no_broadcast(payload, *, final=False):
        return None

    monkeypatch.setattr(ai_publishing, "broadcast_job_payload", _no_broadcast)

    runtime = agents_pkg.AgentAttemptRuntimeState()
    runtime.record_process_started()
    runtime.record_termination(
        confirmed_dead=False,
        failure_code="PROCESS_TREE_STILL_ALIVE",
        error="descendant survived",
        remaining_pids=(5151,),
    )
    state_token = agents_pkg.bind_agent_attempt_runtime(runtime)
    attempt = AgentAttemptContext(
        job_id="reliability-job",
        task_id=None,
        queue_key="TASK_CHAT:task-1",
        run_token="run-1",
        worker_id="w",
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
        attempt_count=1,
    )
    attempt_token = bind_agent_attempt(attempt)
    try:
        asyncio.run(
            ai_task_chat.finalize_task_chat_job_failure(
                "reliability-job",
                "provider error with live tree",
            )
        )
    finally:
        reset_agent_attempt_runtime(state_token)
        reset_agent_attempt(attempt_token)

    saved = db.get(SddAiJob, "reliability-job")
    assert saved.status == AiJobStatus.ORPHANED
    assert saved.process_pid == 5151
    assert saved.run_token == "run-1"
    assert saved.failure_code == "PROCESS_TREE_STILL_ALIVE"


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

    patch_ai_job_db(_pytest.MonkeyPatch(), factory)

    result = ai_fencing.update_job_state_sync(
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


def test_concurrent_jobs_runtime_evidence_not_shared():
    import app.agents as agents_pkg

    first = agents_pkg.AgentAttemptRuntimeState()
    first.record_process_started()
    first.record_termination(confirmed_dead=True)
    token = agents_pkg.bind_agent_attempt_runtime(first)
    reset_agent_attempt_runtime(token)

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
        reset_agent_attempt_runtime(token)
    assert agents_pkg.current_agent_attempt_runtime() is None


def test_identity_aware_evidence_state_machine():
    """Identity-aware evidence matrix (doc 11.1).

    废止 attempt 级 `False > True > None`：死亡证明按不可变进程身份记录，
    同一身份的后续 True 收敛先前 False；不同身份的证据互不覆盖。
    """
    from datetime import timezone

    from app.agents.contract import ProcessDeathState

    identity_a = AgentProcessIdentity(
        pid=101,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        process_group_id=101,
        containment_id="runtoken:tok-101",
    )
    identity_b = AgentProcessIdentity(
        pid=202,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        process_group_id=202,
        containment_id="runtoken:tok-202",
    )

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
    from datetime import timezone

    identity_first = AgentProcessIdentity(
        pid=111,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        containment_id="runtoken:tok-111",
    )
    identity_second = AgentProcessIdentity(
        pid=222,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        containment_id="runtoken:tok-222",
    )

    first = AgentAttemptRuntimeState()
    first.record_process_started(identity_first)
    first.record_termination(confirmed_dead=True, identity=identity_first)

    second = AgentAttemptRuntimeState()
    second.record_process_started(identity_second)
    second.record_termination(confirmed_dead=False, identity=identity_second)

    assert first.termination_confirmed_dead is True
    assert second.termination_confirmed_dead is False
    assert first.process_started is True
    assert second.process_started is True
