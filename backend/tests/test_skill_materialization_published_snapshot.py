import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.skill.services import skill_service


def _run_git(args, cwd):
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed with code {result.returncode}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    return result


class SkillMaterializationSnapshotTest(unittest.TestCase):
    def test_copy_single_skill_package_uses_published_commit_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_dir = os.path.join(tmpdir, "skill_repo")
            os.makedirs(repo_dir, exist_ok=True)
            _run_git(["init"], cwd=repo_dir)
            _run_git(["config", "user.email", "tester@example.com"], cwd=repo_dir)
            _run_git(["config", "user.name", "tester"], cwd=repo_dir)

            source_file = os.path.join(repo_dir, "SKILL.md")
            with open(source_file, "w", encoding="utf-8") as file:
                file.write("published\n")
            _run_git(["add", "SKILL.md"], cwd=repo_dir)
            _run_git(["commit", "-m", "initial"], cwd=repo_dir)
            published_sha = _run_git(["rev-parse", "HEAD"], cwd=repo_dir).stdout.strip()

            # Draft changes remain in worktree and should not be copied.
            with open(source_file, "w", encoding="utf-8") as file:
                file.write("draft\n")

            target_dir = os.path.join(tmpdir, "materialized")
            fake_skill = SimpleNamespace(package_path="unused", head_commit_sha=published_sha)

            with mock.patch.object(skill_service, "_repo_path", return_value=repo_dir):
                skill_service._copy_single_skill_package(fake_skill, target_dir)

            copied_file = os.path.join(target_dir, "SKILL.md")
            with open(copied_file, "r", encoding="utf-8") as file:
                copied = file.read()

            self.assertEqual(copied, "published\n")


if __name__ == "__main__":
    unittest.main()
