"""Agent 适配层阶段 2 契约/事件/注册测试。"""

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "agent_events"

from app.agents import AgentEvent, AgentRunRequest
from app.agents.adapters.claude_code.event_mapper import map_claude_event
from app.agents.adapters.claude_code.claude_code_adapter import ClaudeCodeAdapter
from app.agents.adapters.dsh.event_mapper import map_dsh_event
from app.agents.adapters.mock.mock_adapter import MockAdapter
from app.agents.adapters.opencode.event_mapper import map_opencode_event
from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
from app.agents.registry import create_agent_backend
from app.agents.process_supervisor import TerminationResult
from app.config import settings


class MockAdapterTest(unittest.IsolatedAsyncioTestCase):
    async def test_mock_adapter_emits_unified_events_and_returns_result(self):
        adapter = MockAdapter()
        events: list[AgentEvent] = []

        async def sink(event: AgentEvent) -> None:
            events.append(event)

        result = await adapter.run(
            AgentRunRequest(run_id="run-1", prompt="hello", project_path=os.getcwd()),
            sink,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.finish_reason, "completed")
        self.assertEqual(result.run_id, "run-1")
        self.assertIn("mock", {e.provider for e in events})
        self.assertTrue(any(e.type == "session_started" for e in events))
        self.assertTrue(any(e.type == "text" for e in events))
        self.assertTrue(any(e.type == "tool_use" for e in events))
        self.assertTrue(any(e.type == "result" for e in events))

    async def test_mock_adapter_does_not_send_text_delta_without_capability(self):
        adapter = MockAdapter()
        events: list[AgentEvent] = []

        async def sink(event: AgentEvent) -> None:
            events.append(event)

        await adapter.run(AgentRunRequest(prompt="x", project_path=os.getcwd()), sink)

        self.assertFalse(any(e.type == "text_delta" for e in events))


class ClaudeStartupLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def _start_with_never_ready_callback(self, *, cancel_call=True):
        adapter = ClaudeCodeAdapter()
        bridge = MagicMock()
        bridge.cancel = AsyncMock(
            return_value=TerminationResult(confirmed_dead=True, root_return_code=None)
        )
        bridge.is_running.return_value = True
        adapter._bridge = bridge
        captured = {}
        active = [True]

        async def fake_run(_backend, request, _sink):
            captured["request"] = request
            await asyncio.sleep(60)

        async def on_started(_identity):
            return active[0]

        with patch("app.agents.run_logging.run_agent_backend_with_logging", new=fake_run), \
             patch.object(settings, "AGENT_STARTUP_TIMEOUT_SECONDS", 0.01), \
             patch.object(settings, "AGENT_TERMINATION_TIMEOUT_SECONDS", 0.01):
            with self.assertRaises(asyncio.TimeoutError):
                await adapter.start_session(
                    prompt="hello",
                    project_path=os.getcwd(),
                    event_callback=AsyncMock(),
                    on_process_started=on_started,
                )

        if cancel_call:
            bridge.cancel.assert_awaited_once()
        self.assertIsNone(adapter._legacy_run_task)
        return adapter, bridge, captured, active

    async def test_start_callback_timeout_cancels_bridge_and_legacy_task(self):
        await self._start_with_never_ready_callback()

    async def test_start_callback_cancellation_cleans_process_tree(self):
        adapter = ClaudeCodeAdapter()
        bridge = MagicMock()
        bridge.cancel = AsyncMock(
            return_value=TerminationResult(confirmed_dead=True, root_return_code=None)
        )
        bridge.is_running.return_value = True
        adapter._bridge = bridge

        async def fake_run(_backend, _request, _sink):
            await asyncio.sleep(60)

        with patch("app.agents.run_logging.run_agent_backend_with_logging", new=fake_run), \
             patch.object(settings, "AGENT_TERMINATION_TIMEOUT_SECONDS", 0.01):
            task = asyncio.create_task(
                adapter.start_session(
                    prompt="hello",
                    project_path=os.getcwd(),
                    event_callback=AsyncMock(),
                    on_process_started=lambda _identity: True,
                )
            )
            await asyncio.sleep(0.01)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        bridge.cancel.assert_awaited_once()
        self.assertIsNone(adapter._legacy_run_task)

    async def test_start_callback_late_success_cannot_revive_attempt(self):
        active = True
        adapter, _bridge, captured, active = await self._start_with_never_ready_callback()
        request = captured["request"]
        active[0] = False
        accepted = await request.on_process_started(object())
        self.assertFalse(accepted)
        self.assertIsNone(adapter._legacy_run_task)

    async def test_run_cli_single_turn_cleans_up_when_start_session_raises(self):
        from app.domains.ai.services import ai_job_service

        class FailingBridge:
            def __init__(self):
                self.cancelled = False
                self.last_termination = None

            async def start_session(self, **_kwargs):
                self.cancelled = False
                raise RuntimeError("startup failed")

            async def cancel(self):
                self.cancelled = True
                self.last_termination = TerminationResult(
                    confirmed_dead=True,
                    root_return_code=None,
                )
                return self.last_termination

            def is_running(self):
                return not self.cancelled

        bridge = FailingBridge()
        with patch.object(ai_job_service, "create_cli_bridge", return_value=bridge):
            with self.assertRaises(RuntimeError):
                await ai_job_service.run_cli_single_turn(
                    "hello",
                    os.getcwd(),
                    max_attempts=1,
                )
        self.assertTrue(bridge.cancelled)


