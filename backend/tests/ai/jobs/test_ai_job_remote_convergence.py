"""Agent attempt 收敛验收（原 test_ai_job_convergence.py，doc V3 §14）。

覆盖：
- 14.3 远程 Agent：REMOTE_SESSION ack/失败/未确认的决策表；
- P1-3 JobExecutionOutcome（doc §8）；
- P1-5 远程 reaper 使用持久化 stop locator（doc §10）；
- 远程 NORMAL_FINALIZE 证据底线（doc 修复方案 §8.3）。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from tests.ai.jobs.ai_job_test_utils import (
    _job,
    _no_broadcast,
    _session_factory,
    patch_ai_job_db,
)
from app.agents.contract import (
    EXECUTION_KIND_REMOTE_SESSION,
    AgentAttemptContext,
    AgentAttemptRuntimeState,
    AgentStopResult,
    bind_agent_attempt,
    bind_agent_attempt_runtime,
    reset_agent_attempt,
    reset_agent_attempt_runtime,
)
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services import ai_job_convergence_service as convergence
from app.domains.ai.services.ai_job_convergence_service import (
    AttemptConvergenceRequest,
    ConvergenceIntent,
    REMOTE_STOP_UNCONFIRMED,
    evidence_from_stop_result,
)
from app.domains.ai.services.jobs import executors as ai_executors
from app.domains.ai.services.jobs import publishing as ai_publishing
from app.domains.ai.services.jobs import queue_runner as ai_queue_runner
from app.domains.ai.services.jobs import reaper as ai_reaper
from app.domains.ai.services.jobs import registry as ai_registry


# ────────────────────── 14.3 远程 Agent ──────────────────────


def _remote_job(db, *, status=AiJobStatus.TERMINATING, cancel_requested=False):
    return _job(
        db,
        status=status,
        run_token="run-1",
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
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
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
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
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
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
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
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


# ────────────── P1-3：JobExecutionOutcome（doc §8） ──────────────


def _remote_attempt():
    return AgentAttemptContext(
        job_id="convergence-job",
        task_id="task-1",
        queue_key="TASK_CHAT:task-1",
        run_token="run-1",
        worker_id="w",
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
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
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
        execution_kind=EXECUTION_KIND_REMOTE_SESSION,
        pid=None,
        cancel_requested=True,
    )
    patch_ai_job_db(monkeypatch, factory)
    monkeypatch.setattr(ai_publishing, "broadcast_job_payload", _no_broadcast)

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
            await ai_queue_runner._converge_runner_exit(
                attempt,
                runtime,
                ai_executors.JobExecutionOutcome(
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
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
        execution_kind=EXECUTION_KIND_REMOTE_SESSION,
        pid=None,
        cancel_requested=True,
    )
    patch_ai_job_db(monkeypatch, factory)
    monkeypatch.setattr(ai_publishing, "broadcast_job_payload", _no_broadcast)

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
            await ai_queue_runner._converge_runner_exit(
                attempt,
                runtime,
                ai_executors.JobExecutionOutcome(requested_status=None),
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
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
        execution_kind=EXECUTION_KIND_REMOTE_SESSION,
        pid=None,
        cancel_requested=True,
    )
    patch_ai_job_db(monkeypatch, factory)
    monkeypatch.setattr(ai_publishing, "broadcast_job_payload", _no_broadcast)

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
            await ai_queue_runner._converge_runner_exit(
                attempt,
                runtime,
                ai_executors.JobExecutionOutcome(
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
        self.close_calls: int = 0
        self._acknowledged = acknowledged
        self._failure_code = failure_code

    async def cancel_persisted_session(self, session_id: str) -> AgentStopResult:
        # fake 签名与正式 contract 一致：显式 session id，不用宽松 **kwargs。
        self.calls.append(str(session_id or ""))
        return AgentStopResult(
            execution_kind=EXECUTION_KIND_REMOTE_SESSION,
            stop_acknowledged=self._acknowledged,
            failure_code=self._failure_code,
            error_message=None if self._acknowledged else "cancel rejected",
        )

    async def close(self) -> None:
        self.close_calls += 1


def test_remote_reaper_uses_persisted_backend_and_session_id(monkeypatch):
    factory = _session_factory()
    db = factory()
    _seed_orphaned_remote_job(db)
    patch_ai_job_db(monkeypatch, factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)

    fake_backend = _FakeRemoteBackend(acknowledged=True)
    monkeypatch.setattr(
        "app.agents.selection.create_agent_backend_by_name",
        lambda name: fake_backend,
    )
    monkeypatch.setattr(ai_publishing, "broadcast_job_payload", _no_broadcast)

    reclaimed = asyncio.run(ai_reaper.reap_stale_jobs())
    assert reclaimed == 1
    # 调用参数来自持久化行，而不是内存 runtime（doc §10.4.2）。
    assert fake_backend.calls == ["persisted-session-1"]

    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == "remote-reap-job").first()
    assert saved.status == AiJobStatus.INTERRUPTED
    assert saved.run_token is None
    # ACK 后不再反复进入 reaper。
    rows = ai_reaper.list_reclaimable_jobs_sync()
    assert all(row["job_id"] != "remote-reap-job" for row in rows)


def test_remote_reaper_nack_remains_orphaned(monkeypatch):
    factory = _session_factory()
    db = factory()
    _seed_orphaned_remote_job(db)
    patch_ai_job_db(monkeypatch, factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)

    fake_backend = _FakeRemoteBackend(acknowledged=False, failure_code=REMOTE_STOP_UNCONFIRMED)
    monkeypatch.setattr(
        "app.agents.selection.create_agent_backend_by_name",
        lambda name: fake_backend,
    )
    monkeypatch.setattr(ai_publishing, "broadcast_job_payload", _no_broadcast)

    reclaimed = asyncio.run(ai_reaper.reap_stale_jobs())
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
    patch_ai_job_db(monkeypatch, factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)
    monkeypatch.setattr(ai_publishing, "broadcast_job_payload", _no_broadcast)

    row = {
        "job_id": "remote-reap-job",
        "run_token": "run-remote",
        "reason": "WORKER_RESTART",
        "execution_kind": EXECUTION_KIND_REMOTE_SESSION,
        "agent_backend": None,
        "session_id": None,
    }
    result = asyncio.run(ai_reaper.stop_attempt_processes(row, "run-remote"))
    assert isinstance(result, AgentStopResult)
    assert result.stop_acknowledged is False
    assert result.failure_code == "REMOTE_STOP_LOCATOR_MISSING"


# ────────────────── 远程 NORMAL_FINALIZE 证据底线（doc 修复方案 §8.3）──────────────────


def _remote_normal_request(
    *,
    requested_status=AiJobStatus.INTERRUPTED,
    remote_session_started=True,
    provider_outcome_seen=False,
    remote_stop_acknowledged=None,
    failure_code=None,
    error_message=None,
) -> AttemptConvergenceRequest:
    evidence = convergence.AttemptFinalizerEvidence(
        execution_kind=EXECUTION_KIND_REMOTE_SESSION,
        process_started=False,
        termination_confirmed_dead=None,
        remote_stop_acknowledged=remote_stop_acknowledged,
        failure_code=failure_code,
        error_message=error_message,
        remaining_pids=(),
        source="remote",
        remote_session_started=remote_session_started,
        provider_outcome_seen=provider_outcome_seen,
    )
    return AttemptConvergenceRequest(
        job_id="convergence-job",
        run_token="run-1",
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
        requested_status=requested_status,
        reason="transport disconnected",
        evidence=evidence,
        intent=ConvergenceIntent.NORMAL_FINALIZE,
    )


def _seed_running_remote_job(db):
    job = SddAiJob(
        id="convergence-job",
        workspace_id="ws-1",
        channel=AiJobChannel.TASK_CHAT,
        queue_key="TASK_CHAT:task-1",
        status=AiJobStatus.RUNNING,
        creator_id="user-1",
        run_token="run-1",
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
        process_execution_kind=EXECUTION_KIND_REMOTE_SESSION,
        agent_backend="dsh",
        session_id="persisted-session-1",
        task_id="task-1",
    )
    db.add(job)
    db.commit()
    return job


def test_remote_normal_failure_without_outcome_or_stop_ack_is_orphaned():
    """P1-2 最小反例：会话已建立、无 outcome、无 ACK → ORPHANED 保留 ownership。"""
    factory = _session_factory()
    db = factory()
    _seed_running_remote_job(db)
    request = _remote_normal_request(
        requested_status=AiJobStatus.INTERRUPTED,
        error_message="transport disconnected",
    )
    result = convergence.converge_job_attempt_sync(db, request)

    assert result.changed is True
    assert result.status == AiJobStatus.ORPHANED.value
    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    # ownership / durable locator 必须保留给 reaper。
    assert saved.run_token == "run-1"
    assert saved.session_id == "persisted-session-1"


def test_remote_normal_stop_nack_is_orphaned():
    """stop NACK（ack=False）同样不得清 ownership。"""
    factory = _session_factory()
    db = factory()
    _seed_running_remote_job(db)
    request = _remote_normal_request(remote_stop_acknowledged=False)
    result = convergence.converge_job_attempt_sync(db, request)

    assert result.changed is True
    assert result.status == AiJobStatus.ORPHANED.value
    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.run_token == "run-1"


def test_remote_normal_result_allows_business_terminal():
    """provider outcome 明确完成 → 允许请求的业务终态并清 ownership。"""
    factory = _session_factory()
    db = factory()
    _seed_running_remote_job(db)
    request = _remote_normal_request(
        requested_status=AiJobStatus.FAILED,
        provider_outcome_seen=True,
    )
    result = convergence.converge_job_attempt_sync(db, request)

    assert result.changed is True
    assert result.status == AiJobStatus.FAILED.value
    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.run_token is None
    assert saved.finished_at is not None


def test_remote_session_never_started_allows_clean_failure():
    """远程会话从未建立 → 没有服务端回合需要停止，允许干净失败。"""
    factory = _session_factory()
    db = factory()
    _seed_running_remote_job(db)
    request = _remote_normal_request(
        requested_status=AiJobStatus.FAILED,
        remote_session_started=False,
    )
    result = convergence.converge_job_attempt_sync(db, request)

    assert result.changed is True
    assert result.status == AiJobStatus.FAILED.value
    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.run_token is None


def test_remote_stop_ack_allows_interrupted():
    """明确 stop ACK → 允许失败/中断业务终态。"""
    factory = _session_factory()
    db = factory()
    _seed_running_remote_job(db)
    request = _remote_normal_request(
        requested_status=AiJobStatus.INTERRUPTED,
        remote_stop_acknowledged=True,
    )
    result = convergence.converge_job_attempt_sync(db, request)

    assert result.changed is True
    assert result.status == AiJobStatus.INTERRUPTED.value
    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.run_token is None
