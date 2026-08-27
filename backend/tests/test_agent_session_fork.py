"""会话 fork（baseline → 评审线程上下文复用）单元测试。"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.agents.adapters.claude_code import claude_code_adapter
from app.agents.adapters.dsh import session_files
from app.agents.adapters.dsh.dsh_adapter import DSHAdapter, dsh_sessions_root
from app.agents.errors import SessionForkError


class _EnvHomeMixin:
    """把 CLAUDE/DSH 的家目录隔离到临时目录，避免污染真实 ~/.claude / ~/.dsh。"""

    def setUp(self) -> None:
        self._home = tempfile.TemporaryDirectory(prefix="tf-fork-test-home-")
        self._old_claude = os.environ.get("CLAUDE_CONFIG_DIR")
        self._old_dsh = os.environ.get("DSH_HOME")
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(self._home.name, "claude")
        os.environ["DSH_HOME"] = os.path.join(self._home.name, "dsh")

    def tearDown(self) -> None:
        if self._old_claude is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self._old_claude
        if self._old_dsh is None:
            os.environ.pop("DSH_HOME", None)
        else:
            os.environ["DSH_HOME"] = self._old_dsh
        self._home.cleanup()


class ClaudeSessionForkTest(_EnvHomeMixin, unittest.IsolatedAsyncioTestCase):
    def _make_baseline_snapshot(self, baseline_dir: str, session_id: str, extra=False) -> None:
        store = claude_code_adapter._claude_project_store_dir(baseline_dir)
        os.makedirs(store, exist_ok=True)
        with open(os.path.join(store, f"{session_id}.jsonl"), "w", encoding="utf-8") as f:
            f.write('{"type":"user","message":"read the big doc"}\n')
        if extra:
            with open(os.path.join(store, "other-session.jsonl"), "w", encoding="utf-8") as f:
                f.write("{}\n")

    async def test_fork_copies_single_session_file_to_target_store(self):
        baseline_dir = os.path.join(self._home.name, "baseline")
        thread_dir = os.path.join(self._home.name, "thread")
        os.makedirs(baseline_dir, exist_ok=True)
        self._make_baseline_snapshot(baseline_dir, "sess-1", extra=True)

        adapter = claude_code_adapter.ClaudeCodeAdapter()
        new_id = await adapter.fork_session("sess-1", source_dir=baseline_dir, target_dir=thread_dir)

        self.assertEqual(new_id, "sess-1")
        target_store = claude_code_adapter._claude_project_store_dir(thread_dir)
        forked = os.path.join(target_store, "sess-1.jsonl")
        self.assertTrue(os.path.isfile(forked))
        # 只复制目标会话文件，不带走 project store 里的其他会话
        self.assertFalse(os.path.exists(os.path.join(target_store, "other-session.jsonl")))
        # 源快照保持只读原样
        source_store = claude_code_adapter._claude_project_store_dir(baseline_dir)
        self.assertTrue(os.path.isfile(os.path.join(source_store, "sess-1.jsonl")))

    async def test_fork_is_idempotent(self):
        baseline_dir = os.path.join(self._home.name, "baseline")
        thread_dir = os.path.join(self._home.name, "thread")
        os.makedirs(baseline_dir, exist_ok=True)
        self._make_baseline_snapshot(baseline_dir, "sess-1")
        adapter = claude_code_adapter.ClaudeCodeAdapter()
        await adapter.fork_session("sess-1", source_dir=baseline_dir, target_dir=thread_dir)
        again = await adapter.fork_session("sess-1", source_dir=baseline_dir, target_dir=thread_dir)
        self.assertEqual(again, "sess-1")

    async def test_fork_raises_when_snapshot_missing(self):
        adapter = claude_code_adapter.ClaudeCodeAdapter()
        with self.assertRaises(SessionForkError):
            await adapter.fork_session(
                "missing", source_dir=os.path.join(self._home.name, "b"), target_dir=os.path.join(self._home.name, "t")
            )


class DshSessionFilesTest(_EnvHomeMixin, unittest.TestCase):
    def _write_baseline_log(self, baseline_dir: str, session_id: str) -> str:
        log_path = session_files.session_log_path(
            dsh_sessions_root(), baseline_dir, session_id, ".jsonl"
        )
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        header = {
            "type": "session",
            "version": 0,
            "id": session_id,
            "createdAt": "2026-08-22T00:00:00.000Z",
            "cwd": os.path.abspath(baseline_dir),
            "delegationDepth": 0,
        }
        with open(log_path, "w", encoding="utf-8", newline="") as f:
            f.write(json.dumps(header) + "\n")
            f.write(json.dumps({"type": "user/message", "seq": 1}) + "\n")
            f.write(json.dumps({"type": "turn/end", "seq": 2, "data": {"reason": {"kind": "completed"}}}) + "\n")
        return log_path

    def test_path_encoding_matches_dsh_layout(self):
        # 复刻 format.ts：分隔符折叠为 -，不安全字符转 ~XXXX，两侧包裹 --
        self.assertEqual(session_files.project_key(r"G:\proj\x"), "--G-proj-x--")
        self.assertEqual(session_files.project_key("/home/u/项目"), "--home-u-~9879~76EE--")
        # encodeSegment 对 '.' 保留字面量，仅整段 "." / ".." 特判
        self.assertEqual(session_files.encode_segment("session-abc.1"), "session-abc.1")
        self.assertEqual(session_files.encode_segment(".."), "~002E~002E")
        self.assertEqual(session_files.encode_segment("a~b"), "a~007Eb")

    def test_fork_rewrites_header_and_lands_in_target_project_key(self):
        baseline_dir = os.path.join(self._home.name, "baseline")
        thread_dir = os.path.join(self._home.name, "thread")
        os.makedirs(baseline_dir, exist_ok=True)
        self._write_baseline_log(baseline_dir, "session-base")

        new_id = "session-fork-1"
        session_files.fork_session_log(
            dsh_sessions_root(),
            "session-base",
            new_session_id=new_id,
            target_cwd=thread_dir,
        )

        forked = session_files.session_log_path(dsh_sessions_root(), thread_dir, new_id, ".jsonl")
        self.assertTrue(os.path.isfile(forked))
        with open(forked, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        header = json.loads(lines[0])
        # 头部 id/cwd 已指向新会话与新目录（加载端一致性校验的前提）
        self.assertEqual(header["id"], new_id)
        self.assertEqual(header["cwd"], os.path.abspath(thread_dir))
        # 事件行原样保留
        self.assertEqual(json.loads(lines[2])["type"], "turn/end")

    def test_locate_rejects_duplicate_ids_across_projects(self):
        dir_a = os.path.join(self._home.name, "a")
        dir_b = os.path.join(self._home.name, "b")
        os.makedirs(dir_a, exist_ok=True)
        os.makedirs(dir_b, exist_ok=True)
        self._write_baseline_log(dir_a, "session-dup")
        self._write_baseline_log(dir_b, "session-dup")
        with self.assertRaises(SessionForkError):
            session_files.locate_session_log(dsh_sessions_root(), "session-dup")

    def test_discover_latest_session_finds_newest(self):
        baseline_dir = os.path.join(self._home.name, "baseline")
        os.makedirs(baseline_dir, exist_ok=True)
        self._write_baseline_log(baseline_dir, "session-old")
        found = session_files.discover_latest_session(dsh_sessions_root(), baseline_dir)
        self.assertIsNotNone(found)
        self.assertEqual(found[0], "session-old")


class DshAdapterForkTest(_EnvHomeMixin, unittest.IsolatedAsyncioTestCase):
    async def test_fork_session_returns_new_id_under_target_cwd(self):
        baseline_dir = os.path.join(self._home.name, "baseline")
        thread_dir = os.path.join(self._home.name, "thread")
        os.makedirs(baseline_dir, exist_ok=True)
        log_path = session_files.session_log_path(
            dsh_sessions_root(), baseline_dir, "session-base", ".jsonl"
        )
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w", encoding="utf-8", newline="") as f:
            f.write(json.dumps({
                "type": "session", "version": 0, "id": "session-base",
                "createdAt": "2026-08-22T00:00:00.000Z",
                "cwd": os.path.abspath(baseline_dir), "delegationDepth": 0,
            }) + "\n")

        adapter = DSHAdapter()
        new_id = await adapter.fork_session(
            "session-base", source_dir=baseline_dir, target_dir=thread_dir
        )
        self.assertNotEqual(new_id, "session-base")
        forked = session_files.locate_session_log(dsh_sessions_root(), new_id)
        self.assertTrue(os.path.isfile(forked[0]))


class ClaudeBridgeForkFlagTest(unittest.IsolatedAsyncioTestCase):
    """bridge 层 --fork-session 参数构造与新 session id 捕获。"""

    async def test_start_session_appends_fork_flag_and_captures_new_sid(self):
        import asyncio as aio

        from app.engine.claude_bridge import SubprocessCliBridge

        ndjson = "\n".join([
            json.dumps({"type": "system", "subtype": "init", "session_id": "forked-new-1"}),
            json.dumps({
                "type": "result", "subtype": "success",
                "result": "ok", "session_id": "forked-new-1",
            }),
        ]).encode("utf-8") + b"\n"

        class FakeStdout:
            def __init__(self, data: bytes):
                self._data = data

            async def read(self, _n: int = -1) -> bytes:
                data, self._data = self._data, b""
                return data

        class FakeStderr(FakeStdout):
            async def read(self, _n: int = -1) -> bytes:
                return b""

        class FakeProcess:
            pid = 4242
            returncode = 0
            stdout = FakeStdout(ndjson)
            stderr = FakeStderr(b"")

            async def wait(self) -> int:
                return 0

        captured: dict = {}

        async def fake_exec(*args, **kwargs):
            captured["args"] = list(args)
            return FakeProcess()

        bridge = SubprocessCliBridge(cli_path="claude")
        with mock.patch.object(bridge, "_resolve_cli_base_args", return_value=["claude"]), \
             mock.patch("app.engine.claude_bridge.asyncio.create_subprocess_exec", fake_exec):
            events: list[dict] = []

            async def on_event(event: dict) -> None:
                events.append(event)

            returned = await bridge.start_session(
                prompt="hi",
                project_path=os.getcwd(),
                event_callback=on_event,
                session_id="baseline-sid",
                fork_session=True,
            )
            await bridge.wait()

        args = captured["args"]
        self.assertIn("--resume", args)
        self.assertEqual(args[args.index("--resume") + 1], "baseline-sid")
        self.assertIn("--fork-session", args)
        # 返回的是 resume 传入 id；真实新 id 由 system/init 事件更新
        self.assertEqual(returned, "baseline-sid")
        self.assertEqual(bridge.session_id, "forked-new-1")
        self.assertTrue(any(e.get("type") == "system" and e.get("subtype") == "init" for e in events))

    async def test_start_session_without_fork_omits_flag(self):
        from app.engine.claude_bridge import SubprocessCliBridge

        class FakeStdout:
            async def read(self, _n: int = -1) -> bytes:
                return b""

        class FakeProcess:
            pid = 1
            returncode = 0
            stdout = FakeStdout()
            stderr = FakeStdout()

            async def wait(self) -> int:
                return 0

        captured: dict = {}

        async def fake_exec(*args, **kwargs):
            captured["args"] = list(args)
            return FakeProcess()

        bridge = SubprocessCliBridge(cli_path="claude")
        with mock.patch.object(bridge, "_resolve_cli_base_args", return_value=["claude"]), \
             mock.patch("app.engine.claude_bridge.asyncio.create_subprocess_exec", fake_exec):
            async def on_event(event: dict) -> None:
                return None

            await bridge.start_session(
                prompt="hi",
                project_path=os.getcwd(),
                event_callback=on_event,
                session_id="sid-x",
                fork_session=False,
            )
            await bridge.wait()

        self.assertNotIn("--fork-session", captured["args"])


class OpenCodeForkTest(unittest.IsolatedAsyncioTestCase):
    async def test_fork_uses_v1_route_then_moves_session(self):
        from httpx import AsyncClient, MockTransport, Response
        from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter

        adapter = OpenCodeAdapter(server_url="http://mock:4097")
        calls: list[tuple[str, dict]] = []

        def handler(request) -> Response:
            body = json.loads(request.content or b"{}")
            calls.append((f"{request.method} {request.url.path}", body))
            path = request.url.path
            if path == "/session/base-1/fork":
                return Response(200, json={"id": "fork-9"})
            if path == "/experimental/control-plane/move-session":
                return Response(200, json={})
            return Response(404, json={})

        adapter._client = AsyncClient(transport=MockTransport(handler))

        new_id = await adapter.fork_session(
            "base-1", source_dir="C:/b", target_dir="C:/t"
        )
        self.assertEqual(new_id, "fork-9")
        paths = [c[0] for c in calls]
        self.assertIn("POST /session/base-1/fork", paths)
        self.assertIn("POST /experimental/control-plane/move-session", paths)
        move_body = next(body for path, body in calls if "move-session" in path)
        self.assertEqual(move_body["sessionID"], "fork-9")
        self.assertEqual(move_body["destination"]["directory"], os.path.abspath("C:/t"))
        await adapter._client.aclose()

    async def test_fork_same_source_and_target_skips_move(self):
        from httpx import AsyncClient, MockTransport, Response
        from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter

        adapter = OpenCodeAdapter(server_url="http://mock:4097")
        calls: list[str] = []

        def handler(request) -> Response:
            calls.append(f"{request.method} {request.url.path}")
            if request.url.path == "/session/base-1/fork":
                return Response(200, json={"id": "fork-same"})
            return Response(404, json={})

        adapter._client = AsyncClient(transport=MockTransport(handler))
        same_dir = os.path.abspath("C:/task")
        new_id = await adapter.fork_session(
            "base-1", source_dir=same_dir, target_dir=same_dir
        )
        self.assertEqual(new_id, "fork-same")
        self.assertEqual(calls, ["POST /session/base-1/fork"])
        await adapter._client.aclose()

    async def test_fork_falls_back_to_v2_routes(self):
        from httpx import AsyncClient, MockTransport, Response
        from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter

        adapter = OpenCodeAdapter(server_url="http://mock:4097")

        def handler(request) -> Response:
            path = request.url.path
            if path == "/api/session/base-1/fork":
                return Response(200, json={"data": {"id": "fork-v2"}})
            if path == "/api/session/fork-v2/move":
                return Response(200, json={"data": {}})
            return Response(404, json={})

        adapter._client = AsyncClient(transport=MockTransport(handler))
        new_id = await adapter.fork_session("base-1", source_dir="C:/b", target_dir="C:/t")
        self.assertEqual(new_id, "fork-v2")
        await adapter._client.aclose()

    async def test_fork_cleans_up_when_move_fails(self):
        from httpx import AsyncClient, MockTransport, Response
        from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter

        adapter = OpenCodeAdapter(server_url="http://mock:4097")
        deleted: list[str] = []

        def handler(request) -> Response:
            path = request.url.path
            if path == "/session/base-1/fork":
                return Response(200, json={"id": "fork-x"})
            if path.startswith("/session/fork-x") and request.method == "DELETE":
                deleted.append(path)
                return Response(204)
            return Response(404, json={})

        adapter._client = AsyncClient(transport=MockTransport(handler))
        with self.assertRaises(SessionForkError):
            await adapter.fork_session("base-1", source_dir="C:/b", target_dir="C:/t")
        self.assertEqual(deleted, ["/session/fork-x"])  # move 失败时清理 fork 产物
        await adapter._client.aclose()


class DshServerAdapterTest(unittest.IsolatedAsyncioTestCase):
    async def test_rpc_envelope_and_business_error(self):
        from httpx import AsyncClient, MockTransport, Response
        from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter
        from app.agents.errors import AgentError

        adapter = DshServerAdapter(server_url="http://mock:3097")
        seen: list[dict] = []

        def handler(request) -> Response:
            body = json.loads(request.content or b"{}")
            seen.append(body)
            if body.get("method") == "session.list":
                return Response(200, json={
                    "type": "server-response", "rpcId": body.get("rpcId"),
                    "result": {"ok": True, "value": {"items": []}},
                })
            return Response(200, json={
                "type": "server-response", "rpcId": body.get("rpcId"),
                "result": {"ok": False, "error": {"code": "boom", "message": "nope"}},
            })

        adapter._client = AsyncClient(transport=MockTransport(handler))
        value = await adapter._rpc("session.list", {})
        self.assertEqual(value, {"items": []})
        envelope = seen[0]
        self.assertEqual(envelope["type"], "client-request")
        self.assertEqual(envelope["method"], "session.list")
        self.assertIn("rpcId", envelope)
        with self.assertRaises(AgentError):
            await adapter._rpc("session.cancel", {"sessionId": "x"})
        await adapter._client.aclose()

    def test_event_mapper_extracts_text_and_usage(self):
        from app.agents.adapters.dsh.dsh_server_adapter import map_dsh_event

        event = map_dsh_event({
            "type": "assistant/message",
            "seq": 7,
            "data": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "BASELINE_READY"},
                    {"type": "reasoning", "text": "thinking..."},
                ],
                "usage": {"inputTokens": 10, "outputTokens": 5, "cacheReadTokens": 2},
            },
        })
        self.assertIsNotNone(event)
        self.assertEqual(event.type, "text")
        self.assertEqual(event.payload["text"], "BASELINE_READY")
        self.assertEqual(event.payload["usage"]["input_tokens"], 10)

        tool = map_dsh_event({"type": "tool/call", "data": {"name": "read_file", "arguments": {"path": "a.md"}}})
        self.assertEqual(tool.type, "tool_use")
        self.assertEqual(tool.payload["tool"], "read_file")

        text_delta = map_dsh_event({
            "type": "assistant/chunk",
            "data": {"chunk": {"type": "text-delta", "index": 1, "text": "hello"}},
        })
        self.assertEqual(text_delta.type, "text_delta")
        self.assertEqual(text_delta.payload["text"], "hello")

        thinking = map_dsh_event({
            "type": "assistant/chunk",
            "data": {"chunk": {"type": "reasoning-delta", "index": 0, "text": "checking"}},
        })
        self.assertEqual(thinking.type, "thinking")
        self.assertEqual(thinking.payload["text"], "checking")

        control = map_dsh_event({
            "type": "assistant/chunk",
            "data": {"chunk": {"type": "block-start", "index": 1, "blockType": "text"}},
        })
        self.assertIsNone(control)

    def test_server_mode_capabilities(self):
        from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter

        caps = DshServerAdapter().capabilities
        self.assertTrue(caps.supports_resume)
        self.assertTrue(caps.supports_tool_events)
        self.assertTrue(caps.supports_usage)
        self.assertTrue(caps.supports_fork)
        self.assertEqual(caps.preferred_mode, "server")

    async def test_read_only_event_stream_auto_rejects_dsh_approval(self):
        import app.agents.adapters.dsh.dsh_server_adapter as dsh_mod
        from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter

        frames = [
            json.dumps({
                "type": "server-request",
                "rpcId": "rpc-approval",
                "method": "approval/requested",
                "payload": {
                    "sessionId": "session-1",
                    "approvalId": "approval-1",
                    "toolName": "write_file",
                    "reason": "writes a file",
                },
            }),
            json.dumps({
                "type": "server-request",
                "rpcId": "rpc-turn",
                "method": "session/event",
                "payload": {
                    "sessionId": "session-1",
                    "event": {"type": "turn/end", "data": {"reason": {"kind": "completed"}}},
                },
            }),
        ]

        class _FakeWs:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            def __aiter__(self):
                async def _items():
                    for frame in frames:
                        yield frame
                return _items()

        adapter = DshServerAdapter(server_url="http://mock:3080")
        adapter._respond = mock.AsyncMock(return_value=None)
        with mock.patch.object(dsh_mod.websockets, "connect", return_value=_FakeWs()):
            result = await adapter._consume_events(
                "session-1",
                mock.AsyncMock(return_value=None),
                read_only=True,
            )

        self.assertEqual(result["finish_reason"], "completed")
        adapter._respond.assert_awaited_once_with(
            "rpc-approval",
            {
                "sessionId": "session-1",
                "approvalId": "approval-1",
                "outcome": "rejected",
            },
        )

    async def test_delta_only_stream_emits_final_text_fallback(self):
        import app.agents.adapters.dsh.dsh_server_adapter as dsh_mod
        from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter

        frames = [
            json.dumps({
                "type": "server-request",
                "rpcId": "rpc-delta-1",
                "method": "session/event",
                "payload": {
                    "sessionId": "session-1",
                    "event": {
                        "type": "assistant/chunk",
                        "data": {"chunk": {"type": "text-delta", "text": "Hel"}},
                    },
                },
            }),
            json.dumps({
                "type": "server-request",
                "rpcId": "rpc-delta-2",
                "method": "session/event",
                "payload": {
                    "sessionId": "session-1",
                    "event": {
                        "type": "assistant/chunk",
                        "data": {"chunk": {"type": "text-delta", "text": "lo"}},
                    },
                },
            }),
            json.dumps({
                "type": "server-request",
                "rpcId": "rpc-turn",
                "method": "session/event",
                "payload": {
                    "sessionId": "session-1",
                    "event": {"type": "turn/end", "data": {"reason": {"kind": "completed"}}},
                },
            }),
        ]

        class _FakeWs:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            def __aiter__(self):
                async def _items():
                    for frame in frames:
                        yield frame
                return _items()

        adapter = DshServerAdapter(server_url="http://mock:3080")
        seen: list[str] = []

        async def _on_event(event):
            seen.append(event.type)
            if event.type == "text":
                self.assertEqual(event.payload["text"], "Hello")

        with mock.patch.object(dsh_mod.websockets, "connect", return_value=_FakeWs()):
            result = await adapter._consume_events(
                "session-1",
                _on_event,
            )

        self.assertEqual(result["text"], "Hello")
        self.assertEqual(seen.count("text_delta"), 2)
        self.assertEqual(seen.count("text"), 1)

    async def test_dsh_approval_response_uses_host_wire_contract(self):
        from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter

        adapter = DshServerAdapter(server_url="http://mock:3080")
        adapter._pending_asks["rpc-1"] = {
            "kind": "approval/requested",
            "session_id": "session-1",
            "approval_id": "approval-1",
        }
        adapter._respond = mock.AsyncMock(return_value=None)

        await adapter.respond_to_ask_user("rpc-1", "reject")

        adapter._respond.assert_awaited_once_with(
            "rpc-1",
            {
                "sessionId": "session-1",
                "approvalId": "approval-1",
                "outcome": "rejected",
            },
        )


class SelectionForkTest(_EnvHomeMixin, unittest.IsolatedAsyncioTestCase):
    async def test_fork_dispatch_for_claude(self):
        from app.agents.selection import fork_session_for_backend

        baseline_dir = os.path.join(self._home.name, "baseline")
        thread_dir = os.path.join(self._home.name, "thread")
        os.makedirs(baseline_dir, exist_ok=True)
        store = claude_code_adapter._claude_project_store_dir(baseline_dir)
        os.makedirs(store, exist_ok=True)
        with open(os.path.join(store, "sess-9.jsonl"), "w", encoding="utf-8") as f:
            f.write("{}\n")

        new_id = await fork_session_for_backend(
            "claude-code", "sess-9", source_dir=baseline_dir, target_dir=thread_dir
        )
        self.assertEqual(new_id, "sess-9")

    async def test_probe_reports_unsupported_backend(self):
        from app.agents.selection import probe_session_fork

        ok = await probe_session_fork("mock", "s", source_dir="C:/nowhere")
        self.assertFalse(ok)


def test_selection_creates_opencode_backend():
    from app.agents.selection import create_agent_backend_by_name

    backend = create_agent_backend_by_name("opencode")
    assert backend.name == "opencode"


if __name__ == "__main__":
    unittest.main()
