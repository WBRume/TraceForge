import asyncio
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

import app.domains.api_mock.models.api_mock  # noqa: F401,E402
import app.domains.task.models.test_result  # noqa: F401,E402
import app.domains.workflow.models.task_change  # noqa: F401,E402
import app.domains.workspace_asset.models.workspace_asset  # noqa: F401,E402
from app.database import Base  # noqa: E402
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob  # noqa: E402
from app.domains.auth.models.user import User, Workspace  # noqa: E402
from app.domains.workspace_asset.models.workspace_asset import (  # noqa: E402
    SddRequirementImportBatch,
)
from app.domains.workspace_asset.services import workspace_asset_service as service  # noqa: E402


def _build_session(*, expire_on_commit=False):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=expire_on_commit)


def _seed_workspace(db, project_path):
    user = User(id="user-1", email="user@example.com", hashed_password="x", display_name="User")
    workspace = Workspace(
        id="ws-1",
        name="Workspace",
        owner_id=user.id,
        project_path=str(project_path),
    )
    db.add_all([user, workspace])
    db.commit()
    return workspace


def _create_preview_job(db, raw: bytes, *, file_name="requirements.md"):
    return service.create_requirement_import_preview_job(
        db,
        "ws-1",
        "user-1",
        file_name=file_name,
        raw=raw,
    )


def test_create_import_preview_job_persists_parsed_content(tmp_path):
    SessionLocal = _build_session()
    db = SessionLocal()
    _seed_workspace(db, tmp_path)

    response = _create_preview_job(db, b"# Feature A\n\nBody text\n")

    job = db.query(SddAiJob).filter(SddAiJob.id == response.job_id).one()
    context = job.context_json
    assert job.queue_key == "REQUIREMENT_PREVIEW:ws-1"
    assert job.status == service.AiJobStatus.PENDING
    assert context["job_kind"] == "REQUIREMENT_IMPORT_PREVIEW"
    assert "Feature A" in str(context["normalized_markdown"])
    assert context["source_ext"] == ".md"
    assert context["source_mime"]
    assert context["render_json"]
    assert context["source_filename"] == "requirements.md"


def test_create_import_preview_job_rejects_unsupported_and_oversize(tmp_path):
    SessionLocal = _build_session()
    db = SessionLocal()
    _seed_workspace(db, tmp_path)

    with pytest.raises(service.WorkspaceAssetWriteError) as unsupported:
        _create_preview_job(db, b"# x\n", file_name="requirements.pdf")
    assert unsupported.value.status_code == 415

    original_limit = service.REQUIREMENT_IMPORT_MAX_BYTES
    service.REQUIREMENT_IMPORT_MAX_BYTES = 10
    try:
        with pytest.raises(service.WorkspaceAssetWriteError) as oversize:
            _create_preview_job(db, b"# too large content beyond limit\n")
        assert oversize.value.status_code == 413
    finally:
        service.REQUIREMENT_IMPORT_MAX_BYTES = original_limit


def test_run_import_preview_job_executes_from_persisted_context(tmp_path, monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    _seed_workspace(db, tmp_path)
    response = _create_preview_job(db, b"# Feature A\n\nBody text\n")
    job_id = response.job_id

    prompts = []

    async def fake_cli(prompt, project_path, max_attempts=1, backend_name=None):
        prompts.append({"prompt": prompt, "project_path": project_path})
        return {
            "text": '{"items": [{"title": "Feature A", "body": "Body text", "acceptance_criteria": [], "source_ref": "r1"}]}',
            "session_id": "sess-1",
        }

    monkeypatch.setattr(service, "run_cli_single_turn", fake_cli)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)

    asyncio.run(service.run_requirement_import_preview_job(job_id))

    db.expire_all()
    job = db.query(SddAiJob).filter(SddAiJob.id == job_id).one()
    assert job.status == service.AiJobStatus.SUCCESS
    assert len(prompts) == 1
    assert "Feature A" in prompts[0]["prompt"]

    batch = (
        db.query(SddRequirementImportBatch)
        .filter(SddRequirementImportBatch.workspace_id == "ws-1")
        .one()
    )
    assert batch.item_count == 1
    assert batch.source_metadata_json["ai_preview"] is True
    assert batch.source_metadata_json["session_id"] == "sess-1"
    assert "preview_batch_id" in (job.context_json or {})


