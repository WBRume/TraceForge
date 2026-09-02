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
