import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from app.domains.auth.models.user import User, Workspace
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.chat_submission import TaskChatSubmission
from app.domains.task.models.session_turn import TaskSessionTurn
from app.domains.ai.models.ai_job import SddAiJob, AiJobStatus, AiJobChannel
from app.domains.task.services import chat_submission_service as service, task_session_service
from app.domains.search.capture import install_capture
from app.domains.search.models import SearchOutbox, SearchDocumentState
from app.domains.search.projection import build_search_projection


@pytest.fixture
def task_db(db):
    db.add(User(id="u", email="submission@test.local", hashed_password="x", display_name="User"))
    db.add(Workspace(id="w", name="Workspace", owner_id="u"))
    db.add(SddTask(id="t", workspace_id="w", creator_id="u", name="Task", project_path="/tmp/task",
                   status=TaskStatus.CODING, agent_backend="mock", session_generation=1, session_revision=0))
    db.commit()
    return db


def accepted(db, client_id="c", content="private prompt"):
    result = service._accept_sync(db, "t", "u", client_id, content, {})
    db.commit()
    return db.get(TaskChatSubmission, result["id"])


def execution(db, row, status=AiJobStatus.RUNNING):
    job = SddAiJob(id="job", task_id="t", workspace_id="w", creator_id="u",
        channel=AiJobChannel.TASK_CHAT, queue_key="TASK_CHAT:t", status=status, session_generation=1)
    db.add(job)
    turn = TaskSessionTurn(id="turn", task_id="t", workspace_id="w", session_generation=1,
        turn_index=1, session_revision=1, provider="mock", ai_job_id="job")
    db.add(turn)
    db.flush()
    job.session_turn_id = turn.id
    row.ai_job_id, row.status = job.id, "EXECUTING"
    for role in ("user", "assistant"):
        db.add(ChatMessage(id=role, task_id="t", workspace_id="w", creator_id="u", role=role,
            content="private " + role, message_type="text", session_generation=1, session_turn_id=turn.id,
            metadata_json={"submission_id": row.id, "knowledge_state": "pending"}))
    row.chat_message_id = "user"
    db.commit()
    return job


def test_receipt_durable_without_message_job_or_search_event(task_db):
    install_capture()
    before = task_db.query(SearchOutbox).count()
    row = accepted(task_db)
    assert service.list_for_task(task_db, "t")[0]["status"] == "PREPARING"
    assert task_db.query(ChatMessage).count() == task_db.query(SddAiJob).count() == 0
    assert task_db.query(SearchOutbox).count() == before
    assert row.active_task_id == "t"


def test_duplicate_reuses_receipt_and_other_message_is_busy(task_db):
    original = accepted(task_db)
    assert accepted(task_db).id == original.id
    with pytest.raises(service.SubmissionError, match="准备或执行"):
        accepted(task_db, "second")
    task_db.rollback()
    with pytest.raises(service.SubmissionError) as conflict:
        accepted(task_db, content="changed")
    assert conflict.value.code == "MESSAGE_CONFLICT"


@pytest.mark.parametrize("status", [AiJobStatus.FAILED, AiJobStatus.CANCELLED, AiJobStatus.INTERRUPTED])
def test_failed_execution_never_becomes_knowledge(task_db, status):
    install_capture()
    row = accepted(task_db)
    execution(task_db, row, status)
    service._reconcile_sync(task_db)
    task_db.commit()
    assert task_db.get(TaskChatSubmission, row.id).status == "FAILED"
    for message in task_db.query(ChatMessage).all():
        assert build_search_projection(message, "message") is None
        assert task_db.get(SearchDocumentState, "message:" + message.id) is None
    from app.domains.ai.services.ai_job_service import _collect_diagnosis_transcript_sync
    assert _collect_diagnosis_transcript_sync(task_db, "t") == ""


def test_success_publishes_sources_once_with_transactional_outbox(task_db):
    install_capture()
    row = accepted(task_db)
    job = execution(task_db, row)
    assert task_db.query(SearchOutbox).filter(SearchOutbox.entity_key.like("message:%")).count() == 0
    job.status = AiJobStatus.SUCCESS
    task_db.commit()
    service._reconcile_sync(task_db)
    task_db.commit()
    assert task_db.get(TaskChatSubmission, row.id).status == "SUCCEEDED"
    assert task_db.query(SearchOutbox).filter(SearchOutbox.entity_key.like("message:%")).count() == 2
    service._reconcile_sync(task_db)
    task_db.commit()
    assert task_db.query(SearchOutbox).filter(SearchOutbox.entity_key.like("message:%")).count() == 2


def test_preparation_failure_releases_slot_without_formal_message(task_db):
    row = accepted(task_db)
    service._fail_sync(task_db, row.id, "snapshot failed")
    task_db.commit()
    assert row.status == "FAILED" and row.active_task_id is None
    assert task_db.query(ChatMessage).count() == 0
    assert accepted(task_db, "next").status == "PREPARING"


