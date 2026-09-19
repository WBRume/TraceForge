import asyncio
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

import app.domains.api_mock.models.api_mock  # noqa: F401,E402
import app.domains.task.models.test_result  # noqa: F401,E402
import app.domains.workflow.models.task_change  # noqa: F401,E402
import app.domains.workspace_asset.models.workspace_asset  # noqa: F401,E402
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
from app.domains.ai.services.jobs.fencing import AgentAttemptFencedError
from app.database import Base  # noqa: E402
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob  # noqa: E402
from app.domains.auth.models.user import User, Workspace  # noqa: E402
from app.domains.workspace_asset.models.workspace_asset import (  # noqa: E402
    SddRequirementImportBatch,
)
from app.domains.workspace_asset.services.requirements.preview import job_service as preview_job_service  # noqa: E402
from app.domains.workspace_asset.services.requirements.preview import runner as preview_runner  # noqa: E402
from app.domains.workspace_asset.services.common.errors import WorkspaceAssetError  # noqa: E402


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
    return preview_job_service.create_requirement_import_preview_job(
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
    assert job.status == AiJobStatus.PENDING
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

    with pytest.raises(WorkspaceAssetError) as unsupported:
        _create_preview_job(db, b"# x\n", file_name="requirements.pdf")
    assert unsupported.value.status_code == 415

    original_limit = preview_job_service.REQUIREMENT_IMPORT_MAX_BYTES
    preview_job_service.REQUIREMENT_IMPORT_MAX_BYTES = 10
    try:
        with pytest.raises(WorkspaceAssetError) as oversize:
            _create_preview_job(db, b"# too large content beyond limit\n")
        assert oversize.value.status_code == 413
    finally:
        preview_job_service.REQUIREMENT_IMPORT_MAX_BYTES = original_limit


def test_run_import_preview_job_executes_from_persisted_context(tmp_path, monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    _seed_workspace(db, tmp_path)
    response = _create_preview_job(db, b"# Feature A\n\nBody text\n")
    job_id = response.job_id

    prompts = []

    async def fake_cli(prompt, project_path, max_attempts=1, should_cancel=None, backend_name=None):
        prompts.append({"prompt": prompt, "project_path": project_path})
        return {
            "text": '{"items": [{"title": "Feature A", "body": "Body text", "acceptance_criteria": [], "source_ref": "r1"}]}',
            "session_id": "sess-1",
        }

    monkeypatch.setattr(preview_runner, "run_cli_single_turn", fake_cli)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)

    asyncio.run(preview_runner.run_requirement_import_preview_job(job_id))

    db.expire_all()
    job = db.query(SddAiJob).filter(SddAiJob.id == job_id).one()
    assert job.status == AiJobStatus.SUCCESS
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
        channel=AiJobChannel.ASSET_THREAD,
        queue_key="REQUIREMENT_PREVIEW:ws-1",
        status=AiJobStatus.PENDING,
        context_json={"job_kind": "REQUIREMENT_IMPORT_PREVIEW", "source_filename": "requirements.md"},
        creator_id="user-1",
    )
    db.add(job)
    db.commit()

    async def unexpected_cli(*_args, **_kwargs):
        raise AssertionError("CLI must not be called without persisted content")

    monkeypatch.setattr(preview_runner, "run_cli_single_turn", unexpected_cli)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)

    asyncio.run(preview_runner.run_requirement_import_preview_job(job.id))

    db.expire_all()
    failed = db.query(SddAiJob).filter(SddAiJob.id == job.id).one()
    assert failed.status == AiJobStatus.FAILED
    assert "re-upload" in str(failed.error_message)


def test_execute_job_dispatches_split_preview(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    _seed_workspace(db, "G:/tmp/does-not-matter")

    job = SddAiJob(
        id="split-job-1",
        workspace_id="ws-1",
        channel=AiJobChannel.ASSET_THREAD,
        queue_key="REQUIREMENT_PREVIEW:ws-1",
        status=AiJobStatus.RUNNING,
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


    patch_ai_job_db(monkeypatch, SessionLocal)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)
    monkeypatch.setattr(
        preview_runner,
        "run_requirement_split_preview_job",
        _FakePreviewService.run_requirement_split_preview_job,
    )
    monkeypatch.setattr(
        preview_runner,
        "run_requirement_import_preview_job",
        _FakePreviewService.run_requirement_import_preview_job,
    )

    asyncio.run(ai_executors.execute_job("split-job-1"))
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
    job = preview_job_service.create_requirement_split_preview_job(
        db, "ws-1", "req-1", "user-1"
    )
    return job.job_id


def _claim_running(job_id, SessionLocal, *, pid=4242):
    """Simulate claim + process attach: RUNNING + persisted ownership."""
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).one()
        job.status = AiJobStatus.RUNNING
        job.run_token = "run-1"
        job.worker_boot_id = ai_registry.WORKER_BOOT_ID
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
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
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

    monkeypatch.setattr(preview_runner, "run_cli_single_turn", fake_cli)
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
        return await preview_runner.run_requirement_split_preview_job(job_id, run_token="run-1")

    runner(_job())

    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == job_id).one()
    assert saved.status == AiJobStatus.FAILED
    assert saved.run_token is None
    assert saved.process_pid is None
    assert saved.process_group_id is None