def test_run_import_preview_job_fails_when_content_missing(tmp_path, monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    _seed_workspace(db, tmp_path)

    job = SddAiJob(
        id="legacy-job",
        workspace_id="ws-1",
        channel=service.AiJobChannel.ASSET_THREAD,
        queue_key="REQUIREMENT_PREVIEW:ws-1",
        status=service.AiJobStatus.PENDING,
        context_json={"job_kind": "REQUIREMENT_IMPORT_PREVIEW", "source_filename": "requirements.md"},
        creator_id="user-1",
    )
    db.add(job)
    db.commit()

    async def unexpected_cli(*_args, **_kwargs):
        raise AssertionError("CLI must not be called without persisted content")

    monkeypatch.setattr(service, "run_cli_single_turn", unexpected_cli)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)

    asyncio.run(service.run_requirement_import_preview_job(job.id))

    db.expire_all()
    failed = db.query(SddAiJob).filter(SddAiJob.id == job.id).one()
    assert failed.status == service.AiJobStatus.FAILED
    assert "re-upload" in str(failed.error_message)


def test_execute_job_dispatches_split_preview(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    _seed_workspace(db, "G:/tmp/does-not-matter")

    job = SddAiJob(
        id="split-job-1",
        workspace_id="ws-1",
        channel=service.AiJobChannel.ASSET_THREAD,
        queue_key="REQUIREMENT_PREVIEW:ws-1",
        status=service.AiJobStatus.RUNNING,
        context_json={"job_kind": "REQUIREMENT_SPLIT_PREVIEW"},
        creator_id="user-1",
    )
    db.add(job)
    db.commit()

    calls = []

    class _FakePreviewService:
        @staticmethod
        async def run_requirement_split_preview_job(job_id):
            calls.append(job_id)

        @staticmethod
        async def run_requirement_import_preview_job(job_id):
            raise AssertionError("import runner must not be used for split jobs")

    from app.domains.ai.services import ai_job_service

    monkeypatch.setattr(ai_job_service, "SessionLocal", SessionLocal)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)
    monkeypatch.setattr(
        service,
        "run_requirement_split_preview_job",
        _FakePreviewService.run_requirement_split_preview_job,
    )
    monkeypatch.setattr(
        service,
        "run_requirement_import_preview_job",
        _FakePreviewService.run_requirement_import_preview_job,
    )

    asyncio.run(ai_job_service._execute_job("split-job-1"))
    assert calls == ["split-job-1"]


# ── P1-4（doc 修复方案 §10）：异常分支必须携带事件循环已捕获的 attempt 证据 ──


def _seed_split_preview_target(db, tmp_path):
    from app.domains.workspace_asset.models.workspace_asset import SddRequirement

    _seed_workspace(db, tmp_path)
    requirement = SddRequirement(
        id="req-1",
        workspace_id="ws-1",
        created_by_id="user-1",
        title="Big requirement",
        body="Line one\nLine two\nLine three",
    )
    db.add(requirement)
    db.commit()
    job = service.create_requirement_split_preview_job(
        db, "ws-1", "req-1", "user-1"
    )
    return job.job_id


def _claim_running(job_id, SessionLocal, *, pid=4242):
    """Simulate claim + process attach: RUNNING + persisted ownership."""
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).one()
        job.status = service.AiJobStatus.RUNNING
        job.run_token = "run-1"
        job.worker_boot_id = service.WORKER_BOOT_ID
        job.process_pid = pid
        job.process_group_id = pid
        job.process_execution_kind = "LOCAL_PROCESS"
        db.commit()
    finally:
        db.close()


def _make_bound_attempt(job_id, runtime):
    from app.agents.contract import (
        AgentAttemptContext,
        bind_agent_attempt,
        bind_agent_attempt_runtime,
        reset_agent_attempt,
        reset_agent_attempt_runtime,
    )

    attempt = AgentAttemptContext(
        job_id=job_id,
        task_id=None,
        queue_key="REQUIREMENT_PREVIEW:ws-1",
        run_token="run-1",
        worker_id="w-1",
        worker_boot_id=service.WORKER_BOOT_ID,
        attempt_count=1,
        execution_kind="LOCAL_PROCESS",
    )

    def _runner(coro):
        async def _run():
            attempt_token = bind_agent_attempt(attempt)
            runtime_token = bind_agent_attempt_runtime(runtime)
            try:
                return await coro
            finally:
                reset_agent_attempt_runtime(runtime_token)
                reset_agent_attempt(attempt_token)

        return asyncio.run(_run())

    return attempt, _runner