def test_session_changed_during_restart_does_not_execute_old_prompt(task_db):
    row = accepted(task_db)
    task_db.get(SddTask, "t").session_revision += 1
    task_db.commit()
    assert service._load_preparation(task_db, row.id) is None
    task_db.commit()
    assert row.status == "FAILED"


def test_lost_receipt_after_commit_cannot_mark_job_unsent(task_db):
    row = accepted(task_db)
    execution(task_db, row)
    service._fail_sync(task_db, row.id, "lost ack")
    task_db.commit()
    assert row.status == "EXECUTING"


@pytest.mark.asyncio
async def test_slow_checkpoint_remains_visible_and_rejects_second_send(task_db, monkeypatch):
    row = accepted(task_db)
    started, finish = asyncio.Event(), asyncio.Event()
    async def checkpoint(**kwargs):
        started.set()
        await finish.wait()
        raise RuntimeError("simulated snapshot failure")
    @asynccontextmanager
    async def lock(_):
        yield
    async def txn(body):
        try:
            result = body(task_db)
            task_db.commit()
            return result
        except BaseException:
            task_db.rollback()
            raise
    monkeypatch.setattr(service, "lock_task", lock)
    monkeypatch.setattr(service, "run_db", AsyncMock(return_value="t"))
    monkeypatch.setattr(service, "run_db_txn", txn)
    monkeypatch.setattr(task_session_service, "create_task_chat_turn", checkpoint)
    runner = asyncio.create_task(service._run(row.id))
    await started.wait()
    try:
        assert service.list_for_task(task_db, "t")[0]["status"] == "PREPARING"
        with pytest.raises(service.SubmissionError):
            service._accept_sync(task_db, "t", "u", "second", "again", {})
        task_db.rollback()
    finally:
        finish.set()
        await runner
    assert task_db.get(TaskChatSubmission, row.id).status == "FAILED"


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_after_job_flush", [False, True])
async def test_real_turn_creation_commits_receipt_message_and_job_together(task_db, monkeypatch, fail_after_job_flush):
    from app.domains.ai.services import ai_job_service
    from app.domains.task.services import context_token_service, task_session_snapshot_service
    install_capture()
    row = accepted(task_db)
    submission_id = row.id
    async def txn(body):
        try:
            result = body(task_db)
            task_db.commit()
            return result
        except BaseException:
            task_db.rollback()
            raise
    monkeypatch.setattr(task_session_service, "run_db_txn", txn)
    monkeypatch.setattr(task_session_snapshot_service, "create_checkpoint", AsyncMock(return_value={"root": "/fake/checkpoint"}))
    monkeypatch.setattr(task_session_snapshot_service, "cleanup_checkpoint", AsyncMock())
    monkeypatch.setattr(context_token_service, "seed_snapshot_for_job", lambda *args, **kwargs: None)
    original = ai_job_service.create_task_chat_job
    if fail_after_job_flush:
        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("between job flush and receipt update")
        monkeypatch.setattr(ai_job_service, "create_task_chat_job", fail)
    args = service._load_preparation(task_db, submission_id)
    if fail_after_job_flush:
        with pytest.raises(RuntimeError, match="between job flush"):
            await task_session_service.create_task_chat_turn(**args)
        assert task_db.query(ChatMessage).count() == task_db.query(SddAiJob).count() == 0
        assert task_db.get(TaskChatSubmission, submission_id).status == "PREPARING"
        task_session_snapshot_service.cleanup_checkpoint.assert_awaited_once_with("/fake/checkpoint")
    else:
        result = await task_session_service.create_task_chat_turn(**args)
        persisted = task_db.get(TaskChatSubmission, submission_id)
        assert persisted.status == "EXECUTING"
        assert persisted.chat_message_id == result.message_id and persisted.ai_job_id == result.job_id
        assert task_db.get(ChatMessage, result.message_id).metadata_json["knowledge_state"] == "pending"
    assert task_db.query(SearchOutbox).filter(SearchOutbox.entity_key.like("message:%")).count() == 0


def test_pending_message_cannot_be_used_by_generic_decision_source(task_db):
    from app.domains.asset.services.decision_service import _ensure_chat_message, DecisionSourceError
    row = accepted(task_db)
    execution(task_db, row, AiJobStatus.FAILED)
    with pytest.raises(DecisionSourceError, match="本轮尚未成功"):
        _ensure_chat_message(task_db, "w", "t", "user")


@pytest.mark.asyncio
async def test_cancelled_snapshot_drains_worker_and_cleans_unpublished_checkpoint(monkeypatch):
    from app.core import offload
    from app.domains.task.services import task_session_snapshot_service as snapshots
    started, finish = asyncio.Event(), asyncio.Event()
    async def worker(*args):
        started.set()
        await finish.wait()
        return {"root": "/fake/unpublished"}
    cleanup = AsyncMock()
    monkeypatch.setattr(offload, "run_git_job", worker)
    monkeypatch.setattr(snapshots, "cleanup_checkpoint", cleanup)
    task = asyncio.create_task(snapshots.create_checkpoint(
        "/fake", [], "mock", None, workspace_id="w", workspace_name="W", task_id="t", task_name="T"))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    cleanup.assert_awaited_once_with("/fake/unpublished")


