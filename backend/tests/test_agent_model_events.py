"""DSH model observations are reflected in runtime state without model RPCs."""

import os
import sys
import unittest
from unittest import mock

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.agents.events import AgentEvent
from app.engine.workflow_engine import WorkflowEngine


class WorkflowEngineModelEventTest(unittest.IsolatedAsyncioTestCase):
    def _make_engine(self) -> WorkflowEngine:
        engine = WorkflowEngine.__new__(WorkflowEngine)
        engine.task_id = "task-1"
        engine.ws_id = "workspace-1"
        engine.user_id = "user-1"
        engine.current_job_id = "job-1"
        engine.session_id = None
        engine.session_revision = None
        engine._runtime_model = None
        engine.on_session = None
        engine._event_is_current = mock.Mock(return_value=True)
        engine._update_context_snapshot = mock.Mock()
        engine._emit_hook = mock.AsyncMock()
        engine._push_status = mock.AsyncMock()
        return engine

    async def test_dsh_model_event_updates_snapshot_and_runtime_status(self):
        engine = self._make_engine()

        await engine.handle_agent_event(AgentEvent(
            type="session_started",
            payload={"provider_session_id": "session-1", "provider": "dsh"},
            provider="dsh",
        ))

        initial_status = engine._push_status.await_args_list[-1]
        self.assertEqual(initial_status.args[:2], ("INIT", "Agent 会话已启动"))
        self.assertEqual(initial_status.kwargs["model"], None)

        await engine.handle_agent_event(AgentEvent(
            type="model",
            payload={
                "model": "deepseek-official/deepseek-v4-flash",
                "provider": "dsh",
                "source": "request/header",
            },
            provider="dsh",
        ))

        self.assertEqual(engine._runtime_model, "deepseek-official/deepseek-v4-flash")
        engine._update_context_snapshot.assert_any_call(
            model="deepseek-official/deepseek-v4-flash",
            status="RUNNING",
        )
        model_status = engine._push_status.await_args_list[-1]
        self.assertEqual(
            model_status.args[:2],
            ("RUNNING", "Agent 当前模型: deepseek-official/deepseek-v4-flash"),
        )
        self.assertEqual(model_status.kwargs["model"], "deepseek-official/deepseek-v4-flash")


class RemoteStopAfterErrorTest(unittest.IsolatedAsyncioTestCase):
    """异常出口的远程会话兜底停止（doc 修复方案 §8.3）。

    - attempt runtime 已有 stop 证据（interrupt ACK）时绝不覆盖；
    - 停止超时/异常必须落结构化 NACK，不得伪造 ACK；
    - 本地执行类别与未建立会话时完全不动作。
    """

    def _make_engine(self, *, execution_kind="REMOTE_SESSION", session_id="sid-1"):
        engine = WorkflowEngine.__new__(WorkflowEngine)
        engine.task_id = "task-1"
        engine.ws_id = "workspace-1"
        engine.user_id = "user-1"
        engine.current_job_id = "job-1"
        engine.session_id = session_id
        engine.cli = mock.Mock()
        engine.cli.capabilities = mock.Mock(execution_kind=execution_kind)
        return engine

    async def test_existing_stop_ack_is_never_overwritten(self):
        from app.agents.contract import (
            EXECUTION_KIND_REMOTE_SESSION,
            AgentStopResult,
            AgentAttemptRuntimeState,
            bind_agent_attempt_runtime,
            reset_agent_attempt_runtime,
        )

        engine = self._make_engine()
        engine.cli.cancel_persisted_session = mock.AsyncMock(
            side_effect=AssertionError("fallback must not run when ACK exists")
        )
        runtime = AgentAttemptRuntimeState()
        runtime.record_remote_stop(
            AgentStopResult(
                execution_kind=EXECUTION_KIND_REMOTE_SESSION,
                stop_acknowledged=True,
            )
        )
        token = bind_agent_attempt_runtime(runtime)
        try:
            await engine._stop_remote_session_after_error()
        finally:
            reset_agent_attempt_runtime(token)
        self.assertTrue(runtime.remote_stop_acknowledged)

    async def test_stop_failure_records_structured_nack(self):
        from app.agents.contract import (
            AgentAttemptRuntimeState,
            bind_agent_attempt_runtime,
            reset_agent_attempt_runtime,
        )

        engine = self._make_engine()
        engine.cli.cancel_persisted_session = mock.AsyncMock(
            side_effect=RuntimeError("rpc down")
        )
        runtime = AgentAttemptRuntimeState()
        token = bind_agent_attempt_runtime(runtime)
        try:
            await engine._stop_remote_session_after_error()
        finally:
            reset_agent_attempt_runtime(token)
        stop = runtime.remote_stop_result
        self.assertIsNotNone(stop)
        self.assertFalse(stop.stop_acknowledged)
        self.assertEqual(stop.failure_code, "REMOTE_STOP_UNCONFIRMED")

    async def test_local_kind_and_missing_session_never_stop(self):
        engine = self._make_engine(execution_kind="LOCAL_PROCESS")
        engine.cli.cancel = mock.AsyncMock(
            side_effect=AssertionError("local backend must not be stopped here")
        )
        await engine._stop_remote_session_after_error()

        engine = self._make_engine(session_id=None)
        engine.cli.cancel_persisted_session = mock.AsyncMock(
            side_effect=AssertionError("no session to stop")
        )
        await engine._stop_remote_session_after_error()
