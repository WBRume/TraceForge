"""Agent attempt 与 AI job 单点收敛验收（doc V3 §14）。

覆盖：
- 14.1 证据权威性：identity-aware runtime 不被无身份 fallback 覆盖；
- 14.2 运行中取消：TERMINATING 在 runtime 释放前立即收敛，不等待 lease；
- 14.3 远程 Agent：REMOTE_SESSION ack/失败/未确认的决策表；
- 14.4 广播语义：非终态绝不产生 final 事件；
- 14.5 DB 并发状态机：cancel/finalize 两种锁顺序、双 finalizer、旧 token；
- 14.7 execution kind 端到端：claim 持久化 + attempt context 传播。
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

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
    AgentProcessIdentity,
    AgentStopResult,
    bind_agent_attempt,
    bind_agent_attempt_runtime,
    reset_agent_attempt,
    reset_agent_attempt_runtime,
)
from app.agents.errors import AgentError
from app.database import Base
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services import ai_job_convergence_service as convergence
from app.domains.ai.services import ai_job_service
from app.domains.ai.services.ai_job_convergence_service import (
    AttemptConvergenceRequest,
    ConvergenceIntent,
    EVIDENCE_CONFLICT,
    REMOTE_STOP_UNCONFIRMED,
    resolve_attempt_evidence,
    evidence_from_stop_result,
)


def _identity(pid: int) -> AgentProcessIdentity:
    return AgentProcessIdentity(
        pid=pid,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        process_group_id=pid,
        containment_id=f"runtoken:tok-{pid}",
    )


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


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
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
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
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        attempt_count=1,
        execution_kind=kind,
    )


# ────────────────────── 14.1 证据权威性 ──────────────────────


def test_runtime_true_not_downgraded_by_stale_exception_fallback():
    runtime = AgentAttemptRuntimeState()
    runtime.record_process_started(_identity(101))
    runtime.record_termination(confirmed_dead=True, identity=_identity(101))

    evidence = resolve_attempt_evidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        runtime=runtime,
        typed_error=AgentError("stale", termination_confirmed_dead=False, process_started=True),
    )

    assert evidence.termination_confirmed_dead is True
    assert evidence.process_started is True
    assert evidence.source == "runtime"


def test_runtime_true_not_downgraded_by_stale_engine_fallback():
    runtime = AgentAttemptRuntimeState()
    runtime.record_process_started(_identity(101))
    runtime.record_termination(confirmed_dead=True, identity=_identity(101))

    evidence = resolve_attempt_evidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        runtime=runtime,
        fallback_dead=False,
        fallback_started=True,
    )

    assert evidence.termination_confirmed_dead is True


def test_runtime_false_not_upgraded_by_stale_exception():
    runtime = AgentAttemptRuntimeState()
    runtime.record_process_started(_identity(101))
    runtime.record_termination(confirmed_dead=False, identity=_identity(101))

    evidence = resolve_attempt_evidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        runtime=runtime,
        typed_error=AgentError("stale", termination_confirmed_dead=True, process_started=True),
    )

    assert evidence.termination_confirmed_dead is False


def test_runtime_aggregate_none_with_started_identity_keeps_none_for_true_fallback():
    """A True + B STARTED 聚合 None：fallback=True 不得把未知身份确认死亡。"""
    runtime = AgentAttemptRuntimeState()
    runtime.record_process_started(_identity(101))
    runtime.record_process_started(_identity(202))
    runtime.record_termination(confirmed_dead=True, identity=_identity(101))
    assert runtime.termination_confirmed_dead is None

    evidence = resolve_attempt_evidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        runtime=runtime,
        fallback_dead=True,
    )

    assert evidence.termination_confirmed_dead is None
    assert evidence.process_started is True


def test_runtime_aggregate_none_supplemented_by_false_fallback():
    runtime = AgentAttemptRuntimeState()
    runtime.record_process_started(_identity(101))

    evidence = resolve_attempt_evidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        runtime=runtime,
        fallback_dead=False,
    )

    assert evidence.termination_confirmed_dead is False


def test_runtime_without_evidence_uses_typed_exception_compat_path():
    evidence = resolve_attempt_evidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        runtime=None,
        typed_error=AgentError("boom", termination_confirmed_dead=True, process_started=True),
    )

    assert evidence.termination_confirmed_dead is True
    assert evidence.process_started is True
    assert evidence.source == "fallback"


def test_conflicting_identityless_fallbacks_yield_none_with_conflict_code():
    evidence = resolve_attempt_evidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        runtime=None,
        fallback_dead=True,
        typed_error=AgentError("stale", termination_confirmed_dead=False, process_started=True),
    )

    assert evidence.termination_confirmed_dead is None
    assert evidence.failure_code == EVIDENCE_CONFLICT


# ────────────────────── 14.2 运行中取消 ──────────────────────


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
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        requested_status=None,
        reason="USER_CANCEL",
        evidence=evidence,
        intent=intent,
        reap_bookkeeping=True,
    )


def test_running_cancel_with_dead_proof_converges_cancelled_immediately(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.TERMINATING, cancel_requested=True)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    payload = ai_job_service._finish_termination_sync(
        "convergence-job",
        "run-1",
        confirmed_dead=True,
        reason="USER_CANCEL",
        failure_code="CANCEL_REQUESTED",
    )

    assert payload["status"] == AiJobStatus.CANCELLED.value
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.status == AiJobStatus.CANCELLED
    assert saved.process_pid is None
    assert saved.run_token is None


def test_running_cancel_unconfirmed_tree_keeps_ownership(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.TERMINATING, pid=5151, cancel_requested=True)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    payload = ai_job_service._finish_termination_sync(
        "convergence-job",
        "run-1",
        confirmed_dead=False,
        reason="tree survived",
        failure_code="PROCESS_TREE_STILL_ALIVE",
    )

    assert payload["status"] == AiJobStatus.ORPHANED.value
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.process_pid == 5151
    assert saved.run_token == "run-1"
    assert saved.worker_boot_id == ai_job_service.WORKER_BOOT_ID
    assert saved.next_reap_at is not None


def test_running_cancel_never_started_local_process_converges_cancelled():
    factory = _session_factory()
    db = factory()
    _job(
        db,
        status=AiJobStatus.TERMINATING,
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        pid=None,
        cancel_requested=True,
    )
    request = _terminate_request(dead=None, started=False)
    result = convergence.converge_job_attempt_sync(db, request)

    assert result.changed is True
    assert result.status == AiJobStatus.CANCELLED.value


def test_runner_convergence_consumes_runtime_before_reset(monkeypatch):
    """取消 → runner convergence 必须在 reset runtime 前消费死亡证明。"""
    import app.core.offload as offload

    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.TERMINATING, cancel_requested=True)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)

    async def _no_broadcast(payload):
        return None

    monkeypatch.setattr(ai_job_service, "_broadcast_job_payload", _no_broadcast)

    async def _fake_stop(token, reason):
        return None

    monkeypatch.setattr(ai_job_service.process_supervisor, "stop_attempt", _fake_stop)

    async def _run():
        attempt = _make_attempt()
        attempt_token = bind_agent_attempt(attempt)
        runtime = AgentAttemptRuntimeState()
        runtime.record_process_started(_identity(5151))
        runtime.record_termination(
            confirmed_dead=True,
            identity=_identity(5151),
        )
        runtime_token = bind_agent_attempt_runtime(runtime)
        try:
            await ai_job_service._converge_runner_exit(
                attempt, runtime, ai_job_service.JobExecutionOutcome(requested_status=None)
            )
        finally:
            reset_agent_attempt_runtime(runtime_token)
            reset_agent_attempt(attempt_token)

    asyncio.run(_run())

    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.status == AiJobStatus.CANCELLED
    assert saved.process_pid is None


def test_runner_convergence_unconfirmed_cancel_becomes_orphaned(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.TERMINATING, pid=5151, cancel_requested=True)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)

    async def _no_broadcast(payload):
        return None

    monkeypatch.setattr(ai_job_service, "_broadcast_job_payload", _no_broadcast)

    async def _fake_stop(token, reason):
        return None

    monkeypatch.setattr(ai_job_service.process_supervisor, "stop_attempt", _fake_stop)

    async def _run():
        attempt = _make_attempt()
        attempt_token = bind_agent_attempt(attempt)
        runtime = AgentAttemptRuntimeState()
        runtime.record_process_started(_identity(5151))
        runtime.record_termination(
            confirmed_dead=False,
            identity=_identity(5151),
            failure_code="PROCESS_TREE_STILL_ALIVE",
            remaining_pids=(5151,),
        )
        runtime_token = bind_agent_attempt_runtime(runtime)
        try:
            await ai_job_service._converge_runner_exit(
                attempt, runtime, ai_job_service.JobExecutionOutcome(requested_status=None)
            )
        finally:
            reset_agent_attempt_runtime(runtime_token)
            reset_agent_attempt(attempt_token)

    asyncio.run(_run())

    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.status == AiJobStatus.ORPHANED
    assert saved.process_pid == 5151
    assert saved.run_token == "run-1"


def test_runner_convergence_leaves_running_job_safe_terminal(monkeypatch):
    """业务路径漏掉 finalizer 时 runner 兜底，不得静默离开 RUNNING。"""
    factory = _session_factory()
    db = factory()
    # 从未启动本地进程（无 runtime 证据、无 DB 归属）：安全的可恢复 INTERRUPTED。
    _job(
        db,
        status=AiJobStatus.RUNNING,
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        pid=None,
    )
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)

    async def _no_broadcast(payload):
        return None

    monkeypatch.setattr(ai_job_service, "_broadcast_job_payload", _no_broadcast)

    async def _run():
        attempt = _make_attempt()
        attempt_token = bind_agent_attempt(attempt)
        runtime = AgentAttemptRuntimeState()
        runtime_token = bind_agent_attempt_runtime(runtime)
        try:
            await ai_job_service._converge_runner_exit(
                attempt,
                runtime,
                ai_job_service.JobExecutionOutcome(
                    requested_status=None,
                    error=RuntimeError("no finalizer ran"),
                ),
            )
        finally:
            reset_agent_attempt_runtime(runtime_token)
            reset_agent_attempt(attempt_token)

    asyncio.run(_run())

    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.status == AiJobStatus.INTERRUPTED
    assert saved.process_pid is None


# ────────────────────── 14.3 远程 Agent ──────────────────────


def _remote_job(db, *, status=AiJobStatus.TERMINATING, cancel_requested=False):
    return _job(
        db,
        status=status,
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        execution_kind=EXECUTION_KIND_REMOTE_SESSION,
        pid=None,
        cancel_requested=cancel_requested,
    )


def _remote_termination_request(*, ack, remote_started=True, intent=ConvergenceIntent.TERMINATION_FINALIZE):
    evidence = convergence.AttemptFinalizerEvidence(
        execution_kind=EXECUTION_KIND_REMOTE_SESSION,
        process_started=False,
        termination_confirmed_dead=None,
        remote_stop_acknowledged=ack,
        failure_code=None if ack else REMOTE_STOP_UNCONFIRMED,
        error_message=None,
        remaining_pids=(),
        source="stop_result",
        remote_session_started=remote_started,
    )
    return AttemptConvergenceRequest(
        job_id="convergence-job",
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        requested_status=None,
        reason="USER_CANCEL",
        evidence=evidence,
        intent=intent,
        reap_bookkeeping=True,
    )


def test_remote_cancel_acknowledged_converges_cancelled():
    factory = _session_factory()
    db = factory()
    _remote_job(db, cancel_requested=True)

    result = convergence.converge_job_attempt_sync(db, _remote_termination_request(ack=True))

    assert result.changed is True
    assert result.status == AiJobStatus.CANCELLED.value
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.process_execution_kind == EXECUTION_KIND_REMOTE_SESSION


def test_remote_cancel_unacknowledged_becomes_orphaned_with_remote_code():
    factory = _session_factory()
    db = factory()
    _remote_job(db, cancel_requested=True)

    result = convergence.converge_job_attempt_sync(
        db, _remote_termination_request(ack=False, remote_started=True)
    )

    assert result.status == AiJobStatus.ORPHANED.value
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.failure_code == REMOTE_STOP_UNCONFIRMED
    assert saved.run_token == "run-1"
    assert saved.process_pid is None
    assert saved.process_execution_kind == EXECUTION_KIND_REMOTE_SESSION


def test_remote_normal_success_finalizes_success():
    factory = _session_factory()
    db = factory()
    _remote_job(db, status=AiJobStatus.RUNNING)
    evidence = convergence.AttemptFinalizerEvidence(
        execution_kind=EXECUTION_KIND_REMOTE_SESSION,
        process_started=False,
        termination_confirmed_dead=None,
        remote_stop_acknowledged=None,
        failure_code=None,
        error_message=None,
        remaining_pids=(),
        source="remote",
        provider_outcome_seen=True,
    )
    request = AttemptConvergenceRequest(
        job_id="convergence-job",
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        requested_status=AiJobStatus.SUCCESS,
        reason="",
        evidence=evidence,
        intent=ConvergenceIntent.NORMAL_FINALIZE,
    )

    result = convergence.converge_job_attempt_sync(db, request)

    assert result.status == AiJobStatus.SUCCESS.value


def test_remote_provider_error_finalizes_failed():
    factory = _session_factory()
    db = factory()
    _remote_job(db, status=AiJobStatus.RUNNING)
    evidence = convergence.AttemptFinalizerEvidence(
        execution_kind=EXECUTION_KIND_REMOTE_SESSION,
        process_started=False,
        termination_confirmed_dead=None,
        remote_stop_acknowledged=None,
        failure_code="PROVIDER_ERROR",
        error_message="provider down",
        remaining_pids=(),
        source="remote",
        provider_outcome_seen=True,
    )
    request = AttemptConvergenceRequest(
        job_id="convergence-job",
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        requested_status=AiJobStatus.FAILED,
        reason="provider down",
        evidence=evidence,
        intent=ConvergenceIntent.NORMAL_FINALIZE,
    )

    result = convergence.converge_job_attempt_sync(db, request)

    assert result.status == AiJobStatus.FAILED.value
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.failure_code == "PROVIDER_ERROR"


def test_evidence_from_remote_stop_result_shapes_decision_inputs():
    ack = AgentStopResult(
        execution_kind=EXECUTION_KIND_REMOTE_SESSION,
        stop_acknowledged=True,
    )
    nack = AgentStopResult(
        execution_kind=EXECUTION_KIND_REMOTE_SESSION,
        stop_acknowledged=False,
        failure_code="OPENCODE_ABORT_REJECTED",
        error_message="HTTP 500",
    )

    ack_evidence = evidence_from_stop_result(ack, remote_session_started=True)
    nack_evidence = evidence_from_stop_result(nack, remote_session_started=True)

    assert ack_evidence.remote_stop_acknowledged is True
    assert nack_evidence.remote_stop_acknowledged is False
    assert nack_evidence.failure_code == "OPENCODE_ABORT_REJECTED"
    assert nack_evidence.remote_session_started is True


# ────────────────────── 14.4 广播语义 ──────────────────────


class _RoomCapture:
    def __init__(self):
        self.messages = []

    async def send_message_to_room(self, room_id, message):
        self.messages.append((room_id, message.type, message.payload.get("job", {}).get("status")))


def test_broadcast_terminating_never_emits_final_event(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.TERMINATING, cancel_requested=True)
    capture = _RoomCapture()
    monkeypatch.setattr(ai_job_service.task_ws_manager, "send_message_to_room", capture.send_message_to_room)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    asyncio.run(ai_job_service._publish_job_state("convergence-job"))

    types = [message[1] for message in capture.messages]
    assert types and all(t == "chat_job_update" for t in types)
    assert not any(t in ("chat_job_done", "chat_job_failed") for t in types)


def test_broadcast_cancelled_emits_exactly_one_final_event(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.CANCELLED)
    capture = _RoomCapture()
    monkeypatch.setattr(ai_job_service.task_ws_manager, "send_message_to_room", capture.send_message_to_room)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    asyncio.run(ai_job_service._publish_job_state("convergence-job"))

    types = [message[1] for message in capture.messages]
    assert types.count("chat_job_update") == 1
    assert types.count("chat_job_failed") == 1
    assert "chat_job_done" not in types


def test_broadcast_success_emits_exactly_one_done_event(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.SUCCESS)
    capture = _RoomCapture()
    monkeypatch.setattr(ai_job_service.task_ws_manager, "send_message_to_room", capture.send_message_to_room)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    asyncio.run(ai_job_service._publish_job_state("convergence-job"))

    types = [message[1] for message in capture.messages]
    assert types.count("chat_job_update") == 1
    assert types.count("chat_job_done") == 1


def test_broadcast_orphaned_never_emits_final_event(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.ORPHANED)
    capture = _RoomCapture()
    monkeypatch.setattr(ai_job_service.task_ws_manager, "send_message_to_room", capture.send_message_to_room)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    asyncio.run(ai_job_service._publish_job_state("convergence-job"))

    types = [message[1] for message in capture.messages]
    assert types and all(t == "chat_job_update" for t in types)


# ────────────────────── 14.5 DB 并发状态机 ──────────────────────


def test_cancel_locks_row_before_finalize_sees_terminating(monkeypatch):
    """锁顺序 1：cancel 先锁行 → NORMAL finalize 看到 TERMINATING 被拦下。"""
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.RUNNING)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    cancelled = ai_job_service.cancel_job(db, workspace_id="ws-1", job_id="convergence-job")
    assert cancelled.status == AiJobStatus.TERMINATING

    evidence = convergence.AttemptFinalizerEvidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        process_started=True,
        termination_confirmed_dead=True,
        remote_stop_acknowledged=None,
        failure_code=None,
        error_message=None,
        remaining_pids=(),
        source="runtime",
    )
    request = AttemptConvergenceRequest(
        job_id="convergence-job",
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        requested_status=AiJobStatus.SUCCESS,
        reason="",
        evidence=evidence,
        intent=ConvergenceIntent.NORMAL_FINALIZE,
    )
    result = convergence.converge_job_attempt_sync(db, request)

    assert result.changed is False
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.status == AiJobStatus.TERMINATING
    assert saved.process_pid == 5151


def test_finalize_wins_lock_cancel_becomes_idempotent(monkeypatch):
    """锁顺序 2：finalizer 先锁行写入终态 → cancel 幂等返回。"""
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.RUNNING)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    evidence = convergence.AttemptFinalizerEvidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        process_started=True,
        termination_confirmed_dead=True,
        remote_stop_acknowledged=None,
        failure_code=None,
        error_message=None,
        remaining_pids=(),
        source="runtime",
    )
    request = AttemptConvergenceRequest(
        job_id="convergence-job",
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        requested_status=AiJobStatus.SUCCESS,
        reason="",
        evidence=evidence,
        intent=ConvergenceIntent.NORMAL_FINALIZE,
    )
    result = convergence.converge_job_attempt_sync(db, request)
    assert result.changed is True

    cancelled = ai_job_service.cancel_job(db, workspace_id="ws-1", job_id="convergence-job")

    assert cancelled.status == AiJobStatus.SUCCESS
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.status == AiJobStatus.SUCCESS
    assert saved.cancel_requested_at is None


def test_two_finalizers_only_first_writes(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.RUNNING)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    evidence = convergence.AttemptFinalizerEvidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        process_started=True,
        termination_confirmed_dead=True,
        remote_stop_acknowledged=None,
        failure_code=None,
        error_message=None,
        remaining_pids=(),
        source="runtime",
    )

    def _finalize(db2, status):
        request = AttemptConvergenceRequest(
            job_id="convergence-job",
            run_token="run-1",
            worker_boot_id=ai_job_service.WORKER_BOOT_ID,
            requested_status=status,
            reason="",
            evidence=evidence,
            intent=ConvergenceIntent.NORMAL_FINALIZE,
        )
        return convergence.converge_job_attempt_sync(db2, request)

    first = _finalize(db, AiJobStatus.SUCCESS)
    second = _finalize(db, AiJobStatus.FAILED)

    assert first.changed is True
    assert second.changed is False
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.status == AiJobStatus.SUCCESS


def test_stale_run_token_cannot_converge_new_attempt(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.RUNNING, token="current-run")
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    evidence = convergence.AttemptFinalizerEvidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        process_started=True,
        termination_confirmed_dead=True,
        remote_stop_acknowledged=None,
        failure_code=None,
        error_message=None,
        remaining_pids=(),
        source="runtime",
    )
    request = AttemptConvergenceRequest(
        job_id="convergence-job",
        run_token="old-run",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        requested_status=AiJobStatus.SUCCESS,
        reason="",
        evidence=evidence,
        intent=ConvergenceIntent.NORMAL_FINALIZE,
    )
    result = convergence.converge_job_attempt_sync(db, request)

    assert result.changed is False
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.status == AiJobStatus.RUNNING
    assert saved.process_pid == 5151


def test_termination_convergence_cannot_downgrade_orphaned_business_state():
    """TERMINATION 收敛不得把 ORPHANED 降级为业务终态（未证明死亡）。"""
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.ORPHANED, pid=5151)
    db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").update(
        {SddAiJob.orphaned_at: datetime.utcnow()}, synchronize_session=False
    )
    db.commit()

    result = convergence.converge_job_attempt_sync(db, _terminate_request(dead=False))

    assert result.changed is True
    assert result.status == AiJobStatus.ORPHANED.value
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.process_pid == 5151


def test_termination_convergence_proven_dead_leaves_orphaned_to_business_state():
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.ORPHANED, pid=5151)

    result = convergence.converge_job_attempt_sync(db, _terminate_request(dead=True))

    assert result.changed is True
    assert result.status == AiJobStatus.INTERRUPTED.value
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.process_pid is None


# ────────────────────── 14.7 execution kind 端到端 ──────────────────────


def test_claim_persists_execution_kind_for_task_backend(monkeypatch):
    from app.domains.auth.models.user import User, Workspace
    from app.domains.task.models.task import SddTask

    factory = _session_factory()
    db = factory()
    user = User(id="user-1", email="c@example.com", hashed_password="x", display_name="C")
    workspace = Workspace(id="ws-1", name="W", owner_id=user.id)
    task = SddTask(
        id="task-1",
        workspace_id="ws-1",
        creator_id="user-1",
        name="T",
        project_path=".",
        status="CODING",
        agent_backend="opencode",
    )
    job = SddAiJob(
        id="convergence-job",
        workspace_id="ws-1",
        task_id="task-1",
        channel=AiJobChannel.TASK_CHAT,
        queue_key="TASK_CHAT:task-1",
        status=AiJobStatus.PENDING,
        creator_id="user-1",
    )
    db.add_all([user, workspace, task, job])
    db.commit()
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    job_id = ai_job_service._take_next_pending_job_id_sync("TASK_CHAT:task-1")

    assert job_id == "convergence-job"
    claimed = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    # 必须断言显式 execution kind，而不是“PID 为空”。
    assert claimed.process_execution_kind == EXECUTION_KIND_REMOTE_SESSION
    assert claimed.process_pid is None


def test_claim_persists_local_kind_for_claude_backend(monkeypatch):
    from app.domains.auth.models.user import User, Workspace
    from app.domains.task.models.task import SddTask

    factory = _session_factory()
    db = factory()
    user = User(id="user-1", email="c@example.com", hashed_password="x", display_name="C")
    workspace = Workspace(id="ws-1", name="W", owner_id=user.id)
    task = SddTask(
        id="task-1",
        workspace_id="ws-1",
        creator_id="user-1",
        name="T",
        project_path=".",
        status="CODING",
        agent_backend="claude-code",
    )
    job = SddAiJob(
        id="convergence-job",
        workspace_id="ws-1",
        task_id="task-1",
        channel=AiJobChannel.TASK_CHAT,
        queue_key="TASK_CHAT:task-1",
        status=AiJobStatus.PENDING,
        creator_id="user-1",
    )
    db.add_all([user, workspace, task, job])
    db.commit()
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    job_id = ai_job_service._take_next_pending_job_id_sync("TASK_CHAT:task-1")

    assert job_id == "convergence-job"
    claimed = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert claimed.process_execution_kind == EXECUTION_KIND_LOCAL_PROCESS


def test_attempt_context_carries_execution_kind(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.RUNNING, kind=EXECUTION_KIND_REMOTE_SESSION, pid=None)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    context = ai_job_service._load_attempt_context_sync("convergence-job")

    assert context is not None
    assert context.execution_kind == EXECUTION_KIND_REMOTE_SESSION


def test_remote_cancel_via_convergence_requires_ack_not_pid_empty():
    """不得通过“PID 为空”推断远程：显式 kind 决定决策分支。"""
    factory = _session_factory()
    db = factory()
    # 行显式声明 LOCAL_PROCESS 但没有任何 PID（PID 持久化失败）：
    # 取消时仍必须走本地死亡证明，不得因 PID 为空被当成远程。
    _job(
        db,
        status=AiJobStatus.TERMINATING,
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        pid=None,
        cancel_requested=True,
    )

    result = convergence.converge_job_attempt_sync(db, _terminate_request(dead=None, started=False))

    # started=False 且无 ownership → 允许 CANCELLED；但若曾启动（runtime
    # 记录 started）则必须 ORPHANED —— 用另一个请求验证。
    assert result.status == AiJobStatus.CANCELLED.value

    started_request = _terminate_request(dead=None, started=True)
    db2 = _session_factory()()
    _job(
        db2,
        status=AiJobStatus.TERMINATING,
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        pid=None,
        cancel_requested=True,
    )
    orphaned = convergence.converge_job_attempt_sync(db2, started_request)
    assert orphaned.status == AiJobStatus.ORPHANED.value


# ────────────────────── 14.3b 远程 adapter 停止结果协议 ──────────────────────


def test_opencode_abort_success_returns_acknowledged():
    from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter

    class _Resp:
        status_code = 200

    class _Client:
        async def post(self, url):
            return _Resp()

    adapter = OpenCodeAdapter(server_url="http://opencode.test")
    adapter._client = _Client()
    adapter._session_id = "sess-1"

    result = asyncio.run(adapter.cancel())

    assert result.execution_kind == EXECUTION_KIND_REMOTE_SESSION
    assert result.stop_acknowledged is True
    assert result.failure_code is None


def test_opencode_abort_rejected_status_returns_structured_nack():
    from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter

    class _Resp:
        status_code = 500

    class _Client:
        async def post(self, url):
            return _Resp()

    adapter = OpenCodeAdapter(server_url="http://opencode.test")
    adapter._client = _Client()
    adapter._session_id = "sess-1"

    result = asyncio.run(adapter.cancel())

    assert result.stop_acknowledged is False
    assert result.failure_code == "OPENCODE_ABORT_REJECTED"
    assert "500" in (result.error_message or "")


def test_opencode_abort_network_error_is_visible_not_swallowed():
    from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter

    class _Client:
        async def post(self, url):
            raise OSError("connection reset")

    adapter = OpenCodeAdapter(server_url="http://opencode.test")
    adapter._client = _Client()
    adapter._session_id = "sess-1"

    result = asyncio.run(adapter.cancel())

    assert result.stop_acknowledged is False
    assert result.failure_code == "OPENCODE_ABORT_NETWORK_ERROR"
    assert result.error_message


def test_opencode_cancel_without_session_is_unacknowledged():
    from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter

    adapter = OpenCodeAdapter(server_url="http://opencode.test")
    adapter._client = None
    adapter._session_id = None

    result = asyncio.run(adapter.cancel())

    assert result.stop_acknowledged is False
    assert result.failure_code == REMOTE_STOP_UNCONFIRMED


def test_dsh_cancel_rpc_success_is_acknowledged():
    from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter

    adapter = DshServerAdapter(server_url="http://dsh.test")
    adapter._session_id = "sess-1"

    async def _ok_rpc(method, payload):
        return {}

    adapter._rpc = _ok_rpc

    result = asyncio.run(adapter.cancel())

    assert result.execution_kind == EXECUTION_KIND_REMOTE_SESSION
    assert result.stop_acknowledged is True


def test_dsh_cancel_rpc_error_returns_structured_failure():
    from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter
    from app.agents.errors import AgentError

    adapter = DshServerAdapter(server_url="http://dsh.test")
    adapter._session_id = "sess-1"

    async def _bad_rpc(method, payload):
        raise AgentError("DSH server RPC session.cancel failed: HTTP 503")

    adapter._rpc = _bad_rpc

    result = asyncio.run(adapter.cancel())

    assert result.stop_acknowledged is False
    assert result.failure_code == "DSH_CANCEL_RPC_FAILED"
    assert "503" in (result.error_message or "")


def test_dsh_interrupt_without_session_is_unacknowledged():
    from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter

    adapter = DshServerAdapter(server_url="http://dsh.test")
    adapter._session_id = None

    result = asyncio.run(adapter.interrupt())

    assert result.stop_acknowledged is False
    assert result.failure_code == REMOTE_STOP_UNCONFIRMED


def test_legacy_shim_cancel_returns_structured_result_and_records_runtime():
    from types import SimpleNamespace

    from app.agents.selection import LegacyBridgeShim

    class _Backend:
        name = "remote-test"
        capabilities = SimpleNamespace(execution_kind=EXECUTION_KIND_REMOTE_SESSION)

        async def cancel(self):
            return AgentStopResult(
                execution_kind=EXECUTION_KIND_REMOTE_SESSION,
                stop_acknowledged=True,
            )

        async def close(self):
            return None

    runtime = AgentAttemptRuntimeState()
    runtime_token = bind_agent_attempt_runtime(runtime)
    try:
        shim = LegacyBridgeShim(_Backend(), backend_name="remote-test")
        result = asyncio.run(shim.cancel())
        assert result.stop_acknowledged is True
        assert runtime.remote_stop_acknowledged is True
    finally:
        reset_agent_attempt_runtime(runtime_token)


def test_legacy_shim_cancel_error_is_not_swallowed():
    from types import SimpleNamespace

    from app.agents.selection import LegacyBridgeShim

    class _Backend:
        name = "remote-test"
        capabilities = SimpleNamespace(execution_kind=EXECUTION_KIND_REMOTE_SESSION)

        async def cancel(self):
            raise RuntimeError("rpc exploded")

        async def close(self):
            return None

    shim = LegacyBridgeShim(_Backend(), backend_name="remote-test")

    result = asyncio.run(shim.cancel())

    assert result.stop_acknowledged is False
    assert result.failure_code == "REMOTE_CANCEL_FAILED"
    assert "rpc exploded" in (result.error_message or "")


def test_legacy_shim_cancel_none_return_is_unacknowledged():
    from types import SimpleNamespace

    from app.agents.selection import LegacyBridgeShim

    class _Backend:
        name = "remote-test"
        capabilities = SimpleNamespace(execution_kind=EXECUTION_KIND_REMOTE_SESSION)

        async def cancel(self):
            return None

        async def close(self):
            return None

    shim = LegacyBridgeShim(_Backend(), backend_name="remote-test")

    result = asyncio.run(shim.cancel())

    # 远程 cancel 的 None 返回值绝不能被视作成功（doc §17）。
    assert result.stop_acknowledged is False
    assert result.failure_code == REMOTE_STOP_UNCONFIRMED


# ────────────── P0-1：CAS 写入 fail-closed（doc §4.5.3） ──────────────


def _seed_owned_running(db, *, token="run-1", status=AiJobStatus.RUNNING, cancel_requested=False):
    job = _job(
        db,
        status=status,
        run_token=token,
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        pid=5151,
        cancel_requested=cancel_requested,
    )
    return job


def test_active_state_write_without_run_token_is_rejected(monkeypatch):
    """无 token 的迟到状态写必须 fail-closed：不得把已取消 job 写回 RUNNING（doc §4.3）。"""
    factory = _session_factory()
    db = factory()
    _seed_owned_running(db)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    cancelled = ai_job_service.cancel_job(db, workspace_id="ws-1", job_id="convergence-job")
    assert cancelled.status == AiJobStatus.TERMINATING

    result = ai_job_service._update_job_state_sync(
        "convergence-job",
        status=AiJobStatus.RUNNING,
        progress=33,
        message="late writer",
    )

    assert result["broadcast"] is False
    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.status == AiJobStatus.TERMINATING
    assert saved.progress != 33
    assert saved.message != "late writer"


def test_late_progress_after_cancel_affects_zero_rows(monkeypatch):
    """取消提交后，迟到 progress/context callback 必须是 fenced no-op。"""
    factory = _session_factory()
    db = factory()
    _seed_owned_running(db, cancel_requested=True)
    original_context = dict(
        db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first().context_json or {}
    )
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    result = ai_job_service._update_job_state_sync(
        "convergence-job",
        progress=80,
        message="late progress",
        context_patch={"late": True},
        run_token="run-1",
    )

    assert result["broadcast"] is False
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.progress != 80
    assert saved.message != "late progress"
    assert (saved.context_json or {}).get("late") is not True


def test_old_token_cannot_modify_new_attempt(monkeypatch):
    factory = _session_factory()
    db = factory()
    _seed_owned_running(db, token="run-2")
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    result = ai_job_service._update_job_state_sync(
        "convergence-job",
        progress=10,
        run_token="run-1",
    )

    assert result["broadcast"] is False
    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.progress != 10


def test_cas_progress_write_succeeds_for_current_owner(monkeypatch):
    factory = _session_factory()
    db = factory()
    _seed_owned_running(db)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    result = ai_job_service._update_job_state_sync(
        "convergence-job",
        progress=42,
        run_token="run-1",
    )

    assert result["broadcast"] is True
    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.progress == 42
    assert saved.run_token == "run-1"


# ────────────── P1-3：JobExecutionOutcome（doc §8） ──────────────


def _remote_attempt():
    return AgentAttemptContext(
        job_id="convergence-job",
        task_id="task-1",
        queue_key="TASK_CHAT:task-1",
        run_token="run-1",
        worker_id="w",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        attempt_count=1,
        execution_kind=EXECUTION_KIND_REMOTE_SESSION,
    )


def test_remote_runner_exit_nack_with_swallowed_error_stays_orphaned(monkeypatch):
    """remote stop NACK + _execute_job 内部处理异常：必须 ORPHANED 并保留 ownership。"""
    factory = _session_factory()
    db = factory()
    _job(
        db,
        status=AiJobStatus.TERMINATING,
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        execution_kind=EXECUTION_KIND_REMOTE_SESSION,
        pid=None,
        cancel_requested=True,
    )
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    async def _no_broadcast(payload):
        return None

    monkeypatch.setattr(ai_job_service, "_broadcast_job_payload", _no_broadcast)

    async def _run():
        attempt = _remote_attempt()
        attempt_token = bind_agent_attempt(attempt)
        runtime = AgentAttemptRuntimeState()
        runtime.remote_session_started = True
        runtime.record_remote_stop(
            AgentStopResult(
                execution_kind=EXECUTION_KIND_REMOTE_SESSION,
                stop_acknowledged=False,
                failure_code=REMOTE_STOP_UNCONFIRMED,
                error_message="remote cancel failed",
            )
        )
        runtime_token = bind_agent_attempt_runtime(runtime)
        try:
            await ai_job_service._converge_runner_exit(
                attempt,
                runtime,
                ai_job_service.JobExecutionOutcome(
                    requested_status=None,
                    error=RuntimeError("swallowed engine exception"),
                    provider_outcome_seen=False,
                ),
            )
        finally:
            reset_agent_attempt_runtime(runtime_token)
            reset_agent_attempt(attempt_token)

    asyncio.run(_run())

    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.status == AiJobStatus.ORPHANED
    assert saved.run_token == "run-1"
    assert saved.failure_code == REMOTE_STOP_UNCONFIRMED


def test_remote_runner_exit_ack_converges_and_clears_ownership(monkeypatch):
    factory = _session_factory()
    db = factory()
    _job(
        db,
        status=AiJobStatus.TERMINATING,
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        execution_kind=EXECUTION_KIND_REMOTE_SESSION,
        pid=None,
        cancel_requested=True,
    )
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    async def _no_broadcast(payload):
        return None

    monkeypatch.setattr(ai_job_service, "_broadcast_job_payload", _no_broadcast)

    async def _run():
        attempt = _remote_attempt()
        attempt_token = bind_agent_attempt(attempt)
        runtime = AgentAttemptRuntimeState()
        runtime.remote_session_started = True
        runtime.record_remote_stop(
            AgentStopResult(execution_kind=EXECUTION_KIND_REMOTE_SESSION, stop_acknowledged=True)
        )
        runtime_token = bind_agent_attempt_runtime(runtime)
        try:
            await ai_job_service._converge_runner_exit(
                attempt,
                runtime,
                ai_job_service.JobExecutionOutcome(requested_status=None),
            )
        finally:
            reset_agent_attempt_runtime(runtime_token)
            reset_agent_attempt(attempt_token)

    asyncio.run(_run())

    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.status == AiJobStatus.CANCELLED
    assert saved.run_token is None


def test_remote_runner_exit_nack_with_provider_outcome_allows_terminal(monkeypatch):
    """provider 明确自然结束（结果先于取消确认到达）：允许业务终态。"""
    factory = _session_factory()
    db = factory()
    _job(
        db,
        status=AiJobStatus.TERMINATING,
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        execution_kind=EXECUTION_KIND_REMOTE_SESSION,
        pid=None,
        cancel_requested=True,
    )
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    async def _no_broadcast(payload):
        return None

    monkeypatch.setattr(ai_job_service, "_broadcast_job_payload", _no_broadcast)

    async def _run():
        attempt = _remote_attempt()
        attempt_token = bind_agent_attempt(attempt)
        runtime = AgentAttemptRuntimeState()
        runtime.remote_session_started = True
        runtime.record_remote_stop(
            AgentStopResult(
                execution_kind=EXECUTION_KIND_REMOTE_SESSION,
                stop_acknowledged=False,
                failure_code=REMOTE_STOP_UNCONFIRMED,
            )
        )
        runtime_token = bind_agent_attempt_runtime(runtime)
        try:
            await ai_job_service._converge_runner_exit(
                attempt,
                runtime,
                ai_job_service.JobExecutionOutcome(
                    requested_status=None,
                    provider_outcome_seen=True,
                ),
            )
        finally:
            reset_agent_attempt_runtime(runtime_token)
            reset_agent_attempt(attempt_token)

    asyncio.run(_run())

    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.status == AiJobStatus.CANCELLED


# ────────────── P1-2：preview fence 回滚业务副作用（doc §7） ──────────────


def _seed_preview_job(db, *, token="run-1", cancel_requested=False):
    job = SddAiJob(
        id="preview-job",
        workspace_id="ws-1",
        channel=AiJobChannel.ASSET_THREAD,
        queue_key="REQUIREMENT_PREVIEW:ws-1",
        status=AiJobStatus.RUNNING,
        creator_id="user-1",
        run_token=token,
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        process_execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        cancel_requested_at=datetime.utcnow() if cancel_requested else None,
    )
    db.add(job)
    db.commit()
    return job


def test_requirement_preview_fence_rolls_back_batch_and_items(monkeypatch):
    """fence 命中时 finalizer 必须抛出专用异常，外层事务整体 rollback。"""
    from types import SimpleNamespace

    from app.domains.ai.services.ai_job_convergence_service import AttemptFencedError
    from app.domains.workspace_asset.models.workspace_asset import (
        SddRequirementAuditLog,
        SddRequirementImportBatch,
        SddRequirementImportItem,
    )
    from app.domains.workspace_asset.services import workspace_asset_service as was

    factory = _session_factory()
    db = factory()
    _seed_preview_job(db, cancel_requested=True)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)

    async def _run():
        await ai_job_service.run_db_txn(
            lambda session: was._finalize_requirement_import_sync(
                session,
                job_id="preview-job",
                file_name="requirements.md",
                markdown="# md",
                source_kind="document",
                source_uri=None,
                source_ref=None,
                items=[{"title": "Item 1", "body": "b"}],
                metadata={},
                run_token="run-1",
                worker_boot_id=ai_job_service.WORKER_BOOT_ID,
            )
        )

    with pytest.raises(AttemptFencedError):
        asyncio.run(_run())

    # 外层事务 rollback：batch/items/audit 全部不存在。
    assert db.query(SddRequirementImportBatch).count() == 0
    assert db.query(SddRequirementImportItem).count() == 0
    assert db.query(SddRequirementAuditLog).count() == 0
    saved = db.query(SddAiJob).filter(SddAiJob.id == "preview-job").first()
    assert saved.status == AiJobStatus.RUNNING


def test_requirement_preview_success_commits_batch_with_job(monkeypatch):
    """SUCCESS 与 batch/items/audit 必须同事务提交（doc §7.4）。"""
    from app.domains.workspace_asset.models.workspace_asset import (
        SddRequirementAuditLog,
        SddRequirementImportBatch,
        SddRequirementImportItem,
    )
    from app.domains.workspace_asset.services import workspace_asset_service as was

    factory = _session_factory()
    db = factory()
    _seed_preview_job(db)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)

    evidence = convergence.AttemptFinalizerEvidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        process_started=True,
        termination_confirmed_dead=True,
        remote_stop_acknowledged=None,
        failure_code=None,
        error_message=None,
        remaining_pids=(),
        source="runtime",
    )

    async def _run():
        return await ai_job_service.run_db_txn(
            lambda session: was._finalize_requirement_import_sync(
                session,
                job_id="preview-job",
                file_name="requirements.md",
                markdown="# md",
                source_kind="document",
                source_uri=None,
                source_ref=None,
                items=[{"title": "Item 1", "body": "b"}],
                metadata={},
                run_token="run-1",
                worker_boot_id=ai_job_service.WORKER_BOOT_ID,
                evidence=evidence,
            )
        )

    result = asyncio.run(_run())
    assert result["item_count"] == 1
    assert db.query(SddRequirementImportBatch).count() == 1
    assert db.query(SddRequirementImportItem).count() == 1
    assert db.query(SddRequirementAuditLog).count() == 1
    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == "preview-job").first()
    assert saved.status == AiJobStatus.SUCCESS
    assert saved.run_token is None


def test_unknown_death_evidence_converges_orphaned_and_keeps_ownership(monkeypatch):
    """P0-2 验收：UNKNOWN 探测必须落 ORPHANED 且不清 ownership（doc §5.6）。"""
    factory = _session_factory()
    db = factory()
    _job(
        db,
        status=AiJobStatus.TERMINATING,
        run_token="run-1",
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
        pid=5151,
        cancel_requested=True,
    )
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)

    async def _no_broadcast(payload):
        return None

    monkeypatch.setattr(ai_job_service, "_broadcast_job_payload", _no_broadcast)

    async def _run():
        attempt = _make_attempt()
        attempt_token = bind_agent_attempt(attempt)
        runtime = AgentAttemptRuntimeState()
        runtime.record_process_started(_identity(5151))
        runtime.record_termination(
            confirmed_dead=None,
            identity=_identity(5151),
            failure_code="PROCESS_TREE_UNKNOWN",
            remaining_pids=(5151,),
        )
        runtime_token = bind_agent_attempt_runtime(runtime)
        try:
            await ai_job_service._converge_runner_exit(
                attempt,
                runtime,
                ai_job_service.JobExecutionOutcome(requested_status=None),
            )
        finally:
            reset_agent_attempt_runtime(runtime_token)
            reset_agent_attempt(attempt_token)

    asyncio.run(_run())

    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.status == AiJobStatus.ORPHANED
    assert saved.process_pid == 5151
    assert saved.run_token == "run-1"


# ────────────── P1-5：远程 reaper 使用持久化 stop locator（doc §10） ──────────────


def _seed_orphaned_remote_job(db, *, token="run-remote", backend="dsh", session_id="persisted-session-1"):
    job = SddAiJob(
        id="remote-reap-job",
        workspace_id="ws-1",
        task_id="task-1",
        channel=AiJobChannel.TASK_CHAT,
        queue_key=f"{AiJobChannel.TASK_CHAT.value}:task-1",
        status=AiJobStatus.ORPHANED,
        creator_id="user-1",
        run_token=token,
        worker_boot_id="old-worker-boot",
        process_execution_kind=EXECUTION_KIND_REMOTE_SESSION,
        agent_backend=backend,
        session_id=session_id,
        orphaned_at=datetime.utcnow() - timedelta(minutes=5),
        first_failure_at=datetime.utcnow() - timedelta(minutes=5),
        lease_expires_at=datetime.utcnow() - timedelta(minutes=5),
    )
    db.add(job)
    db.commit()
    return job


class _FakeRemoteBackend:
    def __init__(self, *, acknowledged=True, failure_code=None):
        self.calls: list[str] = []
        self._acknowledged = acknowledged
        self._failure_code = failure_code

    async def cancel(self, run_id=None, **kwargs):
        self.calls.append(str(run_id or ""))
        return AgentStopResult(
            execution_kind=EXECUTION_KIND_REMOTE_SESSION,
            stop_acknowledged=self._acknowledged,
            failure_code=self._failure_code,
            error_message=None if self._acknowledged else "cancel rejected",
        )


def test_remote_reaper_uses_persisted_backend_and_session_id(monkeypatch):
    factory = _session_factory()
    db = factory()
    _seed_orphaned_remote_job(db)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)

    fake_backend = _FakeRemoteBackend(acknowledged=True)
    monkeypatch.setattr(
        "app.agents.selection.create_agent_backend_by_name",
        lambda name: fake_backend,
    )

    async def _no_broadcast(payload):
        return None

    monkeypatch.setattr(ai_job_service, "_broadcast_job_payload", _no_broadcast)

    reclaimed = asyncio.run(ai_job_service.reap_stale_jobs())
    assert reclaimed == 1
    # 调用参数来自持久化行，而不是内存 runtime（doc §10.4.2）。
    assert fake_backend.calls == ["persisted-session-1"]

    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == "remote-reap-job").first()
    assert saved.status == AiJobStatus.INTERRUPTED
    assert saved.run_token is None
    # ACK 后不再反复进入 reaper。
    rows = ai_job_service._list_reclaimable_jobs_sync()
    assert all(row["job_id"] != "remote-reap-job" for row in rows)


def test_remote_reaper_nack_remains_orphaned(monkeypatch):
    factory = _session_factory()
    db = factory()
    _seed_orphaned_remote_job(db)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)

    fake_backend = _FakeRemoteBackend(acknowledged=False, failure_code=REMOTE_STOP_UNCONFIRMED)
    monkeypatch.setattr(
        "app.agents.selection.create_agent_backend_by_name",
        lambda name: fake_backend,
    )

    async def _no_broadcast(payload):
        return None

    monkeypatch.setattr(ai_job_service, "_broadcast_job_payload", _no_broadcast)

    reclaimed = asyncio.run(ai_job_service.reap_stale_jobs())
    # NACK 也算完成一轮收割 bookkeeping，但 job 保持 ORPHANED。
    assert reclaimed == 1

    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == "remote-reap-job").first()
    assert saved.status == AiJobStatus.ORPHANED
    # ownership 必须保留（doc §10.4.3）。
    assert saved.run_token is not None
    assert saved.next_reap_at is not None


def test_remote_reaper_missing_locator_never_claims_remote_death(monkeypatch):
    """缺少持久化 backend/session id 时必须 NACK，不得声称远程 session 已停止。"""
    factory = _session_factory()
    db = factory()
    _seed_orphaned_remote_job(db, backend=None, session_id=None)
    monkeypatch.setattr(ai_job_service, "SessionLocal", factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)

    async def _no_broadcast(payload):
        return None

    monkeypatch.setattr(ai_job_service, "_broadcast_job_payload", _no_broadcast)

    row = {
        "job_id": "remote-reap-job",
        "run_token": "run-remote",
        "reason": "WORKER_RESTART",
        "execution_kind": EXECUTION_KIND_REMOTE_SESSION,
        "agent_backend": None,
        "session_id": None,
    }
    result = asyncio.run(ai_job_service._stop_attempt_processes(row, "run-remote"))
    assert isinstance(result, AgentStopResult)
    assert result.stop_acknowledged is False
    assert result.failure_code == "REMOTE_STOP_LOCATOR_MISSING"
