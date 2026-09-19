import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from app.domains.ai.services.jobs import (
    attempts as ai_attempts,
    constants as ai_constants,
    executors as ai_executors,
    publishing as ai_publishing,
    provider_turn as ai_provider_turn,
    queue_runner as ai_queue_runner,
    reaper as ai_reaper,
    registry as ai_registry,
    state as ai_state,
    store as ai_store,
    workers as ai_workers,
)
from app.domains.ai.services.jobs.executors import (
    diagnosis_summary as ai_diagnosis_summary,
    task_chat as ai_task_chat,
)
from app.domains.ai.services.jobs.registry import runtime as ai_runtime
from tests.ai.jobs.ai_job_test_utils import patch_ai_job_db
from app.domains.task.services import diagnosis_result_service
from app.agents.supervision import process_supervisor
from app.domains.auth.models.user import User, Workspace
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.chat_submission import TaskChatSubmission
from app.domains.task.models.task_event_outbox import TaskEventOutbox
from app.domains.task.models.session_turn import TaskSessionTurn
from app.domains.ai.models.ai_job import SddAiJob, AiJobStatus, AiJobChannel
from app.domains.task.services import chat_submission_service as service, task_session_service
from app.domains.search.capture import install_capture
from app.domains.search.models import SearchOutbox, SearchDocumentState
from app.domains.search.projection import build_search_projection


@pytest.fixture(autouse=True)
def local_submission_locks(monkeypatch):
    from app.core import distributed_lock
    monkeypatch.setattr(distributed_lock, "_PROVIDER", distributed_lock.LocalLockProvider())


@pytest.fixture
def recovery_env(task_db, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.domains.websocket.ws.manager import manager
    factory = sessionmaker(bind=task_db.get_bind())
    monkeypatch.setattr("app.database.SessionLocal", factory)
    patch_ai_job_db(monkeypatch, factory)
    monkeypatch.setattr(manager, "send_message_to_room", AsyncMock())
    scheduled = []
    monkeypatch.setattr(service, "schedule", scheduled.append)
    monkeypatch.setattr(service.settings, "TASK_SESSION_REVERT_WAIT_SECONDS", 0.05)
    return scheduled


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [AiJobStatus.FAILED, AiJobStatus.CANCELLED, AiJobStatus.SUCCESS])
async def test_send_releases_terminal_receipt_and_keeps_session(task_db, recovery_env, status):
    row = accepted(task_db)
    execution(task_db, row, status)
    task = task_db.get(SddTask, "t")
    task.session_id = "original-session"
    task_db.commit()
    receipt = await service.accept(task_id="t", actor_id="u", client_message_id="next", content="continue")
    task_db.expire_all()
    assert receipt["status"] == "PREPARING"
    assert task_db.get(TaskChatSubmission, row.id).active_task_id is None
    assert task_db.get(SddTask, "t").session_id == "original-session"
    assert task_db.get(SddTask, "t").session_generation == 1


@pytest.mark.asyncio
async def test_send_after_restart_reclaims_persisted_attempt(task_db, recovery_env, monkeypatch):
    from app.agents.supervision import TerminationResult
    scheduled = recovery_env
    row = accepted(task_db)
    job = execution(task_db, row)
    job.run_token, job.worker_boot_id, job.process_pid = "old-token", "previous-worker", 4321
    task_db.commit()
    monkeypatch.setattr(process_supervisor, "stop_attempt", AsyncMock(return_value=None))
    stop = AsyncMock(return_value=TerminationResult(True, None))
    monkeypatch.setattr(process_supervisor, "stop_persisted", stop)
    receipt = await service.accept(task_id="t", actor_id="u", client_message_id="after-restart", content="continue")
    task_db.expire_all()
    assert receipt["status"] == "PREPARING"
    assert task_db.get(SddAiJob, "job").status not in service.BLOCKING
    assert task_db.get(TaskChatSubmission, row.id).active_task_id is None
    assert scheduled == [receipt["id"]]
    stop.assert_awaited_once()
    assert stop.call_args.kwargs["run_token"] == "old-token"


