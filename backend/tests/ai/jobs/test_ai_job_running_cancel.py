"""Agent attempt 收敛验收（原 test_ai_job_convergence.py，doc V3 §14）。

覆盖：
- 14.2 运行中取消：TERMINATING 在 runtime 释放前立即收敛，不等待 lease；
- 14.4 广播语义：非终态绝不产生 final 事件；
- P1-2 preview fence 回滚业务副作用（doc §7）。
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from tests.ai.jobs.ai_job_test_utils import (
    _identity,
    _job,
    _make_attempt,
    _no_broadcast,
    _owned_job,
    _session_factory,
    _terminate_request,
    patch_ai_job_db,
)
from app.agents.contract import (
    EXECUTION_KIND_LOCAL_PROCESS,
    AgentAttemptRuntimeState,
    bind_agent_attempt,
    bind_agent_attempt_runtime,
    reset_agent_attempt,
    reset_agent_attempt_runtime,
)
from app.core.offload import run_db_txn
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services import ai_job_convergence_service as convergence
from app.domains.ai.services.jobs import attempts as ai_attempts
from app.domains.ai.services.jobs import executors as ai_executors
from app.domains.ai.services.jobs import publishing as ai_publishing
from app.domains.ai.services.jobs import queue_runner as ai_queue_runner
from app.domains.ai.services.jobs import registry as ai_registry
from app.agents.supervision import process_supervisor
from app.domains.websocket.ws.manager import manager as task_ws_manager


# ────────────────────── 14.2 运行中取消 ──────────────────────


def test_running_cancel_with_dead_proof_converges_cancelled_immediately(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.TERMINATING, cancel_requested=True)
    patch_ai_job_db(monkeypatch, factory)

    payload = ai_attempts.finish_termination_sync(
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


def test_interrupt_mode_converges_resumable_interrupted(monkeypatch):
    """INTERRUPT 模式（用户临时中断）+ 死亡已证明：TASK_CHAT 落可恢复
    INTERRUPTED，而不是被 cancel_requested_at 推导成 CANCELLED。"""
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.TERMINATING, cancel_requested=True)
    patch_ai_job_db(monkeypatch, factory)

    row = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    evidence = ai_attempts.termination_evidence_for_row(
        row, confirmed_dead=True, failure_code="USER_INTERRUPT", reason="pause for edits",
    )
    payload = ai_attempts.converge_termination_sync(
        "convergence-job",
        "run-1",
        evidence=evidence,
        reason="pause for edits",
        failure_code="USER_INTERRUPT",
        termination_mode="INTERRUPT",
    )

    assert payload["status"] == AiJobStatus.INTERRUPTED.value
    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.status == AiJobStatus.INTERRUPTED
    # ownership 已清空：恢复流程可以直接重建 attempt。
    assert saved.run_token is None
    assert saved.process_pid is None


def test_cancel_mode_still_converges_cancelled(monkeypatch):
    """CANCEL 模式行为不变：取消请求 + 死亡已证明 → CANCELLED。"""
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.TERMINATING, cancel_requested=True)
    patch_ai_job_db(monkeypatch, factory)

    row = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    evidence = ai_attempts.termination_evidence_for_row(
        row, confirmed_dead=True, failure_code="CANCEL_REQUESTED", reason="USER_CANCEL",
    )
    payload = ai_attempts.converge_termination_sync(
        "convergence-job",
        "run-1",
        evidence=evidence,
        reason="USER_CANCEL",
        failure_code="CANCEL_REQUESTED",
    )

    assert payload["status"] == AiJobStatus.CANCELLED.value


def test_running_cancel_unconfirmed_tree_keeps_ownership(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.TERMINATING, pid=5151, cancel_requested=True)
    patch_ai_job_db(monkeypatch, factory)

    payload = ai_attempts.finish_termination_sync(
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
    assert saved.worker_boot_id == ai_registry.WORKER_BOOT_ID
    assert saved.next_reap_at is not None


def test_running_cancel_never_started_local_process_converges_cancelled():
    factory = _session_factory()
    db = factory()
    _job(
        db,
        status=AiJobStatus.TERMINATING,
        run_token="run-1",
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
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
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.TERMINATING, cancel_requested=True)
    patch_ai_job_db(monkeypatch, factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)
    monkeypatch.setattr(ai_publishing, "broadcast_job_payload", _no_broadcast)

    async def _fake_stop(token, reason):
        return None

    monkeypatch.setattr(process_supervisor, "stop_attempt", _fake_stop)

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
            await ai_queue_runner._converge_runner_exit(
                attempt, runtime, ai_executors.JobExecutionOutcome(requested_status=None)
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
    patch_ai_job_db(monkeypatch, factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)
    monkeypatch.setattr(ai_publishing, "broadcast_job_payload", _no_broadcast)

    async def _fake_stop(token, reason):
        return None

    monkeypatch.setattr(process_supervisor, "stop_attempt", _fake_stop)

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
            await ai_queue_runner._converge_runner_exit(
                attempt, runtime, ai_executors.JobExecutionOutcome(requested_status=None)
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
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
        pid=None,
    )
    patch_ai_job_db(monkeypatch, factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)
    monkeypatch.setattr(ai_publishing, "broadcast_job_payload", _no_broadcast)

    async def _run():
        attempt = _make_attempt()
        attempt_token = bind_agent_attempt(attempt)
        runtime = AgentAttemptRuntimeState()
        runtime_token = bind_agent_attempt_runtime(runtime)
        try:
            await ai_queue_runner._converge_runner_exit(
                attempt,
                runtime,
                ai_executors.JobExecutionOutcome(
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
    monkeypatch.setattr(task_ws_manager, "send_message_to_room", capture.send_message_to_room)
    patch_ai_job_db(monkeypatch, factory)

    asyncio.run(ai_publishing.publish_job_state("convergence-job"))

    types = [message[1] for message in capture.messages]
    assert types and all(t == "chat_job_update" for t in types)
    assert not any(t in ("chat_job_done", "chat_job_failed") for t in types)


def test_broadcast_cancelled_emits_exactly_one_final_event(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.CANCELLED)
    capture = _RoomCapture()
    monkeypatch.setattr(task_ws_manager, "send_message_to_room", capture.send_message_to_room)
    patch_ai_job_db(monkeypatch, factory)

    asyncio.run(ai_publishing.publish_job_state("convergence-job"))

    types = [message[1] for message in capture.messages]
    assert types.count("chat_job_update") == 1
    assert types.count("chat_job_failed") == 1
    assert "chat_job_done" not in types


def test_broadcast_success_emits_exactly_one_done_event(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.SUCCESS)
    capture = _RoomCapture()
    monkeypatch.setattr(task_ws_manager, "send_message_to_room", capture.send_message_to_room)
    patch_ai_job_db(monkeypatch, factory)

    asyncio.run(ai_publishing.publish_job_state("convergence-job"))

    types = [message[1] for message in capture.messages]
    assert types.count("chat_job_update") == 1
    assert types.count("chat_job_done") == 1


def test_broadcast_orphaned_never_emits_final_event(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.ORPHANED)
    capture = _RoomCapture()
    monkeypatch.setattr(task_ws_manager, "send_message_to_room", capture.send_message_to_room)
    patch_ai_job_db(monkeypatch, factory)

    asyncio.run(ai_publishing.publish_job_state("convergence-job"))

    types = [message[1] for message in capture.messages]
    assert types and all(t == "chat_job_update" for t in types)


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
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
        process_execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        cancel_requested_at=datetime.utcnow() if cancel_requested else None,
    )
    db.add(job)
    db.commit()
    return job


def test_requirement_preview_fence_rolls_back_batch_and_items(monkeypatch):
    """fence 命中时 finalizer 必须抛出专用异常，外层事务整体 rollback。"""
    from app.domains.ai.services.ai_job_convergence_service import AttemptFencedError
    from app.domains.workspace_asset.models.workspace_asset import (
        SddRequirementAuditLog,
        SddRequirementImportBatch,
        SddRequirementImportItem,
    )
    from app.domains.workspace_asset.services.requirements.preview import runner as preview_runner

    factory = _session_factory()
    db = factory()
    _seed_preview_job(db, cancel_requested=True)
    patch_ai_job_db(monkeypatch, factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)

    async def _run():
        await run_db_txn(
            lambda session: preview_runner.finalize_requirement_import_sync(
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
                worker_boot_id=ai_registry.WORKER_BOOT_ID,
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
    from app.domains.workspace_asset.services.requirements.preview import runner as preview_runner

    factory = _session_factory()
    db = factory()
    _seed_preview_job(db)
    patch_ai_job_db(monkeypatch, factory)
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
        return await run_db_txn(
            lambda session: preview_runner.finalize_requirement_import_sync(
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
                worker_boot_id=ai_registry.WORKER_BOOT_ID,
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
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
        pid=5151,
        cancel_requested=True,
    )
    patch_ai_job_db(monkeypatch, factory)
    monkeypatch.setattr(ai_publishing, "broadcast_job_payload", _no_broadcast)

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
    assert saved.status == AiJobStatus.ORPHANED
    assert saved.process_pid == 5151
    assert saved.run_token == "run-1"
