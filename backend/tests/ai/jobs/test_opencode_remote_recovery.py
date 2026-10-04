"""Recovery owns the existing job; cancellation and old writers stay fenced."""
import asyncio
import time
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.agents.errors import AgentExecutionDetached
from app.agents.contract import AgentAttemptContext
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.ai.services.jobs import attempts, queue_runner, reaper, remote_recovery, store
from app.domains.ai.services.jobs.registry import WORKER_BOOT_ID, runtime
from app.domains.ai.services.jobs.executors import JobExecutionOutcome
from app.domains.task.models.task import SddTask, TaskStatus
from tests.ai.jobs.ai_job_test_utils import patch_ai_job_db
from tests.ai.jobs.reliability_helpers import _session_factory, _job


@pytest.fixture
def jobs(monkeypatch):
    factory = _session_factory()
    patch_ai_job_db(monkeypatch, factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)
    monkeypatch.setattr(runtime, "queue_runners", {})
    monkeypatch.setattr(runtime, "heartbeat_tasks", {})
    monkeypatch.setattr(runtime, "detached_jobs", set())
    monkeypatch.setattr(runtime, "shutting_down", False)
    with factory() as db:
        db.add(SddTask(id="task-1", workspace_id="ws-1", creator_id="user-1", name="Long task",
                       status=TaskStatus.CODING, session_revision=0, session_generation=1))
        job = _job(db, status=AiJobStatus.RUNNING, run_token="old-token", worker_boot_id="previous-boot")
        job.task_id, job.session_id = "task-1", "ses_original"
        job.session_revision, job.session_generation = 0, 1
        job.agent_backend, job.process_execution_kind = "opencode", "REMOTE_SESSION"
        job.provider_execution_json = {"version": 1, "session_id": "ses_original", "prompt_id": "msg_original",
                                       "deadline": time.time() + 15 * 3600, "phase": "submitted"}
        db.commit()
    return factory


def current(jobs):
    with jobs() as db:
        return db.get(SddAiJob, "reliability-job")


def previous_owner(jobs):
    row = current(jobs)
    return AgentAttemptContext(job_id=row.id, task_id=row.task_id, queue_key=row.queue_key,
                               run_token=row.run_token, worker_id="previous-worker", worker_boot_id=row.worker_boot_id,
                               attempt_count=row.attempt_count, execution_kind="REMOTE_SESSION")


def test_claim_existing_job_rotates_ownership_without_resetting_execution(jobs):
    before = current(jobs)
    assert remote_recovery.claim_existing_sync(before.id, "old-token") == before.queue_key
    after = current(jobs)
    assert after.status == AiJobStatus.RUNNING
    assert after.run_token != "old-token" and after.worker_boot_id == WORKER_BOOT_ID
    assert after.provider_execution_json == before.provider_execution_json
    assert after.session_id == before.session_id and after.started_at == before.started_at
    assert after.attempt_count == before.attempt_count + 1
    assert remote_recovery.claim_existing_sync(after.id, "old-token") is None
    assert remote_recovery.claim_existing_sync(after.id, after.run_token) is None


def test_checkpoint_rejects_replaced_owner_and_changed_input(jobs):
    old = previous_owner(jobs)
    before = current(jobs).provider_execution_json
    remote_recovery.claim_existing_sync(old.job_id, old.run_token)
    with pytest.raises(AgentExecutionDetached):
        remote_recovery.save_checkpoint_sync(old, before)
    owner = attempts.load_attempt_context_sync(old.job_id)
    remote_recovery.save_checkpoint_sync(owner, before)
    for patch in ({"prompt_id": "msg_new"}, {"deadline": time.time() + 86400}, {"session_id": "ses_new"}):
        with pytest.raises(AgentExecutionDetached):
            remote_recovery.save_checkpoint_sync(owner, {**before, **patch})