def test_preview_parse_failure_keeps_runtime_death_evidence(tmp_path, monkeypatch):
    """CLI 已确认退出 + 下游解析失败 → FAILED，不进入 reaper retry。"""
    SessionLocal = _build_session()
    db = SessionLocal()
    job_id = _seed_split_preview_target(db, tmp_path)
    _claim_running(job_id, SessionLocal)

    async def fake_cli(*_args, **_kwargs):
        # 确定性解析失败：split preview 至少需要两个 item。
        return {"text": '{"items": [{"title": "Only one"}]}', "session_id": "sess-1"}

    monkeypatch.setattr(service, "run_cli_single_turn", fake_cli)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)

    from app.agents.contract import (
        AgentAttemptRuntimeState,
        AgentProcessIdentity,
        record_attempt_termination,
    )
    from datetime import datetime, timezone

    runtime = AgentAttemptRuntimeState()
    identity = AgentProcessIdentity(
        pid=4242,
        started_at=datetime.now(timezone.utc),
        process_group_id=4242,
        containment_id="runtoken:run-1",
    )
    runtime.record_process_started(identity)
    runtime.record_termination(confirmed_dead=True, identity=identity)

    _, runner = _make_bound_attempt(job_id, runtime)

    async def _job():
        return await service.run_requirement_split_preview_job(job_id, run_token="run-1")

    runner(_job())

    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == job_id).one()
    assert saved.status == service.AiJobStatus.FAILED
    assert saved.run_token is None
    assert saved.process_pid is None
    assert saved.process_group_id is None


def test_preview_unknown_death_failure_stays_orphaned(tmp_path, monkeypatch):
    """反向：CLI 死亡未证实 + 解析失败 → ORPHANED 且保留 ownership。"""
    SessionLocal = _build_session()
    db = SessionLocal()
    job_id = _seed_split_preview_target(db, tmp_path)
    _claim_running(job_id, SessionLocal)

    async def fake_cli(*_args, **_kwargs):
        return {"text": '{"items": [{"title": "Only one"}]}', "session_id": "sess-1"}

    monkeypatch.setattr(service, "run_cli_single_turn", fake_cli)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)

    from app.agents.contract import (
        AgentAttemptRuntimeState,
        AgentProcessIdentity,
    )
    from datetime import datetime, timezone

    runtime = AgentAttemptRuntimeState()
    identity = AgentProcessIdentity(
        pid=4242,
        started_at=datetime.now(timezone.utc),
        process_group_id=4242,
        containment_id="runtoken:run-1",
    )
    runtime.record_process_started(identity)
    runtime.record_termination(
        confirmed_dead=None,
        identity=identity,
        failure_code="PROCESS_TREE_UNKNOWN",
    )

    _, runner = _make_bound_attempt(job_id, runtime)

    async def _job():
        return await service.run_requirement_split_preview_job(job_id, run_token="run-1")

    runner(_job())

    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == job_id).one()
    assert saved.status == service.AiJobStatus.ORPHANED
    # 防止修复变成乐观终态：ownership 必须完整保留。
    assert saved.run_token == "run-1"
    assert saved.process_pid == 4242
    assert saved.process_group_id == 4242


def test_import_preview_parse_failure_keeps_runtime_death_evidence(tmp_path, monkeypatch):
    """import preview 与 split preview 使用相同 helper（doc 修复方案 §10.4）。"""
    SessionLocal = _build_session()
    db = SessionLocal()
    _seed_workspace(db, tmp_path)
    response = _create_preview_job(db, b"# Feature A\n\nBody text\n")
    job_id = response.job_id
    _claim_running(job_id, SessionLocal)

    async def fake_cli(*_args, **_kwargs):
        # normalize 阶段抛错（非 JSON 且不可兜底的内容）。
        return {"text": "not json at all", "session_id": "sess-1"}

    monkeypatch.setattr(service, "run_cli_single_turn", fake_cli)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)

    from app.agents.contract import (
        AgentAttemptRuntimeState,
        AgentProcessIdentity,
    )
    from datetime import datetime, timezone

    runtime = AgentAttemptRuntimeState()
    identity = AgentProcessIdentity(
        pid=4243,
        started_at=datetime.now(timezone.utc),
        process_group_id=4243,
        containment_id="runtoken:run-1",
    )
    runtime.record_process_started(identity)
    runtime.record_termination(confirmed_dead=True, identity=identity)

    _, runner = _make_bound_attempt(job_id, runtime)

    async def _job():
        return await service.run_requirement_import_preview_job(job_id, run_token="run-1")

    runner(_job())

    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == job_id).one()
    assert saved.status == service.AiJobStatus.FAILED
    assert saved.run_token is None
    assert saved.process_pid is None