class ClaudeEventMapperTest(unittest.TestCase):
    def test_maps_system_init_to_session_started(self):
        events = map_claude_event({"type": "system", "subtype": "init", "session_id": "s-1", "model": "claude-x"})
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, "session_started")
        self.assertEqual(events[0].payload["provider_session_id"], "s-1")

    def test_maps_assistant_blocks(self):
        events = map_claude_event({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "think..."},
                    {"type": "text", "text": "hello"},
                    {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"cmd": "ls"}},
                ]
            },
        })
        types = [e.type for e in events]
        self.assertIn("thinking", types)
        self.assertIn("text", types)
        self.assertIn("tool_use", types)

    def test_maps_result_with_usage(self):
        events = map_claude_event({
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "done",
            "session_id": "s-1",
            "duration_ms": 10,
            "total_cost_usd": 0.001,
            "usage": {"input_tokens": 1, "output_tokens": 2},
        })
        self.assertTrue(any(e.type == "result" for e in events))
        result_event = next(e for e in events if e.type == "result")
        self.assertEqual(result_event.payload["finish_reason"], "completed")
        self.assertEqual(result_event.payload["usage"]["input_tokens"], 1)

    def test_maps_error_result(self):
        events = map_claude_event({"type": "result", "is_error": True, "result": "boom"})
        self.assertTrue(any(e.type == "error" for e in events))


class ClaudeEventMapperFixtureTest(unittest.TestCase):
    """读取 golden fixtures，验证 Claude 原始事件到统一事件映射。"""

    def _load(self, name: str) -> dict:
        with (FIXTURES_DIR / name).open("r", encoding="utf-8") as fp:
            return json.load(fp)

    def test_system_init_fixture(self):
        events = map_claude_event(self._load("claude_system_init.json"))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, "session_started")
        self.assertEqual(events[0].payload["provider_session_id"], "fixture-session-1")
        self.assertEqual(events[0].payload["model"], "claude-fixture-model")

    def test_assistant_fixture(self):
        events = map_claude_event(self._load("claude_assistant.json"))
        types = [event.type for event in events]
        self.assertIn("thinking", types)
        self.assertIn("text", types)
        self.assertIn("tool_use", types)
        tool_event = next(event for event in events if event.type == "tool_use")
        self.assertEqual(tool_event.payload["tool_use_id"], "fixture-tool-1")
        self.assertEqual(tool_event.payload["tool_name"], "Bash")

    def test_result_fixture(self):
        events = map_claude_event(self._load("claude_result.json"))
        self.assertTrue(any(event.type == "result" for event in events))
        result_event = next(event for event in events if event.type == "result")
        self.assertEqual(result_event.payload["finish_reason"], "completed")
        self.assertEqual(result_event.payload["session_id"], "fixture-session-1")
        self.assertEqual(result_event.payload["usage"]["input_tokens"], 10)