def test_persisted_stop_intent_closes_check_to_interrupt_takeover_race(jobs):
    remote_recovery.claim_existing_sync("reliability-job", "old-token")
    owner = attempts.load_attempt_context_sync("reliability-job")
    saved = current(jobs).provider_execution_json
    remote_recovery.save_checkpoint_sync(owner, {**saved, "phase": "stopping"})
    with jobs() as db:
        job = db.get(SddAiJob, owner.job_id)
        job.worker_boot_id = "owner-crashed-before-interrupt"
        job.next_reap_at = None
        db.commit()
    assert remote_recovery.claim_existing_sync(owner.job_id, owner.run_token) is None
    rows = reaper.list_reclaimable_jobs_sync()
    assert len(rows) == 1 and not rows[0]["recoverable_remote"]


@pytest.mark.parametrize("change", ["cancel", "revision", "generation", "terminal"])
def test_cancel_or_superseded_session_cannot_be_recovered(jobs, change):
    with jobs() as db:
        job, task = db.get(SddAiJob, "reliability-job"), db.get(SddTask, "task-1")
        if change == "cancel": job.cancel_requested_at = datetime.utcnow()
        if change == "revision": task.session_revision += 1
        if change == "generation": task.session_generation += 1
        if change == "terminal": job.status = AiJobStatus.SUCCESS
        db.commit()
    assert remote_recovery.claim_existing_sync("reliability-job", "old-token") is None
    assert not any(row["recoverable_remote"] for row in reaper.list_reclaimable_jobs_sync())


@pytest.mark.asyncio
async def test_startup_reaper_attaches_instead_of_stopping_remote(jobs, monkeypatch):
    schedule = Mock()
    stop = AsyncMock()
    monkeypatch.setattr(runtime, "schedule_queue", schedule)
    monkeypatch.setattr(reaper, "stop_attempt_processes", stop)
    await reaper.reap_stale_jobs()
    schedule.assert_called_once_with("TASK_CHAT:task-1", recovered_job_id="reliability-job")
    stop.assert_not_awaited()
    assert current(jobs).status == AiJobStatus.RUNNING


def test_shutdown_preserves_recoverable_job_and_checkpoint_is_private(jobs):
    remote_recovery.claim_existing_sync("reliability-job", "old-token")
    assert reaper.mark_worker_jobs_terminating_sync("WORKER_SHUTDOWN") == []
    job = current(jobs)
    assert job.status == AiJobStatus.RUNNING
    payload = store.serialize_job(job)
    assert "provider_execution_json" not in payload
    assert "msg_original" not in str(payload)


@pytest.mark.asyncio
async def test_recovered_queue_executes_claimed_job_and_detaches_without_finalizer(jobs, monkeypatch):
    remote_recovery.claim_existing_sync("reliability-job", "old-token")
    outcome = JobExecutionOutcome(requested_status=None, error=AgentExecutionDetached("transport"))
    execute = AsyncMock(return_value=outcome)
    finalizer, claim = AsyncMock(), AsyncMock()
    monkeypatch.setattr(queue_runner.executors, "execute_job", execute)
    monkeypatch.setattr(queue_runner, "_converge_runner_exit", finalizer)
    monkeypatch.setattr(queue_runner, "claim_next_pending_job_id", claim)
    monkeypatch.setattr(queue_runner.publishing, "publish_job_state", AsyncMock())
    monkeypatch.setattr(queue_runner.publishing, "broadcast_job_payload", AsyncMock())
    await queue_runner.run_queue("TASK_CHAT:task-1", recovered_job_id="reliability-job")
    execute.assert_awaited_once_with("reliability-job")
    claim.assert_not_awaited()
    finalizer.assert_not_awaited()
    assert current(jobs).status == AiJobStatus.RUNNING
    assert current(jobs).failure_code == "REMOTE_OBSERVER_DETACHED"


def test_old_heartbeat_cannot_cancel_successors_runner(jobs, monkeypatch):
    old = previous_owner(jobs)
    remote_recovery.claim_existing_sync(old.job_id, old.run_token)
    owner = attempts.load_attempt_context_sync(old.job_id)
    engine = SimpleNamespace(attempt=owner, remote_execution_checkpoint=current(jobs).provider_execution_json)
    runner = Mock()
    runner.done.return_value = False
    monkeypatch.setattr("app.engine.session.registry.get_engine", lambda _: engine)
    runtime.queue_runners[owner.queue_key] = runner
    assert remote_recovery.detach_local_observer(old)
    runner.cancel.assert_not_called()
    assert remote_recovery.detach_local_observer(owner)
    runner.cancel.assert_called_once()
    assert owner.job_id in runtime.detached_jobs


