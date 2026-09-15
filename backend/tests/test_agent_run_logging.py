"""统一 AgentBackend 底层 AI 会话日志测试。"""

import asyncio
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.agents import AgentEvent, AgentRunRequest, AgentRunResult
from app.agents.run_logging import run_agent_backend_with_logging
from app.config import settings


class AgentRunLoggingTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._old_ai_session_dir = settings.AI_SESSION_LOG_DIR
        self._trace_tmp = tempfile.TemporaryDirectory()
        settings.AI_SESSION_LOG_DIR = os.path.join(self._trace_tmp.name, "ai_sessions")

    def tearDown(self) -> None:
        settings.AI_SESSION_LOG_DIR = self._old_ai_session_dir
        self._trace_tmp.cleanup()

    async def test_logs_ai_session_start_events_and_success(self):
        events: list[AgentEvent] = []

        async def sink(event: AgentEvent) -> None:
            events.append(event)

        class _Backend:
            name = "fake"

            async def run(self, request: AgentRunRequest, on_event):
                await on_event(AgentEvent(
                    type="session_started",
                    payload={"provider_session_id": "s1", "provider": "fake"},
                    provider="fake",
                ))
                await on_event(AgentEvent(
                    type="text",
                    payload={"text": "hello", "provider": "fake"},
                    provider="fake",
                ))
                await on_event(AgentEvent(
                    type="result",
                    payload={
                        "success": True,
                        "result": "ok",
                        "finish_reason": "completed",
                        "provider": "fake",
                    },
                    provider="fake",
                ))
                return AgentRunResult(
                    run_id=request.run_id,
                    session_id="s1",
                    success=True,
                    result_text="ok",
                    finish_reason="completed",
                )

        request = AgentRunRequest(
            run_id="run-1",
            prompt="hi",
            metadata={
                "task_id": "task-1",
                "workspace_id": "ws-1",
                "user_id": "user-1",
                "ai_job_id": "job-1",
            },
        )

        with patch("app.agents.run_logging.logger") as mock_logger:
            mock_logger.bind.return_value = mock_logger
            result = await run_agent_backend_with_logging(_Backend(), request, sink)

        self.assertEqual(result.result_text, "ok")
        self.assertEqual(result.session_id, "s1")
        self.assertTrue(any(e.type == "session_started" for e in events))

        info_messages = [str(call.args[0]) for call in mock_logger.info.call_args_list]
        self.assertIn("agent run start", info_messages)
        self.assertIn("agent session started", info_messages)
        self.assertIn("agent result", info_messages)
        self.assertIn("agent run success", info_messages)

    async def test_logs_run_error(self):
        class _Backend:
            name = "fake"

            async def run(self, request: AgentRunRequest, on_event):
                raise RuntimeError("boom")

        request = AgentRunRequest(run_id="run-2", prompt="hi")

        with patch("app.agents.run_logging.logger") as mock_logger:
            mock_logger.bind.return_value = mock_logger
            with self.assertRaises(RuntimeError):
                await run_agent_backend_with_logging(_Backend(), request, lambda _: asyncio.sleep(0))

        error_messages = [str(call.args[0]) for call in mock_logger.exception.call_args_list]
        self.assertIn("agent run error", error_messages)

    async def test_writes_session_trace_file(self):
        events: list[AgentEvent] = []

        async def sink(event: AgentEvent) -> None:
            events.append(event)

        class _Backend:
            name = "fake"

            async def run(self, request: AgentRunRequest, on_event):
                await on_event(AgentEvent(
                    type="session_started",
                    payload={"provider_session_id": "trace-session-1", "provider": "fake"},
                    provider="fake",
                ))
                await on_event(AgentEvent(
                    type="result",
                    payload={
                        "success": True,
                        "result": "ok",
                        "finish_reason": "completed",
                        "provider": "fake",
                    },
                    provider="fake",
                ))
                return AgentRunResult(
                    run_id=request.run_id,
                    session_id="trace-session-1",
                    success=True,
                    result_text="ok",
                    finish_reason="completed",
                )

        request = AgentRunRequest(run_id="run-trace", prompt="hi")
        with patch("app.agents.run_logging.logger") as mock_logger:
            mock_logger.bind.return_value = mock_logger
            await run_agent_backend_with_logging(_Backend(), request, sink)

        files = [
            name
            for name in os.listdir(settings.AI_SESSION_LOG_DIR)
            if name.endswith(".log") and "trace-session-1" in name
        ]
        self.assertTrue(files, "session trace file was not created")
        self.assertTrue(any("fake_trace-session-1" in name for name in files))
        content = open(
            os.path.join(settings.AI_SESSION_LOG_DIR, files[0]),
            encoding="utf-8",
        ).read()
        self.assertIn("=== AGENT SESSION TRACE ===", content)
        self.assertIn("trace-session-1", content)
        self.assertIn("=== END SESSION TRACE ===", content)

    async def test_trace_file_waits_for_session_id_before_opening(self):
        events: list[AgentEvent] = []

        async def sink(event: AgentEvent) -> None:
            events.append(event)

        class _Backend:
            name = "fake"

            async def run(self, request: AgentRunRequest, on_event):
                await on_event(AgentEvent(
                    type="log",
                    payload={"message": "pre-session event"},
                    provider="fake",
                ))
                await on_event(AgentEvent(
                    type="session_started",
                    payload={"provider_session_id": "real-session-9", "provider": "fake"},
                    provider="fake",
                ))
                return AgentRunResult(
                    run_id=request.run_id,
                    session_id="real-session-9",
                    success=True,
                    result_text="ok",
                    finish_reason="completed",
                )

        request = AgentRunRequest(run_id="run-trace-wait", prompt="hi")
        with patch("app.agents.run_logging.logger") as mock_logger:
            mock_logger.bind.return_value = mock_logger
            await run_agent_backend_with_logging(_Backend(), request, sink)

        files = [
            name
            for name in os.listdir(settings.AI_SESSION_LOG_DIR)
            if name.endswith(".log") and "real-session-9" in name
        ]
        self.assertTrue(files, "trace file should wait for real session id")
        self.assertFalse(any("_new.log" in name for name in files))
        content = open(
            os.path.join(settings.AI_SESSION_LOG_DIR, files[0]),
            encoding="utf-8",
        ).read()
        self.assertIn("pre-session event", content)


if __name__ == "__main__":
    unittest.main()