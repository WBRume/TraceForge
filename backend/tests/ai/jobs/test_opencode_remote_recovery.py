"""Recovery owns the existing job; cancellation and old writers stay fenced."""

import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.agents.contract import (
    EXECUTION_KIND_REMOTE_SESSION,
    AgentAttemptContext,
    AgentInputImage,
    AgentRunResult,
    AgentStopResult,
)
from app.agents.errors import AgentExecutionDetached
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.schemas.job_result import JobArtifact
from app.domains.ai.services.ai_job_convergence_service import evidence_from_stop_result
from app.domains.ai.services.jobs import attempts, queue_runner, reaper, remote_recovery, store
from app.domains.ai.services.jobs.domain_turn import stage_domain_success
from app.domains.ai.services.jobs.executors import JobExecutionOutcome
from app.domains.ai.services.jobs.executors.task_chat import _load_task_chat_turn_state_sync
from app.domains.ai.services.jobs.registry import WORKER_BOOT_ID, runtime
from app.domains.task.models.chat import TaskChatImage
from app.domains.task.models.task import SddTask, TaskStatus
from tests.ai.jobs.ai_job_test_utils import patch_ai_job_db
from tests.ai.jobs.reliability_helpers import _job, _session_factory


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
        db.add(
            SddTask(
                id="task-1",
                workspace_id="ws-1",
                creator_id="user-1",
                name="Long task",
                status=TaskStatus.RUNNING,
                session_revision=0,
                session_generation=1,
            )
        )
        job = _job(db, status=AiJobStatus.RUNNING, run_token="old-token", worker_boot_id="previous-boot")
        job.task_id, job.session_id = "task-1", "ses_original"
        job.session_revision, job.session_generation = 0, 1
        job.agent_backend, job.process_execution_kind = "opencode", "REMOTE_SESSION"
        job.provider_execution_json = {
            "version": 1,
            "session_id": "ses_original",
            "prompt_id": "msg_original",
            "deadline": time.time() + 15 * 3600,
            "phase": "submitted",
        }
        db.commit()
    return factory


def current(jobs):
    with jobs() as db:
        return db.get(SddAiJob, "reliability-job")


@pytest.mark.asyncio
async def test_old_service_stop_checks_identity_then_reads_terminal_turn(monkeypatch):
    from app.agents.service_binding import AgentService

    session_id = "ses_original"
    service = AgentService("opencode", 1, {"server_url": "http://old.example"})
    binding = {**service.persist(), "native_session": {"id": session_id, "directory": "G:/task", "created": 1}}
    backend = SimpleNamespace(
        name="opencode",
        native_session=AsyncMock(return_value={"directory": "G:/task", "created": 2}),
        session_running=AsyncMock(return_value=False),
        list_messages=AsyncMock(
            return_value=[
                {"id": "msg_original", "type": "user"},
                {"type": "assistant", "content": [{"type": "text", "text": "saved result"}]},
                {"type": "idle", "outcome": "succeeded"},
            ]
        ),
        cancel_persisted_session=AsyncMock(),
        close=AsyncMock(),
    )
    monkeypatch.setattr(AgentService, "adapter", lambda self: backend)
    row = {
        "agent_backend": "opencode",
        "session_id": session_id,
        "agent_service_binding": binding,
        "cancel_requested": True,
        "provider_execution": {
            "version": 1,
            "session_id": session_id,
            "prompt_id": "msg_original",
            "deadline": time.time() + 60,
            "phase": "submitted",
        },
    }
    assert not (await reaper.stop_remote_session(row)).stop_acknowledged
    backend.session_running.assert_not_awaited()

    backend.native_session.return_value["created"] = 1
    result = await reaper.stop_remote_session(row)
    assert result.stop_acknowledged and result.recovered_result.success
    assert result.recovered_result.result_text == "saved result"
    backend.cancel_persisted_session.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("running", [False, True])
