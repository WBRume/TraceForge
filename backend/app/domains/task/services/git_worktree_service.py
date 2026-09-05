"""
Git worktree helpers for workspace/task lifecycle.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from typing import Optional

class GitWorktreeError(ValueError):
    def __init__(self, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


def should_use_git_worktree(project_path: Optional[str], git_repo_url: Optional[str]) -> bool:
    return bool(str(project_path or "").strip() and str(git_repo_url or "").strip())


def task_branch_name(task_id: str) -> str:
    normalized = str(task_id or "").strip()
    if not normalized:
        raise GitWorktreeError("task_id is required for worktree branch", status_code=400)
    return f"task/{normalized}"


def _default_archive_root() -> str:
    try:
        from app.config import settings  # Local import to avoid hard dependency during isolated tests.

        value = str(settings.WORKSPACE_ARCHIVE_ROOT or "").strip()
        if value:
            return value
    except Exception:
        pass
    return str(os.environ.get("WORKSPACE_ARCHIVE_ROOT") or "./workspace_archive").strip()


def _to_abs_path(path: str, *, label: str) -> str:
    normalized = str(path or "").strip()
    if not normalized:
        raise GitWorktreeError(f"{label} is required", status_code=400)
    return os.path.abspath(normalized)


def _assert_not_root_path(path: str, *, label: str) -> None:
    abs_path = os.path.abspath(path)
    if os.path.dirname(abs_path) == abs_path:
        raise GitWorktreeError(f"{label} cannot be a filesystem root path: {abs_path}", status_code=400)


def _normalize_remote_url(url: str) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    if value.endswith(".git"):
        value = value[:-4]
    return value.rstrip("/").lower()


def _run_git_raw(args: list[str], *, cwd: Optional[str] = None) -> subprocess.CompletedProcess[str]:
    from app.core.subprocess_runner import ProcessTimeoutError, run_git

    try:
        return run_git(list(args), cwd=cwd, timeout_seconds=180)
    except FileNotFoundError as exc:
        raise GitWorktreeError("Git executable not found in PATH", status_code=500) from exc
    except ProcessTimeoutError as exc:
        raise GitWorktreeError(f"Git command timed out: git {' '.join(args)}", status_code=409) from exc


def _command_output(result: subprocess.CompletedProcess[str]) -> str:
    message = (result.stderr or "").strip() or (result.stdout or "").strip()
    return message or f"exit code {result.returncode}"


def _run_git_checked(args: list[str], *, cwd: Optional[str] = None, status_code: int = 409) -> str:
    result = _run_git_raw(args, cwd=cwd)
    if result.returncode != 0:
        raise GitWorktreeError(
            f"Git command failed: git {' '.join(args)} | {_command_output(result)}",
            status_code=status_code,
        )
    return (result.stdout or "").strip()


def is_git_repository(repo_path: str) -> bool:
    try:
        abs_repo_path = _to_abs_path(repo_path, label="repo_path")
    except GitWorktreeError:
        return False
    if not os.path.isdir(abs_repo_path):
        return False
    result = _run_git_raw(["rev-parse", "--is-inside-work-tree"], cwd=abs_repo_path)
    return result.returncode == 0 and (result.stdout or "").strip().lower() == "true"


def get_origin_remote_url(repo_path: str) -> str:
    abs_repo_path = _to_abs_path(repo_path, label="repo_path")
    if not is_git_repository(abs_repo_path):
        raise GitWorktreeError(f"Not a git repository: {abs_repo_path}", status_code=400)
    remote = _run_git_checked(["config", "--get", "remote.origin.url"], cwd=abs_repo_path, status_code=409)
    if not remote:
        raise GitWorktreeError(f"remote.origin.url is missing in repository: {abs_repo_path}", status_code=409)
    return remote


def ensure_workspace_repo_matches_remote(repo_path: str, expected_git_repo_url: str) -> None:
    expected = _normalize_remote_url(expected_git_repo_url)
    if not expected:
        return
    actual = _normalize_remote_url(get_origin_remote_url(repo_path))
    if actual != expected:
        raise GitWorktreeError(
            "Workspace repository remote does not match configured git_repo_url",
            status_code=409,
        )


def clone_workspace_repository(project_path: str, git_repo_url: str) -> None:
    repo_path = _to_abs_path(project_path, label="project_path")
    repo_url = str(git_repo_url or "").strip()
    if not repo_url:
        raise GitWorktreeError("git_repo_url is required for git workspace", status_code=400)
    _assert_not_root_path(repo_path, label="project_path")

    if os.path.exists(repo_path):
        raise GitWorktreeError(
            f"project_path already exists, please provide a non-existing path: {repo_path}",
            status_code=400,
        )

    parent_dir = os.path.dirname(repo_path)
    if not parent_dir:
        raise GitWorktreeError("project_path parent directory is invalid", status_code=400)
    os.makedirs(parent_dir, exist_ok=True)

    try:
        _run_git_checked(["clone", repo_url, repo_path], status_code=400)
        ensure_workspace_repo_matches_remote(repo_path, repo_url)
    except Exception:
        if os.path.isdir(repo_path):
            shutil.rmtree(repo_path, ignore_errors=True)
        raise


def init_git_repository(project_path: str) -> None:
    """Initialize a git repository in the given directory if it is not already one."""
    repo_path = _to_abs_path(project_path, label="project_path")
    _assert_not_root_path(repo_path, label="project_path")

    if not os.path.isdir(repo_path):
        os.makedirs(repo_path, exist_ok=True)

    if is_git_repository(repo_path):
        return

    _run_git_checked(["init"], cwd=repo_path, status_code=500)

    if not is_git_repository(repo_path):
        raise GitWorktreeError(
            f"git init succeeded but verification failed for: {repo_path}",
            status_code=500,
        )


def resolve_workspace_base_branch(repo_path: str) -> str:
    abs_repo_path = _to_abs_path(repo_path, label="repo_path")
    result = _run_git_raw(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], cwd=abs_repo_path)
    if result.returncode == 0:
        ref = (result.stdout or "").strip()
        if ref.startswith("origin/") and len(ref) > len("origin/"):
            return ref.split("/", 1)[1]
    return "main"


def _branch_exists(repo_path: str, branch_name: str) -> bool:
    result = _run_git_raw(["show-ref", "--verify", f"refs/heads/{branch_name}"], cwd=repo_path)
    return result.returncode == 0


def _remote_branch_exists(repo_path: str, remote_branch_ref: str) -> bool:
    result = _run_git_raw(["show-ref", "--verify", f"refs/remotes/{remote_branch_ref}"], cwd=repo_path)
    return result.returncode == 0


def create_task_worktree(
    *,
    repo_path: str,
    task_id: str,
    task_project_path: str,
    expected_git_repo_url: Optional[str] = None,
) -> str:
    abs_repo_path = _to_abs_path(repo_path, label="repo_path")
    abs_task_path = _to_abs_path(task_project_path, label="task_project_path")
    _assert_not_root_path(abs_repo_path, label="repo_path")
    _assert_not_root_path(abs_task_path, label="task_project_path")

    if not is_git_repository(abs_repo_path):
        raise GitWorktreeError(f"Workspace project path is not a git repository: {abs_repo_path}", status_code=409)

    if expected_git_repo_url:
        ensure_workspace_repo_matches_remote(abs_repo_path, expected_git_repo_url)

    if os.path.exists(abs_task_path):
        raise GitWorktreeError(f"Task project path already exists: {abs_task_path}", status_code=409)

    os.makedirs(os.path.dirname(abs_task_path), exist_ok=True)

    _run_git_checked(["fetch", "--all", "--prune"], cwd=abs_repo_path, status_code=409)

    base_branch = resolve_workspace_base_branch(abs_repo_path)
    task_branch = task_branch_name(task_id)

    if _branch_exists(abs_repo_path, task_branch):
        raise GitWorktreeError(
            f"Task branch already exists: {task_branch}",
            status_code=409,
        )

    branch_source = f"origin/{base_branch}" if _remote_branch_exists(abs_repo_path, f"origin/{base_branch}") else base_branch
    _run_git_checked(
        ["worktree", "add", "-b", task_branch, abs_task_path, branch_source],
        cwd=abs_repo_path,
        status_code=409,
    )
    return task_branch


def _is_missing_branch_error(message: str) -> bool:
    text = str(message or "").lower()
    return "not found" in text or "did not match any file(s) known to git" in text


def _is_missing_worktree_error(message: str) -> bool:
    text = str(message or "").lower()
    return "does not exist" in text or "not a working tree" in text


def remove_task_worktree(
    *,
    repo_path: str,
    task_id: str,
    task_project_path: str,
    expected_git_repo_url: Optional[str] = None,
    missing_ok: bool = True,
) -> None:
    abs_repo_path = _to_abs_path(repo_path, label="repo_path")
    abs_task_path = _to_abs_path(task_project_path, label="task_project_path")

    if not os.path.isdir(abs_repo_path) or not is_git_repository(abs_repo_path):
        raise GitWorktreeError(f"Workspace repository is missing: {abs_repo_path}", status_code=409)

    if expected_git_repo_url:
        ensure_workspace_repo_matches_remote(abs_repo_path, expected_git_repo_url)

    if os.path.exists(abs_task_path):
        worktree_remove = _run_git_raw(["worktree", "remove", "--force", abs_task_path], cwd=abs_repo_path)
        if worktree_remove.returncode != 0:
            message = _command_output(worktree_remove)
            if not (missing_ok and _is_missing_worktree_error(message)):
                raise GitWorktreeError(
                    f"Failed to remove task worktree {abs_task_path}: {message}",
                    status_code=409,
                )
    elif not missing_ok:
        raise GitWorktreeError(f"Task worktree path does not exist: {abs_task_path}", status_code=409)

    branch = task_branch_name(task_id)
    branch_remove = _run_git_raw(["branch", "-D", branch], cwd=abs_repo_path)
    if branch_remove.returncode != 0:
        message = _command_output(branch_remove)
        if not (missing_ok and _is_missing_branch_error(message)):
            raise GitWorktreeError(
                f"Failed to delete task branch {branch}: {message}",
                status_code=409,
            )


def archive_workspace_repository(
    *,
    workspace_id: str,
    project_path: str,
    expected_git_repo_url: Optional[str] = None,
    archive_root: Optional[str] = None,
) -> str:
    workspace_key = str(workspace_id or "").strip()
    if not workspace_key:
        raise GitWorktreeError("workspace_id is required for archive", status_code=400)

    abs_project_path = _to_abs_path(project_path, label="project_path")
    _assert_not_root_path(abs_project_path, label="project_path")
    if not os.path.isdir(abs_project_path):
        raise GitWorktreeError(f"Workspace project path does not exist: {abs_project_path}", status_code=409)
    if not is_git_repository(abs_project_path):
        raise GitWorktreeError(f"Workspace project path is not a git repository: {abs_project_path}", status_code=409)

    if expected_git_repo_url:
        ensure_workspace_repo_matches_remote(abs_project_path, expected_git_repo_url)

    archive_root_path = _to_abs_path(
        str(archive_root or _default_archive_root()),
        label="archive_root",
    )
    _assert_not_root_path(archive_root_path, label="archive_root")

    try:
        common = os.path.commonpath([archive_root_path, abs_project_path])
    except ValueError:
        common = ""
    if common == abs_project_path:
        raise GitWorktreeError(
            "archive_root cannot be inside workspace project_path",
            status_code=400,
        )

    repo_name = os.path.basename(abs_project_path.rstrip("\\/")) or "repo"
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    archive_parent = os.path.join(archive_root_path, workspace_key)
    os.makedirs(archive_parent, exist_ok=True)

    base_target_name = f"{timestamp}_{repo_name}"
    target_path = os.path.join(archive_parent, base_target_name)
    sequence = 1
    while os.path.exists(target_path):
        target_path = os.path.join(archive_parent, f"{base_target_name}_{sequence}")
        sequence += 1

    moved = False
    try:
        shutil.move(abs_project_path, target_path)
        moved = True

        metadata_path = os.path.join(target_path, ".sdd_workspace_archive.json")
        metadata = {
            "workspace_id": workspace_key,
            "git_repo_url": str(expected_git_repo_url or "").strip() or None,
            "archived_at_utc": datetime.utcnow().isoformat() + "Z",
            "original_project_path": abs_project_path,
            "archive_path": os.path.abspath(target_path),
        }
        with open(metadata_path, "w", encoding="utf-8") as metadata_file:
            json.dump(metadata, metadata_file, ensure_ascii=True, indent=2)
    except Exception as exc:
        if moved and os.path.isdir(target_path) and not os.path.exists(abs_project_path):
            try:
                shutil.move(target_path, abs_project_path)
            except Exception as rollback_exc:
                raise GitWorktreeError(
                    "Failed to archive workspace repository and rollback failed. "
                    f"archive_path={target_path}",
                    status_code=500,
                ) from rollback_exc
        raise GitWorktreeError(f"Failed to archive workspace repository: {exc}", status_code=409) from exc

    return os.path.abspath(target_path)


def restore_archived_workspace(*, archive_path: str, original_project_path: str) -> None:
    abs_archive_path = _to_abs_path(archive_path, label="archive_path")
    abs_original_path = _to_abs_path(original_project_path, label="original_project_path")
    _assert_not_root_path(abs_archive_path, label="archive_path")
    _assert_not_root_path(abs_original_path, label="original_project_path")

    if not os.path.isdir(abs_archive_path):
        raise GitWorktreeError(f"Archived workspace path does not exist: {abs_archive_path}", status_code=500)
    if os.path.exists(abs_original_path):
        raise GitWorktreeError(
            f"Cannot rollback archive because original path already exists: {abs_original_path}",
            status_code=500,
        )

    os.makedirs(os.path.dirname(abs_original_path), exist_ok=True)
    shutil.move(abs_archive_path, abs_original_path)


# ──────────────────────────────────────────────────────────────────────────────
# Multi-repository workspace orchestration
# ──────────────────────────────────────────────────────────────────────────────

class RepoWorktreeBinding:
    """A single repository binding used to orchestrate task worktrees."""

    def __init__(
        self,
        *,
        repo_url: str,
        repo_name: str,
        repo_slug: str,
        branch_name: str,
        base_dir: str,
    ):
        self.repo_url = str(repo_url or "").strip()
        self.repo_name = str(repo_name or "").strip()
        self.repo_slug = str(repo_slug or "").strip()
        self.branch_name = str(branch_name or "").strip()
        self.base_dir = str(base_dir or "").strip()


def ensure_base_repository(repo_url: str, base_dir: str) -> str:
    """Clone a workspace base repository into base_dir if missing, or verify it."""
    repo_url = str(repo_url or "").strip()
    abs_base = _to_abs_path(base_dir, label="base_dir")
    if not repo_url:
        raise GitWorktreeError("repo_url is required for base repository", status_code=400)
    _assert_not_root_path(abs_base, label="base_dir")

    if is_git_repository(abs_base):
        ensure_workspace_repo_matches_remote(abs_base, repo_url)
        return abs_base

    if os.path.exists(abs_base):
        raise GitWorktreeError(
            f"Base repository path already exists and is not a git repository: {abs_base}",
            status_code=409,
        )

    parent_dir = os.path.dirname(abs_base)
    if not parent_dir:
        raise GitWorktreeError("base_dir parent directory is invalid", status_code=400)
    os.makedirs(parent_dir, exist_ok=True)

    try:
        _run_git_checked(["clone", repo_url, abs_base], status_code=400)
        ensure_workspace_repo_matches_remote(abs_base, repo_url)
    except Exception:
        if os.path.isdir(abs_base):
            shutil.rmtree(abs_base, ignore_errors=True)
        raise
    return abs_base


def _cleanup_stale_worktree_dir(path: str) -> None:
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


def remove_single_repo_worktree(
    *,
    binding: RepoWorktreeBinding,
    task_root: str,
    task_id: str,
    missing_ok: bool = True,
) -> None:
    """Remove one repository worktree (and its task branch) from a task root."""
    abs_repo = _to_abs_path(binding.base_dir, label="base_dir")
    abs_task = os.path.join(_to_abs_path(task_root, label="task_root"), binding.repo_slug)

    if not os.path.isdir(abs_repo) or not is_git_repository(abs_repo):
        if not missing_ok:
            raise GitWorktreeError(f"Workspace repository is missing: {abs_repo}", status_code=409)
        _cleanup_stale_worktree_dir(abs_task)
        return

    if os.path.exists(abs_task):
        worktree_remove = _run_git_raw(["worktree", "remove", "--force", abs_task], cwd=abs_repo)
        if worktree_remove.returncode != 0:
            message = _command_output(worktree_remove)
            if not (missing_ok and _is_missing_worktree_error(message)):
                raise GitWorktreeError(
                    f"Failed to remove task worktree {abs_task}: {message}",
                    status_code=409,
                )
        _cleanup_stale_worktree_dir(abs_task)
    elif not missing_ok:
        raise GitWorktreeError(f"Task worktree path does not exist: {abs_task}", status_code=409)

    branch = task_branch_name(task_id)
    branch_remove = _run_git_raw(["branch", "-D", branch], cwd=abs_repo)
    if branch_remove.returncode != 0:
        message = _command_output(branch_remove)
        if not (missing_ok and _is_missing_branch_error(message)):
            raise GitWorktreeError(
                f"Failed to delete task branch {branch} in {binding.repo_name}: {message}",
                status_code=409,
            )


def create_task_worktrees(
    *,
    base_bindings: list,
    task_root: str,
    task_id: str,
) -> list:
    """Create one worktree per repository binding; roll back all on failure.

    Branch name per repository: task/<task_id> (repositories are separate, so
    the same branch name does not collide).
    """
    normalized_bindings = [b for b in base_bindings if isinstance(b, RepoWorktreeBinding)]
    if not normalized_bindings:
        raise GitWorktreeError("At least one repository binding is required", status_code=400)

    abs_task_root = _to_abs_path(task_root, label="task_root")
    _assert_not_root_path(abs_task_root, label="task_root")
    task_branch = task_branch_name(task_id)

    created: list = []
    try:
        for binding in normalized_bindings:
            abs_repo = _to_abs_path(binding.base_dir, label="base_dir")
            abs_task = os.path.join(abs_task_root, binding.repo_slug)

            if not is_git_repository(abs_repo):
                raise GitWorktreeError(
                    f"Workspace repository '{binding.repo_name}' is not a git repository: {abs_repo}",
                    status_code=409,
                )
            if binding.repo_url:
                ensure_workspace_repo_matches_remote(abs_repo, binding.repo_url)
            if os.path.exists(abs_task):
                raise GitWorktreeError(
                    f"Task worktree path already exists for '{binding.repo_name}': {abs_task}",
                    status_code=409,
                )
            if _branch_exists(abs_repo, task_branch):
                raise GitWorktreeError(
                    f"Task branch already exists in '{binding.repo_name}': {task_branch}",
                    status_code=409,
                )

            _run_git_checked(["fetch", "--all", "--prune"], cwd=abs_repo, status_code=409)

            branch_name = binding.branch_name
            branch_source = f"origin/{branch_name}"
            if not _remote_branch_exists(abs_repo, f"origin/{branch_name}"):
                raise GitWorktreeError(
                    f"Branch '{branch_name}' does not exist on origin for repository '{binding.repo_name}'",
                    status_code=409,
                )

            os.makedirs(os.path.dirname(abs_task), exist_ok=True)
            _run_git_checked(
                ["worktree", "add", "-b", task_branch, abs_task, branch_source],
                cwd=abs_repo,
                status_code=409,
            )
            created.append(binding)
    except Exception:
        for binding in created:
            try:
                remove_single_repo_worktree(
                    binding=binding,
                    task_root=abs_task_root,
                    task_id=task_id,
                    missing_ok=True,
                )
            except Exception as rollback_exc:
                import logging

                logging.getLogger(__name__).warning(
                    f"Failed to rollback task worktree {binding.repo_name}: {rollback_exc}"
                )
        raise

    return [task_branch] * len(normalized_bindings)


def remove_task_worktrees(
    *,
    base_bindings: list,
    task_root: str,
    task_id: str,
    missing_ok: bool = True,
) -> None:
    """Remove every repository worktree of a task (best effort per binding)."""
    errors: list = []
    for binding in base_bindings:
        if not isinstance(binding, RepoWorktreeBinding):
            continue
        try:
            remove_single_repo_worktree(
                binding=binding,
                task_root=task_root,
                task_id=task_id,
                missing_ok=missing_ok,
            )
        except GitWorktreeError as exc:
            errors.append(str(exc))
    if errors and not missing_ok:
        raise GitWorktreeError(
            "Failed to remove some task worktrees: " + " | ".join(errors),
            status_code=409,
        )


def read_repo_head_sha(repo_path: str) -> Optional[str]:
    result = _run_git_raw(["rev-parse", "HEAD"], cwd=repo_path)
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip() or None

