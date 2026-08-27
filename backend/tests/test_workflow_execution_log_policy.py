import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.agents import AgentEvent  # noqa: E402
from app.engine.workflow_engine import WorkflowEngine  # noqa: E402


class WorkflowExecutionLogPolicyTest(unittest.IsolatedAsyncioTestCase):
    def _engine(self) -> WorkflowEngine:
        with patch.object(WorkflowEngine, "_create_engine_backend", return_value=MagicMock()):
            engine = WorkflowEngine("task-1", "ws-1", "user-1")
        engine._queue_execution_log = MagicMock()
        engine._record_context_segment = MagicMock()
        engine._ws_push = AsyncMock()
        engine._push_chat = AsyncMock()
        return engine

    async def test_text_and_provider_debug_events_are_not_execution_logs(self):
        engine = self._engine()

        await engine.handle_agent_event(AgentEvent(
            type="text",
            payload={"text": "assistant reply"},
            provider="opencode",
        ))
        await engine.handle_agent_event(AgentEvent(
            type="log",
            payload={"level": "debug", "message": "provider status"},
            provider="opencode",
        ))

        engine._push_chat.assert_awaited_once_with("assistant", "assistant reply")
        engine._queue_execution_log.assert_not_called()

    async def test_thinking_delta_accumulates_and_full_thinking_replaces(self):
        engine = self._engine()

        await engine.handle_agent_event(AgentEvent(
            type="thinking",
            payload={"text": "check", "delta": "check"},
            provider="dsh",
        ))
        await engine.handle_agent_event(AgentEvent(
            type="thinking",
            payload={"text": "ing", "delta": "ing"},
            provider="dsh",
        ))
        await engine.handle_agent_event(AgentEvent(
            type="thinking",
            payload={"text": "FINAL"},
            provider="dsh",
        ))

        self.assertEqual(engine._thinking_buffer, "FINAL")
        self.assertEqual(engine._ws_push.await_count, 3)
        thinking_payloads = [call.args[1] for call in engine._ws_push.await_args_list]
        self.assertEqual(thinking_payloads[0].get("content"), "check")
        self.assertEqual(thinking_payloads[1].get("content"), "checking")
        self.assertEqual(thinking_payloads[2].get("content"), "FINAL")

    async def test_tool_events_are_persisted_once_each(self):
        engine = self._engine()

        with (
            patch(
                "app.engine.workflow_engine.skill_runtime_trace_service.enqueue_tool_use_trace"
            ),
            patch(
                "app.engine.workflow_engine.skill_runtime_trace_service.enqueue_tool_result_trace"
            ),
        ):
            await engine.handle_agent_event(AgentEvent(
                type="tool_use",
                payload={
                    "tool_name": "read_file",
                    "tool_input": {"path": "README.md"},
                    "tool_use_id": "call-1",
                },
                provider="opencode",
            ))
            await engine.handle_agent_event(AgentEvent(
                type="tool_result",
                payload={
                    "tool_use_id": "call-1",
                    "output": "contents",
                    "is_error": False,
                },
                provider="opencode",
            ))

        assert engine._queue_execution_log.call_count == 2
        stored = [json.loads(call.args[0]) for call in engine._queue_execution_log.call_args_list]
        assert stored == [
            {
                "tool_name": "read_file",
                "tool_input": {"path": "README.md"},
                "tool_use_id": "call-1",
            },
            {"tool_use_id": "call-1", "output": "contents", "is_error": False},
        ]

    async def test_compaction_event_keeps_observability_fallback(self):
        engine = self._engine()

        await engine.handle_agent_event(AgentEvent(
            type="context_compacted",
            payload={"summary": "tokens 120000 -> 32000"},
            provider="claude-code",
        ))

        engine._queue_execution_log.assert_called_once()
        assert engine._queue_execution_log.call_args.args[0].startswith("[compaction]")

    async def test_execution_logs_flush_as_one_batch(self):
        with patch.object(WorkflowEngine, "_create_engine_backend", return_value=MagicMock()):
            engine = WorkflowEngine("task-1", "ws-1", "user-1")
        engine._persist_execution_logs_sync = MagicMock()

        with patch("app.engine.workflow_engine.EXECUTION_LOG_FLUSH_INTERVAL_SECONDS", 0):
            engine._queue_execution_log("first")
            engine._queue_execution_log("second")
            await engine._drain_execution_logs()

        engine._persist_execution_logs_sync.assert_called_once()
        batch = engine._persist_execution_logs_sync.call_args.args[0]
        assert [entry[0] for entry in batch] == ["first", "second"]
        assert batch[0][2] < batch[1][2]
