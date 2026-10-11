"""Persist initial checkout metadata and inspect immutable task repository bindings."""

import ntpath
import posixpath
import re

from app.core.subprocess_runner import ProcessTimeoutError, run_git
from app.domains.local_resource.models import TaskExecutionBinding
from app.domains.task.schemas.task_inspection import GitCommitInfo, TaskRepositoryDetail
from app.domains.task.services.task_workspace.repositories import get_task_repositories

COMMIT_SNAPSHOTS_KEY = "repository_checkout_commits"
LEGACY_CHECKOUT_KEY = "legacy_repository_checkout"


def read_commit_info(repo_path: str | None, sha: str | None) -> dict | None:
    """Read only a recorded object ID; never substitute a moving branch or HEAD."""
    if not repo_path or not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", sha or ""):
        return None
    try:
        result = run_git(
            [
                "show",
                "--no-patch",
                "--no-show-signature",
                "--format=%H%x00%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI%x00%B",
                sha,
                "--",
            ],
            cwd=repo_path,
            timeout_seconds=5,
        )
    except (OSError, ProcessTimeoutError):
        return None
    if result.returncode != 0:
        return None
    fields = result.stdout.rstrip("\r\n").split("\0", 7)
    if len(fields) != 8 or fields[0].lower() != sha.lower():
        return None
    return GitCommitInfo(
        sha=fields[0],
        author_name=fields[1],
        author_email=fields[2],
        authored_at=fields[3],
        committer_name=fields[4],
        committer_email=fields[5],
        committed_at=fields[6],
        message=fields[7],
    ).model_dump()


def save_commit_snapshot(task, repo_id: str, commit: dict | None) -> None:
    if not commit:
        return
    metadata = dict(task.task_meta_json or {})
    snapshots = dict(metadata.get(COMMIT_SNAPSHOTS_KEY) or {})
    snapshots.setdefault(repo_id, commit)
    metadata[COMMIT_SNAPSHOTS_KEY] = snapshots
    task.task_meta_json = metadata


def _join_resource_path(root: str | None, relative: str) -> str | None:
    if not root:
        return None
    path_module = ntpath if ntpath.splitdrive(root)[0] or "\\" in root else posixpath
    return path_module.normpath(path_module.join(root, relative))


def _local_commit_details(db, binding, task) -> dict:
    from app.domains.local_resource.client import ResourceClient, ResourceError
    from app.domains.local_resource.service import runtime_profile

    try:
        result = ResourceClient(runtime_profile(db, binding), timeout=4).operation(task.id, "repository_details", {})
    except ResourceError:
        return {}
    return {item["repository_id"]: item.get("base_commit") for item in result.get("repositories", [])}


def inspect_task_repositories(db, task) -> dict:
    local = task.execution_location == "LOCAL"
    binding = db.get(TaskExecutionBinding, task.id) if local else None
    receipt = (binding.receipt_json or {}) if binding else {}
    root = receipt.get("task_root") if local else task.project_path
    receipt_repos = {r["repository_id"]: r for r in receipt.get("repositories", [])}
    metadata = task.task_meta_json or {}
    snapshots = metadata.get(COMMIT_SNAPSHOTS_KEY) or {}
    task_repos = get_task_repositories(db, task.id)
    local_commits = {}
    if binding and any(
        repo.base_commit_sha and not receipt_repos.get(repo.repository_id, {}).get("base_commit") for repo in task_repos
    ):
        local_commits = _local_commit_details(db, binding, task)
    repos = []
    for repo in task_repos:
        actual = receipt_repos.get(repo.repository_id, {})
        commit = snapshots.get(repo.id) or actual.get("base_commit") or local_commits.get(repo.repository_id)
        if commit and commit.get("sha") != repo.base_commit_sha:
            commit = None
        worktree_path = _join_resource_path(root, repo.rel_path)
        if not commit and not local:
            commit = read_commit_info(worktree_path, repo.base_commit_sha)
        repos.append(
            TaskRepositoryDetail(
                id=repo.id,
                repository_id=repo.repository_id,
                repo_name=repo.repo_name,
                repo_url=repo.repo_url,
                branch_name=repo.branch_name,
                task_branch=actual.get("task_branch") if local else f"task/{task.id}",
                rel_path=repo.rel_path,
                worktree_path=worktree_path,
                state=repo.state.value if hasattr(repo.state, "value") else str(repo.state),
                error_message=repo.error_message,
                base_commit_sha=repo.base_commit_sha,
                base_commit=commit,
            )
        )
    if not repos and task.git_repo_url:
        legacy = metadata.get(LEGACY_CHECKOUT_KEY) or {}
        commit = legacy.get("base_commit")
        if not commit and not local:
            commit = read_commit_info(root, legacy.get("base_commit_sha"))
        repos.append(
            TaskRepositoryDetail(
                id="legacy",
                repo_name=task.name,
                repo_url=task.git_repo_url,
                branch_name=legacy.get("branch_name"),
                task_branch=legacy.get("task_branch"),
                rel_path=".",
                worktree_path=root,
                state="READY"
                if legacy.get("base_commit_sha")
                else ("PENDING" if task.status == "PROVISIONING" else "UNKNOWN"),
                base_commit_sha=legacy.get("base_commit_sha"),
                base_commit=commit,
            )
        )
    return {"task": task, "project_path": root, "repositories": repos}
