"""真实 PostgreSQL 双 Session 并发验收。

SQLite ``StaticPool`` 无法验证 ``SELECT ... FOR UPDATE``；本模块使用两个
真正独立的 PostgreSQL 连接覆盖：

- finalizer 先锁行，cancel 后到（B 阻塞在同一 job 行）；
- cancel 先锁行，finalizer 后到（fence + termination convergence）；
- 迟到 progress callback 与 cancel 交错（CAS affected rows = 0）；
- 旧 run token 与新 attempt 同时到达（CAS fenced no-op）。

使用 TRACEFORGE_TEST_POSTGRES_URL 指向 PostgreSQL，测试创建并清理独立 schema。
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime

import pytest
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services.ai_job_convergence_service import (
    AttemptConvergenceRequest,
    AttemptFinalizerEvidence,
    ConvergenceIntent,
    converge_job_attempt_in_txn,
    lock_job_in_txn,
)
from app.domains.ai.services.jobs import (
    attempts as ai_attempts,
)
from app.domains.ai.services.jobs import fencing as ai_fencing
from app.domains.ai.services.jobs import (
    registry as ai_registry,
)
from app.domains.ai.services.jobs import store as ai_store
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.services import chat_steering_service as steering
from app.domains.task.services import status_machine as sm
from app.domains.task.services.chat_submission_service import SubmissionError
from app.domains.task.services.task_session_control_service import _accept_interrupt_command
from tests.ai.jobs.ai_job_test_utils import patched_ai_job_db
from tests.postgres_support import temporary_postgres_schema
from tests.workspace_asset.test_workspace_asset_boundary import _seed_workspace


@pytest.fixture
def postgres_factory():
    with temporary_postgres_schema() as engine:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def _seed_running_job(db, *, token="run-1"):
    _seed_workspace(db)
    job = SddAiJob(
        id=f"postgres-job-{uuid.uuid4().hex[:8]}",
        workspace_id="ws-1",
        task_id="task-1",
        channel=AiJobChannel.TASK_CHAT,
        queue_key=f"{AiJobChannel.TASK_CHAT.value}:task-1",
        status=AiJobStatus.RUNNING,
        creator_id="user-1",
        run_token=token,
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
        process_execution_kind="LOCAL_PROCESS",
        process_pid=5151,
        process_group_id=5151,
    )
    db.add(job)
    db.commit()
    return job


def _dead_evidence(kind="LOCAL_PROCESS"):
    return AttemptFinalizerEvidence(
        execution_kind=kind,
        process_started=True,
        termination_confirmed_dead=True,
        remote_stop_acknowledged=None,
        failure_code=None,
        error_message=None,
        remaining_pids=(),
        source="runtime",
    )


def _run_in_thread(fn):
    result: dict = {}

    def _target():
        try:
            result["value"] = fn()
        except BaseException as exc:  # pragma: no cover - surfaced below
            result["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    started = time.monotonic()
    thread.start()
    return thread, result, started


def test_pending_stop_wins_against_claim(postgres_factory):
    factory = postgres_factory
    with factory() as db:
        job = _seed_running_job(db)
        job_id = job.id
        job.status = AiJobStatus.PENDING
        job.run_token = job.worker_boot_id = job.process_pid = job.process_group_id = None
        db.commit()
    with factory() as stopper, patched_ai_job_db(factory):
        task = stopper.query(SddTask).filter_by(id="task-1").with_for_update().one()
        thread, result, _ = _run_in_thread(lambda: ai_store.take_next_pending_job_id_sync("TASK_CHAT:task-1"))
        time.sleep(0.1)
        assert thread.is_alive()
        _accept_interrupt_command(stopper, task.id, task.creator_id, "stop-before-claim", task.status_seq, "stop")
        thread.join(timeout=8)
        assert not thread.is_alive()
        assert result == {"value": None}
    with factory() as db:
        assert db.get(SddTask, "task-1").status == TaskStatus.INTERRUPTED
        job = db.get(SddAiJob, job_id)
        assert job.status == AiJobStatus.CANCELLED
        assert job.cancel_requested_at is not None and job.attempt_count == 0


def test_job_lock_preserves_pending_task_reading_watermark(postgres_factory):
    with postgres_factory() as db:
        job = _seed_running_job(db)
        task = db.query(SddTask).filter_by(id="task-1").with_for_update().one()
        task.reading_change_seq += 1
        assert lock_job_in_txn(db, db.query(SddAiJob).filter_by(id=job.id)) is job
        db.commit()
    with postgres_factory() as db:
        assert db.get(SddTask, "task-1").reading_change_seq == 1


def test_steering_waits_for_task_before_locking_job(postgres_factory):
    factory = postgres_factory
    with factory() as db:
        job = _seed_running_job(db)
        task = db.get(SddTask, "task-1")
        task.status_run_id = job.id
        job.session_generation, job.session_revision = task.session_generation, task.session_revision
        job.session_id = "native-session"
        job_id = job.id
        db.commit()

    def submit():
        with factory.begin() as db:
            try:
                steering._prepare(
                    db,
                    ws_id="ws-1",
                    task_id="task-1",
                    actor_id="user-1",
                    job_id=job_id,
                    client_id="guide-1",
                    content="Verify the result",
                    message_id="guide-message",
                    run_token="run-1",
                    session_id="native-session",
                )
            except SubmissionError as exc:
                return exc.code
            return "accepted"

    with factory.begin() as db:
        db.query(SddTask).filter_by(id="task-1").with_for_update().one()
        thread, submission, _ = _run_in_thread(submit)
        time.sleep(0.1)
        assert thread.is_alive()
        result = converge_job_attempt_in_txn(
            db,
            AttemptConvergenceRequest(
                job_id=job_id,
                run_token="run-1",
                worker_boot_id=ai_registry.WORKER_BOOT_ID,
                requested_status=AiJobStatus.SUCCESS,
                reason="completed",
                evidence=_dead_evidence(),
            ),
        )
        assert result.status == AiJobStatus.SUCCESS.value
    thread.join(timeout=8)
    assert not thread.is_alive()
    assert submission == {"value": "STEERING_NOT_RUNNING"}


@pytest.mark.parametrize("concurrent_command", ["answer", "stop"])
def test_finalizer_serializes_with_task_transitions(postgres_factory, concurrent_command):
    factory = postgres_factory
    with factory() as db:
        job = _seed_running_job(db)
        job_id = job.id
        task = db.get(SddTask, "task-1")
        task.status = TaskStatus.AWAITING_INPUT if concurrent_command == "answer" else TaskStatus.RUNNING
        task.status_run_id = job.id
        job.session_generation = task.session_generation
        job.session_revision = task.session_revision
        db.commit()

    def finish():
        with factory.begin() as db:
            result = converge_job_attempt_in_txn(
                db,
                AttemptConvergenceRequest(
                    job_id=job_id,
                    run_token="run-1",
                    worker_boot_id=ai_registry.WORKER_BOOT_ID,
                    requested_status=AiJobStatus.SUCCESS,
                    reason="result",
                    evidence=_dead_evidence(),
                    intent=ConvergenceIntent.NORMAL_FINALIZE,
                ),
            )
            return result.changed

    with factory() as actor:
        task = actor.query(SddTask).filter_by(id="task-1").with_for_update().one()
        thread, result, _ = _run_in_thread(finish)
        time.sleep(0.2)
        assert thread.is_alive()
        if concurrent_command == "answer":
            transition = sm.execution_event(
                actor,
                task,
                sm.Trigger.ANSWER_RECEIVED,
                event_key="answered",
                job_id=job_id,
                generation=task.session_generation,
                revision=task.session_revision,
            )
            assert transition["outcome"] == "APPLIED"
            actor.commit()
        else:
            _accept_interrupt_command(actor, task.id, task.creator_id, "racing-stop", task.status_seq, "stop")
        thread.join(timeout=8)
        assert not thread.is_alive()
        assert result == {"value": concurrent_command == "answer"}
    with factory() as db:
        task = db.get(SddTask, "task-1")
        job = db.get(SddAiJob, job_id)
        if concurrent_command == "answer":
            assert task.status == TaskStatus.ROUND_COMPLETED and job.status == AiJobStatus.SUCCESS
        else:
            assert task.status == TaskStatus.INTERRUPTED and job.cancel_requested_at is not None


def test_finalizer_locks_row_cancel_waits_then_idempotent(postgres_factory):
    factory = postgres_factory
    seed_db = factory()
    job = _seed_running_job(seed_db, token="run-lock-a")
    job_id = job.id
    seed_db.close()

    session_a = factory()
    locked = session_a.query(SddAiJob).filter(SddAiJob.id == job_id).with_for_update().first()
    assert locked.status == AiJobStatus.RUNNING

    def _cancel():
        db = factory()
        try:
            return ai_attempts.cancel_job(db, workspace_id="ws-1", job_id=job_id)
        finally:
            db.close()

    thread, result, started = _run_in_thread(_cancel)
    time.sleep(1.0)
    # Session B 必须仍阻塞在同一 job 行，而不是提前读到旧状态。
    assert thread.is_alive(), "cancel did not block on the finalizer row lock"

    locked.status = AiJobStatus.SUCCESS
    locked.progress = 100
    locked.finished_at = datetime.utcnow()
    locked.run_token = None
    locked.worker_id = None
    locked.worker_boot_id = None
    locked.process_pid = None
    locked.process_started_at = None
    locked.process_group_id = None
    session_a.commit()
    session_a.close()

    thread.join(timeout=10)
    assert not thread.is_alive(), "cancel stayed blocked after finalizer commit"
    assert "error" not in result
    cancelled_job = result["value"]
    # finalizer 已写 SUCCESS：cancel 幂等返回，不得恢复为非终态。
    assert cancelled_job is not None
    assert cancelled_job.status == AiJobStatus.SUCCESS
    assert cancelled_job.run_token is None
    assert cancelled_job.process_pid is None
    assert cancelled_job.cancel_requested_at is None

    verify = factory()
    try:
        saved = verify.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        assert saved.status == AiJobStatus.SUCCESS
        assert saved.run_token is None
    finally:
        verify.close()


def test_cancel_locks_row_finalizer_fences_then_terminates(postgres_factory):
    factory = postgres_factory
    seed_db = factory()
    job = _seed_running_job(seed_db, token="run-lock-b")
    job_id = job.id
    seed_db.close()

    def _cancel():
        db = factory()
        try:
            return ai_attempts.cancel_job(db, workspace_id="ws-1", job_id=job_id)
        finally:
            db.close()

    thread, result, _ = _run_in_thread(_cancel)
    thread.join(timeout=10)
    assert "error" not in result
    assert result["value"].status == AiJobStatus.TERMINATING

    # Session A 执行 normal finalize：读到 TERMINATING + cancel_requested
    # 后必须 changed=False（fence），不得写 SUCCESS。
    session_a = factory()
    try:
        normal = converge_job_attempt_in_txn(
            session_a,
            AttemptConvergenceRequest(
                job_id=job_id,
                run_token="run-lock-b",
                worker_boot_id=ai_registry.WORKER_BOOT_ID,
                requested_status=AiJobStatus.SUCCESS,
                reason="late finalizer",
                evidence=_dead_evidence(),
                intent=ConvergenceIntent.NORMAL_FINALIZE,
            ),
        )
        session_a.commit()
        assert normal.changed is False
    finally:
        session_a.close()

    # termination finalizer 依据死亡证据写 CANCELLED 并清 ownership。
    with patched_ai_job_db(factory):
        payload = ai_attempts.finish_termination_sync(
            job_id,
            "run-lock-b",
            confirmed_dead=True,
            reason="USER_CANCEL",
            failure_code="CANCEL_REQUESTED",
        )
    assert payload is not None
    assert payload["status"] == AiJobStatus.CANCELLED.value

    verify = factory()
    try:
        saved = verify.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        assert saved.status == AiJobStatus.CANCELLED
        assert saved.run_token is None
        assert saved.process_pid is None
    finally:
        verify.close()


def test_late_progress_after_cancel_affects_zero_rows(postgres_factory):
    factory = postgres_factory
    seed_db = factory()
    job = _seed_running_job(seed_db, token="run-late")
    job_id = job.id
    seed_db.close()

    # Session A 先普通读取（旧快照）。
    session_a = factory()
    stale = session_a.query(SddAiJob).filter(SddAiJob.id == job_id).first()
    assert stale.status == AiJobStatus.RUNNING

    def _cancel():
        db = factory()
        try:
            return ai_attempts.cancel_job(db, workspace_id="ws-1", job_id=job_id)
        finally:
            db.close()

    thread, result, _ = _run_in_thread(_cancel)
    thread.join(timeout=10)
    assert "error" not in result

    # Session A 依据旧快照继续写 progress：CAS 谓词必须拦下（affected=0）。
    with patched_ai_job_db(factory):
        outcome = ai_fencing.update_job_state_sync(
            job_id,
            progress=77,
            message="late progress",
            run_token="run-late",
        )
    assert outcome["broadcast"] is False

    session_a.close()
    verify = factory()
    try:
        saved = verify.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        assert saved.status == AiJobStatus.TERMINATING
        assert saved.progress != 77
        assert saved.message != "late progress"
        assert saved.cancel_requested_at is not None
    finally:
        verify.close()


def test_stale_token_cannot_write_new_attempt(postgres_factory):
    factory = postgres_factory
    seed_db = factory()
    job = _seed_running_job(seed_db, token="run-new-attempt")
    job_id = job.id
    seed_db.close()

    with patched_ai_job_db(factory):
        outcome = ai_fencing.update_job_state_sync(
            job_id,
            progress=55,
            run_token="run-old-attempt",
        )
    assert outcome["broadcast"] is False

    verify = factory()
    try:
        saved = verify.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        assert saved.progress != 55
        assert saved.status == AiJobStatus.RUNNING
    finally:
        verify.close()
