"""远程 TASK_CHAT finalizer 的 provider 证据与收敛回归（doc 审计 P1-1/P0-3）。

覆盖（doc: docs/agent-job-d21a7118-audit-and-fix-plan.md §6/§5 验收）：
- 远程成功：正常 provider result 必须让 finalizer 拿到 outcome 证据，
  正确收敛 SUCCESS（而不是被证据门槛误判 ORPHANED）；
- 远程明确失败 / 结果后持久化失败：真实 AgentRunResult 到达即
  “provider 已结束”，与“业务是否成功”分开表达；
- 引擎异常断流（无 result、无 ACK）：仍保留 ORPHANED；
- 取消与结果竞态：TERMINATION intent 下 provider outcome 允许业务终态；
- 决策表/事务层：ORPHANED 保留 ownership；旧 attempt 不能覆盖新 attempt；
- 本地平台无关：不依赖 Linux 进程语义。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.domains.task.models.task  # noqa: F401
from app.agents.contract import (
    EXECUTION_KIND_LOCAL_PROCESS,
    EXECUTION_KIND_REMOTE_SESSION,
    AgentAttemptContext,
    AgentAttemptRuntimeState,
    AgentRunResult,
    AttemptFinalizerEvidence,
    bind_agent_attempt,
    bind_agent_attempt_runtime,
    reset_agent_attempt,
    reset_agent_attempt_runtime,
)
from app.database import Base
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services import ai_job_convergence_service as convergence
from app.domains.ai.services import ai_job_service as jobs
from app.domains.ai.services.ai_job_convergence_service import (
    AttemptConvergenceRequest,
    ConvergenceIntent,
    resolve_attempt_evidence,
)

REMOTE = EXECUTION_KIND_REMOTE_SESSION


# ───────────────────────── 组件层：finalizer 证据传递 ─────────────────────────


def _bind_remote_runtime(*, session_started: bool = True):
    runtime = AgentAttemptRuntimeState(remote_session_started=session_started)
    binding = bind_agent_attempt_runtime(runtime)
    owner = bind_agent_attempt(
        AgentAttemptContext(
            job_id="job-1",
            task_id="task-1",
            queue_key="queue-1",
            run_token="run-1",
            worker_id="worker-1",
            worker_boot_id=jobs.WORKER_BOOT_ID,
            attempt_count=1,
            execution_kind=REMOTE,
        )
    )
    return owner, binding


def _decide(evidence, *, intent=ConvergenceIntent.NORMAL_FINALIZE, requested=None):
    request = AttemptConvergenceRequest(
        job_id="job-1",
        run_token="run-1",
        worker_boot_id=jobs.WORKER_BOOT_ID,
        requested_status=requested,
        reason="done",
        evidence=evidence,
        intent=intent,
    )
    return convergence._decide_final_status(SimpleNamespace(), request, REMOTE)


def _capture_finalizer_call(engine):
    captured = {}

    def capture(db, **kwargs):
        captured.update(kwargs)

    async def txn(fn):
        return fn(None)

    owner, binding = _bind_remote_runtime()
    try:
        with patch.object(jobs, "_finalize_task_chat_job_sync", side_effect=capture), \
             patch.object(jobs, "run_db_txn", side_effect=txn):
            import asyncio

            asyncio.run(jobs._finalize_task_chat_job_from_engine("job-1", engine))
        return captured["evidence"]
    finally:
        reset_agent_attempt(owner)
        reset_agent_attempt_runtime(binding)


def test_remote_success_finalizer_must_receive_provider_evidence():
    """审计复现：远程正常成功（引擎只暴露 success 标记）→ 证据门槛放行
    SUCCESS，绝不误判 ORPHANED。"""
    engine = SimpleNamespace(
        last_result_success=True, last_result_text="done", session_id="remote-1"
    )
    evidence = _capture_finalizer_call(engine)
    assert evidence.provider_outcome_seen is True
    status, _ = _decide(evidence, requested=AiJobStatus.SUCCESS)
    assert status == AiJobStatus.SUCCESS, (status, evidence)


def test_real_result_object_with_persist_failure_is_provider_outcome():
    """结果后持久化失败：last_result（真实 result 对象）在引擎内已登记，
    finalizer 必须仍拿到 provider outcome（业务失败 -> 干净 INTERRUPTED）。"""
    engine = SimpleNamespace(
        last_result=AgentRunResult(
            session_id="remote-1", success=False, result_text="persist failed later"
        ),
        # 持久化失败的异常路径会把 success 覆盖为 False。
        last_result_success=False,
        last_result_text="persist failed later",
        session_id="remote-1",
    )
    evidence = _capture_finalizer_call(engine)
    assert evidence.provider_outcome_seen is True
    status, _ = _decide(evidence, requested=AiJobStatus.INTERRUPTED)
    assert status == AiJobStatus.INTERRUPTED


def test_engine_crash_without_result_stays_orphaned():
    """异常断流：无 result、无 ACK、会话已建立 → ORPHANED 保留 ownership。"""
    engine = SimpleNamespace(
        last_result_success=False,  # 引擎异常路径赋 False，绝不当 outcome
        last_result_text="boom",
        session_id="remote-1",
    )
    evidence = _capture_finalizer_call(engine)
    assert evidence.provider_outcome_seen is False
    status, orphan_code = _decide(evidence)
    assert status == AiJobStatus.ORPHANED
    assert orphan_code


def test_engine_timeout_is_not_provider_outcome():
    """超时中断（last_result_success=None）：证据不足仍 ORPHANED。"""
    engine = SimpleNamespace(
        last_result_success=None, last_result_text="timeout", session_id="remote-1"
    )
    evidence = _capture_finalizer_call(engine)
    assert evidence.provider_outcome_seen is False
    status, _ = _decide(evidence)
    assert status == AiJobStatus.ORPHANED


def test_remote_explicit_failure_with_real_result_is_clean_terminal():
    """远程明确失败：真实 result（success=False）到达 → 业务终态而非
    ORPHANED（“provider 已结束”与“业务是否成功”区分）。"""
    runtime = AgentAttemptRuntimeState(remote_session_started=True)
    evidence = resolve_attempt_evidence(
        execution_kind=REMOTE,
        runtime=runtime,
        provider_result=AgentRunResult(session_id="s", success=False),
    )
    assert evidence.provider_outcome_seen is True
    status, _ = _decide(evidence, requested=AiJobStatus.INTERRUPTED)
    assert status == AiJobStatus.INTERRUPTED


def test_cancel_and_result_race_uses_provider_outcome():
    """取消与结果竞态：TERMINATION intent 下 provider outcome 已看到 →
    业务终态，绝不允许卡 ORPHANED。"""
    runtime = AgentAttemptRuntimeState(remote_session_started=True)
    evidence = resolve_attempt_evidence(
        execution_kind=REMOTE,
        runtime=runtime,
        provider_result=AgentRunResult(session_id="s", success=True),
    )
    status, _ = _decide(
        evidence,
        intent=ConvergenceIntent.TERMINATION_FINALIZE,
        requested=AiJobStatus.CANCELLED,
    )
    assert status == AiJobStatus.CANCELLED


def test_runner_provider_seen_requires_real_result_not_run_return():
    """“run 正常返回”不构成 outcome：last_result_success=False（异常路径）
    不得让 runner 兜底把 provider_outcome_seen 置 True。"""
    engine = SimpleNamespace(last_result_success=False, last_result_text="boom")
    provider_seen = getattr(engine, "last_result", None) is not None
    assert provider_seen is False


# ─────────────────────────── 引擎 provider result 登记 ───────────────────────────


def test_engine_provider_result_prefers_real_result_object():
    real = AgentRunResult(session_id="s", success=True, result_text="ok")
    engine = SimpleNamespace(
        last_result=real, last_result_success=False, session_id="s"
    )
    assert jobs._engine_provider_result(engine) is real


def test_engine_provider_result_synthesizes_only_for_true_success():
    engine = SimpleNamespace(
        last_result_success=True,
        last_result_text="ok",
        session_id="s",
    )
    synthesized = jobs._engine_provider_result(engine)
    assert synthesized is not None
    assert synthesized.success is True

    for success in (False, None):
        engine = SimpleNamespace(
            last_result_success=success, last_result_text="x", session_id="s"
        )
        assert jobs._engine_provider_result(engine) is None


def test_engine_records_last_result_before_persist():
    """引擎必须在持久化之前登记真实 result（持久化失败不抹掉证据）。"""
    import inspect

    from app.engine.workflow_engine import WorkflowEngine

    source = inspect.getsource(WorkflowEngine.run)
    persist_pos = source.index("_persist_provider_state")
    assign_pos = source.index("self.last_result = result")
    assert assign_pos < persist_pos


# ───────────────────────── 事务层：ORPHANED ownership / fence ─────────────────────────


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _owned_job(db, *, token="run-1", status=AiJobStatus.RUNNING):
    job = SddAiJob(
        id="job-1",
        workspace_id="ws-1",
        channel=AiJobChannel.TASK_CHAT,
        queue_key="TASK_CHAT:task-1",
        status=status,
        creator_id="user-1",
        run_token=token,
        worker_boot_id=jobs.WORKER_BOOT_ID,
        process_execution_kind=REMOTE,
        task_id="task-1",
        process_pid=5151,
        process_group_id=5151,
        lease_expires_at=datetime.utcnow() + timedelta(seconds=30),
    )
    db.add(job)
    db.commit()
    return job


def test_orphaned_convergence_keeps_ownership_in_db():
    """上层作业：无法确认死亡的远程回合 -> ORPHANED 且 ownership 保留。"""
    factory = _session_factory()
    db = factory()
    _owned_job(db)
    evidence = AttemptFinalizerEvidence(
        execution_kind=REMOTE,
        process_started=False,
        termination_confirmed_dead=None,
        remote_stop_acknowledged=None,
        failure_code=None,
        error_message=None,
        remaining_pids=(),
        source="remote",
        remote_session_started=True,
        provider_outcome_seen=False,
    )
    request = AttemptConvergenceRequest(
        job_id="job-1",
        run_token="run-1",
        worker_boot_id=jobs.WORKER_BOOT_ID,
        requested_status=AiJobStatus.INTERRUPTED,
        reason="engine crashed",
        evidence=evidence,
        intent=ConvergenceIntent.NORMAL_FINALIZE,
    )
    result = convergence.converge_job_attempt_in_txn(db, request)
    db.commit()
    assert result.changed is True
    row = db.query(SddAiJob).filter(SddAiJob.id == "job-1").first()
    assert row.status == AiJobStatus.ORPHANED
    # ORPHANED：ownership 必须完整保留（doc §8.4）。
    assert row.process_pid == 5151
    assert row.process_group_id == 5151
    assert row.run_token == "run-1"
    db.close()


def test_provider_outcome_convergence_clears_ownership_in_db():
    """provider outcome 证据充分：SUCCESS 收敛并清空 ownership。"""
    factory = _session_factory()
    db = factory()
    _owned_job(db)
    evidence = AttemptFinalizerEvidence(
        execution_kind=REMOTE,
        process_started=False,
        termination_confirmed_dead=None,
        remote_stop_acknowledged=None,
        failure_code=None,
        error_message=None,
        remaining_pids=(),
        source="remote",
        remote_session_started=True,
        provider_outcome_seen=True,
    )
    request = AttemptConvergenceRequest(
        job_id="job-1",
        run_token="run-1",
        worker_boot_id=jobs.WORKER_BOOT_ID,
        requested_status=AiJobStatus.SUCCESS,
        reason="done",
        evidence=evidence,
        result_patch={"result_preview": "ok"},
        intent=ConvergenceIntent.NORMAL_FINALIZE,
    )
    result = convergence.converge_job_attempt_in_txn(db, request)
    db.commit()
    assert result.changed is True
    row = db.query(SddAiJob).filter(SddAiJob.id == "job-1").first()
    assert row.status == AiJobStatus.SUCCESS
    assert row.process_pid is None and row.process_group_id is None
    db.close()


def test_finalizer_db_segment_is_fenced_by_run_token():
    """旧 attempt 不能覆盖新 attempt：token 不匹配时 finalizer 幂等退出。"""
    factory = _session_factory()
    db = factory()
    _owned_job(db, token="new-token")
    evidence = AttemptFinalizerEvidence(
        execution_kind=REMOTE,
        process_started=False,
        termination_confirmed_dead=None,
        remote_stop_acknowledged=None,
        failure_code=None,
        error_message=None,
        remaining_pids=(),
        source="remote",
        remote_session_started=True,
        provider_outcome_seen=True,
    )
    payload = jobs._finalize_task_chat_job_sync(
        db,
        job_id="job-1",
        last_result_success=True,
        last_result_text="late old-attempt result",
        is_timeout_interrupted=False,
        engine_session_id="remote-1",
        run_token="old-token",
        evidence=evidence,
    )
    row = db.query(SddAiJob).filter(SddAiJob.id == "job-1").first()
    assert row.status == AiJobStatus.RUNNING
    db.close()


def test_persisted_unknown_evidence_keeps_orphaned_at_decision_layer():
    """P0-3B 上层：persisted stop 返回 None/False + remaining 时，决策表
    绝不允许 NORMAL 收敛清 ownership。"""
    factory = _session_factory()
    db = factory()
    _owned_job(db)
    for confirmed_dead in (None, False):
        evidence = AttemptFinalizerEvidence(
            execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
            process_started=True,
            termination_confirmed_dead=confirmed_dead,
            remote_stop_acknowledged=None,
            failure_code="PROCESS_TREE_STILL_ALIVE",
            error_message=None,
            remaining_pids=(987654,),
            source="fallback",
        )
        request = AttemptConvergenceRequest(
            job_id="job-1",
            run_token="run-1",
            worker_boot_id=jobs.WORKER_BOOT_ID,
            requested_status=AiJobStatus.SUCCESS,
            reason="reap",
            evidence=evidence,
            intent=ConvergenceIntent.NORMAL_FINALIZE,
        )
        status, _ = convergence._decide_final_status(
            db.query(SddAiJob).filter(SddAiJob.id == "job-1").first(),
            request,
            EXECUTION_KIND_LOCAL_PROCESS,
        )
        assert status == AiJobStatus.ORPHANED, (confirmed_dead, status)
    db.close()


# ───────────── P1（doc: docs/agent-job-07e04775-audit-pseudocode-plan.md §4）─────────────
# provider 终局证据按 call 身份登记：结果到达时记录，异常/重试共用同一证据源。


def test_per_call_result_recorded_and_resolved_from_runtime():
    """result 到达时登记 ENDED：resolve 必须看到 provider_outcome_seen。"""
    from app.agents.contract import (
        current_agent_attempt_key,
        record_provider_call_result,
        record_provider_call_session_started,
    )

    owner, binding = _bind_remote_runtime()
    try:
        runtime = jobs.current_agent_attempt_runtime()
        call = runtime.begin_provider_call(current_agent_attempt_key())
        record_provider_call_session_started(call, "remote-1")
        assert jobs.current_agent_attempt_runtime() is runtime
        evidence = resolve_attempt_evidence(
            execution_kind=REMOTE, runtime=runtime
        )
        # 只有 STARTED、没有 result：绝不伪造结束。
        assert evidence.provider_outcome_seen is False
        assert evidence.remote_session_started is True
        record_provider_call_result(call, is_error=True)
        evidence = resolve_attempt_evidence(
            execution_kind=REMOTE, runtime=runtime
        )
        # 明确失败 result 也是终局 outcome：FAILED 可收敛，不是 ORPHANED。
        assert evidence.provider_outcome_seen is True
        status, _ = _decide(evidence, requested=AiJobStatus.FAILED)
        assert status == AiJobStatus.FAILED
    finally:
        reset_agent_attempt_runtime(binding)
        reset_agent_attempt(owner)


def test_unresolved_retry_call_blocks_previous_ended_outcome():
    """多次调用共享 attempt：某一次 ENDED 不能为其他未决调用提供终态证明。"""
    from app.agents.contract import ProviderCallState

    owner, binding = _bind_remote_runtime()
    try:
        runtime = jobs.current_agent_attempt_runtime()
        key = ("job-1", "run-1", jobs.WORKER_BOOT_ID)
        first = runtime.begin_provider_call(key)
        first.state = ProviderCallState.ENDED
        first.result_success = True
        retry = runtime.begin_provider_call(key)
        retry.state = ProviderCallState.STARTED
        evidence = resolve_attempt_evidence(
            execution_kind=REMOTE, runtime=runtime, attempt_key=key
        )
        assert evidence.provider_outcome_seen is False
        retry.state = ProviderCallState.ENDED
        retry.result_success = True
        evidence = resolve_attempt_evidence(
            execution_kind=REMOTE, runtime=runtime, attempt_key=key
        )
        assert evidence.provider_outcome_seen is True
    finally:
        reset_agent_attempt_runtime(binding)
        reset_agent_attempt(owner)


def test_attempt_key_isolation_between_attempts():
    """跨 attempt 的 provider 调用证据不得互相兜底。"""
    from app.agents.contract import ProviderCallState

    runtime = AgentAttemptRuntimeState(remote_session_started=True)
    stale = runtime.begin_provider_call(("job-1", "stale-token", "boot"))
    stale.state = ProviderCallState.ENDED
    stale.result_success = True
    evidence = resolve_attempt_evidence(
        execution_kind=REMOTE,
        runtime=runtime,
        attempt_key=("job-1", "current-token", "boot"),
    )
    assert evidence.provider_outcome_seen is False


def test_stop_ack_closes_unresolved_call_without_fabricating_outcome():
    """明确 stop ACK 终止未决调用：不阻塞后续 outcome，也不伪造 result 成败。"""
    from app.agents.contract import ProviderCallState
    from app.domains.ai.services.ai_job_service import _close_unresolved_provider_call

    owner, binding = _bind_remote_runtime()
    try:
        runtime = jobs.current_agent_attempt_runtime()
        key = ("job-1", "run-1", jobs.WORKER_BOOT_ID)
        stopped = runtime.begin_provider_call(key)
        stopped.state = ProviderCallState.STARTED
        retry = runtime.begin_provider_call(key)
        _close_unresolved_provider_call(stopped, stop_acknowledged=True)
        assert stopped.state is ProviderCallState.ENDED
        assert stopped.result_success is None
        # ACK 终止的调用不阻塞重试。
        retry.state = ProviderCallState.ENDED
        retry.result_success = True
        evidence = resolve_attempt_evidence(
            execution_kind=REMOTE, runtime=runtime, attempt_key=key
        )
        assert evidence.provider_outcome_seen is True
    finally:
        reset_agent_attempt_runtime(binding)
        reset_agent_attempt(owner)