class OpenCodeEventMapperTest(unittest.TestCase):
    def test_maps_text_and_step_result(self):
        events = map_opencode_event({
            "type": "session.next.text.ended",
            "data": {"sessionID": "ses-1", "text": "hello"},
        })
        self.assertTrue(any(e.type == "text" for e in events))
        self.assertEqual(next(e for e in events if e.type == "text").payload["text"], "hello")

        step_events = map_opencode_event({
            "type": "session.next.step.ended",
            "data": {
                "sessionID": "ses-1",
                "finish": "stop",
                "cost": 0,
                "tokens": {"input": 10, "output": 2, "reasoning": 0, "cache": {"read": 0, "write": 0}},
            },
        })
        self.assertTrue(any(e.type == "result" for e in step_events))
        result = next(e for e in step_events if e.type == "result")
        self.assertEqual(result.payload["finish_reason"], "completed")
        self.assertEqual(result.payload["usage"]["input_tokens"], 10)
        self.assertTrue(any(e.type == "usage" for e in step_events))

    def test_maps_tool_events(self):
        use_events = map_opencode_event({
            "type": "session.next.tool.called",
            "data": {"sessionID": "ses-1", "callID": "call-1", "tool": "read", "input": {"path": "."}},
        })
        self.assertTrue(any(e.type == "tool_use" for e in use_events))
        tool_use = next(e for e in use_events if e.type == "tool_use")
        self.assertEqual(tool_use.payload["tool_use_id"], "call-1")

        result_events = map_opencode_event({
            "type": "session.next.tool.success",
            "data": {
                "sessionID": "ses-1",
                "callID": "call-1",
                "structured": {"entries": [{"path": "a", "type": "file"}]},
                "content": [],
            },
        })
        self.assertTrue(any(e.type == "tool_result" for e in result_events))
        tool_result = next(e for e in result_events if e.type == "tool_result")
        self.assertIn("a", tool_result.payload["output"])

    def test_maps_permission_to_ask_user(self):
        events = map_opencode_event({
            "type": "permission.v2.asked",
            "data": {"id": "per-1", "sessionID": "ses-1", "action": "write", "resources": ["/tmp/x"]},
        })
        self.assertTrue(any(e.type == "ask_user" for e in events))
        ask = next(e for e in events if e.type == "ask_user")
        self.assertEqual(ask.payload["ask_user_id"], "per-1")
        self.assertTrue(ask.payload["permission_request"])

    def test_maps_step_failed_to_error(self):
        events = map_opencode_event({
            "type": "session.next.step.failed",
            "data": {
                "sessionID": "ses-1",
                "error": {"message": "boom"},
                "cost": 0,
                "tokens": {"input": 1, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}},
            },
        })
        self.assertTrue(any(e.type == "error" for e in events))
        error = next(e for e in events if e.type == "error")
        self.assertEqual(error.payload["finish_reason"], "error")
        self.assertIn("boom", error.payload["result"])


class OpenCodeUndoApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_undo_uses_provider_message_ids_and_verifies_listing(self):
        calls: list[tuple[str, str, dict | None]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, str(request.url), request.content and json.loads(request.content)))
            path = request.url.path
            if path.endswith("/api/session/s1/revert"):
                return httpx.Response(404)
            if path.endswith("/session/s1/revert"):
                return httpx.Response(204)
            if path.endswith("/api/session/s1/message/m-user"):
                return httpx.Response(405)
            if path.endswith("/session/s1/message/m-user"):
                return httpx.Response(204)
            if path.endswith("/api/session/s1/message"):
                return httpx.Response(404)
            if path.endswith("/session/s1/message"):
                return httpx.Response(200, json={"data": [{"info": {"id": "m-before"}}]})
            return httpx.Response(500)

        adapter = OpenCodeAdapter("http://provider")
        adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            self.assertTrue(await adapter.revert_message("s1", "m-user"))
            self.assertTrue(await adapter.delete_message("s1", "m-user"))
            messages = await adapter.list_messages("s1")
        finally:
            await adapter.close()

        self.assertEqual(messages[0]["info"]["id"], "m-before")
        self.assertEqual(calls[0][0:2], ("POST", "http://provider/api/session/s1/revert"))
        self.assertEqual(calls[1][0:2], ("POST", "http://provider/session/s1/revert"))
        self.assertEqual(calls[1][2], {"messageID": "m-user"})
        self.assertEqual(calls[3][0:2], ("DELETE", "http://provider/session/s1/message/m-user"))


