"""Database acceptance for unified querying, evidence and execution ownership."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app.agents import bind_agent_attempt, reset_agent_attempt
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.models.job_history import JobAttempt, JobEvent
from app.domains.ai.services import queue_service
from app.domains.ai.services.jobs import domain_jobs, reaper, store
from app.domains.ai.services.jobs.backends import schedule_trigger_key
from app.domains.ai.services.jobs.fencing import AgentAttemptFencedError
from app.domains.workflow.models.provision_job import ProvisionJobType, SddProvisionJob
from app.domains.workflow.services import provision_job_service as provision
from tests.ai.jobs.test_domain_jobs import claim, create_provision
from tests.ai.jobs.test_domain_jobs import execution_db as execution_fixture

execution_db = execution_fixture


def test_complete_history_filters_counts_and_stable_pages(execution_db):
    factory, _ = execution_db
    stamp = datetime(2026, 1, 1)
    with factory() as db:
        db.add_all(
            [
                SddAiJob(
                    id=f"job-{i:04}",
                    creator_id="user",
                    channel=AiJobChannel.BACKGROUND,
                    queue_key=f"DOMAIN_JOB:PROVISION:{i}",
                    queue_source="provision",
                    job_type="CREATE_WORKSPACE",
                    status=AiJobStatus.FAILED if i < 5 else AiJobStatus.SUCCESS,
                    created_at=stamp,
                    state_changed_at=stamp,
                )
                for i in range(605)
            ]
        )
        db.commit()
        # All timestamps deliberately equal: ID is the decisive stable order.
        db.query(SddAiJob).update({"state_changed_at": stamp})
        db.commit()
        rows, total = queue_service.list_queue_jobs(db, user_id="user", status="FAILED", page_size=2)
        assert total == 5
        assert [r.job_id for r in rows] == ["job-0004", "job-0003"]
        next_rows, same_total = queue_service.list_queue_jobs(db, user_id="user", status="FAILED", page=2, page_size=2)
        assert same_total == total
        assert [r.job_id for r in next_rows] == ["job-0002", "job-0001"]
        assert queue_service.get_queue_job(db, user_id="user", source="provision", job_id=rows[0].job_id) == rows[0]
        writes = []
        connection = db.connection()

        def observe(_conn, _cursor, sql, *_args):
            if sql.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE")):
                writes.append(sql)

        event.listen(connection, "before_cursor_execute", observe)
        queue_service.list_queue_jobs(db, user_id="user")
        queue_service.get_queue_job(db, user_id="user", source="provision", job_id="job-0000")
        assert writes == []


def test_revoked_workspace_access_applies_to_creator_count_and_detail(execution_db):
    factory, _ = execution_db
    job_id = create_provision(factory)
    with factory() as db:
        assert queue_service.list_queue_jobs(db, user_id="user")[1] == 0
        with pytest.raises(LookupError):
            queue_service.get_queue_job(db, user_id="user", source="provision", job_id=job_id)


def test_mock_visibility_permission_applies_before_counting(execution_db, monkeypatch):
    from app.domains.auth.models.user import WorkspaceMember, WorkspaceRole
    from tests.ai.jobs.test_domain_jobs import create_mock

    factory, _ = execution_db
    job_id = create_mock(factory)
    with factory() as db:
        db.add(WorkspaceMember(id="member", workspace_id="workspace", user_id="user", role=WorkspaceRole.VIEWER))
        db.commit()
        monkeypatch.setattr(queue_service.workspace_service, "user_has_permission", lambda *_args: False)
        assert queue_service.list_queue_jobs(db, user_id="user", source="api_mock")[1] == 0
        with pytest.raises(LookupError):
            queue_service.get_queue_job(db, user_id="user", source="api_mock", job_id=job_id)
        monkeypatch.setattr(queue_service.workspace_service, "user_has_permission", lambda *_args: True)
        assert queue_service.list_queue_jobs(db, user_id="user", source="api_mock")[1] == 1


def test_heartbeat_does_not_change_visible_version_or_order(execution_db):
    factory, _ = execution_db
    job_id = create_provision(factory)
    _, attempt = claim(factory, job_id)
    with factory() as db:
        job = db.get(SddAiJob, job_id)
        stamp, version = job.state_changed_at, job.version
    assert store.heartbeat_job_sync(job_id, attempt.run_token)
    with factory() as db:
        job = db.get(SddAiJob, job_id)
        assert (job.state_changed_at, job.version) == (stamp, version)
        assert db.query(JobAttempt).filter_by(job_id=job_id).one().run_token == attempt.run_token


def test_result_commit_rolls_back_with_artifact_and_rejects_unbound_writer(execution_db):
    factory, _ = execution_db
    job_id = create_provision(factory)
    _, attempt = claim(factory, job_id)
    token = bind_agent_attempt(attempt)
    try:
        with factory() as db:
            row = db.get(SddProvisionJob, job_id)
            row.context_json = {"artifact": "uncommitted"}
            domain_jobs.report(db, job_id, status="SUCCESS", result={"workspace_id": "workspace", "task_id": "task"})
            db.flush()
            db.rollback()
    finally:
        reset_agent_attempt(token)
    with factory() as db:
        assert db.get(SddAiJob, job_id).completion_json is None
        assert db.get(SddProvisionJob, job_id).context_json == {}
        with pytest.raises(AgentAttemptFencedError):
            domain_jobs.report(db, job_id, status="SUCCESS")


def test_committed_result_survives_worker_loss_and_late_cancel(execution_db, monkeypatch):
    factory, _ = execution_db
    job_id = create_provision(factory)
    _, attempt = claim(factory, job_id)
    token = bind_agent_attempt(attempt)
    try:
        provision.mark_success(
            job_id, stage="COMPLETED", message="Ready", result_json={"workspace_id": "workspace", "task_id": "task"}
        )
    finally:
        reset_agent_attempt(token)
    with factory() as db:
        job = db.get(SddAiJob, job_id)
        assert job.status == AiJobStatus.RUNNING
        assert job.completion_json["outcome"] == "SUCCESS"
        assert domain_jobs.request_cancel(db, job_id) is False
        job.error_message = "Transient cleanup verification failure"
        job.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()

    async def stop(*_args):
        return SimpleNamespace(confirmed_dead=True, error_message=None, error_code=None)

    monkeypatch.setattr(reaper, "stop_attempt_processes", stop)
    asyncio.run(reaper.reap_stale_jobs())
    with factory() as db:
        job = db.get(SddAiJob, job_id)
        assert job.status == AiJobStatus.SUCCESS
        assert job.error_message is None
        assert job.attempt_count == 1
        assert db.query(JobEvent).filter_by(job_id=job_id, published_at=None).count() > 0
        assert db.query(JobAttempt).filter_by(job_id=job_id).one().outcome == "SUCCESS"


def test_failed_report_uses_latest_cancel_intent_with_cached_job(execution_db):
    factory, _ = execution_db
    job_id = create_provision(factory)
    _, attempt = claim(factory, job_id)
    token = bind_agent_attempt(attempt)
    try:
        with factory() as worker:
            cached = worker.get(SddAiJob, job_id)
            assert cached.cancel_requested_at is None
            with factory() as controller:
                assert domain_jobs.request_cancel(controller, job_id)
                controller.commit()
            domain_jobs.report(worker, job_id, status="FAILED", error_message="Provider stopped")
            worker.commit()
        with factory() as db:
            assert db.get(SddAiJob, job_id).completion_json["outcome"] == "CANCELLED"
    finally:
        reset_agent_attempt(token)


def test_duplicate_user_rerun_preserves_original_terminal_result(execution_db):
    factory, _ = execution_db
    with factory() as db:
        original = provision.create_job(db, job_type=ProvisionJobType.CREATE_WORKSPACE, creator_id="user")
        original.execution.status = AiJobStatus.FAILED
        original.execution.error_message = "recorded failure"
        db.commit()
        first = queue_service.retry_queue_job(db, source="provision", job_id=original.id, user_id="user")
        second = queue_service.retry_queue_job(db, source="provision", job_id=original.id, user_id="user")
        assert first["new_job_id"] == second["new_job_id"]
        assert first["new_job_id"] != original.id
        assert original.status == AiJobStatus.FAILED
        assert original.error_message == "recorded failure"
        assert db.get(SddAiJob, first["new_job_id"]).retry_of_job_id == original.id


def test_other_backend_cannot_be_claimed_or_reaped(execution_db):
    factory, _ = execution_db
    job_id = create_provision(factory)
    with factory() as db:
        job = db.get(SddAiJob, job_id)
        job.execution_backend = "external"
        queue = job.queue_key
        db.commit()
        assert store.take_next_pending_job_id_sync(queue) is None
        job.status = AiJobStatus.RUNNING
        job.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    assert reaper.list_reclaimable_jobs_sync() == []


def test_deleted_domain_input_keeps_history_without_invalid_actions(execution_db):
    factory, _ = execution_db
    with factory() as db:
        row = provision.create_job(db, job_type=ProvisionJobType.CREATE_WORKSPACE, creator_id="user")
        job_id = row.id
        row.execution.status = AiJobStatus.FAILED
        db.commit()
        db.delete(row)
        db.commit()
        item = queue_service.get_queue_job(db, source="provision", job_id=job_id, user_id="user")
        assert item.status == "FAILED"
        assert not item.actions.can_retry and not item.actions.can_open
        assert db.get(SddAiJob, job_id) is not None


def test_old_owner_cannot_report_after_backend_handoff(execution_db):
    factory, _ = execution_db
    job_id = create_provision(factory)
    _, attempt = claim(factory, job_id)
    with factory() as db:
        db.get(SddAiJob, job_id).execution_backend = "external"
        db.commit()
    token = bind_agent_attempt(attempt)
    try:
        with factory() as db, pytest.raises(AgentAttemptFencedError):
            domain_jobs.report(db, job_id, progress=90)
    finally:
        reset_agent_attempt(token)


def test_schedule_trigger_identity_uses_intended_instant():
    first = datetime(2026, 11, 9, 8, tzinfo=timezone(timedelta(hours=8)))
    second = datetime(2026, 11, 9, 0, tzinfo=timezone.utc)
    assert schedule_trigger_key("schedule", first) == schedule_trigger_key("schedule", second)
    with pytest.raises(ValueError):
        schedule_trigger_key("schedule", second.replace(tzinfo=None))


def test_expired_resource_snapshot_preserves_successful_build_history(execution_db):
    from app.domains.task.models.task_cli_bootstrap import SddTaskCliBootstrap, TaskCliBootstrapStatus

    factory, _ = execution_db
    with factory() as db:
        resource = SddTaskCliBootstrap(id="snapshot", workspace_id="workspace", task_id="task", spec_version_id="v1")
        db.add(resource)
        db.commit()
        first = store.create_task_baseline_job(db, workspace_id="workspace", task_id="task", creator_id="user")
        first.status = AiJobStatus.SUCCESS
        first.result_json = {"spec_version_id": "v1", "baseline_session_id": "session"}
        first.finished_at = datetime.utcnow()
        resource.status = TaskCliBootstrapStatus.STALE
        db.commit()
        second = store.create_task_baseline_job(db, workspace_id="workspace", task_id="task", creator_id="user")
        assert first.id != second.id
        assert resource.execution_job_id == second.id
        assert first.status == AiJobStatus.SUCCESS and first.result_json["baseline_session_id"] == "session"


def test_notification_failure_leaves_committed_event_for_redelivery(execution_db, monkeypatch):
    from unittest.mock import AsyncMock

    from app.domains.ai.services.jobs import publishing

    factory, _ = execution_db
    with factory() as db:
        job_id = provision.create_job(db, job_type=ProvisionJobType.CREATE_WORKSPACE, creator_id="user").id
    monkeypatch.setattr(publishing, "broadcast_job_payload", AsyncMock(side_effect=ConnectionError("offline")))
    with pytest.raises(ConnectionError):
        asyncio.run(publishing.publish_pending_job_events())
    with factory() as db:
        assert db.query(JobEvent).filter_by(job_id=job_id, published_at=None).count() == 1
    delivered = AsyncMock()
    monkeypatch.setattr(publishing, "broadcast_job_payload", delivered)
    assert asyncio.run(publishing.publish_pending_job_events()) == 1
    assert asyncio.run(publishing.publish_pending_job_events()) == 0
    assert delivered.call_args.args[0]["version"] == 1
    with factory() as db:
        assert db.get(SddAiJob, job_id).attempt_count == 0