@pytest.mark.asyncio
async def test_send_does_not_cancel_healthy_attempt(task_db, recovery_env, monkeypatch):
    from datetime import datetime, timedelta
    scheduled = recovery_env
    row = accepted(task_db)
    job = execution(task_db, row)
    job.worker_boot_id, job.run_token = ai_registry.WORKER_BOOT_ID, "live-token"
    job.lease_expires_at = datetime.utcnow() + timedelta(minutes=5)
    task_db.commit()
    stop = AsyncMock()
    monkeypatch.setattr(process_supervisor, "stop_attempt", stop)
    with pytest.raises(service.SubmissionError) as exc:
        await service.accept(task_id="t", actor_id="u", client_message_id="next", content="continue")
    assert exc.value.status_code == 409
    task_db.expire_all()
    assert task_db.get(SddAiJob, "job").status == AiJobStatus.RUNNING
    assert task_db.get(SddAiJob, "job").cancel_requested_at is None
    stop.assert_not_awaited()
    assert scheduled == []


@pytest.mark.asyncio
async def test_unconfirmed_process_remains_blocking_on_send(task_db, recovery_env, monkeypatch):
    from app.agents.supervision import TerminationResult
    scheduled = recovery_env
    row = accepted(task_db)
    job = execution(task_db, row)
    job.worker_boot_id, job.run_token = "previous-worker", "unknown-token"
    task_db.commit()
    monkeypatch.setattr(process_supervisor, "stop_attempt", AsyncMock(return_value=TerminationResult(None, None)))
    with pytest.raises(service.SubmissionError) as exc:
        await service.accept(task_id="t", actor_id="u", client_message_id="next", content="continue")
    assert exc.value.status_code == 409
    task_db.expire_all()
    assert task_db.get(SddAiJob, "job").status == AiJobStatus.ORPHANED
    assert task_db.get(SddAiJob, "job").run_token == "unknown-token"
    assert task_db.query(TaskChatSubmission).count() == 1
    assert scheduled == []


@pytest.mark.asyncio
async def test_duplicate_send_skips_recovery_and_conflicting_payload_is_rejected(task_db, recovery_env, monkeypatch):
    row = accepted(task_db)
    execution(task_db, row)
    recover = AsyncMock()
    monkeypatch.setattr(service, "recover_task_attempts", recover)
    receipt = await service.accept(task_id="t", actor_id="u", client_message_id="c", content="private prompt")
    assert receipt["id"] == row.id
    with pytest.raises(service.SubmissionError) as exc:
        await service.accept(task_id="t", actor_id="u", client_message_id="c", content="different")
    assert exc.value.code == "MESSAGE_CONFLICT"
    recover.assert_not_awaited()
    assert task_db.query(TaskChatSubmission).count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("same_id", [True, False])
async def test_concurrent_sends_accept_only_one_new_receipt(task_db, recovery_env, same_id):
    results = await asyncio.gather(
        service.accept(task_id="t", actor_id="u", client_message_id="first", content="continue"),
        service.accept(task_id="t", actor_id="u", client_message_id="first" if same_id else "second", content="continue"),
        return_exceptions=True,
    )
    assert task_db.query(TaskChatSubmission).count() == 1
    if same_id:
        assert results[0]["id"] == results[1]["id"]
    else:
        assert sum(isinstance(result, service.SubmissionError) for result in results) == 1


