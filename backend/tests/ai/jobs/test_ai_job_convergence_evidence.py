"""Agent attempt 收敛验收（原 test_ai_job_convergence.py，doc V3 §14）。

覆盖：
- 14.1 证据权威性：identity-aware runtime 不被无身份 fallback 覆盖；
- 14.5 DB 并发状态机：cancel/finalize 两种锁顺序、双 finalizer、旧 token；
- P0-1 CAS 写入 fail-closed（doc §4.5.3）。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from tests.ai.jobs.ai_job_test_utils import (
    _identity,
    _job,
    _owned_job,
    _session_factory,
    _terminate_request,
    patch_ai_job_db,
)
from app.agents.contract import (
    EXECUTION_KIND_LOCAL_PROCESS,
    AgentAttemptRuntimeState,
)
from app.agents.errors import AgentError
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.ai.services import ai_job_convergence_service as convergence
from app.domains.ai.services.ai_job_convergence_service import (
    AttemptConvergenceRequest,
    ConvergenceIntent,
    EVIDENCE_CONFLICT,
    resolve_attempt_evidence,
)
from app.domains.ai.services.jobs import attempts as ai_attempts
from app.domains.ai.services.jobs import fencing as ai_fencing
from app.domains.ai.services.jobs import registry as ai_registry


# ────────────────────── 14.1 证据权威性 ──────────────────────


@pytest.mark.parametrize("owner_field", [None, "run_token", "worker_boot_id", "process_pid", "lease_expires_at"])
def test_cancel_interrupted_attempt_only_finishes_when_ownership_is_clear(owner_field):
    factory = _session_factory()
    with factory() as db:
        job = _job(db, status=AiJobStatus.INTERRUPTED)
        if owner_field:
            value = datetime.utcnow() if owner_field == "lease_expires_at" else (123 if owner_field == "process_pid" else "old-owner")
            setattr(job, owner_field, value)
            db.commit()
        result = convergence.request_attempt_termination_in_txn(
            db, convergence.AttemptTerminationRequest(job_id=job.id, mode="CANCEL"),
        )
        db.commit()
        assert result.changed
        assert job.status == (AiJobStatus.TERMINATING if owner_field else AiJobStatus.CANCELLED)
        if owner_field:
            assert getattr(job, owner_field) == value


def test_runtime_true_not_downgraded_by_stale_exception_fallback():
    runtime = AgentAttemptRuntimeState()
    runtime.record_process_started(_identity(101))
    runtime.record_termination(confirmed_dead=True, identity=_identity(101))

    evidence = resolve_attempt_evidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        runtime=runtime,
        typed_error=AgentError("stale", termination_confirmed_dead=False, process_started=True),
    )

    assert evidence.termination_confirmed_dead is True
    assert evidence.process_started is True
    assert evidence.source == "runtime"


def test_runtime_true_not_downgraded_by_stale_engine_fallback():
    runtime = AgentAttemptRuntimeState()
    runtime.record_process_started(_identity(101))
    runtime.record_termination(confirmed_dead=True, identity=_identity(101))

    evidence = resolve_attempt_evidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        runtime=runtime,
        fallback_dead=False,
        fallback_started=True,
    )

    assert evidence.termination_confirmed_dead is True


def test_runtime_false_not_upgraded_by_stale_exception():
    runtime = AgentAttemptRuntimeState()
    runtime.record_process_started(_identity(101))
    runtime.record_termination(confirmed_dead=False, identity=_identity(101))

    evidence = resolve_attempt_evidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        runtime=runtime,
        typed_error=AgentError("stale", termination_confirmed_dead=True, process_started=True),
    )

    assert evidence.termination_confirmed_dead is False


def test_runtime_aggregate_none_with_started_identity_keeps_none_for_true_fallback():
    """A True + B STARTED 聚合 None：fallback=True 不得把未知身份确认死亡。"""
    runtime = AgentAttemptRuntimeState()
    runtime.record_process_started(_identity(101))
    runtime.record_process_started(_identity(202))
    runtime.record_termination(confirmed_dead=True, identity=_identity(101))
    assert runtime.termination_confirmed_dead is None

    evidence = resolve_attempt_evidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        runtime=runtime,
        fallback_dead=True,
    )

    assert evidence.termination_confirmed_dead is None
    assert evidence.process_started is True


def test_runtime_aggregate_none_supplemented_by_false_fallback():
    runtime = AgentAttemptRuntimeState()
    runtime.record_process_started(_identity(101))

    evidence = resolve_attempt_evidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        runtime=runtime,
        fallback_dead=False,
    )

    assert evidence.termination_confirmed_dead is False


def test_runtime_without_evidence_uses_typed_exception_compat_path():
    evidence = resolve_attempt_evidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        runtime=None,
        typed_error=AgentError("boom", termination_confirmed_dead=True, process_started=True),
    )

    assert evidence.termination_confirmed_dead is True
    assert evidence.process_started is True
    assert evidence.source == "fallback"


def test_conflicting_identityless_fallbacks_yield_none_with_conflict_code():
    evidence = resolve_attempt_evidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        runtime=None,
        fallback_dead=True,
        typed_error=AgentError("stale", termination_confirmed_dead=False, process_started=True),
    )

    assert evidence.termination_confirmed_dead is None
    assert evidence.failure_code == EVIDENCE_CONFLICT


# ────────────────────── 14.5 DB 并发状态机 ──────────────────────


def test_cancel_locks_row_before_finalize_sees_terminating(monkeypatch):
    """锁顺序 1：cancel 先锁行 → NORMAL finalize 看到 TERMINATING 被拦下。"""
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.RUNNING)
    patch_ai_job_db(monkeypatch, factory)

    cancelled = ai_attempts.cancel_job(db, workspace_id="ws-1", job_id="convergence-job")
    assert cancelled.status == AiJobStatus.TERMINATING

    evidence = convergence.AttemptFinalizerEvidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        process_started=True,
        termination_confirmed_dead=True,
        remote_stop_acknowledged=None,
        failure_code=None,
        error_message=None,
        remaining_pids=(),
        source="runtime",
    )
    request = AttemptConvergenceRequest(
        job_id="convergence-job",
        run_token="run-1",
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
        requested_status=AiJobStatus.SUCCESS,
        reason="",
        evidence=evidence,
        intent=ConvergenceIntent.NORMAL_FINALIZE,
    )
    result = convergence.converge_job_attempt_sync(db, request)

    assert result.changed is False
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.status == AiJobStatus.TERMINATING
    assert saved.process_pid == 5151


def test_finalize_wins_lock_cancel_becomes_idempotent(monkeypatch):
    """锁顺序 2：finalizer 先锁行写入终态 → cancel 幂等返回。"""
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.RUNNING)
    patch_ai_job_db(monkeypatch, factory)

    evidence = convergence.AttemptFinalizerEvidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        process_started=True,
        termination_confirmed_dead=True,
        remote_stop_acknowledged=None,
        failure_code=None,
        error_message=None,
        remaining_pids=(),
        source="runtime",
    )
    request = AttemptConvergenceRequest(
        job_id="convergence-job",
        run_token="run-1",
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
        requested_status=AiJobStatus.SUCCESS,
        reason="",
        evidence=evidence,
        intent=ConvergenceIntent.NORMAL_FINALIZE,
    )
    result = convergence.converge_job_attempt_sync(db, request)
    assert result.changed is True

    cancelled = ai_attempts.cancel_job(db, workspace_id="ws-1", job_id="convergence-job")

    assert cancelled.status == AiJobStatus.SUCCESS
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.status == AiJobStatus.SUCCESS
    assert saved.cancel_requested_at is None


def test_two_finalizers_only_first_writes(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.RUNNING)
    patch_ai_job_db(monkeypatch, factory)

    evidence = convergence.AttemptFinalizerEvidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        process_started=True,
        termination_confirmed_dead=True,
        remote_stop_acknowledged=None,
        failure_code=None,
        error_message=None,
        remaining_pids=(),
        source="runtime",
    )

    def _finalize(db2, status):
        request = AttemptConvergenceRequest(
            job_id="convergence-job",
            run_token="run-1",
            worker_boot_id=ai_registry.WORKER_BOOT_ID,
            requested_status=status,
            reason="",
            evidence=evidence,
            intent=ConvergenceIntent.NORMAL_FINALIZE,
        )
        return convergence.converge_job_attempt_sync(db2, request)

    first = _finalize(db, AiJobStatus.SUCCESS)
    second = _finalize(db, AiJobStatus.FAILED)

    assert first.changed is True
    assert second.changed is False
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.status == AiJobStatus.SUCCESS


def test_stale_run_token_cannot_converge_new_attempt(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.RUNNING, token="current-run")
    patch_ai_job_db(monkeypatch, factory)

    evidence = convergence.AttemptFinalizerEvidence(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        process_started=True,
        termination_confirmed_dead=True,
        remote_stop_acknowledged=None,
        failure_code=None,
        error_message=None,
        remaining_pids=(),
        source="runtime",
    )
    request = AttemptConvergenceRequest(
        job_id="convergence-job",
        run_token="old-run",
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
        requested_status=AiJobStatus.SUCCESS,
        reason="",
        evidence=evidence,
        intent=ConvergenceIntent.NORMAL_FINALIZE,
    )
    result = convergence.converge_job_attempt_sync(db, request)

    assert result.changed is False
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.status == AiJobStatus.RUNNING
    assert saved.process_pid == 5151


def test_termination_convergence_cannot_downgrade_orphaned_business_state():
    """TERMINATION 收敛不得把 ORPHANED 降级为业务终态（未证明死亡）。"""
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.ORPHANED, pid=5151)
    db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").update(
        {SddAiJob.orphaned_at: datetime.utcnow()}, synchronize_session=False
    )
    db.commit()

    result = convergence.converge_job_attempt_sync(db, _terminate_request(dead=False))

    assert result.changed is True
    assert result.status == AiJobStatus.ORPHANED.value
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.process_pid == 5151


def test_termination_convergence_proven_dead_leaves_orphaned_to_business_state():
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.ORPHANED, pid=5151)

    result = convergence.converge_job_attempt_sync(db, _terminate_request(dead=True))

    assert result.changed is True
    assert result.status == AiJobStatus.INTERRUPTED.value
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.process_pid is None


# ────────────── P0-1：CAS 写入 fail-closed（doc §4.5.3） ──────────────


def _seed_owned_running(db, *, token="run-1", status=AiJobStatus.RUNNING, cancel_requested=False):
    job = _job(
        db,
        status=status,
        run_token=token,
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
        pid=5151,
        cancel_requested=cancel_requested,
    )
    return job


def test_active_state_write_without_run_token_is_rejected(monkeypatch):
    """无 token 的迟到状态写必须 fail-closed：不得把已取消 job 写回 RUNNING（doc §4.3）。"""
    factory = _session_factory()
    db = factory()
    _seed_owned_running(db)
    patch_ai_job_db(monkeypatch, factory)

    cancelled = ai_attempts.cancel_job(db, workspace_id="ws-1", job_id="convergence-job")
    assert cancelled.status == AiJobStatus.TERMINATING

    result = ai_fencing.update_job_state_sync(
        "convergence-job",
        status=AiJobStatus.RUNNING,
        progress=33,
        message="late writer",
    )

    assert result["broadcast"] is False
    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.status == AiJobStatus.TERMINATING
    assert saved.progress != 33
    assert saved.message != "late writer"


def test_late_progress_after_cancel_affects_zero_rows(monkeypatch):
    """取消提交后，迟到 progress/context callback 必须是 fenced no-op。"""
    factory = _session_factory()
    db = factory()
    _seed_owned_running(db, cancel_requested=True)
    original_context = dict(
        db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first().context_json or {}
    )
    patch_ai_job_db(monkeypatch, factory)

    result = ai_fencing.update_job_state_sync(
        "convergence-job",
        progress=80,
        message="late progress",
        context_patch={"late": True},
        run_token="run-1",
    )

    assert result["broadcast"] is False
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.progress != 80
    assert saved.message != "late progress"
    assert (saved.context_json or {}).get("late") is not True


def test_old_token_cannot_modify_new_attempt(monkeypatch):
    factory = _session_factory()
    db = factory()
    _seed_owned_running(db, token="run-2")
    patch_ai_job_db(monkeypatch, factory)

    result = ai_fencing.update_job_state_sync(
        "convergence-job",
        progress=10,
        run_token="run-1",
    )

    assert result["broadcast"] is False
    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.progress != 10


def test_cas_progress_write_succeeds_for_current_owner(monkeypatch):
    factory = _session_factory()
    db = factory()
    _seed_owned_running(db)
    patch_ai_job_db(monkeypatch, factory)

    result = ai_fencing.update_job_state_sync(
        "convergence-job",
        progress=42,
        run_token="run-1",
    )

    assert result["broadcast"] is True
    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert saved.progress == 42
    assert saved.run_token == "run-1"