async def test_reaper_needs_quiescence_to_accept_an_aborted_tool_as_terminal(running):
    backend = SimpleNamespace(
        name="opencode",
        session_running=AsyncMock(return_value=running),
        list_messages=AsyncMock(
            return_value=[
                {"type": "user", "id": "msg_owned"},
                {
                    "type": "assistant",
                    "finish": "error",
                    "time": {"completed": 123},
                    "content": [{"type": "tool", "state": {"status": "error", "error": {"type": "aborted"}}}],
                },
            ]
        ),
    )
    proof = await reaper.completed_remote_session(
        backend,
        {
            "session_id": "ses_owned",
            "provider_execution": {
                "version": 1,
                "session_id": "ses_owned",
                "prompt_id": "msg_owned",
                "deadline": time.time() + 60,
                "phase": "submitted",
            },
        },
    )
    if running:
        assert proof is None
    else:
        assert proof.stop_acknowledged and not proof.recovered_result.success


def previous_owner(jobs):
    row = current(jobs)
    return AgentAttemptContext(
        job_id=row.id,
        task_id=row.task_id,
        queue_key=row.queue_key,
        run_token=row.run_token,
        worker_id="previous-worker",
        worker_boot_id=row.worker_boot_id,
        attempt_count=row.attempt_count,
        execution_kind="REMOTE_SESSION",
    )


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


@pytest.mark.parametrize("phase", ["prepared", "submitting", "submitted"])
def test_checkpoint_recovery_loads_images_only_when_input_can_still_need_submission(jobs, phase):
    with jobs() as db:
        job = db.get(SddAiJob, "reliability-job")
        image = TaskChatImage(
            id="attachment",
            task_id=job.task_id,
            creator_id=job.creator_id,
            filename="fixture.png",
            media_type="image/png",
            data=b"raster bytes",
        )
        job.context_json = {
            "chat_images": [{"id": image.id, "filename": image.filename, "media_type": image.media_type}]
        }
        job.provider_execution_json = {**job.provider_execution_json, "phase": phase}
        if phase != "submitted":
            db.add(image)
        db.commit()

        state = _load_task_chat_turn_state_sync(db, job.id)

    expected = () if phase == "submitted" else (AgentInputImage("fixture.png", "image/png", b"raster bytes"),)
    assert state["images"] == expected


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
        job.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        job.next_reap_at = None
        db.commit()
    assert remote_recovery.claim_existing_sync(owner.job_id, owner.run_token) is None
    rows = reaper.list_reclaimable_jobs_sync()
    assert len(rows) == 1 and rows[0].recovery_queue_key is None


@pytest.mark.parametrize("change", ["cancel", "revision", "generation", "terminal"])
def test_cancel_or_superseded_session_cannot_be_recovered(jobs, change):
    with jobs() as db:
        job, task = db.get(SddAiJob, "reliability-job"), db.get(SddTask, "task-1")
        if change == "cancel":
            job.cancel_requested_at = datetime.utcnow()
        if change == "revision":
            task.session_revision += 1
        if change == "generation":
            task.session_generation += 1
        if change == "terminal":
            job.status = AiJobStatus.SUCCESS
        db.commit()
    assert remote_recovery.claim_existing_sync("reliability-job", "old-token") is None
    assert not any(row.recovery_queue_key is not None for row in reaper.list_reclaimable_jobs_sync())


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


@pytest.mark.asyncio
async def test_checkpoint_committed_after_scan_is_used_for_recovery(jobs, monkeypatch):
    checkpoint = current(jobs).provider_execution_json
    with jobs.begin() as db:
        db.get(SddAiJob, "reliability-job").provider_execution_json = None
    scan = reaper.list_reclaimable_jobs_sync

    def scan_before_checkpoint(task_id=None):
        rows = scan(task_id)
        with jobs.begin() as db:
            db.get(SddAiJob, "reliability-job").provider_execution_json = checkpoint
        return rows

    schedule = Mock()
    stop = AsyncMock(return_value=None)
    monkeypatch.setattr(runtime, "schedule_queue", schedule)
    monkeypatch.setattr(reaper, "stop_attempt_processes", stop)
    with monkeypatch.context() as before_commit:
        before_commit.setattr(reaper, "list_reclaimable_jobs_sync", scan_before_checkpoint)
        await reaper.reap_stale_jobs()
    assert current(jobs).status == AiJobStatus.RUNNING
    await reaper.reap_stale_jobs()
    schedule.assert_called_once_with("TASK_CHAT:task-1", recovered_job_id="reliability-job")
    stop.assert_not_awaited()


