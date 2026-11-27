import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.domains.api_mock.models.api_mock
import app.domains.task.models.test_result
import app.domains.workflow.models.task_change
import app.domains.workspace_asset.models.workspace_asset  # noqa: F401
from app.agents.contract import AgentRunResult
from app.agents.supervision import TerminationResult
from app.database import Base
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services.jobs import attempts as ai_attempts
from app.domains.ai.services.jobs import (
    executors as ai_executors,
)
from app.domains.ai.services.jobs import (
    publishing as ai_publishing,
)
from app.domains.ai.services.jobs import (
    registry as ai_registry,
)
from app.domains.ai.services.jobs import (
    state as ai_state,
)
from app.domains.ai.services.jobs import (
    store as ai_store,
)
from app.domains.ai.services.jobs import (
    workers as ai_workers,
)
from app.domains.ai.services.jobs.executors import (
    task_chat as ai_task_chat,
)
from app.domains.ai.services.jobs.registry import runtime as ai_runtime
from app.domains.auth.models.user import User, Workspace, WorkspaceMember, WorkspaceRole
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.chat_submission import TaskChatSubmission
from app.domains.task.models.session_turn import TaskSessionTurn, TaskSessionTurnStatus
from app.domains.task.models.task import (
    SddTask,
    TaskStatus,
)
from app.domains.task.services import (
    chat_submission_service,
    task_attempt_recovery_service,
    task_session_control_service,
    task_session_service,
)
from app.domains.task.services.conversation import history as task_conversation_history
from tests.ai.jobs.ai_job_test_utils import patch_ai_job_db


def _build_session(*, expire_on_commit=False, autoflush=True):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=expire_on_commit, autoflush=autoflush)


def _seed_task(db, *, task_status=TaskStatus.RUNNING, job_status=AiJobStatus.RUNNING):
    user = User(id="user-1", email="user@example.com", hashed_password="x", display_name="User")
    workspace = Workspace(id="ws-1", name="Workspace", owner_id=user.id)
    task = SddTask(
        id="task-1",
        workspace_id=workspace.id,
        creator_id=user.id,
        name="Task",
        project_path="G:/tmp/task-1",
        status=task_status,
        status_run_id="job-1",
        session_generation=0,
        session_revision=0,
    )
    job = SddAiJob(
        id="job-1",
        workspace_id=workspace.id,
        task_id=task.id,
        channel=AiJobChannel.TASK_CHAT,
        queue_key=f"{AiJobChannel.TASK_CHAT.value}:{task.id}",
        status=job_status,
        session_generation=0,
        session_revision=0,
        prompt_text="work on this",
        creator_id=user.id,
        session_id="session-1",
    )
    member = WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.OWNER)
    db.add_all([user, workspace, member, task, job])
    db.commit()
    return task, job


def test_manual_interrupt_cannot_replace_an_already_accepted_job_cancel():
    from app.domains.ai.services.ai_job_convergence_service import (
        AttemptTerminationRequest,
        request_attempt_termination_in_txn,
    )

    factory = _build_session()
    with factory() as db:
        task, job = _seed_task(db)
        result = request_attempt_termination_in_txn(db, AttemptTerminationRequest(job_id=job.id, mode="CANCEL"))
        assert result.changed
        db.commit()
        with pytest.raises(task_session_control_service.TaskSessionControlError) as blocked:
            task_session_control_service._accept_interrupt_command(
                db,
                task.id,
                task.creator_id,
                "stop-after-cancel",
                task.status_seq,
                "pause",
                user_requested=True,
            )
        assert blocked.value.status_code == 409
        assert task.status == TaskStatus.RUNNING and task.interrupt_kind is None
        assert job.status == AiJobStatus.TERMINATING and job.context_json["termination_mode"] == "CANCEL"


@pytest.mark.parametrize("confirmed_dead", [True, False])
def test_task_interrupt_converges_unclaimed_job_with_stop_evidence(monkeypatch, confirmed_dead):
    SessionLocal = _build_session()
    db = SessionLocal()
    task, job = _seed_task(db)

    class _FakeEngine:
        task_id = task.id
        current_job_id = job.id
        running = True
        session_id = "session-1"
        attempt = None

        def __init__(self):
            self.interrupted = False

        async def interrupt(self):
            self.interrupted = True
            self.running = False
            return TerminationResult(confirmed_dead=confirmed_dead, root_return_code=0 if confirmed_dead else None)

    engine = _FakeEngine()
    published = []
    events = []

    async def _publish_job(job_id):
        published.append(job_id)

    async def _broadcast(task_id, payload):
        events.append((task_id, payload["status"], payload["job"]["id"]))

    monkeypatch.setattr(task_session_control_service, "get_engine", lambda _task_id: engine)
    monkeypatch.setattr(ai_publishing, "publish_job", _publish_job)
    monkeypatch.setattr(task_session_control_service, "_publish_interruption", _broadcast)

    payload = asyncio.run(
        task_session_control_service.interrupt_task(
            db,
            task=task,
            actor_user_id="user-1",
            reason="pause for edits",
        )
    )

    db.refresh(task)
    db.refresh(job)
    assert engine.interrupted is True
    assert task.status == TaskStatus.INTERRUPTED
    assert task.session_id == "session-1"
    assert task.interrupt_reason == "pause for edits"
    assert job.status == (AiJobStatus.INTERRUPTED if confirmed_dead else AiJobStatus.ORPHANED)
    assert (job.next_reap_at is not None) is (not confirmed_dead)
    assert job.session_id == "session-1"
    assert published == ["job-1"]
    assert events == [("task-1", "INTERRUPTED", "job-1")]
    assert payload["status"] == TaskStatus.INTERRUPTED.value


