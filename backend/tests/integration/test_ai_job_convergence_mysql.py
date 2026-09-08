"""真实 MySQL 双 Session 并发验收（doc §4.4 / §12.2）。

SQLite ``StaticPool`` 无法验证 ``SELECT ... FOR UPDATE``；本模块使用两个
真正独立的 MySQL 连接覆盖：

- finalizer 先锁行，cancel 后到（B 阻塞在同一 job 行）；
- cancel 先锁行，finalizer 后到（fence + termination convergence）；
- 迟到 progress callback 与 cancel 交错（CAS affected rows = 0）；
- 旧 run token 与新 attempt 同时到达（CAS fenced no-op）。

约定：测试自行创建/清理唯一命名的临时数据库，绝不连接开发主库执行破坏性
清理。设置环境变量 ``TRACEFORGE_TEST_MYSQL_URL``（例如
``mysql+pymysql://user:pass@127.0.0.1:3306``）后运行；未设置时显式 skip
（上线验收不能只接受 skip 结果）。
"""

from __future__ import annotations

import os
import sys
import threading
import time
import unittest.mock as mock
import uuid
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

import importlib  # noqa: E402
import pkgutil  # noqa: E402

from app import domains as _domains  # noqa: E402

for _name in [n for _, n, _ in pkgutil.iter_modules(_domains.__path__)]:
    try:
        _models_pkg = importlib.import_module(f"app.domains.{_name}.models")
    except ModuleNotFoundError:
        continue
    if not hasattr(_models_pkg, "__path__"):
        continue
    for _, _mod, _ in pkgutil.walk_packages(
        _models_pkg.__path__, prefix=f"app.domains.{_name}.models."
    ):
        importlib.import_module(_mod)

from app.database import Base  # noqa: E402
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob  # noqa: E402
from app.domains.ai.services import ai_job_service  # noqa: E402
from app.domains.ai.services.ai_job_convergence_service import (  # noqa: E402
    AttemptConvergenceRequest,
    AttemptFinalizerEvidence,
    ConvergenceIntent,
    converge_job_attempt_in_txn,
)

MYSQL_TEST_URL = os.environ.get("TRACEFORGE_TEST_MYSQL_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not MYSQL_TEST_URL,
    reason="TRACEFORGE_TEST_MYSQL_URL is not configured (real MySQL concurrency tests skipped)",
)


@pytest.fixture(scope="module")
def mysql_factory():
    """Create a unique-named temp database, yield a session factory, drop it."""
    base_url = MYSQL_TEST_URL.rsplit("/", 1)[0]
    db_name = f"traceforge_test_{uuid.uuid4().hex[:12]}"
    server_engine = create_engine(base_url, isolation_level="AUTOCOMMIT")
    with server_engine.connect() as conn:
        conn.execute(text(f"CREATE DATABASE `{db_name}` CHARACTER SET utf8mb4"))
    server_engine.dispose()

    engine = create_engine(
        f"{base_url}/{db_name}",
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()

    server_engine = create_engine(base_url, isolation_level="AUTOCOMMIT")
    with server_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS `{db_name}`"))
    server_engine.dispose()


def _seed_running_job(db, *, token="run-1"):
    job = SddAiJob(
        id=f"mysql-job-{uuid.uuid4().hex[:8]}",
        workspace_id="ws-1",
        task_id="task-1",
        channel=AiJobChannel.TASK_CHAT,
        queue_key=f"{AiJobChannel.TASK_CHAT.value}:task-1",
        status=AiJobStatus.RUNNING,
        creator_id="user-1",
        run_token=token,
        worker_boot_id=ai_job_service.WORKER_BOOT_ID,
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


def test_finalizer_locks_row_cancel_waits_then_idempotent(mysql_factory):
    factory = mysql_factory
    seed_db = factory()
    job = _seed_running_job(seed_db, token="run-lock-a")
    job_id = job.id
    seed_db.close()

    session_a = factory()
    locked = (
        session_a.query(SddAiJob)
        .filter(SddAiJob.id == job_id)
        .with_for_update()
        .first()
    )
    assert locked.status == AiJobStatus.RUNNING

    def _cancel():
        db = factory()
        try:
            return ai_job_service.cancel_job(db, workspace_id="ws-1", job_id=job_id)
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


def test_cancel_locks_row_finalizer_fences_then_terminates(mysql_factory):
    factory = mysql_factory
    seed_db = factory()
    job = _seed_running_job(seed_db, token="run-lock-b")
    job_id = job.id
    seed_db.close()

    def _cancel():
        db = factory()
        try:
            return ai_job_service.cancel_job(db, workspace_id="ws-1", job_id=job_id)
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
                worker_boot_id=ai_job_service.WORKER_BOOT_ID,
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
    finish_db = factory()
    try:
        payload = ai_job_service._finish_termination_sync(
            job_id,
            "run-lock-b",
            confirmed_dead=True,
            reason="USER_CANCEL",
            failure_code="CANCEL_REQUESTED",
        )
    finally:
        finish_db.close()
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


def test_late_progress_after_cancel_affects_zero_rows(mysql_factory):
    factory = mysql_factory
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
            return ai_job_service.cancel_job(db, workspace_id="ws-1", job_id=job_id)
        finally:
            db.close()

    thread, result, _ = _run_in_thread(_cancel)
    thread.join(timeout=10)
    assert "error" not in result

    # Session A 依据旧快照继续写 progress：CAS 谓词必须拦下（affected=0）。
    with mock.patch.object(ai_job_service, "SessionLocal", factory):
        outcome = ai_job_service._update_job_state_sync(
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


def test_stale_token_cannot_write_new_attempt(mysql_factory):
    factory = mysql_factory
    seed_db = factory()
    job = _seed_running_job(seed_db, token="run-new-attempt")
    job_id = job.id
    seed_db.close()

    with mock.patch.object(ai_job_service, "SessionLocal", factory):
        outcome = ai_job_service._update_job_state_sync(
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
