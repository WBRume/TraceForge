import asyncio
import os
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

import app.domains.api_mock.models.api_mock  # noqa: F401,E402
import app.domains.task.models.test_result  # noqa: F401,E402
import app.domains.workflow.models.task_change  # noqa: F401,E402
import app.domains.workspace_asset.models.workspace_asset  # noqa: F401,E402
from app.database import Base  # noqa: E402
from app.domains.ai.models.ai_job import SddAiJob
from app.domains.auth.models.user import User, Workspace
from app.domains.task.models.task import SddTask
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus  # noqa: E402
from app.domains.task.models.chat import ChatMessage  # noqa: E402
from app.domains.task.models.task import TaskStatus  # noqa: E402
from app.domains.ai.services import ai_job_service
from app.domains.task.services import task_session_control_service


def _build_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed_task(db, *, task_status=TaskStatus.CODING, job_status=AiJobStatus.RUNNING):
    user = User(id="user-1", email="user@example.com", hashed_password="x", display_name="User")
    workspace = Workspace(id="ws-1", name="Workspace", owner_id=user.id)
    task = SddTask(
        id="task-1",
        workspace_id=workspace.id,
        creator_id=user.id,
        name="Task",
        project_path="G:/tmp/task-1",
        status=task_status,
    )
    job = SddAiJob(
        id="job-1",
        workspace_id=workspace.id,
        task_id=task.id,
        channel=AiJobChannel.TASK_CHAT,
        queue_key=f"{AiJobChannel.TASK_CHAT.value}:{task.id}",
        status=job_status,
        prompt_text="work on this",
        creator_id=user.id,
        session_id="session-1",
    )
    db.add_all([user, workspace, task, job])
    db.commit()
    return task, job


