"""
Multi-repository worktree orchestration tests (mock-based, following
test_git_worktree_service.py conventions).
"""

import os
import sys
import unittest
from unittest import mock

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.task.services import git_worktree_service
from app.domains.task.services.git_worktree_service import RepoWorktreeBinding


def _binding(name="billing-core", slug="billing-core", branch="main", base="C:/ws/.repos/billing-core"):
    return RepoWorktreeBinding(
        repo_url="https://git.example.com/billing-core.git",
        repo_name=name,
        repo_slug=slug,
        branch_name=branch,
        base_dir=base,
    )


class MultiRepoWorktreeServiceTest(unittest.TestCase):
    def test_ensure_base_repository_clones_when_missing(self):
        with mock.patch.object(git_worktree_service, "is_git_repository", return_value=False),                 mock.patch.object(git_worktree_service, "_run_git_checked") as run_checked,                 mock.patch.object(git_worktree_service, "ensure_workspace_repo_matches_remote"),                 mock.patch.object(os.path, "exists", return_value=False),                 mock.patch("os.makedirs"):
            base = git_worktree_service.ensure_base_repository(
                "https://git.example.com/r.git", "C:/ws/.repos/r"
            )
            self.assertEqual(base, os.path.abspath("C:/ws/.repos/r"))
            clone_call = run_checked.call_args_list[0]
            self.assertIn("clone", clone_call.args[0])

    def test_ensure_base_repository_verifies_existing_repo(self):
        with mock.patch.object(git_worktree_service, "is_git_repository", return_value=True),                 mock.patch.object(git_worktree_service, "ensure_workspace_repo_matches_remote") as ensure_remote,                 mock.patch.object(os.path, "exists", return_value=True):
            base = git_worktree_service.ensure_base_repository(
                "https://git.example.com/r.git", "C:/ws/.repos/r"
            )
            self.assertEqual(base, os.path.abspath("C:/ws/.repos/r"))
            ensure_remote.assert_called_once()

    def test_create_task_worktrees_executes_per_repo(self):
        bindings = [_binding("billing-core", "billing-core"), _binding("customer-ext", "customer-ext")]
        with mock.patch.object(git_worktree_service, "is_git_repository", return_value=True),                 mock.patch.object(git_worktree_service, "ensure_workspace_repo_matches_remote"),                 mock.patch.object(git_worktree_service, "_branch_exists", return_value=False),                 mock.patch.object(git_worktree_service, "_remote_branch_exists", return_value=True),                 mock.patch.object(git_worktree_service, "_run_git_checked") as run_checked,                 mock.patch("os.path.exists", return_value=False),                 mock.patch("os.makedirs"):
            branches = git_worktree_service.create_task_worktrees(
                base_bindings=bindings,
                task_root="C:/ws/task-1",
                task_id="task-1",
            )
            self.assertEqual(branches, ["task/task-1", "task/task-1"])
            worktree_calls = [call for call in run_checked.call_args_list if "worktree" in call.args[0]]
            self.assertEqual(len(worktree_calls), 2)
            self.assertIn("billing-core", worktree_calls[0].args[0][-2])
            self.assertIn("customer-ext", worktree_calls[1].args[0][-2])

    def test_create_task_worktrees_rolls_back_on_failure(self):
        bindings = [_binding("a", "a"), _binding("b", "b")]
        with mock.patch.object(git_worktree_service, "is_git_repository", return_value=True),                 mock.patch.object(git_worktree_service, "ensure_workspace_repo_matches_remote"),                 mock.patch.object(git_worktree_service, "_branch_exists", return_value=False),                 mock.patch.object(git_worktree_service, "_remote_branch_exists", return_value=True),                 mock.patch.object(git_worktree_service, "_run_git_checked", side_effect=[
                    "fetch-ok", "worktree-ok", "fetch-ok", git_worktree_service.GitWorktreeError("branch missing", status_code=409),
                ]) as run_checked,                 mock.patch.object(git_worktree_service, "remove_single_repo_worktree") as remove_single,                 mock.patch("os.path.exists", return_value=False),                 mock.patch("os.makedirs"):
            with self.assertRaises(git_worktree_service.GitWorktreeError):
                git_worktree_service.create_task_worktrees(
                    base_bindings=bindings,
                    task_root="C:/ws/task-1",
                    task_id="task-1",
                )
            # The first repository worktree must be rolled back.
            remove_single.assert_called_once()
            self.assertEqual(remove_single.call_args.kwargs["binding"].repo_slug, "a")

    def test_remove_task_worktrees_removes_each(self):
        bindings = [_binding("a", "a"), _binding("b", "b")]
        with mock.patch.object(git_worktree_service, "remove_single_repo_worktree") as remove_single:
            git_worktree_service.remove_task_worktrees(
                base_bindings=bindings,
                task_root="C:/ws/task-1",
                task_id="task-1",
            )
            self.assertEqual(remove_single.call_count, 2)

    def test_branch_missing_on_origin_fails_with_repo_name(self):
        bindings = [_binding("a", "a", branch="release/v1")]
        with mock.patch.object(git_worktree_service, "is_git_repository", return_value=True),                 mock.patch.object(git_worktree_service, "ensure_workspace_repo_matches_remote"),                 mock.patch.object(git_worktree_service, "_branch_exists", return_value=False),                 mock.patch.object(git_worktree_service, "_remote_branch_exists", return_value=False),                 mock.patch.object(git_worktree_service, "_run_git_checked", return_value="fetch-ok"),                 mock.patch("os.path.exists", return_value=False),                 mock.patch("os.makedirs"):
            with self.assertRaises(git_worktree_service.GitWorktreeError) as ctx:
                git_worktree_service.create_task_worktrees(
                    base_bindings=bindings,
                    task_root="C:/ws/task-1",
                    task_id="task-1",
                )
            self.assertIn("a", str(ctx.exception))
            self.assertIn("release/v1", str(ctx.exception))