def test_split_preview_cancel_keeps_termination_state(tmp_path, monkeypatch):
    """统一取消通道（doc §9.1）：用户取消 → runner 清内存信号直接返回，
    不写 FAILED（TERMINATING 交由 runner 退出收敛 CANCELLED），不落批次。"""
    from app.agents.errors import AgentCancelledError

    SessionLocal = _build_session()
    db = SessionLocal()
    job_id = _seed_split_preview_target(db, tmp_path)
    _claim_running(job_id, SessionLocal)

    async def cancelled_cli(*_args, **_kwargs):
        raise AgentCancelledError(
            "AI job cancelled by user",
            termination_confirmed_dead=True,
            process_started=True,
            failure_code="USER_CANCELLED",
        )

    monkeypatch.setattr(preview_runner, "run_cli_single_turn", cancelled_cli)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)

    ai_runtime.request_cancel(job_id)
    try:
        asyncio.run(preview_runner.run_requirement_split_preview_job(job_id, run_token="run-1"))

        db.expire_all()
        saved = db.query(SddAiJob).filter(SddAiJob.id == job_id).one()
        assert saved.status != AiJobStatus.FAILED
        assert saved.status != AiJobStatus.SUCCESS
        assert db.query(SddRequirementImportBatch).filter(
            SddRequirementImportBatch.workspace_id == "ws-1"
        ).count() == 0
    finally:
        ai_runtime.clear_cancel(job_id)


def test_split_preview_wires_cancel_signal_into_cli(tmp_path, monkeypatch):
    """should_cancel 必须接到统一取消信号：cancel 请求后 CLI 侧立即可见。"""
    SessionLocal = _build_session()
    db = SessionLocal()
    job_id = _seed_split_preview_target(db, tmp_path)
    _claim_running(job_id, SessionLocal)

    captured: dict = {}

    async def fake_cli(prompt, project_path, *, max_attempts=1, should_cancel=None, backend_name=None, **_kw):
        captured["should_cancel"] = should_cancel
        return {"text": '{"items": [{"title": "one", "body": "a"}, {"title": "two", "body": "b"}]}', "session_id": "s1"}

    monkeypatch.setattr(preview_runner, "run_cli_single_turn", fake_cli)
    monkeypatch.setattr("app.database.SessionLocal", SessionLocal)

    asyncio.run(preview_runner.run_requirement_split_preview_job(job_id, run_token="run-1"))
    assert callable(captured.get("should_cancel"))
    assert captured["should_cancel"]() is False
    ai_runtime.request_cancel(job_id)
    try:
        assert captured["should_cancel"]() is True
    finally:
        ai_runtime.clear_cancel(job_id)


def test_preview_unknown_death_failure_stays_orphaned(tmp_path, monkeypatch):
    """反向：CLI 死亡未证实 + 解析失败 → ORPHANED 且保留 ownership。"""
    SessionLocal = _build_session()
    db = SessionLocal()
    job_id = _seed_split_preview_target(db, tmp_path)
    _claim_running(job_id, SessionLocal)

    async def fake_cli(*_args, **_kwargs):
        return {"text": '{"items": [{"title": "Only one"}]}', "session_id": "sess-1"}

    monkeypatch.setattr(preview_runner, "run_cli_single_turn", fake_cli)
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
        return await preview_runner.run_requirement_split_preview_job(job_id, run_token="run-1")

    runner(_job())

    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == job_id).one()
    assert saved.status == AiJobStatus.ORPHANED
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

    monkeypatch.setattr(preview_runner, "run_cli_single_turn", fake_cli)
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
        return await preview_runner.run_requirement_import_preview_job(job_id, run_token="run-1")

    runner(_job())

    db.expire_all()
    saved = db.query(SddAiJob).filter(SddAiJob.id == job_id).one()
    assert saved.status == AiJobStatus.FAILED
    assert saved.run_token is None
    assert saved.process_pid is None