def test_reaper_recovers_a_failed_chat_turn_as_an_abnormal_interrupt(jobs):
    with jobs.begin() as db:
        job = db.get(SddAiJob, "reliability-job")
        task = db.get(SddTask, job.task_id)
        task.status_run_id = job.id
        job.status = AiJobStatus.TERMINATING
        job.worker_boot_id = WORKER_BOOT_ID
    recovered = AgentRunResult(session_id="ses_original", success=False, result_text="Provider interrupted the turn")
    result = attempts.finish_termination_sync(
        "reliability-job",
        "old-token",
        confirmed_dead=True,
        reason="WORKER_RESTART",
        failure_code="WORKER_RESTART",
        evidence=evidence_from_stop_result(AgentStopResult(EXECUTION_KIND_REMOTE_SESSION, True)),
        recovered_result=recovered,
    )
    assert result["status"] == "INTERRUPTED"
    assert result["interrupt_kind"] == "ABNORMAL"
    assert result["task_snapshot"]["interrupt_kind"] == "ABNORMAL"
    assert result["session_id"] == recovered.session_id


def test_reaper_keeps_the_committed_artifact_result_and_session(jobs):
    with jobs.begin() as db:
        job = db.get(SddAiJob, "reliability-job")
        job.channel = AiJobChannel.ASSET_THREAD
        job.queue_key = "ASSET_THREAD:thread-1"
        job.context_json = {"job_kind": "RESOLUTION_PROPOSAL"}
        job.worker_boot_id = WORKER_BOOT_ID
        stage_domain_success(
            job,
            message="Proposal saved",
            result={"proposal_id": "proposal", "result_preview": "Committed summary"},
            artifact=JobArtifact(kind="resolution_proposal", id="proposal"),
            context_patch={},
            session_id="ses_committed",
        )
        job.status = AiJobStatus.TERMINATING

    result = attempts.finish_termination_sync(
        "reliability-job",
        "old-token",
        confirmed_dead=True,
        reason="WORKER_RESTART",
        failure_code="WORKER_RESTART",
        evidence=evidence_from_stop_result(AgentStopResult(EXECUTION_KIND_REMOTE_SESSION, True)),
        recovered_result=AgentRunResult(session_id="ses_original", success=True, result_text="Provider output"),
    )
    assert result["status"] == "SUCCESS"
    assert result["message"] == "Proposal saved"
    assert result["result_json"] == {"proposal_id": "proposal", "result_preview": "Committed summary"}
    assert result["session_id"] == "ses_committed"


def test_reaper_keeps_a_manual_stop_when_the_provider_returns_success(jobs):
    with jobs.begin() as db:
        job = db.get(SddAiJob, "reliability-job")
        job.worker_boot_id = WORKER_BOOT_ID
        job.status = AiJobStatus.TERMINATING
        job.cancel_requested_at = datetime.utcnow()
        job.interrupted_by_id = job.creator_id
        job.context_json = {"termination_mode": "INTERRUPT", "interrupt_kind": "MANUAL"}
        task = db.get(SddTask, job.task_id)
        task.status = TaskStatus.INTERRUPTED
        task.interrupt_kind = "MANUAL"

    result = attempts.finish_termination_sync(
        "reliability-job",
        "old-token",
        confirmed_dead=True,
        reason="WORKER_RESTART",
        failure_code="WORKER_RESTART",
        evidence=evidence_from_stop_result(AgentStopResult(EXECUTION_KIND_REMOTE_SESSION, True)),
        recovered_result=AgentRunResult(session_id="ses_original", success=True, result_text="Provider output"),
    )
    assert result["status"] == "INTERRUPTED"
    assert result["interrupt_kind"] == result["task_snapshot"]["interrupt_kind"] == "MANUAL"
    assert not result["result_json"]


def test_shutdown_preserves_recoverable_job_and_checkpoint_is_private(jobs):
    remote_recovery.claim_existing_sync("reliability-job", "old-token")
    assert reaper.mark_worker_jobs_terminating_sync("WORKER_SHUTDOWN") == []
    job = current(jobs)
    assert job.status == AiJobStatus.RUNNING
    payload = store.serialize_job(job)
    assert "provider_execution_json" not in payload
    assert "msg_original" not in str(payload)


