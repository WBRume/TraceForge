"""Agent attempt 收敛验收（原 test_ai_job_convergence.py，doc V3 §14）。

覆盖：
- 14.3b 远程 adapter 停止结果协议（opencode / dsh / legacy shim）；
- 14.7 execution kind 端到端：claim 持久化 + attempt context 传播。
"""

from __future__ import annotations

import asyncio

import pytest

from tests.ai.jobs.ai_job_test_utils import (
    _job,
    _owned_job,
    _session_factory,
    _terminate_request,
    patch_ai_job_db,
)
from app.agents.contract import (
    EXECUTION_KIND_LOCAL_PROCESS,
    EXECUTION_KIND_REMOTE_SESSION,
    AgentAttemptRuntimeState,
    AgentStopResult,
    bind_agent_attempt_runtime,
    reset_agent_attempt_runtime,
)
from app.agents.errors import AgentError
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services import ai_job_convergence_service as convergence
from app.domains.ai.services.ai_job_convergence_service import REMOTE_STOP_UNCONFIRMED
from app.domains.ai.services.jobs import attempts as ai_attempts
from app.domains.ai.services.jobs import registry as ai_registry
from app.domains.ai.services.jobs import store as ai_store


# ────────────────────── 14.7 execution kind 端到端 ──────────────────────


def test_claim_persists_execution_kind_for_task_backend(monkeypatch):
    from app.domains.auth.models.user import User, Workspace
    from app.domains.task.models.task import SddTask

    factory = _session_factory()
    db = factory()
    user = User(id="user-1", email="c@example.com", hashed_password="x", display_name="C")
    workspace = Workspace(id="ws-1", name="W", owner_id=user.id)
    task = SddTask(
        id="task-1",
        workspace_id="ws-1",
        creator_id="user-1",
        name="T",
        project_path=".",
        status="CODING",
        agent_backend="opencode",
    )
    job = SddAiJob(
        id="convergence-job",
        workspace_id="ws-1",
        task_id="task-1",
        channel=AiJobChannel.TASK_CHAT,
        queue_key="TASK_CHAT:task-1",
        status=AiJobStatus.PENDING,
        creator_id="user-1",
    )
    db.add_all([user, workspace, task, job])
    db.commit()
    patch_ai_job_db(monkeypatch, factory)

    job_id = ai_store.take_next_pending_job_id_sync("TASK_CHAT:task-1")

    assert job_id == "convergence-job"
    claimed = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    # 必须断言显式 execution kind，而不是“PID 为空”。
    assert claimed.process_execution_kind == EXECUTION_KIND_REMOTE_SESSION
    assert claimed.process_pid is None


def test_claim_persists_local_kind_for_claude_backend(monkeypatch):
    from app.domains.auth.models.user import User, Workspace
    from app.domains.task.models.task import SddTask

    factory = _session_factory()
    db = factory()
    user = User(id="user-1", email="c@example.com", hashed_password="x", display_name="C")
    workspace = Workspace(id="ws-1", name="W", owner_id=user.id)
    task = SddTask(
        id="task-1",
        workspace_id="ws-1",
        creator_id="user-1",
        name="T",
        project_path=".",
        status="CODING",
        agent_backend="claude-code",
    )
    job = SddAiJob(
        id="convergence-job",
        workspace_id="ws-1",
        task_id="task-1",
        channel=AiJobChannel.TASK_CHAT,
        queue_key="TASK_CHAT:task-1",
        status=AiJobStatus.PENDING,
        creator_id="user-1",
    )
    db.add_all([user, workspace, task, job])
    db.commit()
    patch_ai_job_db(monkeypatch, factory)

    job_id = ai_store.take_next_pending_job_id_sync("TASK_CHAT:task-1")

    assert job_id == "convergence-job"
    claimed = db.query(SddAiJob).filter(SddAiJob.id == "convergence-job").first()
    assert claimed.process_execution_kind == EXECUTION_KIND_LOCAL_PROCESS


def test_attempt_context_carries_execution_kind(monkeypatch):
    factory = _session_factory()
    db = factory()
    _owned_job(db, status=AiJobStatus.RUNNING, kind=EXECUTION_KIND_REMOTE_SESSION, pid=None)
    patch_ai_job_db(monkeypatch, factory)

    context = ai_attempts.load_attempt_context_sync("convergence-job")

    assert context is not None
    assert context.execution_kind == EXECUTION_KIND_REMOTE_SESSION


def test_remote_cancel_via_convergence_requires_ack_not_pid_empty():
    """不得通过“PID 为空”推断远程：显式 kind 决定决策分支。"""
    factory = _session_factory()
    db = factory()
    # 行显式声明 LOCAL_PROCESS 但没有任何 PID（PID 持久化失败）：
    # 取消时仍必须走本地死亡证明，不得因 PID 为空被当成远程。
    _job(
        db,
        status=AiJobStatus.TERMINATING,
        run_token="run-1",
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        pid=None,
        cancel_requested=True,
    )

    result = convergence.converge_job_attempt_sync(db, _terminate_request(dead=None, started=False))

    # started=False 且无 ownership → 允许 CANCELLED；但若曾启动（runtime
    # 记录 started）则必须 ORPHANED —— 用另一个请求验证。
    assert result.status == AiJobStatus.CANCELLED.value

    started_request = _terminate_request(dead=None, started=True)
    db2 = _session_factory()()
    _job(
        db2,
        status=AiJobStatus.TERMINATING,
        run_token="run-1",
        worker_boot_id=ai_registry.WORKER_BOOT_ID,
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        pid=None,
        cancel_requested=True,
    )
    orphaned = convergence.converge_job_attempt_sync(db2, started_request)
    assert orphaned.status == AiJobStatus.ORPHANED.value


