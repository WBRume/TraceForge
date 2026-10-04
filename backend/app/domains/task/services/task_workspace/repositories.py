"""Manage task repository bindings, worktrees and CLI working directories."""

import os

from sqlalchemy.orm import Session

from app.domains.auth.models.user import Workspace
from app.domains.task.models.task import SddTask
from app.domains.task.services import git_worktree_service


def _workspace_base_repo_dir(workspace_project_path: str, repo_slug: str) -> str:
    return os.path.join(str(workspace_project_path or "").strip(), repo_slug)


def snapshot_workspace_repositories_into_task(
    db: Session,
    workspace: Workspace,
    task: SddTask,
    branch_overrides: dict[str, str] | None = None,
    selected_ids: list[str] | None = None,
) -> list:
    """Snapshot workspace repository bindings into sdd_task_repositories.

    branch_overrides: repository_id -> 分支名；用于会话创建时按仓库选填分支覆盖。
    selected_ids: 仓库 id 子集；提供时仅为所选仓库创建 worktree 绑定（默认全部仓库）。
    """
    from app.domains.task.models.task_repository import SddTaskRepository, TaskRepositoryState
    from app.domains.workspace.models.workspace_repository import SddWorkspaceRepository

    overrides = {
        str(repo_id or "").strip(): str(branch or "").strip()
        for repo_id, branch in (branch_overrides or {}).items()
        if str(repo_id or "").strip() and str(branch or "").strip()
    }
    ws_repos = (
        db.query(SddWorkspaceRepository)
        .filter(SddWorkspaceRepository.workspace_id == workspace.id)
        .order_by(SddWorkspaceRepository.created_at.asc())
        .all()
    )
    ws_by_id = {row.repository_id: row for row in ws_repos if row.repository_id}
    unknown_overrides = sorted(set(overrides) - set(ws_by_id))
    if unknown_overrides:
        raise ValueError("Repository does not belong to this workspace: " + ", ".join(unknown_overrides))
    if selected_ids is not None:
        normalized_selected = {str(repo_id or "").strip() for repo_id in selected_ids}
        normalized_selected.discard("")
        unknown_selected = sorted(normalized_selected - set(ws_by_id))
        if unknown_selected:
            raise ValueError("Repository does not belong to this workspace: " + ", ".join(unknown_selected))
        if not normalized_selected:
            raise ValueError("At least one repository must be selected for the task")
        ws_repos = [row for row in ws_repos if row.repository_id in normalized_selected]
        # 未被选中的仓库不接受分支覆盖
        overrides = {repo_id: branch for repo_id, branch in overrides.items() if repo_id in normalized_selected}
    bindings: list = []
    for ws_repo in ws_repos:
        override = overrides.get(str(ws_repo.repository_id or ""), "")
        binding = SddTaskRepository(
            task_id=task.id,
            repository_id=ws_repo.repository_id,
            repo_url=ws_repo.repo_url,
            repo_name=ws_repo.repo_name,
            repo_slug=ws_repo.repo_slug,
            branch_name=override or ws_repo.branch_name,
            rel_path=ws_repo.repo_slug,
            state=TaskRepositoryState.PENDING,
        )
        db.add(binding)
        bindings.append(binding)
    return bindings


def build_task_worktree_bindings(
    db: Session,
    workspace: Workspace,
    task: SddTask,
) -> list:
    """Map task repository bindings to worktree orchestration bindings."""
    from app.domains.workspace.models.workspace_repository import SddWorkspaceRepository

    ws_repos = db.query(SddWorkspaceRepository).filter(SddWorkspaceRepository.workspace_id == workspace.id).all()
    ws_by_id = {row.repository_id: row for row in ws_repos}
    bindings: list = []
    for repo in task.repo_bindings:
        ws_repo = ws_by_id.get(repo.repository_id)
        base_dir = (
            ws_repo.base_dir
            if ws_repo and ws_repo.base_dir
            else _workspace_base_repo_dir(workspace.project_path or "", repo.repo_slug)
        )
        bindings.append(
            git_worktree_service.RepoWorktreeBinding(
                repo_url=repo.repo_url,
                repo_name=repo.repo_name,
                repo_slug=repo.repo_slug,
                branch_name=repo.branch_name,
                base_dir=base_dir,
            )
        )
    return bindings


def prepare_task_repositories(
    db: Session,
    workspace: Workspace,
    task: SddTask,
    task_repos: list,
) -> None:
    """Create worktrees for every repository binding and mark them READY."""
    from app.domains.task.models.task_repository import TaskRepositoryState

    bindings = build_task_worktree_bindings(db, workspace, task)
    git_worktree_service.create_task_worktrees(
        base_bindings=bindings,
        task_root=task.project_path,
        task_id=task.id,
    )
    for repo in task_repos:
        worktree_dir = os.path.join(str(task.project_path or "").strip(), repo.rel_path)
        repo.state = TaskRepositoryState.READY
        repo.base_commit_sha = git_worktree_service.read_repo_head_sha(worktree_dir)
        repo.error_message = None


def cleanup_task_repositories(
    db: Session,
    workspace: Workspace,
    task: SddTask,
    missing_ok: bool = True,
) -> None:
    """Remove worktrees for every repository binding of a task."""
    bindings = build_task_worktree_bindings(db, workspace, task)
    if not bindings:
        return
    git_worktree_service.remove_task_worktrees(
        base_bindings=bindings,
        task_root=task.project_path,
        task_id=task.id,
        missing_ok=missing_ok,
    )


def resolve_task_cli_dir(db: Session, task: SddTask) -> str:
    """Resolve the CLI working directory of a task.

    Always returns the task working directory root (task.project_path), so
    Claude CLI runs from the task root and can access every repository
    worktree materialized underneath it (one per repository binding).
    """
    # The task root is where all repository worktrees are materialized
    # (<task_root>/<repo_slug>/...). Running the CLI anywhere deeper (e.g. the
    # primary repository worktree) would hide the other repositories from the
    # session, so keep the root for both single- and multi-repository tasks.
    from app.domains.local_resource.service import is_local, local_path

    if is_local(task):
        return local_path(db, task)
    return str(task.project_path or "").strip() or "."


def get_task_repositories(db: Session, task_id: str) -> list:
    from app.domains.task.models.task_repository import SddTaskRepository

    return (
        db.query(SddTaskRepository)
        .filter(SddTaskRepository.task_id == task_id)
        .order_by(SddTaskRepository.created_at.asc())
        .all()
    )


def serialize_task_repository(repo) -> dict:
    return {
        "id": repo.id,
        "task_id": repo.task_id,
        "repository_id": repo.repository_id,
        "repo_url": repo.repo_url,
        "repo_name": repo.repo_name,
        "repo_slug": repo.repo_slug,
        "branch_name": repo.branch_name,
        "base_commit_sha": repo.base_commit_sha,
        "rel_path": repo.rel_path,
        "state": repo.state.value if hasattr(repo.state, "value") else str(repo.state),
        "error_message": repo.error_message,
        "created_at": repo.created_at,
    }
