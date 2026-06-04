import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.task.services import git_worktree_service


def _run_git(args, cwd):
    result = subprocess.run(
        ["git", "-c", "protocol.file.allow=always", *args],
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


class GitWorktreeServiceTest(unittest.TestCase):
    def test_should_use_git_worktree(self):
        self.assertTrue(git_worktree_service.should_use_git_worktree("C:/tmp/repo", "https://example.com/repo.git"))
        self.assertFalse(git_worktree_service.should_use_git_worktree("", "https://example.com/repo.git"))
        self.assertFalse(git_worktree_service.should_use_git_worktree("C:/tmp/repo", ""))

    def test_task_branch_name(self):
        self.assertEqual(git_worktree_service.task_branch_name("abc"), "task/abc")
        with self.assertRaises(git_worktree_service.GitWorktreeError):
            git_worktree_service.task_branch_name("")

    def test_clone_workspace_repository_rejects_existing_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            existing_path = os.path.join(tmpdir, "exists")
            os.makedirs(existing_path, exist_ok=True)
            with self.assertRaises(git_worktree_service.GitWorktreeError):
                git_worktree_service.clone_workspace_repository(existing_path, "https://example.com/repo.git")

    def test_create_task_worktree_executes_expected_git_commands(self):
        repo_path = "C:/repo"
        task_path = "C:/repo/task-id"
        with mock.patch.object(git_worktree_service, "is_git_repository", return_value=True), \
            mock.patch.object(git_worktree_service, "ensure_workspace_repo_matches_remote"), \
            mock.patch.object(git_worktree_service, "_branch_exists", return_value=False), \
            mock.patch.object(git_worktree_service, "_remote_branch_exists", return_value=True), \
            mock.patch.object(git_worktree_service, "resolve_workspace_base_branch", return_value="main"), \
            mock.patch.object(git_worktree_service, "_run_git_checked") as run_checked, \
            mock.patch("os.path.exists", return_value=False), \
            mock.patch("os.makedirs"):
            branch = git_worktree_service.create_task_worktree(
                repo_path=repo_path,
                task_id="task-id",
                task_project_path=task_path,
                expected_git_repo_url="https://example.com/repo.git",
            )
            self.assertEqual(branch, "task/task-id")
            self.assertEqual(run_checked.call_count, 2)
            fetch_call = run_checked.call_args_list[0]
            add_call = run_checked.call_args_list[1]
            self.assertIn("fetch", fetch_call.args[0])
            self.assertIn("worktree", add_call.args[0])

    def test_archive_and_restore_workspace_repository(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = os.path.join(tmpdir, "workspace_repo")
            archive_root = os.path.join(tmpdir, "archive")

            os.makedirs(workspace_path, exist_ok=True)
            _run_git(["init"], cwd=workspace_path)
            _run_git(["config", "user.email", "tester@example.com"], cwd=workspace_path)
            _run_git(["config", "user.name", "tester"], cwd=workspace_path)
            with open(os.path.join(workspace_path, "README.md"), "w", encoding="utf-8") as handle:
                handle.write("seed\n")
            _run_git(["add", "README.md"], cwd=workspace_path)
            _run_git(["commit", "-m", "seed"], cwd=workspace_path)

            archived_path = git_worktree_service.archive_workspace_repository(
                workspace_id="ws-1",
                project_path=workspace_path,
                expected_git_repo_url=None,
                archive_root=archive_root,
            )
            self.assertFalse(os.path.exists(workspace_path))
            self.assertTrue(os.path.isdir(archived_path))
            self.assertTrue(os.path.isfile(os.path.join(archived_path, ".sdd_workspace_archive.json")))

            git_worktree_service.restore_archived_workspace(
                archive_path=archived_path,
                original_project_path=workspace_path,
            )
            self.assertTrue(os.path.isdir(workspace_path))


if __name__ == "__main__":
    unittest.main()