def test_task_interrupt_with_claimed_attempt_converges_to_resumable_interrupted(monkeypatch):
    """带 run_token 的 RUNNING 作业临时中断：job 必须落可恢复 INTERRUPTED。

    回归：INTERRUPT 模式经统一 convergence 推导时曾被
    ``cancel_requested_at -> CANCELLED`` 吞掉，导致任务 INTERRUPTED 但
    没有任何 INTERRUPTED 作业，pre_input 提交/恢复会话报 409。
    """
    SessionLocal = _build_session()
    db = SessionLocal()
    task, job = _seed_task(db)
    job.status = AiJobStatus.RUNNING
    job.run_token = "run-interrupt-1"
    job.worker_boot_id = ai_registry.WORKER_BOOT_ID
    db.commit()
    patch_ai_job_db(monkeypatch, SessionLocal)

    class _FakeEngine:
        task_id = task.id
        current_job_id = job.id
        running = True
        session_id = "session-1"
        attempt = SimpleNamespace(run_token=job.run_token, worker_boot_id=job.worker_boot_id)

        async def interrupt(self):
            return TerminationResult(confirmed_dead=True, root_return_code=0)

    engine = _FakeEngine()
    published = []
    events = []
    reason = "DSH rejected the image input because this configured model does not support images."

    async def _publish_job(job_id):
        published.append(job_id)

    async def _broadcast(task_id, payload):
        events.append((task_id, payload["status"], payload["job"]["id"]))

    monkeypatch.setattr(task_session_control_service, "get_engine", lambda _task_id: engine)
    monkeypatch.setattr(ai_publishing, "publish_job", _publish_job)
    monkeypatch.setattr(task_session_control_service, "_publish_interruption", _broadcast)

    payload = asyncio.run(
        task_session_control_service.interrupt_task(
            db,
            task=task,
            actor_user_id="user-1",
            reason=reason,
        )
    )

    db.refresh(task)
    db.refresh(job)
    assert task.status == TaskStatus.INTERRUPTED
    assert job.status == AiJobStatus.INTERRUPTED
    assert job.failure_code == "SYSTEM_INTERRUPT"
    assert job.terminal_reason == reason
    assert job.session_id == "session-1"
    # ownership 已清空，恢复流程可以直接基于该行重建 attempt。
    assert job.run_token is None
    assert job.process_pid is None
    assert published == [job.id]
    assert events == [(task.id, "INTERRUPTED", job.id)]
    assert payload["status"] == TaskStatus.INTERRUPTED.value
    # 恢复入口现在能找到可恢复作业。
    db.expire_all()
    assert task_session_control_service._find_latest_interrupted_job(db, task) is not None


