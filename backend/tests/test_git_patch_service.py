import os
import subprocess
import sys
import tempfile
from types import SimpleNamespace

import pytest


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.task.services import git_patch_service  # noqa: E402


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


def _seed_repo(repo_path: str):
    _run_git(["init"], cwd=repo_path)
    _run_git(["config", "user.email", "tester@example.com"], cwd=repo_path)
    _run_git(["config", "user.name", "tester"], cwd=repo_path)
    with open(os.path.join(repo_path, "README.md"), "w", encoding="utf-8") as handle:
        handle.write("hello\n")
    with open(os.path.join(repo_path, "delete_me.txt"), "w", encoding="utf-8") as handle:
        handle.write("remove\n")
    with open(os.path.join(repo_path, "old_name.txt"), "w", encoding="utf-8") as handle:
        handle.write("rename me\n")
    _run_git(["add", "-A"], cwd=repo_path)
    _run_git(["commit", "-m", "seed"], cwd=repo_path)
    _run_git(["branch", "-M", "main"], cwd=repo_path)


def _task(repo_path: str):
    return SimpleNamespace(id="task-1", project_path=repo_path, git_repo_url="https://example.com/repo.git")


def _workspace(repo_path: str):
    return SimpleNamespace(project_path=repo_path, git_repo_url="https://example.com/repo.git")


def test_generate_task_patch_snapshot_rejects_no_changes():
    with tempfile.TemporaryDirectory() as repo_path:
        _seed_repo(repo_path)
        with pytest.raises(git_patch_service.GitPatchError, match="No changes in task worktree"):
            git_patch_service.generate_task_patch_snapshot(_task(repo_path), _workspace(repo_path))


def test_generate_task_patch_snapshot_includes_worktree_changes_without_polluting_index(monkeypatch):
    git_calls = []
    original_run = git_patch_service.subprocess.run

    def _tracking_run(args, **kwargs):
        git_calls.append(list(args))
        return original_run(args, **kwargs)

    monkeypatch.setattr(git_patch_service.subprocess, "run", _tracking_run)

    with tempfile.TemporaryDirectory() as repo_path:
        _seed_repo(repo_path)
        with open(os.path.join(repo_path, "README.md"), "a", encoding="utf-8") as handle:
            handle.write("world\n")
        os.remove(os.path.join(repo_path, "delete_me.txt"))
        os.rename(os.path.join(repo_path, "old_name.txt"), os.path.join(repo_path, "new_name.txt"))
        with open(os.path.join(repo_path, "new_file.txt"), "w", encoding="utf-8") as handle:
            handle.write("new\n")
        with open(os.path.join(repo_path, "binary.bin"), "wb") as handle:
            handle.write(b"\x00\x01\x02")
        os.makedirs(os.path.join(repo_path, ".sdd"), exist_ok=True)
        with open(os.path.join(repo_path, ".sdd", "hidden.txt"), "w", encoding="utf-8") as handle:
            handle.write("must not leak\n")

        snapshot = git_patch_service.generate_task_patch_snapshot(_task(repo_path), _workspace(repo_path))

        changed_paths = {item.file_path for item in snapshot.files}
        assert "README.md" in changed_paths
        assert "delete_me.txt" in changed_paths
        assert "new_name.txt" in changed_paths
        assert "new_file.txt" in changed_paths
        assert "binary.bin" in changed_paths
        assert all(not path.startswith(".sdd/") for path in changed_paths)
        assert ".sdd/hidden.txt" not in snapshot.patch_text
        assert "new_file.txt" in snapshot.patch_text
        assert snapshot.changed_files_count == 5
        assert snapshot.insertions >= 2

        cached = _run_git(["diff", "--cached", "--name-only"], cwd=repo_path).stdout.strip()
        assert cached == ""
        assert all("push" not in call for call in git_calls)
