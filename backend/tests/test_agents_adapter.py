"""Agent 适配层阶段 2 契约/事件/注册测试。"""

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "agent_events"

from app.agents import AgentEvent, AgentRunRequest
from app.agents.adapters.claude_code.event_mapper import map_claude_event
from app.agents.adapters.dsh.event_mapper import map_dsh_event
from app.agents.adapters.mock.mock_adapter import MockAdapter
from app.agents.adapters.opencode.event_mapper import map_opencode_event
from app.agents.registry import create_agent_backend


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


if __name__ == "__main__":
    unittest.main()