def test_undo_commits_before_deleted_message_is_accessed_and_ignores_broadcast_failure(monkeypatch):
    """A deleted target ORM row must not convert a durable undo into FAILED."""
    # The production session expires ORM instances after commit.  Keep that
    # behavior here so a deleted target reproduces SQLAlchemy's ObjectDeletedError.
    SessionLocal = _build_session(expire_on_commit=True)
    db = SessionLocal()
    task, job = _seed_task(db, task_status=TaskStatus.RUNNING, job_status=AiJobStatus.SUCCESS)
    task.session_generation = 1
    task.session_revision = 1
    task.session_id = "session-1"
    message = ChatMessage(
        id="message-1",
        task_id=task.id,
        workspace_id=task.workspace_id,
        creator_id="user-1",
        role="user",
        content="remember the old marker",
        message_type="text",
        session_generation=1,
    )
    turn = TaskSessionTurn(
        id="turn-1",
        task_id=task.id,
        workspace_id=task.workspace_id,
        user_message_id=message.id,
        ai_job_id=job.id,
        session_generation=1,
        turn_index=1,
        session_revision=1,
        provider="claude-code",
        provider_session_id="session-1",
        checkpoint_path="G:/tmp/traceforge-undo-checkpoint",
        status=TaskSessionTurnStatus.ACTIVE,
    )
    message.session_turn_id = turn.id
    job.session_turn_id = turn.id
    job.session_generation = 1
    job.session_revision = 1
    db.add_all([message, turn])
    db.commit()
    task_id = str(task.id)
    job_id = str(job.id)
    message_id = str(message.id)
    turn_id = str(turn.id)

    @asynccontextmanager
    async def _fake_task_lock(*_args, **_kwargs):
        yield

    async def _fake_lock_provider():
        return SimpleNamespace(backend_name="redis")

    async def _raise_broadcast(*_args, **_kwargs):
        raise RuntimeError("websocket disconnected")

    monkeypatch.setattr(task_session_service, "get_lock_provider", _fake_lock_provider)
    monkeypatch.setattr(task_session_service, "lock_task", _fake_task_lock)
    monkeypatch.setattr(task_session_service, "_stop_engine_and_wait", lambda _task_id: _noop_async())
    monkeypatch.setattr(
        task_session_service.skill_runtime_trace_service,
        "wait_for_pending_writes",
        lambda *_args, **_kwargs: _noop_async(),
    )
    monkeypatch.setattr(
        task_session_service.task_session_snapshot_service,
        "backup_current_provider",
        lambda *_args, **_kwargs: _noop_async(),
    )
    monkeypatch.setattr(
        task_session_service.task_session_snapshot_service, "restore_provider", lambda *_args, **_kwargs: _noop_async()
    )
    monkeypatch.setattr(
        task_session_service.task_session_snapshot_service, "restore_worktree", lambda *_args, **_kwargs: _noop_async()
    )
    monkeypatch.setattr(
        task_session_service.task_session_snapshot_service,
        "cleanup_checkpoint",
        lambda *_args, **_kwargs: _noop_async(),
    )
    monkeypatch.setattr(task_session_service.manager, "send_message_to_room", _raise_broadcast)

    payload = asyncio.run(
        task_session_service.undo_task_message(
            db,
            task=task,
            message_id=message_id,
            actor_user_id="user-1",
            operation_id="undo-operation-1",
        )
    )

    assert payload["target_message_id"] == "message-1"
    assert payload["status"] == TaskSessionTurnStatus.REVERTED.value
    with SessionLocal() as retry_db:
        replay = task_session_service._prepare_undo_sync(
            retry_db, task_id=task_id, message_id=message_id, actor_user_id="user-1", operation_id="undo-operation-1"
        )
        assert replay == {"duplicate_result": payload}
        with pytest.raises(task_session_service.TaskSessionUndoError, match="identity"):
            task_session_service._prepare_undo_sync(
                retry_db,
                task_id=task_id,
                message_id="different-message",
                actor_user_id="user-1",
                operation_id="undo-operation-1",
            )
    check_db = SessionLocal()
    try:
        assert check_db.query(ChatMessage).filter(ChatMessage.id == message_id).first() is None
        stored_job = check_db.query(SddAiJob).filter(SddAiJob.id == job_id).one()
        assert stored_job.prompt_text is None
        assert stored_job.result_json == {"redacted": True, "reason": "session_undo"}
        assert (
            check_db.query(TaskSessionTurn).filter(TaskSessionTurn.id == turn_id).one().status
            == TaskSessionTurnStatus.REVERTED
        )
        assert check_db.query(SddTask).filter(SddTask.id == task_id).one().status == TaskStatus.ROUND_COMPLETED
    finally:
        check_db.close()


async def _noop_async():
    return None


def test_undo_stop_engine_does_not_swallow_stop_failure(monkeypatch):
    closed = []

    class _FakeCli:
        def is_running(self):
            return False

        async def close(self):
            closed.append(True)

    class _FakeEngine:
        running = False
        cli = _FakeCli()

        async def stop(self):
            raise RuntimeError("stop failed")

    monkeypatch.setattr(task_session_service, "get_engine", lambda _task_id: _FakeEngine())

    with pytest.raises(RuntimeError, match="stop failed"):
        asyncio.run(task_session_service._stop_engine_and_wait("task-1"))
    assert closed == [True]