@pytest.mark.asyncio
async def test_recovered_send_creates_one_turn_using_existing_provider_session(task_db, recovery_env, monkeypatch):
    from app.domains.task.services import context_token_service
    scheduled = recovery_env
    row = accepted(task_db)
    execution(task_db, row, AiJobStatus.FAILED)
    task_db.get(SddTask, "t").session_id = "preserved-session"
    task_db.commit()
    monkeypatch.setattr(task_session_service.task_session_snapshot_service, "create_checkpoint", AsyncMock(return_value={"root": "/fake/checkpoint"}))
    monkeypatch.setattr(context_token_service, "seed_snapshot_for_job", lambda *args, **kwargs: None)
    enqueue = AsyncMock()
    monkeypatch.setattr(ai_publishing, "enqueue_task_chat_job", enqueue)
    receipt = await service.accept(task_id="t", actor_id="u", client_message_id="continue", content="try again")
    await service._run(receipt["id"])
    task_db.expire_all()
    new = task_db.get(TaskChatSubmission, receipt["id"])
    assert new.status == "EXECUTING"
    job = task_db.get(SddAiJob, new.ai_job_id)
    assert job.session_id == "preserved-session"
    assert job.prompt_text == "try again"
    assert task_db.query(SddAiJob).count() == 2
    enqueue.assert_awaited_once_with(job.id)


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
    state = service.build_session_state(task_db, "t", actor_id="u")
    assert state["receipts"][0]["status"] == "PREPARING"
    assert state["receipts"][0]["version"] == 1
    assert task_db.query(ChatMessage).count() == task_db.query(SddAiJob).count() == 0
    assert task_db.query(SearchOutbox).count() == before
    assert row.active_task_id == "t"
    events = task_db.query(TaskEventOutbox).all()
    assert len(events) == 1
    assert events[0].receipt_id == row.id
    assert events[0].payload_json["receipt"]["status"] == "PREPARING"
    assert events[0].status == "pending"


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
    from app.domains.ai.services.jobs.executors.diagnosis_summary import collect_diagnosis_transcript_sync
    assert collect_diagnosis_transcript_sync(task_db, "t") == ""


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
        assert service.build_session_state(task_db, "t", actor_id="u")["receipts"][0]["status"] == "PREPARING"
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
    original = ai_store.create_task_chat_job
    if fail_after_job_flush:
        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("between job flush and receipt update")
        monkeypatch.setattr(ai_store, "create_task_chat_job", fail)
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


def test_every_state_change_queues_one_outbox_event(task_db):
    row = accepted(task_db)
    assert task_db.query(TaskEventOutbox).count() == 1
    # execution() seeds the EXECUTING row directly (its turn owner commits the
    # same transition with message/job in _persist_chat_turn_sync); emulate the
    # event that owner writes by transitioning a fresh receipt instead.
    row.status = "EXECUTING"
    row.ai_job_id = None
    task_db.commit()
    job = execution(task_db, row)
    service._transition(task_db, row, "SUCCEEDED")
    task_db.commit()
    assert row.status == "SUCCEEDED" and row.version == 2
    latest = task_db.query(TaskEventOutbox).order_by(TaskEventOutbox.id.desc()).first()
    assert latest.payload_json["receipt"]["status"] == "SUCCEEDED"
    assert latest.payload_json["receipt"]["version"] == 2
    assert latest.receipt_version == 2


def test_terminal_receipt_rejects_further_transitions(task_db):
    row = accepted(task_db)
    execution(task_db, row)  # seeds EXECUTING directly, as the turn owner does
    job = task_db.get(SddAiJob, "job")
    job.status = AiJobStatus.SUCCESS
    task_db.commit()
    service._transition(task_db, row, "SUCCEEDED")
    task_db.commit()
    with pytest.raises(service.SubmissionError):
        service._transition(task_db, row, "FAILED")
    task_db.rollback()


@pytest.mark.asyncio
async def test_publisher_relays_outbox_and_backs_off(task_db, recovery_env, monkeypatch):
    from app.domains.task.services import task_event_publisher as publisher
    from app.domains.websocket.ws.manager import manager
    row = accepted(task_db)
    task_db.commit()
    sent = []
    async def record(task_id, message):
        sent.append((task_id, message.type, message.payload))
        return 1
    monkeypatch.setattr(manager, "send_message_to_room", record)
    published = await publisher.publish_once()
    assert published == 1
    assert sent[0][0] == "t" and sent[0][1] == "chat_submission_update"
    assert sent[0][2]["receipt"]["id"] == row.id
    assert sent[0][2]["event_id"]
    assert task_db.query(TaskEventOutbox).one().status == "published"
    # A failed publish defers with backoff instead of dropping the event.
    row.status, row.active_task_id = "FAILED", None  # release the active slot
    task_db.commit()
    row2 = accepted(task_db, "again")
    task_db.commit()
    async def boom(task_id, message):
        raise RuntimeError("room unavailable")
    monkeypatch.setattr(manager, "send_message_to_room", boom)
    published = await publisher.publish_once()
    assert published == 0
    deferred = task_db.query(TaskEventOutbox).filter_by(status="pending").one()
    assert deferred.last_error_code == "RuntimeError"
    assert deferred.available_at is not None


