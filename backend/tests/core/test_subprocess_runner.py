"""app.core.subprocess_runner：硬超时、进程组回收、git 防挂环境。"""

import sys
import unittest
from unittest import mock

from app.core.subprocess_runner import (
    GIT_REPOSITORY_ENV_VARS,
    ProcessTimeoutError,
    _git_safe_env,
    run_git,
    run_process,
)

PYTHON = sys.executable or "python"


class SubprocessRunnerTest(unittest.TestCase):
    def test_run_process_returns_output(self):
        result = run_process([PYTHON, "-c", "print('hello-runner')"], timeout_seconds=30)
        self.assertEqual(result.returncode, 0)
        self.assertIn("hello-runner", result.stdout)

    def test_run_process_timeout_raises_and_reaps_process(self):
        with self.assertRaises(ProcessTimeoutError) as ctx:
            run_process(
                [PYTHON, "-c", "import time; time.sleep(60)"],
                timeout_seconds=1,
            )
        self.assertLess(ctx.exception.timeout_seconds, 5)
        self.assertIn("import time", " ".join(ctx.exception.command))

    def test_run_git_injects_anti_hang_env(self):
        env = _git_safe_env()
        self.assertEqual(env.get("GIT_TERMINAL_PROMPT"), "0")
        self.assertEqual(env.get("GIT_ASKPASS"), "echo")
        self.assertEqual(env.get("SSH_ASKPASS"), "echo")
        self.assertEqual(env.get("GCM_INTERACTIVE"), "Never")
        # extra 覆盖生效
        merged = _git_safe_env({"GIT_INDEX_FILE": "idx"})
        self.assertEqual(merged.get("GIT_INDEX_FILE"), "idx")

    def test_private_git_environment_removal_is_opt_in_and_preserves_explicit_overrides(self):
        inherited = dict.fromkeys(GIT_REPOSITORY_ENV_VARS, "inherited-value")
        with mock.patch.dict("os.environ", inherited):
            self.assertEqual(_git_safe_env()["GIT_INDEX_FILE"], "inherited-value")
            isolated = _git_safe_env(unset=GIT_REPOSITORY_ENV_VARS)
            self.assertFalse(set(GIT_REPOSITORY_ENV_VARS) & isolated.keys())
            explicit = _git_safe_env({"GIT_INDEX_FILE": "explicit-index"}, unset=GIT_REPOSITORY_ENV_VARS)
            self.assertEqual(explicit["GIT_INDEX_FILE"], "explicit-index")

    def test_run_git_real_command(self):
        # 真实 git（若可用）：版本查询走完整链路（进程组 + env + 超时）
        try:
            result = run_git(["--version"], timeout_seconds=30)
        except FileNotFoundError:
            self.skipTest("git not installed")
        self.assertEqual(result.returncode, 0)
        self.assertIn("git", result.stdout)

    def test_run_git_timeout_raises(self):
        # 用 mock 冒充挂死的 git：run_git 直接以 args 调 run_process
        with mock.patch(
            "app.core.subprocess_runner.run_process",
            side_effect=lambda args, **kwargs: (_ for _ in ()).throw(
                ProcessTimeoutError("timed out", timeout_seconds=1, command=args)
            ),
        ):
            with self.assertRaises(ProcessTimeoutError):
                run_git(["clone", "https://example.invalid/repo.git"], timeout_seconds=1)


if __name__ == "__main__":
    unittest.main()
