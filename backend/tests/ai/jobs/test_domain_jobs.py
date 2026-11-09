"""Shared execution: durable inputs, independent cancellation, leases and fences."""

import asyncio
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents import bind_agent_attempt, current_agent_attempt, reset_agent_attempt
from app.agents.errors import AgentCancelledError
from app.database import Base
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.ai.services.jobs import attempts, domain_jobs, queue_runner, reaper, registry, store
from app.domains.ai.services.jobs.executors import domain_job
from app.domains.ai.services.jobs.fencing import AgentAttemptFencedError
from app.domains.api_mock.models.api_mock import ApiMockJobStatus, SddApiMockJob, SddApiMockProject
from app.domains.api_mock.services import api_mock_service
from app.domains.api_mock.services.api_mock import job_service
from app.domains.skill.models.skill import SddSkillAnalysis, SkillAnalysisRefKind
from app.domains.skill.services import skill_analysis_service
from app.domains.workflow.models.provision_job import ProvisionJobStatus, ProvisionJobType, SddProvisionJob
from app.domains.workflow.services import provision_job_service as provision
from tests.ai.jobs.ai_job_test_utils import patch_ai_job_db


@pytest.fixture
def execution_db(monkeypatch, tmp_path):
    path = tmp_path / "jobs.sqlite"
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    patch_ai_job_db(monkeypatch, factory)
    for target in (domain_job, provision, job_service, api_mock_service, skill_analysis_service):
        monkeypatch.setattr(target, "SessionLocal", factory)
    monkeypatch.setattr("app.database.SessionLocal", factory)
    monkeypatch.setattr(store, "resolve_execution_kind_for_claim", lambda *_args, **_kwargs: "LOCAL_PROCESS")
    monkeypatch.setattr(job_service, "_broadcast_job_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(registry.runtime, "schedule_queue", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(registry.runtime, "shutting_down", False)
    yield factory, path
    engine.dispose()


def create_provision(factory, *, task_id="task"):
    with factory() as db:
        return provision.create_job(
            db,
            job_type=ProvisionJobType.CREATE_TASK,
            creator_id="user",
            workspace_id="workspace",
            task_id=task_id,
        ).id


def create_mock(factory, *, inputs=None):
    with factory() as db:
        project = SddApiMockProject(
            id="project",
            workspace_id="workspace",
            task_id="task",
            creator_id="user",
            temp_workspace_path="unused",
        )
        db.add(project)
        db.commit()
        return job_service.create_job(
            db,
            project,
            creator_id="user",
            job_type="IMPORT_SWAGGER",
            execution_input=inputs or {"source_name": "spec", "source_url": None, "raw_content": "document"},
        ).id


def claim(factory, job_id):
    with factory() as db:
        queue = db.get(SddAiJob, job_id).queue_key
    assert store.take_next_pending_job_id_sync(queue) == job_id
    assert store.take_next_pending_job_id_sync(queue) is None
    return queue, attempts.load_attempt_context_sync(job_id)


def test_skill_creation_and_retry_commit_execution_receipts(execution_db, monkeypatch):
    factory, _ = execution_db
    monkeypatch.setattr(
        skill_analysis_service,
        "_resolve_ref",
        lambda *_args, **_kwargs: (
            SkillAnalysisRefKind.WORKTREE,
            None,
            None,
        ),
    )
    with factory() as db:
        analysis = skill_analysis_service.create_analysis_job(
            db,
            user=SimpleNamespace(id="user"),
            skill=SimpleNamespace(id="skill"),
            workspace_id="workspace",
            ref_kind="WORKTREE",
        )
        retry = skill_analysis_service.retry_analysis_job(db, source=analysis, user_id="user")
        ids = [analysis.id, retry.id]
    with factory() as db:
        for job_id in ids:
            assert db.get(SddSkillAnalysis, job_id) is not None
            assert db.get(SddAiJob, job_id).context_json["job_kind"] == "SKILL_ANALYSIS"
    assert len(store.list_pending_queue_keys_sync()) == 2


def test_receipt_rolls_back_with_business_row(execution_db):
    factory, _ = execution_db
    with factory() as db:
        row = SddProvisionJob(job_type=ProvisionJobType.CREATE_TASK, creator_id="user", stage="QUEUED")
        db.add(row)
        db.flush()
        job_id = row.id
        domain_jobs.enqueue(
            db,
            job_id=job_id,
            kind="PROVISION",
            creator_id="user",
            workspace_id=None,
            resource_id=job_id,
            inputs={"job_type": "CREATE_TASK"},
        )
        db.flush()
        db.rollback()
    with factory() as db:
        assert db.get(SddProvisionJob, job_id) is None
        assert db.get(SddAiJob, job_id) is None


def test_dispatch_after_restart_uses_persisted_import_inputs(execution_db, monkeypatch):
    factory, _ = execution_db
    inputs = {"source_name": "接口定义", "source_url": None, "raw_content": '{"openapi":"3.1.0"}'}
    job_id = create_mock(factory, inputs=inputs)
    queue = store.list_pending_queue_keys_sync()[0]
    calls = []

    def run(received_id, **params):
        assert received_id == job_id
        assert current_agent_attempt().run_token
        assert {key: params[key] for key in inputs} == inputs
        calls.append(received_id)
        with domain_jobs.business_session(factory) as db:
            row = db.get(SddApiMockJob, job_id)
            job_service._set_job_success(db, "project", row, {"endpoints_imported": 1}, "Imported")

    monkeypatch.setattr(api_mock_service, "run_import_job_background", run)
    asyncio.run(queue_runner.run_queue(queue))
    asyncio.run(queue_runner.run_queue(queue))
    assert calls == [job_id]
    with factory() as db:
        assert db.get(SddAiJob, job_id).status == AiJobStatus.SUCCESS
        assert db.get(SddApiMockJob, job_id).result_json == {"endpoints_imported": 1}


def test_cancel_from_another_process_is_observed_without_local_event(execution_db):
    factory, path = execution_db
    job_id = create_mock(factory)
    _, attempt = claim(factory, job_id)
    job_service._clear_cancel_event(job_id)
    script = """
import sqlite3, sys
with sqlite3.connect(sys.argv[1]) as db:
    db.execute('UPDATE sdd_api_mock_jobs SET result_json = ? WHERE id = ?',
               ('{"cancel_requested": true}', sys.argv[2]))
    db.execute('UPDATE sdd_ai_jobs SET cancel_requested_at = ? WHERE id = ?',
               ('2026-11-09 00:00:00', sys.argv[2]))
"""
    subprocess.run([sys.executable, "-c", script, str(path), job_id], check=True, timeout=10)
    assert job_service._is_cancel_requested(job_id)
    token = bind_agent_attempt(attempt)
    try:
        assert domain_jobs.should_cancel()
        with domain_jobs.business_session(factory) as db:
            row = db.get(SddApiMockJob, job_id)
            with pytest.raises(AgentCancelledError):
                job_service._set_job_success(db, "project", row, {"created_count": 9}, "Too late")
            db.rollback()
    finally:
        reset_agent_attempt(token)
    with factory() as db:
        assert db.get(SddApiMockJob, job_id).status == ApiMockJobStatus.PENDING
        assert db.get(SddApiMockJob, job_id).result_json == {"cancel_requested": True}


def test_cancel_queued_provision_runs_cleanup_before_terminal_receipt(execution_db, monkeypatch):
    factory, _ = execution_db
    job_id = create_provision(factory)
    with factory() as db:
        assert provision.request_cancel(db, db.get(SddProvisionJob, job_id))
        queue = db.get(SddAiJob, job_id).queue_key
        assert db.get(SddAiJob, job_id).status == AiJobStatus.PENDING
    cleanups = []

    async def cleanup(**kwargs):
        with factory() as db:
            assert db.get(SddAiJob, job_id).status == AiJobStatus.RUNNING
        cleanups.append(kwargs["task_id"])

    monkeypatch.setattr(provision, "_workspace_uses_git", lambda _: False)
    monkeypatch.setattr(provision, "_rollback_task_resources", cleanup)
    asyncio.run(queue_runner.run_queue(queue))
    assert cleanups == ["task"]
    with factory() as db:
        assert db.get(SddAiJob, job_id).status == AiJobStatus.CANCELLED
        row = db.get(SddProvisionJob, job_id)
        assert row.status == ProvisionJobStatus.FAILED
        assert row.stage == "CANCELLED"


@pytest.mark.parametrize("change", ["token", "expired_lease", "terminal"])
def test_stale_attempt_cannot_commit_business_changes(execution_db, change):
    factory, _ = execution_db
    job_id = create_provision(factory)
    _, attempt = claim(factory, job_id)
    with factory() as db:
        receipt = db.get(SddAiJob, job_id)
        if change == "token":
            receipt.run_token = "replacement-attempt"
        elif change == "expired_lease":
            receipt.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        else:
            receipt.status = AiJobStatus.SUCCESS
        db.commit()
    token = bind_agent_attempt(attempt)
    try:
        with pytest.raises(AgentAttemptFencedError):
            provision.mark_success(job_id, stage="COMPLETED", message="late result")
    finally:
        reset_agent_attempt(token)
    with factory() as db:
        assert db.get(SddProvisionJob, job_id).status == ProvisionJobStatus.PENDING


def test_other_process_with_valid_lease_is_not_reclaimed(execution_db):
    factory, _ = execution_db
    job_id = create_provision(factory)
    claim(factory, job_id)
    with factory() as db:
        db.get(SddAiJob, job_id).worker_boot_id = "another-live-process"
        db.commit()
    assert reaper.list_reclaimable_jobs_sync() == []


def test_reaper_rechecks_a_renewed_lease_before_adopting(execution_db):
    factory, _ = execution_db
    job_id = create_provision(factory)
    _, attempt = claim(factory, job_id)
    with factory() as db:
        db.get(SddAiJob, job_id).lease_expires_at = datetime.utcnow() + timedelta(seconds=60)
        db.commit()
    assert not reaper.adopt_reclaimable_job_sync(job_id, attempt.run_token, "reaper-token", "LEASE_EXPIRED")


@pytest.mark.parametrize("exhausted", [False, True])
def test_recovery_requeues_or_finishes_business_state(execution_db, monkeypatch, exhausted):
    factory, _ = execution_db
    job_id = create_provision(factory)
    queue, old_attempt = claim(factory, job_id)
    with factory() as db:
        receipt = db.get(SddAiJob, job_id)
        receipt.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        if exhausted:
            receipt.attempt_count = receipt.max_attempts
        db.get(SddProvisionJob, job_id).status = ProvisionJobStatus.RUNNING
        db.commit()

    async def stop(*_):
        return SimpleNamespace(confirmed_dead=True, error_message=None, error_code=None)

    monkeypatch.setattr(reaper, "stop_attempt_processes", stop)
    assert asyncio.run(reaper.reap_stale_jobs()) == 1
    with factory() as db:
        receipt = db.get(SddAiJob, job_id)
        assert receipt.run_token is None
        assert receipt.status == (AiJobStatus.FAILED if exhausted else AiJobStatus.PENDING)
        assert db.get(SddProvisionJob, job_id).status.value == receipt.status.value
    if not exhausted:
        assert store.take_next_pending_job_id_sync(queue) == job_id
        assert attempts.load_attempt_context_sync(job_id).run_token != old_attempt.run_token


def test_thread_is_drained_before_cancelled_executor_exits():
    started = threading.Event()
    finish = threading.Event()
    completed = threading.Event()

    def work():
        started.set()
        assert finish.wait(timeout=5)
        completed.set()

    async def run():
        task = asyncio.create_task(domain_job.run_sync(work))
        while not started.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert completed.is_set()

    asyncio.run(run())


def test_upgrade_recovers_old_jobs_and_requires_reupload_for_lost_imports(execution_db):
    import importlib.util
    from pathlib import Path

    factory, _ = execution_db
    path = Path(__file__).parents[3] / "alembic/versions/c84f0e2a9137_domain_job_execution.py"
    spec = importlib.util.spec_from_file_location("domain_job_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with factory() as db:
        db.add(SddSkillAnalysis(id="old-analysis", workspace_id="workspace", skill_id="skill", created_by_id="user"))
        db.add(
            SddProvisionJob(
                id="old-provision", job_type=ProvisionJobType.CREATE_WORKSPACE, creator_id="user", stage="QUEUED"
            )
        )
        db.add(
            SddApiMockProject(
                id="old-project",
                workspace_id="workspace",
                task_id="task",
                creator_id="user",
                temp_workspace_path="unused",
            )
        )
        for job_id, job_type in (
            ("old-sync", "SYNC_TASK_SOURCE"),
            ("old-auto", "AUTO_GENERATE_MOCK_CASES"),
            ("old-import", "IMPORT_SWAGGER"),
        ):
            db.add(
                SddApiMockJob(
                    id=job_id,
                    project_id="old-project",
                    creator_id="user",
                    job_type=job_type,
                    result_json={"target_endpoint_id": "endpoint"},
                )
            )
        db.commit()
        migration.backfill_receipts(db.connection())
        db.commit()
        migration.backfill_receipts(db.connection())
        db.commit()
        assert db.query(SddAiJob).count() == 4
        assert db.get(SddAiJob, "old-provision").workspace_id is None
        assert db.get(SddAiJob, "old-auto").context_json["inputs"]["endpoint_id"] == "endpoint"
        assert db.get(SddAiJob, "old-sync").context_json["inputs"]["job_type"] == "SYNC_TASK_SOURCE"
        assert db.get(SddApiMockJob, "old-import").status == ApiMockJobStatus.FAILED
        assert "upload" in db.get(SddApiMockJob, "old-import").message


def test_cancellation_during_worker_start_converges_receipt(execution_db, monkeypatch):
    factory, _ = execution_db
    job_id = create_mock(factory)
    with factory() as db:
        row = db.get(SddApiMockJob, job_id)
        row.status = ApiMockJobStatus.RUNNING
        db.commit()
        job_service.request_job_cancel(db, "project", job_id)
        queue = db.get(SddAiJob, job_id).queue_key
    monkeypatch.setattr(api_mock_service, "ensure_project", lambda db, *_: db.get(SddApiMockProject, "project"))
    asyncio.run(queue_runner.run_queue(queue))
    with factory() as db:
        assert db.get(SddAiJob, job_id).status == AiJobStatus.CANCELLED
        row = db.get(SddApiMockJob, job_id)
        assert row.status == ApiMockJobStatus.FAILED
        assert row.result_json["cancelled"]


def test_cancel_after_business_commit_preserves_success(execution_db):
    factory, _ = execution_db
    job_id = create_mock(factory)
    claim(factory, job_id)
    with factory() as db:
        row = db.get(SddApiMockJob, job_id)
        row.status = ApiMockJobStatus.SUCCESS
        row.result_json = {"endpoints_imported": 2}
        db.commit()
    with factory() as db:
        row = job_service.request_job_cancel(db, "project", job_id)
        assert row.status == ApiMockJobStatus.SUCCESS
        assert db.get(SddAiJob, job_id).cancel_requested_at is None
        assert row.result_json == {"endpoints_imported": 2}


def test_worker_shutdown_preserves_domain_job_for_recovery(execution_db):
    from app.domains.ai.services.ai_job_convergence_service import (
        AttemptTerminationRequest,
        request_attempt_termination_in_txn,
    )

    factory, _ = execution_db
    job_id = create_provision(factory)
    _, attempt = claim(factory, job_id)
    with factory() as db:
        request_attempt_termination_in_txn(
            db,
            AttemptTerminationRequest(
                job_id=job_id,
                mode="WORKER_SHUTDOWN",
                reason="WORKER_SHUTDOWN",
            ),
        )
        db.commit()
        assert db.get(SddAiJob, job_id).cancel_requested_at is None
    attempts.finish_termination_sync(
        job_id, attempt.run_token, confirmed_dead=True, reason="WORKER_SHUTDOWN", failure_code="WORKER_SHUTDOWN"
    )
    with factory() as db:
        assert db.get(SddAiJob, job_id).status == AiJobStatus.PENDING
        assert db.get(SddProvisionJob, job_id).status == ProvisionJobStatus.PENDING


def test_provision_dispatch_preserves_application_loop(execution_db, monkeypatch):
    factory, _ = execution_db
    job_id = create_provision(factory)
    with factory() as db:
        queue = db.get(SddAiJob, job_id).queue_key

    async def run():
        expected = asyncio.get_running_loop()

        async def provision_job(received_id):
            assert asyncio.get_running_loop() is expected
            provision.mark_success(received_id, stage="COMPLETED", message="Ready")

        monkeypatch.setattr(provision, "run_create_task_job", provision_job)
        await queue_runner.run_queue(queue)

    asyncio.run(run())
    with factory() as db:
        assert db.get(SddAiJob, job_id).status == AiJobStatus.SUCCESS


def test_auto_mock_target_and_execution_input_commit_together(execution_db):
    factory, _ = execution_db
    create_mock(factory)
    with factory() as db:
        project = db.get(SddApiMockProject, "project")
        job_id = job_service.create_job(
            db,
            project,
            creator_id="user",
            job_type="AUTO_GENERATE_MOCK_CASES",
            execution_input={"endpoint_id": "endpoint"},
        ).id
    with factory() as db:
        assert db.get(SddApiMockJob, job_id).result_json["target_endpoint_id"] == "endpoint"
        assert db.get(SddAiJob, job_id).context_json["inputs"]["endpoint_id"] == "endpoint"
