"""Real InnoDB races at the artifact/completion/cancellation boundary."""

import os
import threading
import time
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.agents import bind_agent_attempt, reset_agent_attempt
from app.database import Base
from app.domains.ai.models.ai_job import SddAiJob
from app.domains.ai.services.jobs import attempts, domain_jobs, registry, store
from app.domains.auth.models.user import User
from app.domains.workflow.models.provision_job import ProvisionJobType, SddProvisionJob
from app.domains.workflow.services import provision_job_service as provision
from tests.ai.jobs.ai_job_test_utils import patch_ai_job_db

MYSQL_URL = os.environ.get("TRACEFORGE_TEST_MYSQL_URL", "")
pytestmark = pytest.mark.skipif(not MYSQL_URL, reason="TRACEFORGE_TEST_MYSQL_URL not configured")


@pytest.fixture
def mysql_jobs(monkeypatch):
    url = make_url(MYSQL_URL).set(database=None)
    name = "tf_jobs_" + uuid4().hex
    options = {"connect_timeout": 10, "read_timeout": 30, "write_timeout": 30}
    server = create_engine(url, isolation_level="AUTOCOMMIT", connect_args=options)
    with server.connect() as connection:
        connection.execute(text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4"))
    engine = create_engine(url.set(database=name), connect_args=options)
    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
        patch_ai_job_db(monkeypatch, factory)
        monkeypatch.setattr(provision, "SessionLocal", factory)
        monkeypatch.setattr(registry.runtime, "shutting_down", False)
        with factory() as db:
            db.add(User(id="user", email="job-test@example.test", hashed_password="x", display_name="Test"))
            db.commit()
            job = provision.create_job(db, job_type=ProvisionJobType.CREATE_WORKSPACE, creator_id="user")
            job_id, queue_key = job.id, job.execution.queue_key
        monkeypatch.setattr(store, "resolve_execution_kind_for_claim", lambda *_args, **_kwargs: "LOCAL_PROCESS")
        assert store.take_next_pending_job_id_sync(queue_key) == job_id
        yield factory, job_id, attempts.load_attempt_context_sync(job_id)
    finally:
        engine.dispose()
        with server.connect() as connection:
            connection.execute(text(f"DROP DATABASE `{name}`"))
        server.dispose()


def test_completion_lock_serializes_cancel_and_preserves_artifact(mysql_jobs):
    factory, job_id, attempt = mysql_jobs
    session = factory()
    token = bind_agent_attempt(attempt)
    try:
        row = session.get(SddProvisionJob, job_id)
        domain_jobs.report(session, job_id, status="SUCCESS", result={"workspace_id": "created"})
        row.context_json = {"committed_artifact": "created"}
        session.flush()
        started, done = threading.Event(), threading.Event()
        result = {}

        def cancel():
            try:
                with factory() as db:
                    started.set()
                    result["accepted"] = domain_jobs.request_cancel(db, job_id)
                    db.commit()
            except BaseException as error:
                result["error"] = error
            finally:
                done.set()

        thread = threading.Thread(target=cancel)
        thread.start()
        assert started.wait(5)
        time.sleep(0.2)
        assert not done.is_set()
        session.commit()
        thread.join(10)
        assert done.is_set() and "error" not in result
        assert result["accepted"] is False
        with factory() as db:
            job = db.get(SddAiJob, job_id)
            assert job.completion_json["outcome"] == "SUCCESS"
            assert job.cancel_requested_at is None
            assert db.get(SddProvisionJob, job_id).context_json["committed_artifact"] == "created"
    finally:
        reset_agent_attempt(token)
        session.close()


def test_cancel_wins_before_completion_and_rolls_back_artifact(mysql_jobs):
    from app.agents.errors import AgentCancelledError

    factory, job_id, attempt = mysql_jobs
    with factory() as db:
        assert domain_jobs.request_cancel(db, job_id)
        db.commit()
    token = bind_agent_attempt(attempt)
    try:
        with factory() as db:
            db.get(SddProvisionJob, job_id).context_json = {"must_rollback": True}
            with pytest.raises(AgentCancelledError):
                domain_jobs.report(db, job_id, status="SUCCESS", result={"workspace_id": "late"})
            db.rollback()
        with factory() as db:
            assert db.get(SddAiJob, job_id).completion_json is None
            assert db.get(SddProvisionJob, job_id).context_json == {}
    finally:
        reset_agent_attempt(token)


def test_cached_worker_reads_committed_cancel_under_repeatable_read(mysql_jobs):
    factory, job_id, attempt = mysql_jobs
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


def test_business_timestamp_uses_database_clock_after_claim_and_report(mysql_jobs):
    factory, job_id, attempt = mysql_jobs
    token = bind_agent_attempt(attempt)
    try:
        with factory() as db:
            job = db.get(SddAiJob, job_id)
            database_now = db.execute(text("SELECT CURRENT_TIMESTAMP")).scalar()
            assert abs((job.state_changed_at - database_now).total_seconds()) < 10
            domain_jobs.report(db, job_id, progress=45, message="Clock verification")
            db.commit()
            db.refresh(job)
            database_now = db.execute(text("SELECT CURRENT_TIMESTAMP")).scalar()
            assert abs((job.state_changed_at - database_now).total_seconds()) < 10
    finally:
        reset_agent_attempt(token)


def test_expired_attempt_cannot_commit_even_with_matching_token(mysql_jobs):
    from app.domains.ai.services.jobs.fencing import AgentAttemptFencedError

    factory, job_id, attempt = mysql_jobs
    with factory() as db:
        db.get(SddAiJob, job_id).lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    token = bind_agent_attempt(attempt)
    try:
        with factory() as db, pytest.raises(AgentAttemptFencedError):
            domain_jobs.report(db, job_id, status="SUCCESS")
    finally:
        reset_agent_attempt(token)


def test_concurrent_rerun_commands_share_one_successor(mysql_jobs, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from app.domains.ai.models.ai_job import AiJobStatus
    from app.domains.ai.services import queue_service

    factory, job_id, _attempt = mysql_jobs
    monkeypatch.setattr(registry.runtime, "schedule_queue", lambda *_args: None)
    with factory() as db:
        original = db.get(SddAiJob, job_id)
        original.status = AiJobStatus.FAILED
        db.commit()
    ready = threading.Barrier(2)

    def rerun():
        with factory() as db:
            # Establish an older REPEATABLE READ snapshot before either
            # command locks the original job. Successor lookup must be current.
            db.get(SddAiJob, job_id)
            ready.wait(timeout=10)
            return queue_service.retry_queue_job(db, source="provision", job_id=job_id, user_id="user")["new_job_id"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: rerun(), range(2)))
    assert results[0] == results[1] and results[0] != job_id
    with factory() as db:
        assert db.query(SddAiJob).filter_by(retry_of_job_id=job_id).count() == 1
        assert db.get(SddAiJob, job_id).status == AiJobStatus.FAILED
