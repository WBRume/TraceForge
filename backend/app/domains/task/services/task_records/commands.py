"""Change task status, following and trash lifecycle."""

import os
import shutil

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domains.auth.models.user import Workspace
from app.domains.task.models.task import SddTask, SddTaskFollower, TaskStatus
from app.domains.task.services import git_worktree_service
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


def update_task_status(db: Session, task: SddTask, status: TaskStatus, error_message: str | None = None) -> SddTask:
    task.status = status
    if error_message:
        task.error_message = error_message
    db.commit()
    db.refresh(task)
    return task


DELETE_TRASH_DIR_NAME = ".delete"


def _archive_task_dir_into_delete_trash(task_project_path: str, workspace_project_path: str) -> None:
    """删除任务后把工作区内残留的任务目录移入 <工作区根>/.delete/ 软删除区。

    仅移动工作区根直接下属的任务目录（.delete 自身除外）；移动失败只告警，
    不影响删除主流程。归档名冲突时追加 _1/_2 序号。
    """
    try:
        task_abs = os.path.abspath(str(task_project_path or "").strip())
        stop_abs = os.path.abspath(str(workspace_project_path or "").strip())
        if not stop_abs or not os.path.isdir(stop_abs):
            return
        if not task_abs.startswith(stop_abs + os.sep):
            return
        trash_root = os.path.join(stop_abs, DELETE_TRASH_DIR_NAME)
        if os.path.commonpath([task_abs, trash_root]) == trash_root:
            return
        if not os.path.isdir(task_abs):
            return

        base_name = os.path.basename(task_abs.rstrip("\\/")) or "task"
        os.makedirs(trash_root, exist_ok=True)
        target = os.path.join(trash_root, base_name)
        sequence = 1
        while os.path.exists(target):
            target = os.path.join(trash_root, f"{base_name}_{sequence}")
            sequence += 1
        shutil.move(task_abs, target)
        logger.info(f"Task dir moved to delete trash: {task_abs} -> {target}")
    except Exception as exc:
        logger.warning(f"Failed to move task dir to delete trash {task_project_path}: {exc}")


def delete_task(db: Session, task_id: str, workspace_id: str) -> bool:
    task = db.query(SddTask).filter(SddTask.id == task_id, SddTask.workspace_id == workspace_id).first()
    if not task:
        return False

    from app.domains.local_resource.service import is_local, release_or_defer

    if is_local(task):
        release_or_defer(db, task)
        db.delete(task)
        db.commit()
        return True

    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    workspace_project_path = (
        str(workspace.project_path or "").strip() if workspace else os.path.dirname(os.path.abspath(task.project_path))
    )
    task_remote = str(task.git_repo_url or "").strip()

    task_repos = task_task_workspace_repositories.get_task_repositories(db, task.id)
    if task_repos:
        if not workspace:
            # Without a workspace we cannot resolve base dirs; fall back to
            # removing the whole task root to avoid stale worktrees.
            shutil.rmtree(task.project_path, ignore_errors=True)
        else:
            task_task_workspace_repositories.cleanup_task_repositories(db, workspace, task, missing_ok=True)
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
    _archive_task_dir_into_delete_trash(task.project_path, workspace_project_path)

    db.delete(task)
    db.commit()
    return True
