"""
Generate git patch metadata from task worktrees without mutating the real index.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.config import settings
from app.domains.task.models.task import SddTask
from app.domains.auth.models.user import Workspace
from app.domains.task.services import git_worktree_service


class GitPatchError(ValueError):
    def __init__(self, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class PatchFileChange:
    file_path: str
    change_type: str
    old_path: Optional[str] = None
    new_path: Optional[str] = None
    insertions: int = 0
    deletions: int = 0
    diff_excerpt: str = ""
    is_binary: bool = False


@dataclass
class TaskPatchSnapshot:
    base_repo_url: Optional[str]
    base_branch: str
    base_commit_sha: str
    cloud_task_branch: str
    cloud_head_sha: Optional[str]
    patch_text: str
    changed_files_count: int
    insertions: int
    deletions: int
    files: List[PatchFileChange] = field(default_factory=list)


@dataclass
class RepoPatchSnapshot:
    """Patch snapshot of one repository inside a multi-repository task."""

    repository_id: Optional[str]
    repo_url: Optional[str]
    repo_name: str
    repo_slug: str
    base_branch: str
    base_commit_sha: str
    cloud_task_branch: str
    cloud_head_sha: Optional[str]
    patch_text: str
    changed_files_count: int
    insertions: int
    deletions: int
    files: List[PatchFileChange] = field(default_factory=list)


_EXCLUDED_PATHS = [":(exclude).sdd/**"]
_DIFF_PATHSPEC = ["--", ".", *_EXCLUDED_PATHS]
_GIT_TIMEOUT_SECONDS = 180


def _normalize_git_path(value: str) -> str:
    return str(value or "").replace("\\", "/").strip("/")


def _is_excluded_path(path: Optional[str]) -> bool:
    normalized = _normalize_git_path(path or "")
    return normalized == ".sdd" or normalized.startswith(".sdd/")


def _command_output(result: subprocess.CompletedProcess[str]) -> str:
    message = (result.stderr or "").strip() or (result.stdout or "").strip()
    return message or f"exit code {result.returncode}"


def _run_git(
    repo_path: str,
    args: List[str],
    *,
    env: Optional[Dict[str, str]] = None,
    check: bool = True,
) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=os.path.abspath(repo_path),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitPatchError("Git executable not found in PATH", status_code=500) from exc
    except subprocess.TimeoutExpired as exc:
        raise GitPatchError(f"Git command timed out: git {' '.join(args)}", status_code=409) from exc

    if check and result.returncode != 0:
        raise GitPatchError(f"Git command failed: git {' '.join(args)} | {_command_output(result)}")
    return (result.stdout or "").strip()


def _try_git(repo_path: str, args: List[str]) -> Optional[str]:
    try:
        value = _run_git(repo_path, args, check=True).strip()
    except GitPatchError:
        return None
    return value or None


def _assert_task_repo(task: SddTask) -> str:
    repo_path = os.path.abspath(str(task.project_path or "").strip())
    if not repo_path or not os.path.isdir(repo_path):
        raise GitPatchError("Task worktree path does not exist", status_code=409)
    inside = _try_git(repo_path, ["rev-parse", "--is-inside-work-tree"])
    if str(inside or "").lower() != "true":
        raise GitPatchError("Task worktree is not a git repository", status_code=409)
    return repo_path


def _resolve_base_branch(task_repo_path: str, workspace: Optional[Workspace]) -> str:
    workspace_repo = str((workspace.project_path if workspace else "") or "").strip()
    if workspace_repo and os.path.isdir(workspace_repo):
        try:
            return git_worktree_service.resolve_workspace_base_branch(workspace_repo)
        except Exception:
            pass
    branch = _try_git(task_repo_path, ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"])
    if branch and branch.startswith("origin/"):
        return branch.split("/", 1)[1] or "main"
    return "main"


def _resolve_base_commit(task_repo_path: str, base_branch: str) -> str:
    candidates = [
        ["merge-base", "HEAD", f"origin/{base_branch}"],
        ["rev-parse", f"origin/{base_branch}"],
        ["rev-parse", base_branch],
        ["rev-parse", "HEAD"],
    ]
    for args in candidates:
        value = _try_git(task_repo_path, args)
        if value:
            return value.splitlines()[0].strip()
    raise GitPatchError("Unable to resolve base commit for task worktree", status_code=409)


def _parse_name_status(output: str) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split("\t")
        status_token = parts[0]
        status = status_token[:1].upper()
        if status == "R" and len(parts) >= 3:
            old_path = _normalize_git_path(parts[1])
            new_path = _normalize_git_path(parts[2])
            if _is_excluded_path(old_path) or _is_excluded_path(new_path):
                continue
            entries.append({"status": "R", "old_path": old_path, "path": new_path})
            continue
        if len(parts) >= 2:
            path = _normalize_git_path(parts[1])
            if _is_excluded_path(path):
                continue
            entries.append({"status": status, "path": path})
    return entries


def _parse_numstat(output: str) -> List[Tuple[Optional[int], Optional[int], bool, str]]:
    entries: List[Tuple[Optional[int], Optional[int], bool, str]] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        add_raw, del_raw, path_raw = parts[0], parts[1], parts[2]
        path = _normalize_git_path(path_raw)
        if _is_excluded_path(path):
            continue
        is_binary = add_raw == "-" or del_raw == "-"
        additions = None if is_binary else int(add_raw or 0)
        deletions = None if is_binary else int(del_raw or 0)
        entries.append((additions, deletions, is_binary, path))
    return entries


def _change_type(status: str) -> str:
    normalized = (status or "M").upper()
    if normalized == "A":
        return "added"
    if normalized == "D":
        return "deleted"
    if normalized == "R":
        return "renamed"
    return "modified"


def _stats_by_path(
    status_entries: List[Dict[str, str]],
    numstat_entries: List[Tuple[Optional[int], Optional[int], bool, str]],
) -> Dict[str, Tuple[int, int, bool]]:
    mapping: Dict[str, Tuple[int, int, bool]] = {}
    for idx, item in enumerate(numstat_entries):
        additions, deletions, is_binary, path = item
        key = _normalize_git_path(path)
        if " => " in key:
            if idx < len(status_entries):
                key = _normalize_git_path(status_entries[idx].get("path") or key)
        mapping[key] = (int(additions or 0), int(deletions or 0), bool(is_binary))
    return mapping


def _truncate_excerpt(text: str) -> str:
    limit = max(1000, int(settings.TASK_CHANGE_DIFF_EXCERPT_CHARS or 12000))
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...<diff excerpt truncated>..."


def _diff_for_path(repo_path: str, env: Dict[str, str], entry: Dict[str, str]) -> str:
    status = str(entry.get("status") or "M").upper()
    path = _normalize_git_path(entry.get("path") or "")
    path_args = [path]
    if status == "D":
        path_args = [_normalize_git_path(entry.get("old_path") or path)]
    try:
        return _run_git(
            repo_path,
            ["diff", "--cached", "--find-renames", "--", *path_args],
            env=env,
            check=True,
        )
    except GitPatchError:
        return ""


def _build_temp_index(repo_path: str, base_commit_sha: str) -> Dict[str, str]:
    temp_dir = tempfile.mkdtemp(prefix="sdd-task-patch-")
    index_path = os.path.join(temp_dir, "index")
    env = dict(os.environ)
    env["GIT_INDEX_FILE"] = index_path
    env["_SDD_TEMP_INDEX_DIR"] = temp_dir
    _run_git(repo_path, ["read-tree", base_commit_sha], env=env)
    _run_git(repo_path, ["add", "-A", "--", ".", *_EXCLUDED_PATHS], env=env)
    return env


def _cleanup_temp_index(env: Dict[str, str]) -> None:
    temp_dir = str(env.get("_SDD_TEMP_INDEX_DIR") or "")
    if not temp_dir:
        return
    try:
        import shutil

        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        pass


def _generate_patch_snapshot_for_repo(
    repo_path: str,
    *,
    base_repo_url: Optional[str] = None,
    base_branch_hint: Optional[str] = None,
    workspace: Optional[Workspace] = None,
    task_id: Optional[str] = None,
) -> TaskPatchSnapshot:
    abs_repo_path = os.path.abspath(repo_path)
    if not abs_repo_path or not os.path.isdir(abs_repo_path):
        raise GitPatchError("Task worktree path does not exist", status_code=409)
    inside = _try_git(abs_repo_path, ["rev-parse", "--is-inside-work-tree"])
    if str(inside or "").lower() != "true":
        raise GitPatchError("Task worktree is not a git repository", status_code=409)

    base_branch = (str(base_branch_hint or "").strip()) or _resolve_base_branch(abs_repo_path, workspace)
    base_commit_sha = _resolve_base_commit(abs_repo_path, base_branch)
    cloud_head_sha = _try_git(abs_repo_path, ["rev-parse", "HEAD"])
    branch = _try_git(abs_repo_path, ["rev-parse", "--abbrev-ref", "HEAD"])
    cloud_task_branch = (
        branch
        if branch and branch != "HEAD"
        else git_worktree_service.task_branch_name(str(task_id or "").strip())
    )
    resolved_repo_url = (
        str((base_repo_url or "")).strip()
        or _try_git(abs_repo_path, ["config", "--get", "remote.origin.url"])
    )

    env = _build_temp_index(abs_repo_path, base_commit_sha)
    try:
        name_status = _run_git(abs_repo_path, ["diff", "--cached", "--name-status", "--find-renames", *_DIFF_PATHSPEC], env=env)
        status_entries = _parse_name_status(name_status)
        if not status_entries:
            raise GitPatchError("No changes in task worktree", status_code=409)

        numstat = _run_git(abs_repo_path, ["diff", "--cached", "--numstat", "--find-renames", *_DIFF_PATHSPEC], env=env)
        numstat_entries = _parse_numstat(numstat)
        stat_mapping = _stats_by_path(status_entries, numstat_entries)
        patch_text = _run_git(abs_repo_path, ["diff", "--cached", "--binary", "--find-renames", *_DIFF_PATHSPEC], env=env)
        if not patch_text.strip():
            raise GitPatchError("No changes in task worktree", status_code=409)

        files: List[PatchFileChange] = []
        total_insertions = 0
        total_deletions = 0
        for entry in status_entries:
            path = _normalize_git_path(entry.get("path") or "")
            additions, deletions, is_binary = stat_mapping.get(path, (0, 0, False))
            total_insertions += additions
            total_deletions += deletions
            files.append(
                PatchFileChange(
                    file_path=path,
                    old_path=_normalize_git_path(entry.get("old_path") or "") or None,
                    new_path=path if entry.get("status") == "R" else None,
                    change_type=_change_type(str(entry.get("status") or "M")),
                    insertions=additions,
                    deletions=deletions,
                    diff_excerpt=_truncate_excerpt(_diff_for_path(abs_repo_path, env, entry)),
                    is_binary=is_binary,
                )
            )

        return TaskPatchSnapshot(
            base_repo_url=resolved_repo_url or None,
            base_branch=base_branch,
            base_commit_sha=base_commit_sha,
            cloud_task_branch=cloud_task_branch,
            cloud_head_sha=cloud_head_sha,
            patch_text=patch_text,
            changed_files_count=len(files),
            insertions=total_insertions,
            deletions=total_deletions,
            files=files,
        )
    finally:
        _cleanup_temp_index(env)


def generate_task_patch_snapshot(
    task: SddTask,
    workspace: Optional[Workspace] = None,
) -> TaskPatchSnapshot:
    repo_path = _assert_task_repo(task)
    base_repo_url = (
        str((task.git_repo_url or "")).strip()
        or str(((workspace.git_repo_url if workspace else "") or "")).strip()
    )
    return _generate_patch_snapshot_for_repo(
        repo_path,
        base_repo_url=base_repo_url,
        workspace=workspace,
        task_id=task.id,
    )


def generate_task_repo_patch_snapshots(
    task: SddTask,
    workspace: Optional[Workspace] = None,
    db=None,
) -> List[RepoPatchSnapshot]:
    """Generate one patch snapshot per changed repository of a task.

    Repository bindings come from sdd_task_repositories (READY state).
    Unchanged repositories are skipped; if nothing changed anywhere, raise.
    Falls back to the legacy single-repository snapshot when the task has no
    repository bindings.
    """
    from app.domains.task.models.task_repository import TaskRepositoryState
    from app.domains.task.services import task_service

    bindings = []
    if db is not None:
        bindings = [
            binding
            for binding in task_service.get_task_repositories(db, task.id)
            if binding.state == TaskRepositoryState.READY
        ]

    if not bindings:
        legacy = generate_task_patch_snapshot(task, workspace)
        return [
            RepoPatchSnapshot(
                repository_id=None,
                repo_url=legacy.base_repo_url,
                repo_name="repository",
                repo_slug="repo",
                base_branch=legacy.base_branch,
                base_commit_sha=legacy.base_commit_sha,
                cloud_task_branch=legacy.cloud_task_branch,
                cloud_head_sha=legacy.cloud_head_sha,
                patch_text=legacy.patch_text,
                changed_files_count=legacy.changed_files_count,
                insertions=legacy.insertions,
                deletions=legacy.deletions,
                files=legacy.files,
            )
        ]

    task_root = os.path.abspath(str(task.project_path or "").strip())
    snapshots: List[RepoPatchSnapshot] = []
    for binding in bindings:
        repo_path = os.path.join(task_root, str(binding.rel_path or binding.repo_slug).strip())
        if not os.path.isdir(repo_path):
            continue
        try:
            inner = _generate_patch_snapshot_for_repo(
                repo_path,
                base_repo_url=binding.repo_url,
                base_branch_hint=binding.branch_name,
                task_id=task.id,
            )
        except GitPatchError as exc:
            if "No changes" in str(exc):
                continue
            raise
        snapshots.append(
            RepoPatchSnapshot(
                repository_id=binding.repository_id,
                repo_url=inner.base_repo_url or binding.repo_url,
                repo_name=binding.repo_name,
                repo_slug=binding.repo_slug,
                base_branch=inner.base_branch,
                base_commit_sha=inner.base_commit_sha,
                cloud_task_branch=inner.cloud_task_branch,
                cloud_head_sha=inner.cloud_head_sha,
                patch_text=inner.patch_text,
                changed_files_count=inner.changed_files_count,
                insertions=inner.insertions,
                deletions=inner.deletions,
                files=inner.files,
            )
        )

    if not snapshots:
        raise GitPatchError("No changes in any task repository", status_code=409)
    return snapshots