# ─────────── P1-1（doc: docs/agent-job-bc6ca89-remaining-code-audit.md）───────────
# 远程需求预览（import/split）必须把 provider 终局结果传入 finalizer evidence：
# 会话已建立且 provider 正常返回时，收敛不得判 ORPHANED。


def _bind_remote_attempt(job_id: str):
    from app.agents.contract import (
        AgentAttemptContext,
        AgentAttemptRuntimeState,
        EXECUTION_KIND_REMOTE_SESSION,
        bind_agent_attempt,
        bind_agent_attempt_runtime,
    )

    owner = bind_agent_attempt(AgentAttemptContext(
        job_id=job_id, task_id=None, queue_key="preview", run_token="audit-token",
        worker_id="audit-worker", worker_boot_id="audit-boot", attempt_count=1,
        execution_kind=EXECUTION_KIND_REMOTE_SESSION,
    ))
    binding = bind_agent_attempt_runtime(AgentAttemptRuntimeState(remote_session_started=True))
    return owner, binding


def _decide_status(evidence, requested):
    from types import SimpleNamespace
    from app.domains.ai.services import ai_job_convergence_service as convergence
    from app.agents.contract import EXECUTION_KIND_REMOTE_SESSION

    request = convergence.AttemptConvergenceRequest(
        job_id="audit-job", run_token="audit-token", worker_boot_id="audit-boot",
        requested_status=requested, reason="done", evidence=evidence,
        intent=convergence.ConvergenceIntent.NORMAL_FINALIZE,
    )
    return convergence._decide_final_status(SimpleNamespace(), request, EXECUTION_KIND_REMOTE_SESSION)[0]


def test_remote_split_preview_evidence_enables_convergence(monkeypatch):
    """split 预览：provider 正常返回 → finalizer evidence 带 outcome → SUCCESS。"""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    owner, binding = _bind_remote_attempt("audit-job")
    captured = {}

    async def txn(fn):
        return fn(None)

    def capture(db, **kwargs):
        captured.update(kwargs)

    try:
        prepared = {"backend_name": "dsh", "prompt": "split", "project_path": "/tmp"}
        provider_reply = {
            "text": '{"items": [{"title": "one", "body": "a"}, {"title": "two", "body": "b"}]}',
            "session_id": "remote-1",
        }
        monkeypatch.setattr(service, "run_db_txn", txn)
        monkeypatch.setattr(service, "_prepare_requirement_split_sync", lambda db, **kw: prepared)
        monkeypatch.setattr(service, "run_cli_single_turn", AsyncMock(return_value=provider_reply))
        monkeypatch.setattr(service, "_finalize_requirement_split_sync", capture)
        assert asyncio.run(service.run_requirement_split_preview_job("audit-job")) is True
        evidence = captured["evidence"]
        assert evidence.provider_outcome_seen is True
        assert _decide_status(evidence, service.AiJobStatus.SUCCESS) == service.AiJobStatus.SUCCESS
    finally:
        from app.agents.contract import reset_agent_attempt, reset_agent_attempt_runtime
        reset_agent_attempt_runtime(binding)
        reset_agent_attempt(owner)