def test_task_interrupt_cancels_pending_job_when_engine_not_running(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    task, job = _seed_task(db, task_status=TaskStatus.RUNNING, job_status=AiJobStatus.PENDING)

    published = []
    events = []

    async def _publish_job(job_id):
        published.append(job_id)

    async def _broadcast(task_id, payload):
        events.append((task_id, payload["status"], payload["job"]["id"]))

    monkeypatch.setattr(task_session_control_service, "get_engine", lambda _task_id: None)
    monkeypatch.setattr(ai_publishing, "publish_job", _publish_job)
    monkeypatch.setattr(task_session_control_service, "_publish_interruption", _broadcast)

    payload = asyncio.run(
        task_session_control_service.interrupt_task(
            db,
            task=task,
            actor_user_id="user-1",
            reason="stop before start",
        )
    )

    db.refresh(task)
    db.refresh(job)
    assert job.status == AiJobStatus.CANCELLED
    assert job.message == "stop before start"
    assert task.status == TaskStatus.INTERRUPTED
    assert published == ["job-1"]
    assert events == [("task-1", "INTERRUPTED", "job-1")]
    assert payload["job"]["status"] == AiJobStatus.CANCELLED.value
    prepared = task_session_control_service._prepare_interrupted_resume(
        db,
        task_id=task.id,
        actor_user_id="user-1",
        idempotency_key=None,
        prompt="Continue the queued task",
        confirm_continue=False,
    )
    assert prepared["old_job_id"] == job.id
    assert prepared["prompt_text"] == "Continue the queued task"


@pytest.mark.parametrize("provider_finished", [False, True])
def test_interrupt_without_engine_only_stops_current_attempt(monkeypatch, provider_finished):
    SessionLocal = _build_session()
    patch_ai_job_db(monkeypatch, SessionLocal)
    with SessionLocal() as db:
        task, job = _seed_task(db)
        task.session_revision = job.session_revision = 2
        job.run_token = "active-token"
        job.worker_boot_id = ai_registry.WORKER_BOOT_ID
        db.add(
            SddAiJob(
                id="earlier-job",
                workspace_id=job.workspace_id,
                task_id=task.id,
                creator_id=job.creator_id,
                queue_key=job.queue_key,
                channel=job.channel,
                status=AiJobStatus.INTERRUPTED,
                prompt_text="earlier prompt",
                session_generation=task.session_generation,
                session_revision=1,
            )
        )
        db.commit()
        monkeypatch.setattr(task_session_control_service, "get_engine", lambda _task_id: None)
        monkeypatch.setattr(ai_publishing, "publish_job", AsyncMock())
        monkeypatch.setattr(task_session_control_service, "_publish_interruption", AsyncMock())
        cancelled = []
        monkeypatch.setattr(ai_registry.runtime, "request_cancel", cancelled.append)

        async def stop():
            return await task_session_control_service.interrupt_task(
                db,
                task=task,
                actor_user_id=task.creator_id,
                command_id="stop-current",
                expected_status_seq=0,
                reason="pause for edits",
            )

        result = asyncio.run(stop())
        assert result["status"] == "INTERRUPTED"
        assert result["job"]["status"] == "TERMINATING"
        db.refresh(job)
        assert job.context_json["termination_mode"] == "INTERRUPT"
        assert db.get(SddAiJob, "earlier-job").status == AiJobStatus.INTERRUPTED
        assert cancelled == [job.id]
        assert asyncio.run(stop())["duplicate"] is True
        assert cancelled == [job.id]
        payload = ai_attempts.finish_termination_sync(
            job.id,
            "active-token",
            confirmed_dead=True,
            reason="stop confirmed",
            failure_code="USER_INTERRUPT",
            recovered_result=AgentRunResult(success=False, result_text="provider aborted")
            if provider_finished
            else None,
        )
        assert payload["status"] == "INTERRUPTED"
        db.refresh(job)
        db.refresh(task)
        assert job.run_token is None
        assert job.interrupt_reason == "pause for edits"
        assert job.terminal_reason == "stop confirmed"
        prepared = task_session_control_service._prepare_interrupted_resume(
            db,
            task_id=task.id,
            actor_user_id=task.creator_id,
            idempotency_key=None,
            prompt="resume current job",
            confirm_continue=False,
        )
        assert prepared["old_job_id"] == job.id


@pytest.mark.asyncio
@pytest.mark.parametrize("early_samples", [0, 2], ids=["expired-since-scan", "early-timer"])
async def test_resume_reaps_the_previous_attempt_when_its_stop_lease_expires(monkeypatch, early_samples):
    from app.domains.ai.services.jobs import reaper

    factory = _build_session()
    with factory() as db:
        task, job = _seed_task(db, task_status=TaskStatus.INTERRUPTED, job_status=AiJobStatus.TERMINATING)
        task_id, job_id = task.id, job.id
        job.context_json = {"termination_mode": "INTERRUPT"}
        job.cancel_requested_at = datetime.utcnow()
        job.lease_expires_at = datetime.utcnow() + timedelta(minutes=1)
        db.commit()

    async def txn(body):
        with factory.begin() as db:
            return body(db)

    async def reap(*, task_id):
        assert task_id == "task-1"
        with factory.begin() as db:
            job = db.get(SddAiJob, job_id)
            if datetime.utcnow() >= job.lease_expires_at:
                job.status = AiJobStatus.INTERRUPTED
                job.lease_expires_at = None

    samples = []

    def lease_remaining(db, task_id):
        assert task_id == "task-1"
        samples.append(task_id)
        if len(samples) <= early_samples:
            # The monotonic wait reaches its wake-up point while the wall
            # clock still reports a live stop lease.
            return 0.001
        db.get(SddAiJob, job_id).lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        return 0

    reaper_spy = AsyncMock(side_effect=reap)
    monkeypatch.setattr(reaper, "reap_stale_jobs", reaper_spy)
    monkeypatch.setattr(task_attempt_recovery_service, "_interrupt_lease_remaining", lease_remaining)
    monkeypatch.setattr(task_attempt_recovery_service.settings, "TASK_SESSION_REVERT_WAIT_SECONDS", 1.0)
    await task_attempt_recovery_service.recover_task_attempts(task_id, run_txn=txn, wait_for_interrupt_lease=True)
    assert reaper_spy.await_count == 2
    assert len(samples) == max(2, early_samples + 1)
    with factory() as db:
        assert db.get(SddAiJob, job_id).status == AiJobStatus.INTERRUPTED


def test_task_resume_requires_interrupted_status(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    task, _job = _seed_task(db, task_status=TaskStatus.FAILED, job_status=AiJobStatus.INTERRUPTED)
    monkeypatch.setattr(task_session_control_service, "get_engine", lambda _task_id: None)
    # run_db_txn 在线程内从 app.database 惰性导入 SessionLocal
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)

    with pytest.raises(task_session_control_service.TaskSessionControlError) as exc:
        asyncio.run(
            task_session_control_service.resume_interrupted_task(
                task_id=task.id,
                actor_user_id="user-1",
                prompt="continue",
            )
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_resume_waits_for_running_job_to_record_abnormal_interruption(monkeypatch):
    from app.domains.ai.services.jobs import reaper

    factory = _build_session()
    with factory() as db:
        task, job = _seed_task(db, task_status=TaskStatus.INTERRUPTED)
        task.status_run_id = None
        task.interrupt_kind = "ABNORMAL"
        job.lease_expires_at = datetime.utcnow() + timedelta(seconds=3)
        db.commit()
        task_id, job_id = task.id, job.id

    read_active = task_attempt_recovery_service.active_statuses
    reads = 0

    def settle_during_wait(db, target):
        nonlocal reads
        reads += 1
        if reads == 3:
            old = db.get(SddAiJob, job_id)
            old.status = AiJobStatus.INTERRUPTED
            old.lease_expires_at = None
        return read_active(db, target)

    monkeypatch.setattr(task_attempt_recovery_service, "active_statuses", settle_during_wait)
    monkeypatch.setattr(reaper, "reap_stale_jobs", AsyncMock())
    monkeypatch.setattr(task_session_control_service, "get_engine", lambda _task_id: SimpleNamespace(running=reads < 3))
    monkeypatch.setattr(chat_submission_service, "schedule", lambda _receipt_id: None)
    patch_ai_job_db(monkeypatch, factory)

    result = await task_session_control_service.resume_interrupted_task(
        task_id=task_id, actor_user_id="user-1", prompt="continue", client_message_id="resume-after-error"
    )

    assert result["submission"]["status"] == "PREPARING"
    with factory() as db:
        row = db.get(TaskChatSubmission, result["submission"]["id"])
        assert row.metadata_json["resumed_from_job_id"] == job_id


@pytest.mark.parametrize("session_id", ["session-1", None])
@pytest.mark.parametrize("checkpoint_fails", [False, True])
def test_task_resume_keeps_a_recoverable_owner_until_checkpoint(monkeypatch, session_id, checkpoint_fails):
    SessionLocal = _build_session(autoflush=False)
    db = SessionLocal()
    task, job = _seed_task(db, task_status=TaskStatus.INTERRUPTED, job_status=AiJobStatus.INTERRUPTED)
    task.session_id = session_id
    job.session_id = session_id
    db.commit()

    enqueued = []
    scheduled = []

    async def _enqueue(job_id):
        enqueued.append(job_id)
        return

    async def _checkpoint(*_args, **_kwargs):
        if checkpoint_fails:
            raise task_session_service.task_session_snapshot_service.TaskSessionSnapshotError("checkpoint failed")
        return {"root": "G:/tmp/fake-session-checkpoint", "worktree": {}, "provider": {}}

    async def _cleanup(_path):
        return None

    monkeypatch.setattr(task_session_control_service, "get_engine", lambda _task_id: None)
    monkeypatch.setattr(ai_publishing, "enqueue_task_chat_job", _enqueue)
    monkeypatch.setattr(chat_submission_service, "schedule", scheduled.append)
    patch_ai_job_db(monkeypatch, SessionLocal)
    monkeypatch.setattr(task_session_service.task_session_snapshot_service, "create_checkpoint", _checkpoint)
    monkeypatch.setattr(task_session_service.task_session_snapshot_service, "cleanup_checkpoint", _cleanup)

    payload = asyncio.run(
        task_session_control_service.resume_interrupted_task(
            task_id=task.id,
            actor_user_id="user-1",
            prompt="use this correction",
            client_message_id="client-resume-1",
        )
    )

    submission_id = payload["submission"]["id"]
    assert payload["submission"]["status"] == "PREPARING"
    assert scheduled == [submission_id]
    db.refresh(job)
    assert job.status == AiJobStatus.INTERRUPTED
    assert db.query(SddAiJob).count() == 1
    asyncio.run(chat_submission_service._run(submission_id))

    db.refresh(task)
    db.refresh(job)
    if checkpoint_fails:
        assert task.status == TaskStatus.INTERRUPTED
        assert job.status == AiJobStatus.INTERRUPTED
        assert db.query(SddAiJob).count() == 1
        assert db.query(ChatMessage).count() == 0
        assert db.get(TaskChatSubmission, submission_id).status == "FAILED"
        assert not enqueued
        return
    resume_job = db.query(SddAiJob).filter(SddAiJob.id != job.id).one()
    assert task.status == TaskStatus.RUNNING
    assert task.reading_change_seq == 1
    assert task.session_id == session_id
    assert job.status == AiJobStatus.INTERRUPTED
    assert job.context_json["superseded_by_resume_job_id"] == resume_job.id
    assert resume_job.status == AiJobStatus.PENDING
    assert resume_job.session_id == session_id
    assert resume_job.prompt_text == "use this correction"
    assert resume_job.context_json["resumed_from_job_id"] == job.id
    assert resume_job.context_json["client_message_id"] == "client-resume-1"
    assert db.query(ChatMessage).filter(ChatMessage.task_id == task.id).count() == 1
    assert enqueued == [resume_job.id]
    assert db.get(TaskChatSubmission, submission_id).ai_job_id == resume_job.id

    # Retrying the same request returns the durable, updated receipt.
    duplicate = asyncio.run(
        task_session_control_service.resume_interrupted_task(
            task_id=task.id,
            actor_user_id="user-1",
            prompt="use this correction",
            client_message_id="client-resume-1",
        )
    )
    assert duplicate["submission"]["id"] == submission_id
    assert duplicate["submission"]["ai_job_id"] == resume_job.id
    assert db.query(SddAiJob).count() == 2
    for changed in (
        {"new_agent_session": True},
        {"metadata_json": {"agent_model": {"backend": "opencode", "model": "different-model"}}},
    ):
        with pytest.raises(task_session_control_service.TaskSessionControlError) as conflict:
            asyncio.run(
                task_session_control_service.resume_interrupted_task(
                    task_id=task.id,
                    actor_user_id="user-1",
                    prompt="use this correction",
                    client_message_id="client-resume-1",
                    **changed,
                )
            )
        assert conflict.value.status_code == 409
    assert db.query(TaskChatSubmission).count() == 1


def test_initialize_turn_captures_incremental_boundary_and_is_undoable(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    task, _job = _seed_task(db, task_status=TaskStatus.RUNNING, job_status=AiJobStatus.SUCCESS)
    db.close()

    checkpoint_calls = []

    async def _initial_checkpoint(*args, **kwargs):
        checkpoint_calls.append((args, kwargs))
        return {"root": "initial-incremental-checkpoint"}

    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)
    monkeypatch.setattr("app.agents.selection.resolve_task_backend", lambda *_args: "opencode")
    monkeypatch.setattr(
        task_session_service.task_session_snapshot_service,
        "create_checkpoint",
        _initial_checkpoint,
    )

    created = asyncio.run(
        task_session_service.create_task_chat_turn(
            task_id=task.id,
            actor_user_id="user-1",
            content="初始化任务",
            context_json={"source": "task_initialize", "fresh_session": True},
            fresh_session=True,
        )
    )

    assert len(checkpoint_calls) == 1
    assert created.can_undo is True
    check_db = SessionLocal()
    try:
        message = check_db.query(ChatMessage).filter(ChatMessage.id == created.message_id).one()
        turn = check_db.query(TaskSessionTurn).filter(TaskSessionTurn.id == created.session_turn_id).one()
        assert message.session_turn_id == turn.id
        assert turn.checkpoint_path == "initial-incremental-checkpoint"
        assert turn.worktree_snapshot_path

        history = task_conversation_history.get_task_history(
            check_db,
            task.id,
            task.workspace_id,
        )
        assert history["messages"][0]["can_undo"] is True
    finally:
        check_db.close()


def test_execute_job_failure_converges_running_resume_attempt_to_interrupted(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    task, job = _seed_task(db, task_status=TaskStatus.RUNNING, job_status=AiJobStatus.RUNNING)
    job.context_json = {"resume_interrupted": True, "resumed_from_job_id": "old-job"}
    db.commit()
    db.close()

    async def _raise(_job_id, _dispatch):
        raise RuntimeError("simulated resume executor failure")

    async def _ignore_broadcast(*_args, **_kwargs):
        return None

    patch_ai_job_db(monkeypatch, SessionLocal)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)
    monkeypatch.setattr(ai_task_chat, "execute_task_chat_job", _raise)
    monkeypatch.setattr(ai_publishing, "broadcast_job_payload", _ignore_broadcast)

    asyncio.run(ai_executors.execute_job(job.id))

    check_db = SessionLocal()
    try:
        interrupted = check_db.query(SddAiJob).filter(SddAiJob.id == job.id).one()
        check_task = check_db.query(SddTask).filter(SddTask.id == task.id).one()
        assert interrupted.status == AiJobStatus.INTERRUPTED
        assert "simulated resume executor failure" in interrupted.interrupt_reason
        assert check_task.status == TaskStatus.INTERRUPTED
    finally:
        check_db.close()


def test_startup_recovery_schedules_requirement_preview_queues(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    task, _job = _seed_task(db, task_status=TaskStatus.RUNNING, job_status=AiJobStatus.SUCCESS)
    managed = SddAiJob(
        id="managed-pending",
        workspace_id=task.workspace_id,
        task_id=task.id,
        channel=AiJobChannel.TASK_CHAT,
        queue_key=f"TASK_CHAT:{task.id}",
        status=AiJobStatus.PENDING,
        creator_id="user-1",
    )
    preview = SddAiJob(
        id="requirement-pending",
        workspace_id=task.workspace_id,
        channel=AiJobChannel.ASSET_THREAD,
        queue_key=f"REQUIREMENT_PREVIEW:{task.workspace_id}",
        status=AiJobStatus.PENDING,
        creator_id="user-1",
    )
    db.add_all([managed, preview])
    db.commit()
    db.close()

    scheduled = []
    patch_ai_job_db(monkeypatch, SessionLocal)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)
    monkeypatch.setattr(ai_runtime, "schedule_queue", scheduled.append)

    count = asyncio.run(ai_workers.recover_pending_queues())

    assert count == 2
    assert sorted(scheduled) == sorted(
        [
            f"TASK_CHAT:{task.id}",
            f"REQUIREMENT_PREVIEW:{task.workspace_id}",
        ]
    )


def test_execute_job_dispatches_requirement_preview_jobs(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    task, _job = _seed_task(db, task_status=TaskStatus.RUNNING, job_status=AiJobStatus.SUCCESS)
    preview_job = SddAiJob(
        id="preview-job-1",
        workspace_id=task.workspace_id,
        channel=AiJobChannel.ASSET_THREAD,
        queue_key=f"REQUIREMENT_PREVIEW:{task.workspace_id}",
        status=AiJobStatus.RUNNING,
        context_json={"job_kind": "REQUIREMENT_IMPORT_PREVIEW"},
        creator_id="user-1",
    )
    db.add(preview_job)
    db.commit()
    db.close()

    calls = []

    class _FakePreviewService:
        @staticmethod
        async def run_requirement_import_preview_job(job_id):
            calls.append(("import", job_id))

        @staticmethod
        async def run_requirement_split_preview_job(job_id):
            calls.append(("split", job_id))

    from app.domains.workspace_asset.services.requirements.preview import runner as preview_runner

    patch_ai_job_db(monkeypatch, SessionLocal)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)
    monkeypatch.setattr(
        preview_runner, "run_requirement_import_preview_job", _FakePreviewService.run_requirement_import_preview_job
    )
    monkeypatch.setattr(
        preview_runner, "run_requirement_split_preview_job", _FakePreviewService.run_requirement_split_preview_job
    )

    asyncio.run(ai_executors.execute_job("preview-job-1"))
    assert calls == [("import", "preview-job-1")]


@pytest.mark.parametrize("owns_process", [False, True])
def test_ai_job_queue_blocks_only_on_interrupted_job_with_ownership(monkeypatch, owns_process):
    SessionLocal = _build_session()
    db = SessionLocal()
    task, job = _seed_task(db, task_status=TaskStatus.RUNNING, job_status=AiJobStatus.INTERRUPTED)
    if owns_process:
        job.process_containment_id = "previous-attempt"
    pending = SddAiJob(
        id="job-2",
        workspace_id="ws-1",
        task_id=task.id,
        channel=AiJobChannel.TASK_CHAT,
        queue_key=f"{AiJobChannel.TASK_CHAT.value}:{task.id}",
        status=AiJobStatus.PENDING,
        prompt_text="next",
        creator_id="user-1",
    )
    db.add(pending)
    db.commit()
    db.close()

    patch_ai_job_db(monkeypatch, SessionLocal)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)

    claimed = ai_store.take_next_pending_job_id_sync(f"{AiJobChannel.TASK_CHAT.value}:task-1")
    assert claimed == (None if owns_process else "job-2")
    check_db = SessionLocal()
    try:
        assert check_db.get(SddAiJob, "job-2").status == (AiJobStatus.PENDING if owns_process else AiJobStatus.RUNNING)
    finally:
        check_db.close()


def test_ai_job_queue_pauses_failed_task_pending_jobs(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    task, job = _seed_task(db, task_status=TaskStatus.FAILED, job_status=AiJobStatus.SUCCESS)
    pending = SddAiJob(
        id="job-2",
        workspace_id="ws-1",
        task_id=task.id,
        channel=AiJobChannel.TASK_CHAT,
        queue_key=f"{AiJobChannel.TASK_CHAT.value}:{task.id}",
        status=AiJobStatus.PENDING,
        prompt_text="next",
        creator_id="user-1",
    )
    db.add(pending)
    db.commit()
    db.close()

    patch_ai_job_db(monkeypatch, SessionLocal)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)

    assert ai_store.take_next_pending_job_id_sync(f"{AiJobChannel.TASK_CHAT.value}:task-1") is None
    check_db = SessionLocal()
    try:
        assert check_db.query(SddAiJob).filter(SddAiJob.id == "job-2").first().status == AiJobStatus.PENDING
        assert check_db.query(SddAiJob).filter(SddAiJob.id == job.id).first().status == AiJobStatus.SUCCESS
    finally:
        check_db.close()


async def _noop_update_job_state(job_id, **kwargs):
    return None


async def _noop_finalize(job_id, engine):
    return None


def test_run_task_chat_turn_restores_job_session_for_resume(monkeypatch):
    """After an interrupt/stop, the next chat turn must keep the persisted
    session_id on the engine so start_session uses --resume (send_message),
    instead of starting a completely fresh Claude session."""
    SessionLocal = _build_session()
    db = SessionLocal()
    task, job = _seed_task(db, task_status=TaskStatus.RUNNING, job_status=AiJobStatus.RUNNING)
    job.session_id = "session-1"
    db.commit()

    calls = {"sent": [], "run": []}

    class _FakeEngine:
        task_id = task.id
        running = False
        session_id = "session-stale"  # stale in-memory value that must be overwritten

        def set_job_callbacks(self, **kwargs):
            return None

        async def send_message(self, prompt, *, job_id=None):
            calls["sent"].append((task.id, prompt, job_id))

        async def run(self, prompt, *, fresh_session=False):
            calls["run"].append((task.id, prompt, fresh_session))

    engine = _FakeEngine()

    patch_ai_job_db(monkeypatch, SessionLocal)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)
    monkeypatch.setattr(ai_task_chat, "get_engine", lambda _task_id: engine)
    monkeypatch.setattr(ai_state, "update_job_state", _noop_update_job_state)
    monkeypatch.setattr(ai_task_chat, "finalize_task_chat_job_from_engine", _noop_finalize)

    asyncio.run(ai_task_chat._run_task_chat_turn(job.id, "continue from where I stopped"))

    # The persisted session id must win over the (stale) in-memory engine value.
    assert engine.session_id == "session-1"
    assert calls["sent"] == [(task.id, "continue from where I stopped", job.id)]
    assert calls["run"] == []