def test_incremental_migration_round_trip_preserves_existing_data(monkeypatch):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, text, inspect
    path = Path(__file__).parents[1] / "alembic/versions/e6a718293b4c_chat_submissions.py"
    spec = importlib.util.spec_from_file_location("submission_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        for table in ("sdd_tasks", "workspaces", "users", "sdd_ai_jobs", "chat_messages"):
            connection.execute(text(f"CREATE TABLE {table} (id VARCHAR(36) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO chat_messages (id) VALUES ('existing')"))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        constraints = inspect(connection).get_unique_constraints("sdd_task_chat_submissions")
        assert {item["name"] for item in constraints} == {"uq_chat_submission_client", "uq_chat_submission_active_task"}
        migration.downgrade()
        assert "sdd_task_chat_submissions" not in inspect(connection).get_table_names()
        assert connection.execute(text("SELECT id FROM chat_messages")).scalar_one() == "existing"
    engine.dispose()


def test_failed_turn_cannot_leak_into_summary_through_provider_fork(task_db, monkeypatch):
    from app.domains.ai.services import ai_job_service
    row = accepted(task_db)
    execution(task_db, row, AiJobStatus.FAILED)
    task = task_db.get(SddTask, "t")
    task.task_type, task.session_id = "DIAGNOSIS", "provider-with-failed-turn"
    task_db.add(SddAiJob(id="summary", task_id="t", workspace_id="w", creator_id="u",
        channel=AiJobChannel.TASK_CHAT, queue_key="summary:t", status=AiJobStatus.RUNNING,
        context_json={"source_session_id": task.session_id}))
    task_db.commit()
    monkeypatch.setattr(ai_job_service, "_attempt_is_current_sync", lambda *args, **kwargs: True)
    monkeypatch.setattr(ai_job_service, "_resolve_task_project_path", lambda task: "/fake")
    monkeypatch.setattr(ai_job_service.diagnosis_result_service, "build_diagnosis_summary_prompt", lambda task, transcript: transcript)
    prepared = ai_job_service._prepare_diagnosis_summary_sync(task_db, "summary")
    assert prepared["source_session_id"] == ""
    assert prepared["prompt"] == ""


def test_confirmation_reply_is_private_until_owning_turn_succeeds(task_db):
    row = accepted(task_db)
    job = execution(task_db, row)
    parent = task_db.get(ChatMessage, "assistant")
    parent.metadata_json = {**parent.metadata_json, "confirmation": {"interaction_id": "question"}}
    task_db.commit()
    reply = task_session_service._persist_confirmation_reply_sync(task_db, task_id="t", actor_user_id="u",
        content="private answer", client_message_id="reply", interaction_id="question",
        reply_to_message_id="assistant", confirmation_value="yes")
    message = task_db.get(ChatMessage, reply.message_id)
    assert message.session_turn_id == "turn"
    assert build_search_projection(message, "message") is None
    job.status = AiJobStatus.SUCCESS
    task_db.commit()
    service._reconcile_sync(task_db)
    task_db.commit()
    assert build_search_projection(message, "message") is not None


def test_http_acceptance_recovery_idempotency_and_access(task_db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker
    from app.domains.auth.models.user import WorkspaceMember, WorkspaceRole
    from app.domains.task.routers import task as router
    task_db.add(WorkspaceMember(workspace_id="w", user_id="u", role=WorkspaceRole.DEVELOPER))
    task_db.commit()
    user = task_db.get(User, "u")
    factory = sessionmaker(bind=task_db.get_bind())
    monkeypatch.setattr("app.database.SessionLocal", factory)
    monkeypatch.setattr(service, "schedule", lambda receipt_id: None)
    async def no_broadcast(*args, **kwargs):
        pass
    from app.domains.websocket.ws.manager import manager
    monkeypatch.setattr(manager, "send_message_to_room", no_broadcast)
    app = FastAPI()
    app.include_router(router.router, prefix="/api")
    def get_db():
        with factory() as db:
            yield db
    app.dependency_overrides[router.get_db] = get_db
    app.dependency_overrides[router.get_current_user] = lambda: user
    url = "/api/workspaces/w/tasks/t/chat-submissions"
    with TestClient(app) as client:
        payload = {"client_message_id": "http", "content": "prompt"}
        first = client.post(url, json=payload)
        assert first.status_code == 202, first.text
        assert first.json()["status"] == "PREPARING"
        assert client.post(url, json=payload).json()["id"] == first.json()["id"]
        assert client.get(url).json()["items"][0]["id"] == first.json()["id"]
        assert client.post(url, json={**payload, "client_message_id": "second"}).status_code == 409
        assert client.post(url.replace("/w/", "/other/"), json=payload).status_code == 403
    assert task_db.query(ChatMessage).count() == task_db.query(SddAiJob).count() == 0