def test_remote_import_preview_evidence_enables_convergence(monkeypatch):
    """import 预览与 split 使用相同漏传修复（doc 审计 P1-1 静态证据路径）。"""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    owner, binding = _bind_remote_attempt("audit-job")
    captured = {}

    async def txn(fn):
        return fn(None)

    def capture(db, **kwargs):
        captured.update(kwargs)

    try:
        context = {
            "markdown": "# Feature A\n\nBody\n", "source_kind": "file",
            "source_ref": "requirements.md", "source_uri": "", "file_name": "requirements.md",
            "source_ext": ".md", "source_mime": "text/markdown", "render_json": {},
        }
        prepared = {"backend_name": "dsh", "prompt": "import", "project_path": "/tmp"}
        provider_reply = {
            "text": '{"items": [{"title": "Feature A", "body": "Body", "acceptance_criteria": [], "source_ref": "r1"}]}',
            "session_id": "remote-1",
        }
        monkeypatch.setattr(service, "run_db_txn", txn)
        monkeypatch.setattr(service, "_load_requirement_import_context_sync", lambda db, job_id: context)
        monkeypatch.setattr(service, "_prepare_requirement_import_sync", lambda db, **kw: prepared)
        monkeypatch.setattr(service, "run_cli_single_turn", AsyncMock(return_value=provider_reply))
        monkeypatch.setattr(service, "_finalize_requirement_import_sync", capture)
        assert asyncio.run(service.run_requirement_import_preview_job("audit-job")) is True
        evidence = captured["evidence"]
        assert evidence.provider_outcome_seen is True
        assert _decide_status(evidence, service.AiJobStatus.SUCCESS) == service.AiJobStatus.SUCCESS
    finally:
        from app.agents.contract import reset_agent_attempt, reset_agent_attempt_runtime
        reset_agent_attempt_runtime(binding)
        reset_agent_attempt(owner)


def test_remote_split_parse_failure_keeps_provider_outcome_evidence(monkeypatch):
    """provider 正常返回但解析失败：落 FAILED，且不得误判远程仍在运行。"""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    owner, binding = _bind_remote_attempt("audit-job")
    captured = {}

    async def txn(fn):
        return fn(None)

    def capture_fail(db, **kwargs):
        captured.update(kwargs)

    try:
        prepared = {"backend_name": "dsh", "prompt": "split", "project_path": "/tmp"}
        provider_reply = {"text": '{"items": [{"title": "Only one"}]}', "session_id": "remote-1"}
        monkeypatch.setattr(service, "run_db_txn", txn)
        monkeypatch.setattr(service, "_prepare_requirement_split_sync", lambda db, **kw: prepared)
        monkeypatch.setattr(service, "run_cli_single_turn", AsyncMock(return_value=provider_reply))
        monkeypatch.setattr(service, "_fail_requirement_preview_sync", capture_fail)
        assert asyncio.run(service.run_requirement_split_preview_job("audit-job")) is True
        evidence = captured["evidence"]
        assert evidence.provider_outcome_seen is True
        # provider outcome 已见：解析失败落 FAILED，绝不是 ORPHANED（远程已停）。
        assert _decide_status(evidence, service.AiJobStatus.FAILED) == service.AiJobStatus.FAILED
    finally:
        from app.agents.contract import reset_agent_attempt, reset_agent_attempt_runtime
        reset_agent_attempt_runtime(binding)
        reset_agent_attempt(owner)


def test_remote_preview_without_provider_outcome_stays_unresolved(monkeypatch):
    """无 outcome 断流（CLI 抛错）：outcome 未见到，收敛保持 ORPHANED。"""
    from unittest.mock import AsyncMock, patch

    owner, binding = _bind_remote_attempt("audit-job")
    captured = {}

    async def txn(fn):
        return fn(None)

    def capture_fail(db, **kwargs):
        captured.update(kwargs)

    async def broken_cli(*_args, **_kwargs):
        raise RuntimeError("provider stream died before any result event")

    try:
        prepared = {"backend_name": "dsh", "prompt": "split", "project_path": "/tmp"}
        monkeypatch.setattr(service, "run_db_txn", txn)
        monkeypatch.setattr(service, "_prepare_requirement_split_sync", lambda db, **kw: prepared)
        monkeypatch.setattr(service, "run_cli_single_turn", broken_cli)
        monkeypatch.setattr(service, "_fail_requirement_preview_sync", capture_fail)
        assert asyncio.run(service.run_requirement_split_preview_job("audit-job")) is False
        evidence = captured["evidence"]
        assert evidence.provider_outcome_seen is False
        assert evidence.remote_session_started is True
        assert _decide_status(evidence, service.AiJobStatus.FAILED) == service.AiJobStatus.ORPHANED
    finally:
        from app.agents.contract import reset_agent_attempt, reset_agent_attempt_runtime
        reset_agent_attempt_runtime(binding)
        reset_agent_attempt(owner)
