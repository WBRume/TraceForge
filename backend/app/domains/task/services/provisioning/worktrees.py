"""Register under the workspace lock; materialize under the task bootstrap lock."""

import os

from sqlalchemy.orm import Session

from app.domains.auth.models.user import Workspace
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.models.task_repository import TaskRepositoryState
from app.domains.task.services import git_worktree_service as git
from app.domains.task.services.task_repository_details import (
    LEGACY_CHECKOUT_KEY,
    read_commit_info,
    save_commit_snapshot,
)
from app.domains.task.services.task_workspace import repositories

REGISTRATION_KEY = "provision_worktrees"


def register_worktrees(db: Session, *, workspace_id: str, task_id: str) -> None:
    """Pin commits and persist ownership before releasing the workspace lock."""
    task = db.query(SddTask).filter_by(id=task_id, workspace_id=workspace_id).one()
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise ValueError("Workspace not found")
    if task.status == TaskStatus.INITIALIZED:
        return  # Re-delivery after readiness was committed, before job success.
    if task.status != TaskStatus.PROVISIONING:
        raise ValueError("Task no longer provisioning")
    if (task.task_meta_json or {}).get(REGISTRATION_KEY):
        return  # Resume the original pinned commits, never fetch again.
    task_repos = repositories.get_task_repositories(db, task.id)
    entries = []
    if task_repos:
        bindings = repositories.build_task_worktree_bindings(db, workspace, task)
        git.create_task_worktrees(base_bindings=bindings, task_root=task.project_path, task_id=task.id, checkout=False)
        bases = {binding.repo_slug: binding.base_dir for binding in bindings}
        for repo in task_repos:
            path = os.path.join(task.project_path, repo.rel_path)
            sha = git.read_repo_head_sha(path)
            repo.base_commit_sha = sha
            save_commit_snapshot(task, repo.id, read_commit_info(path, sha))
            entries.append({"repository_id": repo.id, "base": bases[repo.repo_slug], "path": path, "sha": sha})
    else:
        details = {}
        git.create_task_worktree(
            repo_path=workspace.project_path,
            task_id=task.id,
            task_project_path=task.project_path,
            expected_git_repo_url=workspace.git_repo_url,
            checkout_details=details,
            checkout=False,
        )
        task.task_meta_json = {**(task.task_meta_json or {}), LEGACY_CHECKOUT_KEY: details}
        entries.append({"base": workspace.project_path, "path": task.project_path, "sha": details["base_commit_sha"]})
    if any(not entry["sha"] for entry in entries):
        raise ValueError("Registered worktree has no pinned commit")
    task.task_meta_json = {**(task.task_meta_json or {}), REGISTRATION_KEY: {"version": 1, "entries": entries}}
    db.commit()


def materialize_worktrees(db: Session, task: SddTask, checkpoint) -> bool:
    """Return false for legacy/direct callers without a staged registration."""
    receipt = (task.task_meta_json or {}).get(REGISTRATION_KEY)
    if not receipt:
        return False
    if receipt.get("files_ready"):
        return True
    for entry in receipt["entries"]:
        checkpoint()
        git.checkout_registered_worktree(
            repo_path=entry["base"], task_path=entry["path"], task_id=task.id, sha=entry["sha"]
        )
    checkpoint()
    for repo in repositories.get_task_repositories(db, task.id):
        repo.state = TaskRepositoryState.READY
        repo.error_message = None
    task.task_meta_json = {**task.task_meta_json, REGISTRATION_KEY: {**receipt, "files_ready": True}}
    # Re-delivery must not reset files after skill materialization or snapshots.
    db.commit()
    return True
