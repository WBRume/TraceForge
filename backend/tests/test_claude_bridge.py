import os
import sys
import tempfile
import unittest


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.engine.claude_bridge import SubprocessCliBridge


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


if __name__ == "__main__":
    unittest.main()
