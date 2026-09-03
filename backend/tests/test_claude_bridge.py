import json
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.engine.claude_bridge import SubprocessCliBridge, resolve_claude_permission_args


class ClaudeBridgePermissionArgsTest(unittest.TestCase):
    """read-only 不得再映射为 plan 模式（plan 模式会让总结任务重新调研并写 plan 文件）。"""

    def test_read_only_maps_to_default_with_denied_write_tools(self):
        args = resolve_claude_permission_args("read-only")
        self.assertIn("--permission-mode", args)
        self.assertEqual(args[args.index("--permission-mode") + 1], "default")
        self.assertNotIn("plan", args)
        self.assertIn("--disallowedTools", args)
        denied = args[args.index("--disallowedTools") + 1].split(",")
        for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "ExitPlanMode"):
            self.assertIn(tool, denied)
        # 保留读类工具，允许必要的上下文核对
        for allowed in ("Read", "Grep", "Glob"):
            self.assertNotIn(allowed, denied)

    def test_readonly_alias_matches_read_only(self):
        self.assertEqual(
            resolve_claude_permission_args("readonly"),
            resolve_claude_permission_args("read-only"),
        )
        self.assertEqual(
            resolve_claude_permission_args(" READ-ONLY "),
            resolve_claude_permission_args("read-only"),
        )

    def test_explicit_plan_keeps_plan_mode(self):
        self.assertEqual(
            resolve_claude_permission_args("plan"),
            ["--permission-mode", "plan"],
        )

    def test_default_and_unknown_keep_bypass_permissions(self):
        for mode in ("default", "", None, "anything"):
            self.assertEqual(
                resolve_claude_permission_args(mode),
                ["--permission-mode", "bypassPermissions"],
            )


class ClaudeBridgeCliResolutionTest(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows .cmd shim behavior")
    def test_windows_cmd_shim_resolves_to_claude_exe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bin_dir = os.path.join(tmpdir, "node_modules", "@anthropic-ai", "claude-code", "bin")
            os.makedirs(bin_dir, exist_ok=True)
            target = os.path.join(bin_dir, "claude.exe")
            with open(target, "wb") as fp:
                fp.write(b"")

            cmd_path = os.path.join(tmpdir, "claude.cmd")
            with open(cmd_path, "w", encoding="utf-8") as fp:
                fp.write(
                    "@ECHO off\n"
                    "SETLOCAL\n"
                    'CALL "%~dp0\\node_modules\\@anthropic-ai\\claude-code\\bin\\claude.exe"   %*\n'
                )

            args = SubprocessCliBridge(cli_path=cmd_path)._resolve_cli_base_args()

        self.assertEqual(args, [target])
        self.assertFalse(args[0].lower().endswith(".cmd"))


@unittest.skipUnless(os.name == "nt", "Windows process-tree cancellation")
class ClaudeBridgeProcessTreeTest(unittest.IsolatedAsyncioTestCase):
    async def test_force_stop_kills_tree_before_waiting_for_root_exit(self):
        bridge = SubprocessCliBridge(cli_path="claude")
        bridge.process = MagicMock(pid=12345, returncode=None)
        bridge._taskkill_tree = AsyncMock(return_value=None)
        bridge._wait_for_exit = AsyncMock(return_value=True)

        await bridge._force_stop_process(reason="timeout")

        bridge._taskkill_tree.assert_awaited_once()
        bridge.process.terminate.assert_not_called()


class _ChunkedStdout:
    """按固定大小输出字节块，模拟流式 stdout.read(4096) 的块边界。"""

    def __init__(self, payload: bytes, chunk_size: int):
        self._chunks = [payload[i:i + chunk_size] for i in range(0, len(payload), chunk_size)]

    async def read(self, _n: int) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


class ClaudeBridgeUtf8StreamDecodeTest(unittest.IsolatedAsyncioTestCase):
    """回归：流式块边界切断多字节 UTF-8 字符时不得产生 U+FFFD 乱码。

    复现场景：CLI 以 stream-json 输出 NDJSON，包含中文的 JSON 行被 read(4096)
    的块边界切碎。修复前逐块 decode("utf-8", errors="replace") 会把切碎的
    字节替换成 \\ufffd（如「回顾校验」→「回校验」）；修复后用增量解码器
    跨块保留未完成序列。
    """

    def _ndjson(self, *payloads):
        return b"".join(
            (json.dumps(p, ensure_ascii=False) + "\n").encode("utf-8") for p in payloads
        )

    async def _run_read_loop(self, payload: bytes, chunk_size: int):
        received = []
        bridge = SubprocessCliBridge(cli_path="claude")
        bridge._event_cb = received.append
        bridge.process = MagicMock()
        bridge.process.stdout = _ChunkedStdout(payload, chunk_size)
        await bridge._read_loop()
        return received

    async def test_no_replacement_chars_when_chinese_split_across_chunks(self):
        payload = self._ndjson(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "提交前对 popup.html 做格式回顾校验"}],
                },
            },
            {"type": "result", "subtype": "success", "result": "完成"},
        )
        # 4 字节块：必然把若干 3 字节中文字符切断，等价于 4096 边界命中多字节字符
        received = await self._run_read_loop(payload, chunk_size=4)

        joined = ""
        for event in received:
            if event.get("type") == "assistant":
                for block in event.get("message", {}).get("content", []):
                    joined += str(block.get("text") or "")
            elif event.get("type") == "result":
                joined += str(event.get("result") or "")

        self.assertNotIn("\ufffd", joined)
        self.assertIn("提交前对 popup.html 做格式回顾校验", joined)
        self.assertIn("完成", joined)

    async def test_ascii_only_stream_unchanged(self):
        payload = self._ndjson(
            {"type": "result", "subtype": "success", "result": "ok"},
        )
        received = await self._run_read_loop(payload, chunk_size=2)
        self.assertEqual(received, [{"type": "result", "subtype": "success", "result": "ok"}])

    async def test_emoji_split_across_chunks_still_decodes(self):
        # emoji 是 4 字节 UTF-8，用 7 字节块必然切断部分 emoji
        payload = self._ndjson(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "成功 🎉 完成"}]}},
        )
        received = await self._run_read_loop(payload, chunk_size=7)
        joined = ""
        for event in received:
            for block in event.get("message", {}).get("content", []):
                joined += str(block.get("text") or "")
        self.assertNotIn("\ufffd", joined)
        self.assertIn("成功 🎉 完成", joined)


if __name__ == "__main__":
    unittest.main()
