"""统一 AgentBackend 底层 AI 会话日志测试。"""

import asyncio
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
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

    async def test_trace_records_prompt_and_skips_debug_logs(self):
        class _Backend:
            name = "fake"

            async def run(self, request: AgentRunRequest, on_event):
                await on_event(AgentEvent(
                    type="log",
                    payload={"level": "debug", "message": "noisy progress tick"},
                    provider="fake",
                ))
                await on_event(AgentEvent(
                    type="log",
                    payload={"level": "info", "message": "auditable provider event"},
                    provider="fake",
                ))
                await on_event(AgentEvent(
                    type="session_started",
                    payload={"provider_session_id": "prompt-session-1", "provider": "fake"},
                    provider="fake",
                ))
                await on_event(AgentEvent(
                    type="log",
                    payload={"level": "debug", "message": "post-session progress tick"},
                    provider="fake",
                ))
                return AgentRunResult(
                    run_id=request.run_id,
                    session_id="prompt-session-1",
                    success=True,
                    result_text="ok",
                    finish_reason="completed",
                )

        request = AgentRunRequest(run_id="run-prompt", prompt="请解释这个 bug")
        with patch("app.agents.run_logging.logger") as mock_logger:
            mock_logger.bind.return_value = mock_logger
            await run_agent_backend_with_logging(_Backend(), request, lambda _: asyncio.sleep(0))

        files = [
            name
            for name in os.listdir(settings.AI_SESSION_LOG_DIR)
            if name.endswith(".log") and "prompt-session-1" in name
        ]
        self.assertTrue(files, "session trace file was not created")
        content = open(
            os.path.join(settings.AI_SESSION_LOG_DIR, files[0]),
            encoding="utf-8",
        ).read()
        self.assertIn("请解释这个 bug", content)
        self.assertIn("prompt_length: 9", content)
        self.assertIn("auditable provider event", content)
        self.assertNotIn("noisy progress tick", content)
        self.assertNotIn("post-session progress tick", content)

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
        with open(
            os.path.join(settings.AI_SESSION_LOG_DIR, files[0]),
            encoding="utf-8",
        ) as f:
            content = f.read()
        self.assertIn("pre-session event", content)

    async def test_trace_and_logger_filter_out_streaming_text_and_thinking_events(self):
        sink_events: list[AgentEvent] = []

        async def sink(event: AgentEvent) -> None:
            sink_events.append(event)

        class _StreamingBackend:
            name = "opencode"

            async def run(self, request: AgentRunRequest, on_event):
                await on_event(AgentEvent(
                    type="session_started",
                    payload={"provider_session_id": "ses-filter-test", "model": "test-model"},
                    provider="opencode",
                ))
                # 模拟高频思考与流式增量事件
                await on_event(AgentEvent(
                    type="thinking",
                    payload={"text": "正在分析问题..."},
                    provider="opencode",
                ))
                await on_event(AgentEvent(
                    type="text_delta",
                    payload={"delta": "你好", "text": "你好"},
                    provider="opencode",
                ))
                await on_event(AgentEvent(
                    type="text_delta",
                    payload={"delta": "，世界", "text": "，世界"},
                    provider="opencode",
                ))
                await on_event(AgentEvent(
                    type="thinking",
                    payload={"text": "组织最终回答"},
                    provider="opencode",
                ))
                await on_event(AgentEvent(
                    type="text",
                    payload={"text": "你好，世界"},
                    provider="opencode",
                ))
                await on_event(AgentEvent(
                    type="result",
                    payload={"success": True, "result": "你好，世界", "finish_reason": "completed"},
                    provider="opencode",
                ))
                return AgentRunResult(
                    run_id=request.run_id,
                    session_id="ses-filter-test",
                    success=True,
                    result_text="你好，世界",
                    finish_reason="completed",
                )

        request = AgentRunRequest(run_id="run-streaming-filter", prompt="你好")
        with patch("app.agents.run_logging.logger") as mock_logger:
            mock_logger.bind.return_value = mock_logger
            result = await run_agent_backend_with_logging(_StreamingBackend(), request, sink)

        self.assertEqual(result.result_text, "你好，世界")
        # 验证前端/外部 sink 仍能正常接收流式打字与思考事件
        self.assertEqual([e.type for e in sink_events], [
            "session_started", "thinking", "text_delta", "text_delta", "thinking", "text", "result"
        ])

        # 验证 logger debug 中不应记录 agent text / agent thinking
        debug_messages = [str(call.args[0]) for call in mock_logger.debug.call_args_list if call.args]
        self.assertNotIn("agent text", debug_messages)
        self.assertNotIn("agent thinking", debug_messages)

        # 验证 trace 文件中不包含 [thinking], [text_delta], [text] 等无意义心跳/碎片
        files = [
            name
            for name in os.listdir(settings.AI_SESSION_LOG_DIR)
            if name.endswith(".log") and "ses-filter-test" in name
        ]
        self.assertTrue(files, "trace file should be created")
        with open(os.path.join(settings.AI_SESSION_LOG_DIR, files[0]), encoding="utf-8") as f:
            content = f.read()

        self.assertIn("=== AGENT SESSION TRACE ===", content)
        self.assertIn("[session_started]", content)
        self.assertIn("[result]", content)
        self.assertIn("----- RESULT TEXT BEGIN -----", content)
        self.assertIn("你好，世界", content)
        self.assertIn("----- RESULT TEXT END -----", content)

        # 重点：必须过滤掉 [thinking], [text_delta], [text] 及 text_length=
        self.assertNotIn("[thinking]", content)
        self.assertNotIn("[text_delta]", content)
        self.assertNotIn("[text]", content)
        self.assertNotIn("text_length=", content)


if __name__ == "__main__":
    unittest.main()