def test_finalize_timeout_marks_task_and_job_interrupted(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    task, job = _seed_task(db, task_status=TaskStatus.RUNNING, job_status=AiJobStatus.RUNNING)
    db.commit()
    db.close()

    engine = SimpleNamespace(
        last_result_success=None,
        last_result_text="Claude Code session timed out after 300.0s",
        last_result_interrupted=True,
        session_id="session-1",
    )
    broadcasted = []
    scheduled = []

    async def _broadcast(payload):
        broadcasted.append(payload["id"])

    patch_ai_job_db(monkeypatch, SessionLocal)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)
    monkeypatch.setattr(ai_publishing, "broadcast_job_payload", _broadcast)
    monkeypatch.setattr(ai_runtime, "schedule_queue", lambda queue_key: scheduled.append(queue_key))

    asyncio.run(ai_task_chat.finalize_task_chat_job_from_engine(job.id, engine))

    check_db = SessionLocal()
    try:
        check_task = check_db.query(SddTask).filter(SddTask.id == task.id).first()
        check_job = check_db.query(SddAiJob).filter(SddAiJob.id == job.id).first()
        assert check_task.status == TaskStatus.INTERRUPTED
        assert check_task.session_id == "session-1"
        assert check_task.interrupt_reason and "timed out" in check_task.interrupt_reason
        assert check_job.status == AiJobStatus.INTERRUPTED
        assert check_job.session_id == "session-1"
        assert check_job.interrupt_reason and "timed out" in check_job.interrupt_reason
        assert check_job.context_json.get("timeout_interrupted") is True
    finally:
        check_db.close()

    assert broadcasted == ["job-1"]
    assert scheduled == []


