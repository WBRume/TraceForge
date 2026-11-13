"""Task following and trash lifecycle. Status belongs to status_machine."""

import os
import shutil

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domains.auth.models.user import Workspace
from app.domains.task.models.task import SddTask, SddTaskFollower, TaskStatus
from app.domains.task.services import git_worktree_service
from app.domains.task.services.task_records import deletion
from app.domains.task.services.task_workspace import repositories as task_task_workspace_repositories

logger = get_logger(__name__, category="task_execution")


def set_task_following(
    db: Session,
    *,
    task: SddTask,
    user_id: str,
    following: bool,
) -> bool:
    normalized_user_id = str(user_id or "").strip()
    row = (
        db.query(SddTaskFollower)
        .filter(
            SddTaskFollower.task_id == task.id,
            SddTaskFollower.workspace_id == task.workspace_id,
            SddTaskFollower.user_id == normalized_user_id,
        )
        .first()
    )
    if following and row is None:
        db.add(
            SddTaskFollower(
                task_id=task.id,
                workspace_id=task.workspace_id,
                user_id=normalized_user_id,
            )
        )
    elif not following and row is not None:
        db.delete(row)
    db.commit()
    return following


DELETE_TRASH_DIR_NAME = ".delete"


def _archive_task_dir_into_delete_trash(task_project_path: str, workspace_project_path: str) -> str | None:
    """Archive a task directory inside its workspace and retain its contents."""
    if not task_project_path or not workspace_project_path:
        return None
    task_abs = os.path.abspath(task_project_path)
    workspace_abs = os.path.realpath(workspace_project_path)
    trash_root = os.path.join(workspace_abs, DELETE_TRASH_DIR_NAME)
    task_real = os.path.realpath(task_abs)
    try:
        if os.path.commonpath([task_real, workspace_abs]) != workspace_abs:
            return None
    except ValueError:
        return None  # Different Windows drives.
    if task_real in (workspace_abs, trash_root) or os.path.commonpath([task_real, trash_root]) == trash_root:
        return None
    if not os.path.isdir(task_abs):
        return None
    if os.path.normcase(task_abs) != os.path.normcase(task_real) or os.path.realpath(trash_root) != trash_root:
        raise ValueError("Task archive paths must not traverse symbolic links or junctions")

    base_name = os.path.basename(task_abs)
    os.makedirs(trash_root, exist_ok=True)
    target = os.path.join(trash_root, base_name)
    sequence = 1
    while os.path.lexists(target):
        target = os.path.join(trash_root, f"{base_name}_{sequence}")
        sequence += 1
    shutil.move(task_abs, target)
    logger.info(f"Task dir moved to delete trash: {task_abs} -> {target}")
    return target


def delete_task(db: Session, task_id: str, workspace_id: str) -> bool:
    task = (
        db.query(SddTask)
        .filter(SddTask.id == task_id, SddTask.workspace_id == workspace_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if not task:
        return False
    if task.status == TaskStatus.PROVISIONING:
        raise ValueError("任务正在准备，请先取消创建并等待清理完成")

    deletion.ensure_execution_stopped(db, task_id)
    deletion.enqueue(db, task)
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    task_path = task.project_path
    archived = archive_server_task(db, workspace, task)
    try:
        db.delete(task)
        db.commit()
    except Exception:
        db.rollback()
        if archived and not os.path.lexists(task_path):
            shutil.move(archived, task_path)
        raise
    return True


def archive_server_task(db: Session, workspace: Workspace, task: SddTask) -> str | None:
    from app.domains.local_resource.service import is_local

    if is_local(task) or not task.project_path:
        return None
    workspace_project_path = str(workspace.project_path or "").strip()
    task_dir_name = os.path.basename(task.project_path)
    if not workspace_project_path and (task_dir_name == task.id or task_dir_name.startswith(f"{task.id}__")):
        workspace_project_path = os.path.dirname(os.path.abspath(task.project_path))
    task_remote = str(task.git_repo_url or "").strip()

    task_repos = task_task_workspace_repositories.get_task_repositories(db, task.id)
    if task_repos:
        task_task_workspace_repositories.cleanup_task_repositories(db, workspace, task, strict=True)
    elif git_worktree_service.should_use_git_worktree(workspace_project_path, task_remote):
        git_worktree_service.remove_task_worktree(
            repo_path=workspace_project_path,
            task_id=task.id,
            task_project_path=task.project_path,
            expected_git_repo_url=task_remote,
            missing_ok=True,
        )

    # git worktree 已由 git 移除目录；其余情况（非 git 目录、多仓残留任务根）
    # 会留在工作区，统一移入 .delete 软删除区而非原地删除。
    return _archive_task_dir_into_delete_trash(task.project_path, workspace_project_path)