class OpenCodeEventMapperFixtureTest(unittest.TestCase):
    def test_server_events_fixture(self):
        with (FIXTURES_DIR / "opencode_server_events.json").open("r", encoding="utf-8") as fp:
            raw_events = json.load(fp)
        mapped_types = set()
        for raw in raw_events:
            for event in map_opencode_event(raw):
                mapped_types.add(event.type)
        self.assertIn("tool_use", mapped_types)
        self.assertIn("tool_result", mapped_types)
        self.assertIn("text", mapped_types)
        self.assertIn("result", mapped_types)
        self.assertIn("ask_user", mapped_types)


class DSHEventMapperTest(unittest.TestCase):
    def test_maps_usage_tool_and_text(self):
        usage_events = map_dsh_event({
            "type": "assistant/chunk",
            "data": {"turn": 1, "step": 1, "chunk": {"type": "usage", "usage": {"inputTokens": 3, "outputTokens": 4}}},
        })
        self.assertTrue(any(e.type == "usage" for e in usage_events))
        usage = next(e for e in usage_events if e.type == "usage")
        self.assertEqual(usage.payload["input_tokens"], 3)

        tool_events = map_dsh_event({
            "type": "tool/call",
            "data": {"turn": 1, "step": 1, "callId": "call-1", "name": "read_file", "arguments": "{\"path\": \"a\"}"},
        })
        self.assertTrue(any(e.type == "tool_use" for e in tool_events))
        tool_use = next(e for e in tool_events if e.type == "tool_use")
        self.assertEqual(tool_use.payload["tool_input"], {"path": "a"})

        text_events = map_dsh_event({
            "type": "assistant/message",
            "data": {
                "message": {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
                "usage": {"inputTokens": 1, "outputTokens": 2},
            },
        })
        self.assertTrue(any(e.type == "text" for e in text_events))
        self.assertTrue(any(e.type == "usage" for e in text_events))

    def test_maps_turn_end_to_result(self):
        events = map_dsh_event({
            "type": "turn/end",
            "data": {"turn": 1, "reason": {"kind": "completed"}},
        })
        self.assertTrue(any(e.type == "result" for e in events))
        result = next(e for e in events if e.type == "result")
        self.assertEqual(result.payload["finish_reason"], "completed")


class DSHEventMapperFixtureTest(unittest.TestCase):
    def test_session_sample_jsonl(self):
        fixture = FIXTURES_DIR / "dsh_session_sample.jsonl"
        mapped_types = set()
        with fixture.open("r", encoding="utf-8") as fp:
            for line in fp:
                raw = json.loads(line)
                for event in map_dsh_event(raw):
                    mapped_types.add(event.type)
        self.assertIn("tool_use", mapped_types)
        self.assertIn("tool_result", mapped_types)
        self.assertIn("text", mapped_types)
        self.assertIn("usage", mapped_types)
        self.assertIn("result", mapped_types)


class OpenCodeAdapterRunTest(unittest.IsolatedAsyncioTestCase):
    """用 fake HTTP client 验证 OpenCode server 模式 run() 的流程。"""

    class _FakeResponse:
        def __init__(self, status_code: int, payload: dict):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

        @property
        def text(self):
            return str(self._payload)

    class _FakeStream:
        def __init__(self, lines: list[str]):
            self.lines = lines
            self.status_code = 200
            self.text = ""

        def aiter_lines(self):
            async def _gen():
                for line in self.lines:
                    yield line
            return _gen()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

    class _FakeClient:
        def __init__(self):
            self.aclose = AsyncMock(return_value=None)

        async def post(self, url: str, json: dict | None = None, **kwargs):
            if url.endswith("/api/session"):
                return OpenCodeAdapterRunTest._FakeResponse(200, {"data": {"id": "ses_test"}})
            return OpenCodeAdapterRunTest._FakeResponse(200, {"data": {"id": "msg_test"}})

        async def get(self, url: str, params: dict | None = None, **kwargs):
            if url.endswith("/message"):
                return OpenCodeAdapterRunTest._FakeResponse(200, {"data": [{
                    "type": "assistant",
                    "content": [{"type": "text", "text": "ok"}],
                    "finish": "stop",
                    "cost": 0,
                    "tokens": {"input": 1, "output": 1, "reasoning": 0, "cache": {"read": 0, "write": 0}},
                }]})
            return OpenCodeAdapterRunTest._FakeResponse(200, {})

        def stream(self, method: str, url: str, **kwargs):
            return OpenCodeAdapterRunTest._FakeStream([
                'data: {"id":"e1","type":"session.next.text.ended","data":{"sessionID":"ses_test","text":"ok"}}',
                'data: {"id":"e2","type":"session.next.step.ended","data":{"sessionID":"ses_test","finish":"stop","cost":0,"tokens":{"input":1,"output":1,"reasoning":0,"cache":{"read":0,"write":0}}}}',
            ])

    async def test_run_creates_session_streams_events_and_returns_result(self):
        import app.agents.adapters.opencode.opencode_adapter as opencode_mod
        from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter

        events: list[AgentEvent] = []
        fake_client = self._FakeClient()

        async def sink(event: AgentEvent) -> None:
            events.append(event)

        adapter = OpenCodeAdapter(server_url="http://127.0.0.1:9999")
        with patch.object(opencode_mod.OpenCodeAdapter, "_ensure_client", new=AsyncMock(return_value=fake_client)):
            result = await adapter.run(
                AgentRunRequest(
                    run_id="oc-run-1",
                    prompt="hi",
                    project_path=r"D:\project\TraceForge",
                ),
                sink,
            )
            await adapter.close()

        self.assertTrue(result.success)
        self.assertEqual(result.finish_reason, "completed")
        self.assertEqual(result.result_text, "ok")
        self.assertEqual(result.session_id, "ses_test")
        self.assertIsNotNone(result.usage)
        types = [e.type for e in events]
        self.assertIn("session_started", types)
        self.assertIn("text", types)
        self.assertEqual(types.count("result"), 1)


class OpenCodeAdapterFallbackTest(unittest.IsolatedAsyncioTestCase):
    """验证 SSE 缺失时从最终 message 补齐 thinking/tool/usage。"""

    class _FakeClient:
        def __init__(self):
            self.aclose = AsyncMock(return_value=None)

        async def post(self, url: str, json: dict | None = None, **kwargs):
            if url.endswith("/api/session"):
                return OpenCodeAdapterRunTest._FakeResponse(200, {"data": {"id": "ses_test"}})
            return OpenCodeAdapterRunTest._FakeResponse(200, {"data": {"id": "msg_test"}})

        async def get(self, url: str, params: dict | None = None, **kwargs):
            if url.endswith("/message"):
                return OpenCodeAdapterRunTest._FakeResponse(200, {"data": [{
                    "type": "assistant",
                    "content": [
                        {"type": "text", "text": "done"},
                        {"type": "reasoning", "text": "thinking here"},
                        {"type": "tool", "id": "call-1", "name": "read", "state": {
                            "status": "completed",
                            "input": {"path": "a"},
                            "structured": {"entries": [{"path": "a"}]},
                            "content": [{"type": "text", "text": "file content"}],
                        }},
                    ],
                    "finish": "stop",
                    "cost": 0,
                    "tokens": {"input": 10, "output": 2, "reasoning": 3, "cache": {"read": 0, "write": 0}},
                }]})
            return OpenCodeAdapterRunTest._FakeResponse(200, {})

        def stream(self, method: str, url: str, **kwargs):
            # 只回放终态 step.ended，不提供 reasoning/tool SSE，验证 fallback
            return OpenCodeAdapterRunTest._FakeStream([
                'data: {"id":"e2","type":"session.next.step.ended","data":{"sessionID":"ses_test","finish":"stop","cost":0,"tokens":{"input":10,"output":2,"reasoning":3,"cache":{"read":0,"write":0}}}}',
            ])

    async def test_run_falls_back_to_final_message_for_missing_events(self):
        import app.agents.adapters.opencode.opencode_adapter as opencode_mod
        from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter

        events: list[AgentEvent] = []
        fake_client = self._FakeClient()

        async def sink(event: AgentEvent) -> None:
            events.append(event)

        adapter = OpenCodeAdapter(server_url="http://127.0.0.1:9999")
        with patch.object(opencode_mod.OpenCodeAdapter, "_ensure_client", new=AsyncMock(return_value=fake_client)):
            result = await adapter.run(
                AgentRunRequest(
                    run_id="oc-fallback",
                    prompt="hi",
                    project_path=r"D:\project\TraceForge",
                ),
                sink,
            )
            await adapter.close()

        types = [e.type for e in events]
        self.assertIn("thinking", types)
        self.assertIn("tool_use", types)
        self.assertIn("tool_result", types)
        self.assertIn("usage", types)
        self.assertEqual(result.result_text, "done")
        thinking = next(e for e in events if e.type == "thinking")
        self.assertEqual(thinking.payload["text"], "thinking here")
        tool_result = next(e for e in events if e.type == "tool_result")
        self.assertIn("file content", tool_result.payload["output"])
        usage = next(e for e in events if e.type == "usage")
        self.assertEqual(usage.payload["input_tokens"], 10)


class OpenCodeAdapterInterruptAbortTest(unittest.IsolatedAsyncioTestCase):
    """OpenCode Server 没有 /interrupt，interrupt/cancel 必须走 /abort。"""

    class _FakeClient:
        def __init__(self):
            self.posted: list[str] = []

        async def post(self, url: str, **kwargs):
            if not url.endswith("/abort"):
                raise AssertionError(f"interrupt/cancel must use /abort, got: {url}")
            self.posted.append(url)
            return OpenCodeAdapterRunTest._FakeResponse(200, {})

    async def _make_adapter(self, client):
        from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter

        adapter = OpenCodeAdapter("http://127.0.0.1:9999")
        adapter._client = client
        adapter._session_id = "ses_test"
        return adapter

    async def test_interrupt_uses_abort_endpoint_not_interrupt(self):
        client = self._FakeClient()
        adapter = await self._make_adapter(client)

        await adapter.interrupt()

        self.assertEqual(client.posted, ["http://127.0.0.1:9999/session/ses_test/abort"])
        self.assertTrue(adapter._interrupted)

    async def test_interrupt_explicit_session_uses_abort_endpoint(self):
        client = self._FakeClient()
        adapter = await self._make_adapter(client)

        await adapter.interrupt(session_id="other-ses")

        self.assertEqual(client.posted, ["http://127.0.0.1:9999/session/other-ses/abort"])
        self.assertTrue(adapter._interrupted)

    async def test_cancel_uses_abort_endpoint(self):
        client = self._FakeClient()
        adapter = await self._make_adapter(client)

        await adapter.cancel()

        self.assertEqual(client.posted, ["http://127.0.0.1:9999/session/ses_test/abort"])
        self.assertFalse(adapter.is_running())


class RegistryTest(unittest.TestCase):
    def test_create_mock_backend(self):
        backend = create_agent_backend("mock")
        self.assertEqual(backend.name, "mock")

    def test_create_opencode_and_dsh_backends(self):
        opencode = create_agent_backend("opencode")
        dsh = create_agent_backend("dsh")
        self.assertEqual(opencode.name, "opencode")
        self.assertEqual(dsh.name, "dsh")
        self.assertEqual(opencode.capabilities.preferred_mode, "server")
        self.assertEqual(dsh.capabilities.preferred_mode, "server")


class PersistedSessionStopContractTest(unittest.IsolatedAsyncioTestCase):
    """durable remote stop 契约（doc 修复方案 §9.3）。

    reaper 每次新建 adapter（内存 session 为空），持久化 session id 必须
    通过显式参数到达 provider stop API；测试 fake 的方法签名与正式
    contract 一致，不用宽松 **kwargs 掩盖签名错误。
    """

    async def test_dsh_persisted_cancel_uses_explicit_session(self):
        from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter

        adapter = DshServerAdapter()
        rpc = AsyncMock()
        with patch.object(adapter, "_rpc", rpc):
            result = await adapter.cancel_persisted_session("persisted-session-1")

        self.assertTrue(result.stop_acknowledged)
        rpc.assert_awaited_once_with(
            "session.cancel", {"sessionId": "persisted-session-1"}
        )

    async def test_dsh_persisted_cancel_requires_explicit_session_id(self):
        from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter

        adapter = DshServerAdapter()
        rpc = AsyncMock()
        with patch.object(adapter, "_rpc", rpc):
            result = await adapter.cancel_persisted_session("")

        self.assertFalse(result.stop_acknowledged)
        self.assertEqual(result.failure_code, "REMOTE_STOP_LOCATOR_MISSING")
        rpc.assert_not_awaited()

    async def test_dsh_persisted_cancel_rpc_failure_is_structured_nack(self):
        from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter

        adapter = DshServerAdapter()
        rpc = AsyncMock(side_effect=RuntimeError("rpc down"))
        with patch.object(adapter, "_rpc", rpc):
            result = await adapter.cancel_persisted_session("persisted-session-1")

        self.assertFalse(result.stop_acknowledged)
        self.assertEqual(result.failure_code, "DSH_CANCEL_RPC_FAILED")

    async def test_opencode_persisted_cancel_uses_explicit_session(self):
        from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
        from app.agents.contract import (
            EXECUTION_KIND_REMOTE_SESSION,
            AgentStopResult,
        )

        adapter = OpenCodeAdapter()
        abort = AsyncMock(
            return_value=AgentStopResult(
                execution_kind=EXECUTION_KIND_REMOTE_SESSION,
                stop_acknowledged=True,
            )
        )
        with patch.object(adapter, "_abort_session", abort):
            result = await adapter.cancel_persisted_session("persisted-session-1")

        abort.assert_awaited_once_with("persisted-session-1")
        self.assertTrue(result.stop_acknowledged)

    async def test_opencode_persisted_cancel_requires_explicit_session_id(self):
        from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter

        adapter = OpenCodeAdapter()
        abort = AsyncMock()
        with patch.object(adapter, "_abort_session", abort):
            result = await adapter.cancel_persisted_session("")

        self.assertFalse(result.stop_acknowledged)
        self.assertEqual(result.failure_code, "REMOTE_STOP_LOCATOR_MISSING")
        abort.assert_not_awaited()

    async def test_claude_code_persisted_cancel_is_capability_error(self):
        adapter = ClaudeCodeAdapter()

        result = await adapter.cancel_persisted_session("persisted-session-1")

        # 本地执行类别不应被远程 reaper 调用；调用时必须返回结构化
        # capability 错误而不是 ACK。
        self.assertFalse(result.stop_acknowledged)
        self.assertEqual(result.failure_code, "CAPABILITY_UNSUPPORTED")

    async def test_mock_persisted_cancel_records_explicit_session(self):
        adapter = MockAdapter()

        result = await adapter.cancel_persisted_session("persisted-session-1")

        self.assertTrue(result.stop_acknowledged)
        self.assertEqual(getattr(adapter, "_last_persisted_cancel", None), "persisted-session-1")

    async def test_reaper_stop_closes_backend_on_ack_nack_and_error(self):
        """_stop_remote_session 的 ACK/NACK/异常三条路径都必须 close adapter。"""
        from app.agents.contract import (
            EXECUTION_KIND_REMOTE_SESSION,
            AgentStopResult,
        )
        from app.domains.ai.services import ai_job_service

        class _CloseTrackingBackend:
            def __init__(self, *, acknowledged: bool, raise_error: bool = False):
                self.close_calls = 0
                self._acknowledged = acknowledged
                self._raise_error = raise_error

            async def cancel_persisted_session(self, session_id: str) -> AgentStopResult:
                if self._raise_error:
                    raise RuntimeError("remote stop failed")
                return AgentStopResult(
                    execution_kind=EXECUTION_KIND_REMOTE_SESSION,
                    stop_acknowledged=self._acknowledged,
                    failure_code=None if self._acknowledged else "REMOTE_STOP_UNCONFIRMED",
                )

            async def close(self) -> None:
                self.close_calls += 1

        row = {
            "reason": "REAP",
            "agent_backend": "dsh",
            "session_id": "persisted-session-1",
        }
        backend = _CloseTrackingBackend(acknowledged=True)
        with patch(
            "app.agents.selection.create_agent_backend_by_name",
            lambda name: backend,
        ):
            ack = await ai_job_service._stop_remote_session(dict(row))
            self.assertTrue(ack.stop_acknowledged)
            self.assertEqual(backend.close_calls, 1)

            backend = _CloseTrackingBackend(acknowledged=False)
            nack = await ai_job_service._stop_remote_session(dict(row))
            self.assertFalse(nack.stop_acknowledged)
            self.assertEqual(backend.close_calls, 1)

            backend = _CloseTrackingBackend(acknowledged=False, raise_error=True)
            error = await ai_job_service._stop_remote_session(dict(row))
            self.assertFalse(error.stop_acknowledged)
            self.assertEqual(error.failure_code, "REMOTE_CANCEL_FAILED")
            self.assertEqual(backend.close_calls, 1)


if __name__ == "__main__":
    unittest.main()