def test_finalize_auto_failure_marks_task_and_job_interrupted(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    task, job = _seed_task(db, task_status=TaskStatus.RUNNING, job_status=AiJobStatus.RUNNING)
    db.commit()
    db.close()

    engine = SimpleNamespace(
        last_result_success=False,
        last_result_text="API quota exceeded",
        last_result_interrupted=False,
        session_id="session-1",
    )
    broadcasted = []
    scheduled = []

    async def _broadcast(payload):
        broadcasted.append(payload["id"])

    patch_ai_job_db(monkeypatch, SessionLocal)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)
    monkeypatch.setattr(ai_publishing, "broadcast_job_payload", _broadcast)
    monkeypatch.setattr(ai_runtime, "schedule_queue", lambda queue_key: scheduled.append(queue_key))

    asyncio.run(ai_task_chat.finalize_task_chat_job_from_engine(job.id, engine))

    check_db = SessionLocal()
    try:
        check_task = check_db.query(SddTask).filter(SddTask.id == task.id).first()
        check_job = check_db.query(SddAiJob).filter(SddAiJob.id == job.id).first()
        assert check_task.status == TaskStatus.INTERRUPTED
        assert check_task.session_id == "session-1"
        assert check_task.interrupt_reason and "API quota exceeded" in check_task.interrupt_reason
        assert check_job.status == AiJobStatus.INTERRUPTED
        assert check_job.session_id == "session-1"
        assert check_job.interrupt_reason and "API quota exceeded" in check_job.interrupt_reason
        assert check_job.context_json.get("interrupted") is True
        assert check_job.context_json.get("timeout_interrupted") is None
    finally:
        check_db.close()

    assert broadcasted == ["job-1"]
    assert scheduled == []