@pytest.mark.asyncio
async def test_engine_shutdown_closes_observer_but_honors_explicit_interrupt(monkeypatch):
    from app.engine.session import registry
    saved = {"version": 1, "session_id": "ses_test", "prompt_id": "msg_test",
             "deadline": time.time() + 10, "phase": "submitted"}
    continuing = SimpleNamespace(remote_execution_checkpoint=saved, _interrupt_requested=False,
                                 cli=SimpleNamespace(close=AsyncMock()), stop=AsyncMock())
    cancelled = SimpleNamespace(remote_execution_checkpoint=saved, _interrupt_requested=True,
                                cli=SimpleNamespace(close=AsyncMock()), stop=AsyncMock())
    monkeypatch.setattr(registry, "_active_engines", {"keep": continuing, "cancel": cancelled})
    monkeypatch.setattr(registry, "_idle_sweeper_task", None)
    await registry.shutdown_active_engines()
    continuing.cli.close.assert_awaited_once()
    continuing.stop.assert_not_awaited()
    cancelled.stop.assert_awaited_once()


def test_checkpoint_migration_preserves_existing_rows_and_downgrades():
    import runpy
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text
    migration = runpy.run_path(str(Path(__file__).resolve().parents[3] / "alembic/versions/f294bd81a0e3_provider_execution_checkpoint.py"))
    with create_engine("sqlite://").begin() as connection:
        connection.execute(text("CREATE TABLE sdd_ai_jobs (id TEXT PRIMARY KEY)"))
        connection.execute(text("INSERT INTO sdd_ai_jobs VALUES ('existing')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()
            assert "provider_execution_json" in {column["name"] for column in inspect(connection).get_columns("sdd_ai_jobs")}
            assert connection.execute(text("SELECT id, provider_execution_json FROM sdd_ai_jobs")).one() == ("existing", None)
            migration["downgrade"]()
        assert connection.execute(text("SELECT id FROM sdd_ai_jobs")).scalar() == "existing"


@pytest.mark.asyncio
async def test_recovered_provider_terminal_reaches_durable_job_finalizer(jobs, monkeypatch):
    import httpx
    from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
    from app.agents.contract import AgentRunRequest, bind_agent_attempt, reset_agent_attempt
    from app.domains.ai.services.jobs.executors import task_chat

    remote_recovery.claim_existing_sync("reliability-job", "old-token")
    owner = attempts.load_attempt_context_sync("reliability-job")
    token = bind_agent_attempt(owner)
    saved = current(jobs).provider_execution_json
    calls = []

    def provider(request):
        calls.append((request.method, request.url.path))
        assert request.method == "GET" and request.url.path.endswith("/message")
        return httpx.Response(200, json={"data": [
            {"id": saved["prompt_id"], "type": "user"},
            {"id": "msg_answer", "type": "assistant", "time": {"completed": 123},
             "content": [{"type": "text", "text": "finished while backend was down"}]},
            {"type": "idle", "outcome": "succeeded"},
        ], "cursor": {}})

    async def save(value):
        remote_recovery.save_checkpoint_sync(owner, value)

    adapter = OpenCodeAdapter("http://agent")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    monkeypatch.setattr(task_chat.publishing, "broadcast_job_payload", AsyncMock())
    monkeypatch.setattr(task_chat.publishing, "reschedule_if_pending", Mock())
    try:
        result = await adapter.run(AgentRunRequest(session_id=saved["session_id"], execution_checkpoint=saved,
                                                   on_execution_checkpoint=save), AsyncMock())
        engine = SimpleNamespace(last_result=result, last_result_success=result.success,
                                 last_result_text=result.result_text, session_id=result.session_id)
        await task_chat.finalize_task_chat_job_from_engine(owner.job_id, engine)
        job = current(jobs)
        assert job.status == AiJobStatus.SUCCESS and job.finished_at is not None
        assert job.run_token is None and job.lease_expires_at is None
        assert job.result_json["result_preview"] == result.result_text
        assert calls and all(method == "GET" for method, _ in calls)
    finally:
        reset_agent_attempt(token)
        await adapter.close()