# ─────────── P1（doc: docs/agent-job-07e04775-audit-pseudocode-plan.md §4）───────────
# 远程需求预览（import/split）必须把 provider 终局证据传入 finalizer evidence：
# 会话已建立且 provider 正常返回时，收敛不得判 ORPHANED。调用链测试必须包含
# 真实 single-turn helper，不只 mock 返回 dict（doc 审计 §4.5）。


def _bind_remote_attempt(job_id: str):
    from unittest.mock import patch  # noqa: F401

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


class _StubRemoteBridge:
    """远程 bridge 桩：发出 legacy 风格事件，不调用真实远程服务。"""

    def __init__(self, events=(), session_id="remote-1", start_error=None):
        self.session_id = session_id
        self._events = list(events)
        self._start_error = start_error

    async def start_session(self, **kwargs):
        callback = kwargs["event_callback"]
        for event in self._events:
            await callback(event)
        if self._start_error is not None:
            raise self._start_error
        return self.session_id

    async def wait(self):
        return None

    def is_running(self):
        return False

    async def cancel(self):
        from app.agents.contract import (
            EXECUTION_KIND_REMOTE_SESSION,
            AgentStopResult,
        )

        return AgentStopResult(
            execution_kind=EXECUTION_KIND_REMOTE_SESSION,
            stop_acknowledged=False,
            failure_code="REMOTE_STOP_UNCONFIRMED",
        )


async def _async_txn(fn):
    return fn(None)


from unittest.mock import patch  # noqa: E402



def test_remote_split_preview_evidence_enables_convergence(monkeypatch):
    """split 预览：provider 正常返回（真实 helper + 明确 result 事件）→
    finalizer evidence 带 outcome → SUCCESS。"""
    owner, binding = _bind_remote_attempt("audit-job")
    captured = {}

    def capture(db, **kwargs):
        captured.update(kwargs)

    stub = _StubRemoteBridge(
        events=[
            {"type": "system", "subtype": "init", "session_id": "remote-1"},
            {
                "type": "result", "subtype": "success", "is_error": False,
                "result": '{"items": [{"title": "one", "body": "a"}, {"title": "two", "body": "b"}]}',
                "session_id": "remote-1",
            },
        ]
    )
    try:
        prepared = {"backend_name": "dsh", "prompt": "split", "project_path": "/tmp"}
        monkeypatch.setattr(
        preview_runner, "prepare_requirement_split_sync", lambda db, **kw: prepared
        )
        monkeypatch.setattr(preview_runner, "finalize_requirement_split_sync", capture)
        with patch("app.agents.selection.create_legacy_bridge", return_value=stub), \
                patch.object(preview_runner, "run_db_txn", _async_txn), \
                patch.object(preview_runner, "run_cli_single_turn", ai_provider_turn.run_cli_single_turn):
            assert asyncio.run(preview_runner.run_requirement_split_preview_job("audit-job")) is True
        evidence = captured["evidence"]
        assert evidence.provider_outcome_seen is True
        assert _decide_status(evidence, AiJobStatus.SUCCESS) == AiJobStatus.SUCCESS
    finally:
        from app.agents.contract import reset_agent_attempt, reset_agent_attempt_runtime
        reset_agent_attempt_runtime(binding)
        reset_agent_attempt(owner)