@pytest.mark.asyncio
async def test_convergence_finalizes_receipt_in_same_transaction(task_db, monkeypatch):
    from app.domains.ai.services import ai_job_convergence_service as convergence
    row = accepted(task_db)
    execution(task_db, row)  # seeds EXECUTING directly, as the turn owner does
    task_db.commit()
    request = convergence.AttemptConvergenceRequest(
        job_id="job", run_token="", worker_boot_id="",
        requested_status=AiJobStatus.SUCCESS, reason="turn done",
        evidence=convergence.resolve_attempt_evidence(
            execution_kind="remote_session", fallback_dead=True),
        intent=convergence.ConvergenceIntent.NORMAL_FINALIZE,
    )
    result = convergence.converge_job_attempt_sync(task_db, request)
    assert result.changed and result.is_final
    task_db.expire_all()
    assert row.status == "SUCCEEDED"
    assert row.active_task_id is None
    events = task_db.query(TaskEventOutbox).all()
    assert events[-1].payload_json["receipt"]["status"] == "SUCCEEDED"
    for message in task_db.query(ChatMessage).all():
        if message.metadata_json.get("submission_id") == row.id:
            assert message.metadata_json["knowledge_state"] == "published"


def test_session_state_resolves_unconfirmed_key_beyond_any_window(task_db):
    row = accepted(task_db, "ancient-key")
    execution(task_db, row, AiJobStatus.FAILED)
    task_db.get(SddTask, "t").session_generation = 9  # receipt is from an old generation
    task_db.commit()
    state = service.build_session_state(task_db, "t", actor_id="u",
                                        client_message_ids=["ancient-key", "never-seen"])
    ids = {receipt["id"] for receipt in state["receipts"]}
    assert row.id in ids
    by_client = {receipt["client_message_id"]: receipt for receipt in state["receipts"]}
    assert "ancient-key" in by_client
    assert "never-seen" not in by_client
    assert state["session_generation"] == 9
    assert any(message["id"] == "user" for message in state["messages"])


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
    path = Path(__file__).parents[2] / "alembic/versions/e6a718293b4c_chat_submissions.py"
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
    row = accepted(task_db)
    execution(task_db, row, AiJobStatus.FAILED)
    task = task_db.get(SddTask, "t")
    task.task_type, task.session_id = "DIAGNOSIS", "provider-with-failed-turn"
    task_db.add(SddAiJob(id="summary", task_id="t", workspace_id="w", creator_id="u",
        channel=AiJobChannel.TASK_CHAT, queue_key="summary:t", status=AiJobStatus.RUNNING,
        context_json={"source_session_id": task.session_id}))
    task_db.commit()
    monkeypatch.setattr(ai_diagnosis_summary, "attempt_is_current_sync", lambda *args, **kwargs: True)
    monkeypatch.setattr(ai_diagnosis_summary, "_resolve_task_project_path", lambda task: "/fake")
    monkeypatch.setattr(diagnosis_result_service, "build_diagnosis_summary_prompt", lambda task, transcript: transcript)
    prepared = ai_diagnosis_summary._prepare_diagnosis_summary_sync(task_db, "summary")
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
    async def no_wake():
        pass
    monkeypatch.setattr(service, "wake_event_publisher", no_wake)
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
        state_url = "/api/workspaces/w/tasks/t/session-state?client_message_ids=http"
        state = client.get(state_url)
        assert state.status_code == 200, state.text
        assert state.json()["receipts"][0]["id"] == first.json()["id"]
        other = client.get("/api/workspaces/other/tasks/t/session-state")
        assert other.status_code == 403
        assert client.post(url, json={**payload, "client_message_id": "second"}).status_code == 409
        assert client.post(url.replace("/w/", "/other/"), json=payload).status_code == 403
    assert task_db.query(ChatMessage).count() == task_db.query(SddAiJob).count() == 0
