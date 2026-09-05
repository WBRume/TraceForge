"""snapshot `_run_git` 超时映射与检查语义。"""

import os
import subprocess
import sys
import unittest
from unittest import mock

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.core.subprocess_runner import ProcessTimeoutError  # noqa: E402
from app.domains.task.services.task_session_snapshot_service import (  # noqa: E402
    TaskSessionSnapshotError,
    _run_git,
)


class SnapshotGitRunnerTest(unittest.TestCase):
    def test_timeout_maps_to_worktree_git_timeout(self):
        def _raise_timeout(args, **kwargs):
            raise ProcessTimeoutError(
                "Process timed out after 180s: git status",
                timeout_seconds=180,
                command=args,
            )

        with mock.patch("app.core.subprocess_runner.run_git", side_effect=_raise_timeout):
            with self.assertRaises(TaskSessionSnapshotError) as ctx:
                _run_git("G:/tmp/repo", ["status", "--porcelain"])
        self.assertEqual(ctx.exception.code, "WORKTREE_GIT_TIMEOUT")

    def test_timeout_with_check_false_returns_failed_result(self):
        def _raise_timeout(args, **kwargs):
            raise ProcessTimeoutError("timed out", timeout_seconds=180, command=args)

        with mock.patch("app.core.subprocess_runner.run_git", side_effect=_raise_timeout):
            result = _run_git("G:/tmp/repo", ["status"], check=False)
        self.assertEqual(result.returncode, -1)
        self.assertIn("timed out", result.stderr)

    def test_nonzero_exit_raises_worktree_git_error(self):
        failed = subprocess.CompletedProcess(args=["git", "status"], returncode=128, stdout="", stderr="fatal: not a git repository")
        with mock.patch("app.core.subprocess_runner.run_git", return_value=failed):
            with self.assertRaises(TaskSessionSnapshotError) as ctx:
                _run_git("G:/tmp/repo", ["status"])
        self.assertEqual(ctx.exception.code, "WORKTREE_GIT_ERROR")

    def test_check_false_returns_nonzero_result(self):
        failed = subprocess.CompletedProcess(args=["git", "status"], returncode=128, stdout="", stderr="fatal: x")
        with mock.patch("app.core.subprocess_runner.run_git", return_value=failed):
            result = _run_git("G:/tmp/repo", ["status"], check=False)
        self.assertEqual(result.returncode, 128)


if __name__ == "__main__":
    unittest.main()