def test_run_task_chat_turn_fresh_session_clears_engine_session(monkeypatch):
    """A fresh-session job must clear the engine session so run(..., fresh_session=True)
    starts a brand-new Claude session without --resume."""
    SessionLocal = _build_session()
    db = SessionLocal()
    task, job = _seed_task(db, task_status=TaskStatus.RUNNING, job_status=AiJobStatus.RUNNING)
    job.session_id = "session-1"
    job.context_json = {"fresh_session": True}
    db.commit()

    calls = {"sent": [], "run": []}

    class _FakeEngine:
        task_id = task.id
        running = False
        session_id = "session-1"

        def set_job_callbacks(self, **kwargs):
            return None

        async def send_message(self, prompt, *, job_id=None):
            calls["sent"].append((task.id, prompt, job_id))

        async def run(self, prompt, *, fresh_session=False):
            calls["run"].append((task.id, prompt, fresh_session))

    engine = _FakeEngine()

    patch_ai_job_db(monkeypatch, SessionLocal)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)
    monkeypatch.setattr(ai_task_chat, "get_engine", lambda _task_id: engine)
    monkeypatch.setattr(ai_state, "update_job_state", _noop_update_job_state)
    monkeypatch.setattr(ai_task_chat, "finalize_task_chat_job_from_engine", _noop_finalize)

    asyncio.run(ai_task_chat._run_task_chat_turn(job.id, "start fresh"))

    assert engine.session_id is None
    assert calls["run"] == [(task.id, "start fresh", True)]
    assert calls["sent"] == []