# ────────────────────── 14.3b 远程 adapter 停止结果协议 ──────────────────────


def test_opencode_abort_success_returns_acknowledged():
    from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter

    class _Resp:
        status_code = 200

    class _Client:
        async def post(self, url):
            return _Resp()

    adapter = OpenCodeAdapter(server_url="http://opencode.test")
    adapter._client = _Client()
    adapter._session_id = "sess-1"

    result = asyncio.run(adapter.cancel())

    assert result.execution_kind == EXECUTION_KIND_REMOTE_SESSION
    assert result.stop_acknowledged is True
    assert result.failure_code is None


def test_opencode_abort_rejected_status_returns_structured_nack():
    from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter

    class _Resp:
        status_code = 500

    class _Client:
        async def post(self, url):
            return _Resp()

    adapter = OpenCodeAdapter(server_url="http://opencode.test")
    adapter._client = _Client()
    adapter._session_id = "sess-1"

    result = asyncio.run(adapter.cancel())

    assert result.stop_acknowledged is False
    assert result.failure_code == "OPENCODE_ABORT_REJECTED"
    assert "500" in (result.error_message or "")


def test_opencode_abort_network_error_is_visible_not_swallowed():
    from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter

    class _Client:
        async def post(self, url):
            raise OSError("connection reset")

    adapter = OpenCodeAdapter(server_url="http://opencode.test")
    adapter._client = _Client()
    adapter._session_id = "sess-1"

    result = asyncio.run(adapter.cancel())

    assert result.stop_acknowledged is False
    assert result.failure_code == "OPENCODE_ABORT_NETWORK_ERROR"
    assert result.error_message


def test_opencode_cancel_without_session_is_unacknowledged():
    from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter

    adapter = OpenCodeAdapter(server_url="http://opencode.test")
    adapter._client = None
    adapter._session_id = None

    result = asyncio.run(adapter.cancel())

    assert result.stop_acknowledged is False
    assert result.failure_code == REMOTE_STOP_UNCONFIRMED


def test_dsh_cancel_rpc_success_is_acknowledged():
    from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter

    adapter = DshServerAdapter(server_url="http://dsh.test")
    adapter._session_id = "sess-1"

    async def _ok_rpc(method, payload):
        return {}

    adapter._rpc = _ok_rpc

    result = asyncio.run(adapter.cancel())

    assert result.execution_kind == EXECUTION_KIND_REMOTE_SESSION
    assert result.stop_acknowledged is True


def test_dsh_cancel_rpc_error_returns_structured_failure():
    from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter

    adapter = DshServerAdapter(server_url="http://dsh.test")
    adapter._session_id = "sess-1"

    async def _bad_rpc(method, payload):
        raise AgentError("DSH server RPC session.cancel failed: HTTP 503")

    adapter._rpc = _bad_rpc

    result = asyncio.run(adapter.cancel())

    assert result.stop_acknowledged is False
    assert result.failure_code == "DSH_CANCEL_RPC_FAILED"
    assert "503" in (result.error_message or "")


def test_dsh_interrupt_without_session_is_unacknowledged():
    from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter

    adapter = DshServerAdapter(server_url="http://dsh.test")
    adapter._session_id = None

    result = asyncio.run(adapter.interrupt())

    assert result.stop_acknowledged is False
    assert result.failure_code == REMOTE_STOP_UNCONFIRMED


def test_legacy_shim_cancel_returns_structured_result_and_records_runtime():
    from types import SimpleNamespace

    from app.agents.selection import LegacyBridgeShim

    class _Backend:
        name = "remote-test"
        capabilities = SimpleNamespace(execution_kind=EXECUTION_KIND_REMOTE_SESSION)

        async def cancel(self):
            return AgentStopResult(
                execution_kind=EXECUTION_KIND_REMOTE_SESSION,
                stop_acknowledged=True,
            )

        async def close(self):
            return None

    runtime = AgentAttemptRuntimeState()
    runtime_token = bind_agent_attempt_runtime(runtime)
    try:
        shim = LegacyBridgeShim(_Backend(), backend_name="remote-test")
        result = asyncio.run(shim.cancel())
        assert result.stop_acknowledged is True
        assert runtime.remote_stop_acknowledged is True
    finally:
        reset_agent_attempt_runtime(runtime_token)


def test_legacy_shim_cancel_error_is_not_swallowed():
    from types import SimpleNamespace

    from app.agents.selection import LegacyBridgeShim

    class _Backend:
        name = "remote-test"
        capabilities = SimpleNamespace(execution_kind=EXECUTION_KIND_REMOTE_SESSION)

        async def cancel(self):
            raise RuntimeError("rpc exploded")

        async def close(self):
            return None

    shim = LegacyBridgeShim(_Backend(), backend_name="remote-test")

    result = asyncio.run(shim.cancel())

    assert result.stop_acknowledged is False
    assert result.failure_code == "REMOTE_CANCEL_FAILED"
    assert "rpc exploded" in (result.error_message or "")


def test_legacy_shim_cancel_none_return_is_unacknowledged():
    from types import SimpleNamespace

    from app.agents.selection import LegacyBridgeShim

    class _Backend:
        name = "remote-test"
        capabilities = SimpleNamespace(execution_kind=EXECUTION_KIND_REMOTE_SESSION)

        async def cancel(self):
            return None

        async def close(self):
            return None

    shim = LegacyBridgeShim(_Backend(), backend_name="remote-test")

    result = asyncio.run(shim.cancel())

    # 远程 cancel 的 None 返回值绝不能被视作成功（doc §17）。
    assert result.stop_acknowledged is False
    assert result.failure_code == REMOTE_STOP_UNCONFIRMED