def test_remote_import_preview_evidence_enables_convergence(monkeypatch):
    """import 预览与 split 使用相同 helper（真实 single-turn 调用链）。"""
    owner, binding = _bind_remote_attempt("audit-job")
    captured = {}

    def capture(db, **kwargs):
        captured.update(kwargs)

    stub = _StubRemoteBridge(
        events=[
            {"type": "system", "subtype": "init", "session_id": "remote-1"},
            {
                "type": "result", "subtype": "success", "is_error": False,
                "result": '{"items": [{"title": "Feature A", "body": "Body", "acceptance_criteria": [], "source_ref": "r1"}]}',
                "session_id": "remote-1",
            },
        ]
    )
    try:
        context = {
            "markdown": "# Feature A\n\nBody\n", "source_kind": "file",
            "source_ref": "requirements.md", "source_uri": "", "file_name": "requirements.md",
            "source_ext": ".md", "source_mime": "text/markdown", "render_json": {},
        }
        prepared = {"backend_name": "dsh", "prompt": "import", "project_path": "/tmp"}
        monkeypatch.setattr(
        preview_runner, "load_requirement_import_context_sync", lambda db, job_id: context
        )
        monkeypatch.setattr(
        preview_runner, "prepare_requirement_import_sync", lambda db, **kw: prepared
        )
        monkeypatch.setattr(preview_runner, "finalize_requirement_import_sync", capture)
        with patch("app.agents.selection.create_legacy_bridge", return_value=stub), \
                patch.object(preview_runner, "run_db_txn", _async_txn), \
                patch.object(preview_runner, "run_cli_single_turn", ai_provider_turn.run_cli_single_turn):
            assert asyncio.run(preview_runner.run_requirement_import_preview_job("audit-job")) is True
        evidence = captured["evidence"]
        assert evidence.provider_outcome_seen is True
        assert _decide_status(evidence, AiJobStatus.SUCCESS) == AiJobStatus.SUCCESS
    finally:
        from app.agents.contract import reset_agent_attempt, reset_agent_attempt_runtime
        reset_agent_attempt_runtime(binding)
        reset_agent_attempt(owner)


def test_remote_split_parse_failure_keeps_provider_outcome_evidence(monkeypatch):
    """provider 正常返回（明确 result）但解析失败：落 FAILED，outcome 仍
    保留，绝不误判远程仍在运行（doc 审计 §4.5 验收）。"""
    owner, binding = _bind_remote_attempt("audit-job")
    captured = {}

    def capture_fail(db, **kwargs):
        captured.update(kwargs)

    stub = _StubRemoteBridge(
        events=[
            {"type": "system", "subtype": "init", "session_id": "remote-1"},
            {
                "type": "result", "subtype": "success", "is_error": False,
                "result": '{"items": [{"title": "Only one"}]}',
                "session_id": "remote-1",
            },
        ]
    )
    try:
        prepared = {"backend_name": "dsh", "prompt": "split", "project_path": "/tmp"}
        monkeypatch.setattr(
        preview_runner, "prepare_requirement_split_sync", lambda db, **kw: prepared
        )
        monkeypatch.setattr(preview_runner, "fail_requirement_preview_sync", capture_fail)
        with patch("app.agents.selection.create_legacy_bridge", return_value=stub), \
                patch.object(preview_runner, "run_db_txn", _async_txn), \
                patch.object(preview_runner, "run_cli_single_turn", ai_provider_turn.run_cli_single_turn):
            assert asyncio.run(preview_runner.run_requirement_split_preview_job("audit-job")) is True
        evidence = captured["evidence"]
        assert evidence.provider_outcome_seen is True
        # provider outcome 已见：解析失败落 FAILED，绝不是 ORPHANED（远程已停）。
        assert _decide_status(evidence, AiJobStatus.FAILED) == AiJobStatus.FAILED
    finally:
        from app.agents.contract import reset_agent_attempt, reset_agent_attempt_runtime
        reset_agent_attempt_runtime(binding)
        reset_agent_attempt(owner)


def test_real_single_turn_error_outcome_survives_preview_failure(monkeypatch):
    """明确失败 result（真实 helper 调用链）：业务 FAILED 而非 ORPHANED
    （07e04775 §4.1 repro：result 到达时登记证据，异常路径不丢失）。"""
    owner, binding = _bind_remote_attempt("audit-job")
    captured = {}

    def capture_fail(db, **kwargs):
        captured.update(kwargs)

    stub = _StubRemoteBridge(
        events=[
            {
                "type": "result", "subtype": "error", "is_error": True,
                "result": "provider rejected request",
            },
        ],
        session_id="remote-07",
    )
    try:
        prepared = {"backend_name": "dsh", "prompt": "split", "project_path": "/tmp"}
        monkeypatch.setattr(
        preview_runner, "prepare_requirement_split_sync", lambda db, **kw: prepared
        )
        monkeypatch.setattr(preview_runner, "fail_requirement_preview_sync", capture_fail)
        with patch("app.agents.selection.create_legacy_bridge", return_value=stub), \
                patch.object(preview_runner, "run_db_txn", _async_txn), \
                patch.object(preview_runner, "run_cli_single_turn", ai_provider_turn.run_cli_single_turn):
            # 返回协议保持既有语义（异常路径返回 outcome 局部布尔）；
            # 收敛正确性由 finalizer evidence 决定。
            asyncio.run(preview_runner.run_requirement_split_preview_job("audit-job"))
        evidence = captured["evidence"]
        # provider 明确失败 result 也是终局 outcome：FAILED，不是 ORPHANED。
        assert evidence.provider_outcome_seen is True
        assert _decide_status(evidence, AiJobStatus.FAILED) == AiJobStatus.FAILED
    finally:
        from app.agents.contract import reset_agent_attempt, reset_agent_attempt_runtime
        reset_agent_attempt_runtime(binding)
        reset_agent_attempt(owner)