def test_task_interrupt_marks_task_and_job_interrupted(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    task, job = _seed_task(db)

    class _FakeEngine:
        task_id = task.id
        current_job_id = job.id
        running = True
        session_id = "session-1"

        def __init__(self):
            self.interrupted = False

        async def interrupt(self):
            self.interrupted = True
            self.running = False

    engine = _FakeEngine()
    published = []
    events = []

    async def _publish_job(job_id, *, final=False):
        published.append((job_id, final))

    async def _broadcast(event_type, event_task, job_payload):
        events.append((event_type, event_task.id, job_payload["id"]))

    monkeypatch.setattr(task_session_control_service, "get_engine", lambda _task_id: engine)
    monkeypatch.setattr(task_session_control_service.ai_job_service, "publish_job", _publish_job)
    monkeypatch.setattr(task_session_control_service, "_broadcast_task_event", _broadcast)

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
    assert job.status == AiJobStatus.INTERRUPTED
    assert job.session_id == "session-1"
    assert published == [("job-1", False)]
    assert events == [("task_interrupted", "task-1", "job-1")]
    assert payload["status"] == TaskStatus.INTERRUPTED.value


def test_task_interrupt_cancels_pending_job_when_engine_not_running(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    task, job = _seed_task(db, task_status=TaskStatus.CODING, job_status=AiJobStatus.PENDING)

    published = []
    events = []

    async def _publish_job(job_id, *, final=False):
        published.append((job_id, final))

    async def _broadcast(event_type, event_task, job_payload):
        events.append((event_type, event_task.id, job_payload["id"]))

    monkeypatch.setattr(task_session_control_service, "get_engine", lambda _task_id: None)
    monkeypatch.setattr(task_session_control_service.ai_job_service, "publish_job", _publish_job)
    monkeypatch.setattr(task_session_control_service, "_broadcast_task_event", _broadcast)

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
    assert task.status == TaskStatus.CODING
    assert published == [("job-1", True)]
    assert events == [("task_interrupted", "task-1", "job-1")]
    assert payload["job"]["status"] == AiJobStatus.CANCELLED.value


def test_task_resume_requires_interrupted_status(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    task, _job = _seed_task(db, task_status=TaskStatus.FAILED, job_status=AiJobStatus.INTERRUPTED)
    monkeypatch.setattr(task_session_control_service, "get_engine", lambda _task_id: None)

    with pytest.raises(task_session_control_service.TaskSessionControlError) as exc:
        asyncio.run(
            task_session_control_service.resume_interrupted_task(
                db,
                task=task,
                actor_user_id="user-1",
                prompt="continue",
            )
        )

    assert exc.value.status_code == 409


def test_task_resume_creates_new_attempt_and_keeps_interrupted_attempt_terminal(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    task, job = _seed_task(db, task_status=TaskStatus.INTERRUPTED, job_status=AiJobStatus.INTERRUPTED)
    task.session_id = "session-1"
    db.commit()

    published = []
    events = []
    enqueued = []

    async def _publish_job(job_id, *, final=False):
        published.append((job_id, final))

    async def _broadcast(event_type, event_task, job_payload):
        events.append((event_type, event_task.id, job_payload["id"]))

    async def _enqueue(job_id):
        enqueued.append(job_id)
        return None

    monkeypatch.setattr(task_session_control_service, "get_engine", lambda _task_id: None)
    monkeypatch.setattr(task_session_control_service.ai_job_service, "publish_job", _publish_job)
    monkeypatch.setattr(task_session_control_service.ai_job_service, "enqueue_task_chat_job", _enqueue)
    monkeypatch.setattr(task_session_control_service, "_broadcast_task_event", _broadcast)

    payload = asyncio.run(
        task_session_control_service.resume_interrupted_task(
            db,
            task=task,
            actor_user_id="user-1",
            prompt="use this correction",
            client_message_id="client-resume-1",
        )
    )

    db.refresh(task)
    db.refresh(job)
    resume_job = db.query(SddAiJob).filter(SddAiJob.id != job.id).one()
    assert task.status == TaskStatus.CODING
    assert task.session_id == "session-1"
    assert job.status == AiJobStatus.CANCELLED
    assert resume_job.status == AiJobStatus.PENDING
    assert resume_job.session_id == "session-1"
    assert resume_job.prompt_text == "use this correction"
    assert resume_job.context_json["resumed_from_job_id"] == job.id
    assert resume_job.context_json["client_message_id"] == "client-resume-1"
    assert db.query(ChatMessage).filter(ChatMessage.task_id == task.id).count() == 1
    assert published == [("job-1", True)]
    assert events == [("task_resumed", "task-1", resume_job.id)]
    assert enqueued == [resume_job.id]
    assert payload["status"] == TaskStatus.CODING.value

    # Retrying the same HTTP request is idempotent even though the task is now CODING.
    duplicate = asyncio.run(
        task_session_control_service.resume_interrupted_task(
            db,
            task=task,
            actor_user_id="user-1",
            prompt="use this correction",
            client_message_id="client-resume-1",
        )
    )
    assert duplicate["job"]["id"] == resume_job.id
    assert db.query(SddAiJob).count() == 2


def test_execute_job_failure_converges_running_resume_attempt_to_interrupted(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    task, job = _seed_task(db, task_status=TaskStatus.CODING, job_status=AiJobStatus.RUNNING)
    job.context_json = {"resume_interrupted": True, "resumed_from_job_id": "old-job"}
    db.commit()
    db.close()

    async def _raise(_job_id):
        raise RuntimeError("simulated resume executor failure")

    async def _ignore_broadcast(*_args, **_kwargs):
        return None

    monkeypatch.setattr(ai_job_service, "SessionLocal", SessionLocal)
    monkeypatch.setattr(ai_job_service, "_execute_task_chat_job", _raise)
    monkeypatch.setattr(ai_job_service, "_broadcast_job_payload", _ignore_broadcast)

    asyncio.run(ai_job_service._execute_job(job.id))

    check_db = SessionLocal()
    try:
        interrupted = check_db.query(SddAiJob).filter(SddAiJob.id == job.id).one()
        check_task = check_db.query(SddTask).filter(SddTask.id == task.id).one()
        assert interrupted.status == AiJobStatus.INTERRUPTED
        assert "simulated resume executor failure" in interrupted.interrupt_reason
        assert check_task.status == TaskStatus.INTERRUPTED
    finally:
        check_db.close()


def test_startup_recovery_only_schedules_queues_owned_by_ai_job_service(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    task, _job = _seed_task(db, task_status=TaskStatus.CODING, job_status=AiJobStatus.SUCCESS)
    managed = SddAiJob(
        id="managed-pending",
        workspace_id=task.workspace_id,
        task_id=task.id,
        channel=AiJobChannel.TASK_CHAT,
        queue_key=f"TASK_CHAT:{task.id}",
        status=AiJobStatus.PENDING,
        creator_id="user-1",
    )
    foreign = SddAiJob(
        id="requirement-pending",
        workspace_id=task.workspace_id,
        channel=AiJobChannel.ASSET_THREAD,
        queue_key=f"REQUIREMENT_PREVIEW:{task.workspace_id}",
        status=AiJobStatus.PENDING,
        creator_id="user-1",
    )
    db.add_all([managed, foreign])
    db.commit()
    db.close()

    scheduled = []
    monkeypatch.setattr(ai_job_service, "SessionLocal", SessionLocal)
    monkeypatch.setattr(ai_job_service, "schedule_queue", scheduled.append)

    count = asyncio.run(ai_job_service.recover_pending_queues())

    assert count == 1
    assert scheduled == [f"TASK_CHAT:{task.id}"]


def test_ai_job_queue_blocks_on_interrupted_job(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    task, _job = _seed_task(db, task_status=TaskStatus.CODING, job_status=AiJobStatus.INTERRUPTED)
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

    monkeypatch.setattr(ai_job_service, "SessionLocal", SessionLocal)

    assert ai_job_service._take_next_pending_job_id_sync(f"{AiJobChannel.TASK_CHAT.value}:task-1") is None
    check_db = SessionLocal()
    try:
        assert check_db.query(SddAiJob).filter(SddAiJob.id == "job-2").first().status == AiJobStatus.PENDING
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

    monkeypatch.setattr(ai_job_service, "SessionLocal", SessionLocal)

    assert ai_job_service._take_next_pending_job_id_sync(f"{AiJobChannel.TASK_CHAT.value}:task-1") is None
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
    task, job = _seed_task(db, task_status=TaskStatus.INTERRUPTED, job_status=AiJobStatus.INTERRUPTED)
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

    monkeypatch.setattr(ai_job_service, "SessionLocal", SessionLocal)
    monkeypatch.setattr(ai_job_service, "get_engine", lambda _task_id: engine)
    monkeypatch.setattr(ai_job_service, "_update_job_state", _noop_update_job_state)
    monkeypatch.setattr(ai_job_service, "_finalize_task_chat_job_from_engine", _noop_finalize)

    asyncio.run(ai_job_service._run_task_chat_turn(job.id, "continue from where I stopped"))

    # The persisted session id must win over the (stale) in-memory engine value.
    assert engine.session_id == "session-1"
    assert calls["sent"] == [(task.id, "continue from where I stopped", job.id)]
    assert calls["run"] == []


def test_finalize_timeout_marks_task_and_job_interrupted(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    task, job = _seed_task(db, task_status=TaskStatus.CODING, job_status=AiJobStatus.RUNNING)
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

    async def _broadcast(payload, *, final):
        broadcasted.append((payload["id"], final))

    monkeypatch.setattr(ai_job_service, "SessionLocal", SessionLocal)
    monkeypatch.setattr(ai_job_service, "_broadcast_job_payload", _broadcast)
    monkeypatch.setattr(ai_job_service, "schedule_queue", lambda queue_key: scheduled.append(queue_key))

    asyncio.run(ai_job_service._finalize_task_chat_job_from_engine(job.id, engine))

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

    assert broadcasted == [("job-1", False)]
    assert scheduled == []


def test_finalize_auto_failure_marks_task_and_job_interrupted(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    task, job = _seed_task(db, task_status=TaskStatus.CODING, job_status=AiJobStatus.RUNNING)
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

    async def _broadcast(payload, *, final):
        broadcasted.append((payload["id"], final))

    monkeypatch.setattr(ai_job_service, "SessionLocal", SessionLocal)
    monkeypatch.setattr(ai_job_service, "_broadcast_job_payload", _broadcast)
    monkeypatch.setattr(ai_job_service, "schedule_queue", lambda queue_key: scheduled.append(queue_key))

    asyncio.run(ai_job_service._finalize_task_chat_job_from_engine(job.id, engine))

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

    assert broadcasted == [("job-1", False)]
    assert scheduled == []


def test_run_task_chat_turn_fresh_session_clears_engine_session(monkeypatch):
    """A fresh-session job must clear the engine session so run(..., fresh_session=True)
    starts a brand-new Claude session without --resume."""
    SessionLocal = _build_session()
    db = SessionLocal()
    task, job = _seed_task(db, task_status=TaskStatus.CODING, job_status=AiJobStatus.RUNNING)
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

    monkeypatch.setattr(ai_job_service, "SessionLocal", SessionLocal)
    monkeypatch.setattr(ai_job_service, "get_engine", lambda _task_id: engine)
    monkeypatch.setattr(ai_job_service, "_update_job_state", _noop_update_job_state)
    monkeypatch.setattr(ai_job_service, "_finalize_task_chat_job_from_engine", _noop_finalize)

    asyncio.run(ai_job_service._run_task_chat_turn(job.id, "start fresh"))

    assert engine.session_id is None
    assert calls["run"] == [(task.id, "start fresh", True)]
    assert calls["sent"] == []