def test_closeout_retry_is_distinct_from_an_unavailable_bound_service(jobs):
    with jobs.begin() as db:
        db.get(SddAiJob, "reliability-job").agent_service_binding = {"backend": "opencode", "generation": 1}
    remote_recovery.claim_existing_sync("reliability-job", "old-token")
    attempt = attempts.load_attempt_context_sync("reliability-job")
    payload = remote_recovery.defer_observation_sync(attempt, failure_code=remote_recovery.REMOTE_CLOSEOUT_PENDING)
    assert payload["status"] == "RUNNING"
    assert payload["failure_code"] == remote_recovery.REMOTE_CLOSEOUT_PENDING
    assert current(jobs).run_token == attempt.run_token
    assert current(jobs).provider_execution_json["prompt_id"] == "msg_original"


@pytest.mark.asyncio
@pytest.mark.parametrize("publication_fails", [False, True])
async def test_recovered_queue_executes_claimed_job_and_detaches_without_finalizer(
    jobs, monkeypatch, publication_fails
):
    remote_recovery.claim_existing_sync("reliability-job", "old-token")
    outcome = JobExecutionOutcome(requested_status=None, error=AgentExecutionDetached("transport"))
    execute = AsyncMock(return_value=outcome)
    finalizer, claim = AsyncMock(), AsyncMock()
    monkeypatch.setattr(queue_runner.executors, "execute_job", execute)
    monkeypatch.setattr(queue_runner, "_converge_runner_exit", finalizer)
    monkeypatch.setattr(queue_runner, "claim_next_pending_job_id", claim)
    monkeypatch.setattr(
        queue_runner.publishing,
        "publish_job_state",
        AsyncMock(side_effect=OSError("initial state publication unavailable") if publication_fails else None),
    )
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

    saved = {
        "version": 1,
        "session_id": "ses_test",
        "prompt_id": "msg_test",
        "deadline": time.time() + 10,
        "phase": "submitted",
    }
    continuing = SimpleNamespace(
        remote_execution_checkpoint=saved,
        _interrupt_requested=False,
        cli=SimpleNamespace(close=AsyncMock()),
        stop=AsyncMock(),
    )
    cancelled = SimpleNamespace(
        remote_execution_checkpoint=saved,
        _interrupt_requested=True,
        cli=SimpleNamespace(close=AsyncMock()),
        stop=AsyncMock(),
    )
    monkeypatch.setattr(registry, "_active_engines", {"keep": continuing, "cancel": cancelled})
    monkeypatch.setattr(registry, "_idle_sweeper_task", None)
    await registry.shutdown_active_engines()
    continuing.cli.close.assert_awaited_once()
    continuing.stop.assert_not_awaited()
    cancelled.stop.assert_awaited_once()


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
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": saved["prompt_id"], "type": "user"},
                    {
                        "id": "msg_answer",
                        "type": "assistant",
                        "time": {"completed": 123},
                        "content": [{"type": "text", "text": "finished while backend was down"}],
                    },
                    {"type": "idle", "outcome": "succeeded"},
                ],
                "cursor": {},
            },
        )

    async def save(value):
        remote_recovery.save_checkpoint_sync(owner, value)

    adapter = OpenCodeAdapter("http://agent")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    monkeypatch.setattr(task_chat.publishing, "broadcast_job_payload", AsyncMock())
    monkeypatch.setattr(task_chat.publishing, "reschedule_if_pending", Mock())
    try:
        result = await adapter.run(
            AgentRunRequest(session_id=saved["session_id"], execution_checkpoint=saved, on_execution_checkpoint=save),
            AsyncMock(),
        )
        engine = SimpleNamespace(
            last_result=result,
            last_result_success=result.success,
            last_result_text=result.result_text,
            session_id=result.session_id,
        )
        await task_chat.finalize_task_chat_job_from_engine(owner.job_id, engine)
        job = current(jobs)
        assert job.status == AiJobStatus.SUCCESS and job.finished_at is not None
        assert job.run_token is None and job.lease_expires_at is None
        assert job.result_json["result_preview"] == result.result_text
        assert calls and all(method == "GET" for method, _ in calls)
    finally:
        reset_agent_attempt(token)
        await adapter.close()