def test_remote_preview_without_provider_outcome_stays_unresolved(monkeypatch):
    """只有 assistant 文本、没有 result 事件的断流（真实 helper）：outcome
    未见到（不伪造结束），收敛保持 ORPHANED。"""
    owner, binding = _bind_remote_attempt("audit-job")
    captured = {}

    def capture_fail(db, **kwargs):
        captured.update(kwargs)

    stub = _StubRemoteBridge(
        events=[
            {"type": "system", "subtype": "init", "session_id": "remote-1"},
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "partial stream"}]},
            },
        ]
    )
    try:
        prepared = {"backend_name": "dsh", "prompt": "split", "project_path": "/tmp"}
        monkeypatch.setattr(
        preview_runner, "prepare_requirement_split_sync", lambda db, **kw: prepared
        )
        monkeypatch.setattr(preview_runner, "fail_requirement_preview_sync", capture_fail)
        with patch("app.agents.selection.create_legacy_bridge", return_value=stub), \
                patch.object(preview_runner, "run_db_txn", _async_txn), \
                patch.object(preview_runner, "run_cli_single_turn", ai_provider_turn.run_cli_single_turn):
            assert asyncio.run(preview_runner.run_requirement_split_preview_job("audit-job")) is False
        evidence = captured["evidence"]
        assert evidence.provider_outcome_seen is False
        assert evidence.remote_session_started is True
        assert _decide_status(evidence, AiJobStatus.FAILED) == AiJobStatus.ORPHANED
    finally:
        from app.agents.contract import reset_agent_attempt, reset_agent_attempt_runtime
        reset_agent_attempt_runtime(binding)
        reset_agent_attempt(owner)


# ── 浮窗支撑：响应字段（job_kind/requirement_*）与 active 恢复列表 ──


def test_preview_job_response_includes_kind_and_title(tmp_path):
    SessionLocal = _build_session()
    db = SessionLocal()
    _seed_split_preview_target(db, tmp_path)

    response = preview_job_service.create_requirement_split_preview_job(
        db, "ws-1", "req-1", "user-1"
    )
    assert response.job_kind == "REQUIREMENT_SPLIT_PREVIEW"
    assert response.requirement_id == "req-1"
    assert response.requirement_title == "Big requirement"

    # 导入预览：requirement_title 回退为来源文件名
    import_response = _create_preview_job(db, b"# Feature A\n", file_name="imported.md")
    assert import_response.job_kind == "REQUIREMENT_IMPORT_PREVIEW"
    assert import_response.requirement_id is None
    assert import_response.requirement_title == "imported.md"


def test_list_active_requirement_preview_jobs_filters_creator_and_status(tmp_path):
    SessionLocal = _build_session()
    db = SessionLocal()
    _seed_split_preview_target(db, tmp_path)

    pending = preview_job_service.create_requirement_split_preview_job(
        db, "ws-1", "req-1", "user-1"
    )
    finished = preview_job_service.create_requirement_split_preview_job(
        db, "ws-1", "req-1", "user-1"
    )
    other_user = User(id="user-2", email="u2@example.com", hashed_password="x", display_name="U2")
    db.add(other_user)
    db.commit()
    foreign = preview_job_service.create_requirement_split_preview_job(
        db, "ws-1", "req-1", "user-2"
    )

    db.expire_all()
    done = db.query(SddAiJob).filter(SddAiJob.id == finished.job_id).one()
    done.status = AiJobStatus.SUCCESS
    db.commit()

    active = preview_job_service.list_active_requirement_preview_jobs(db, "user-1")
    active_ids = {item.job_id for item in active}
    assert pending.job_id in active_ids
    assert finished.job_id not in active_ids
    assert foreign.job_id not in active_ids
    item = next(i for i in active if i.job_id == pending.job_id)
    assert item.status in (AiJobStatus.PENDING.value, AiJobStatus.RUNNING.value)
    assert item.requirement_title == "Big requirement"
