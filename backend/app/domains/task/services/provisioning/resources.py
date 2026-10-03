"""Prepare task resources with cancellation checkpoints and compensating cleanup."""

import os
import shutil
from typing import Callable, Optional
from sqlalchemy.orm import Session
from app.core.logging import bind_task_context, get_logger
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.auth.models.user import Workspace

from app.domains.task.services import git_worktree_service
from app.domains.task.services.task_workspace import repositories as task_task_workspace_repositories

from app.domains.skill.services.runtime import materialization as skill_runtime_materialization


logger = get_logger(__name__, category="task_execution")


class ProvisionJobCancelled(Exception):
    """任务创建准备过程被创建人取消（触发回滚：清理磁盘资源并删除任务记录）。"""


def _prepare_initial_workspace_checkpoint(db: Session, ws: Workspace, task: SddTask) -> None:
    """Seed persistent snapshot indexes while the task is still PROVISIONING."""
    from app.domains.local_resource import service as resource
    from app.domains.local_resource.snapshots import encode
    from app.domains.task.services import task_session_snapshot_service as snapshots

    metadata = dict(task.task_meta_json or {})
    if metadata.get("initial_workspace_checkpoint"):
        return
    if resource.is_local(task):
        result = resource.execute(db, task, "snapshot", {
            "action": "create", "provider": "opencode", "session_id": None,
        }, "snapshot-initial-" + task.id)
        checkpoint = encode(task.id, result["root"])
    else:
        result = snapshots._create_checkpoint_sync(
            task.project_path, [repo.rel_path for repo in task_task_workspace_repositories.get_task_repositories(db, task.id)],
            "none", None, ws.id, ws.name, task.id, task.name,
        )
        checkpoint = result["root"]
    metadata["initial_workspace_checkpoint"] = checkpoint
    task.task_meta_json = metadata
    # Persist ownership before the next cancellation check / terminal rollback.
    db.commit()


def prepare_task_resources_for_provision(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    cancel_check: Optional[Callable[[], bool]] = None,
    snapshot_progress: Optional[Callable[[], None]] = None,
) -> SddTask:
    task = db.query(SddTask).filter(SddTask.id == task_id, SddTask.workspace_id == workspace_id).first()
    if not task:
        raise ValueError("Task not found")

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise ValueError("Workspace not found")

    def _checkpoint() -> None:
        # 取消检查点：命中即抛出，走 except 分支清理已创建的资源后上抛，
        # 由 provision job 终局回滚删除任务记录。
        if cancel_check is not None and cancel_check():
            raise ProvisionJobCancelled("Task creation cancelled by user")

    def _initialize_snapshot() -> None:
        _checkpoint()
        db.commit()
        if snapshot_progress:
            snapshot_progress()
        _prepare_initial_workspace_checkpoint(db, ws, task)
        _checkpoint()
        db.refresh(task)
        if task.status != TaskStatus.PROVISIONING:
            raise ProvisionJobCancelled("Task no longer provisioning")

    from app.domains.local_resource.service import is_local, provision_task
    with bind_task_context(task_id=task.id, workspace_id=workspace_id, user_id=task.creator_id):
        try:
            _checkpoint()
            if is_local(task):
                provision_task(db, task)
            else:
                task_repos = task_task_workspace_repositories.get_task_repositories(db, task.id)
                if task_repos:
                    task_task_workspace_repositories.prepare_task_repositories(db, ws, task, task_repos)
                elif git_worktree_service.should_use_git_worktree(ws.project_path, ws.git_repo_url):
                    git_worktree_service.create_task_worktree(
                        repo_path=ws.project_path or "",
                        task_id=task.id,
                        task_project_path=task.project_path,
                        expected_git_repo_url=ws.git_repo_url,
                    )
                else:
                    os.makedirs(task.project_path, exist_ok=False)

            _checkpoint()
            if task.skill_links:
                skill_runtime_materialization.materialize_task_skills(db, task.id)
            _initialize_snapshot()
            db.expire(task)
            db.refresh(task)
            if task.status != TaskStatus.PROVISIONING:
                raise ProvisionJobCancelled("Task no longer provisioning")
            task.status = TaskStatus.PENDING
            task.current_phase = None
            task.error_message = None
            db.commit()
            db.refresh(task)
            return task
        except Exception:
            db.rollback()
            # The provision job owns terminal compensation in a fresh transaction.
            # Local ResourceError keeps its binding for reconciliation; other failures
            # and cancellation use rollback_provision_task, including partial worktrees.
            raise


def _prune_empty_parent_dirs(task_project_path: str, workspace_project_path: str) -> None:
    """best-effort 清理任务目录下残留的空父目录（不超过工作区根目录）。"""
    try:
        stop = os.path.abspath(str(workspace_project_path or "").strip())
        if not stop or not os.path.isdir(stop):
            return
        current = os.path.dirname(os.path.abspath(str(task_project_path or "").strip()))
        while current.startswith(stop + os.sep):
            try:
                os.rmdir(current)
            except OSError:
                break
            current = os.path.dirname(current)
    except Exception as exc:
        logger.warning(f"Failed to prune empty task parent dirs {task_project_path}: {exc}")


def rollback_provision_task(db: Session, *, workspace_id: str, task_id: str) -> bool:
    """任务创建失败/被取消后的终局回滚：清理磁盘资源并删除任务记录。

    与 prepare_task_resources_for_provision 的资源分支一一对应：
    multi-repo → 清理各仓库 worktree；单仓 git → 移除 worktree；非 git → 删除目录。
    任务记录删除后任务不会以 FAILED 形式残留（FAILED 仅允许用户标记触发）。
    """
    task = db.query(SddTask).filter(SddTask.id == task_id, SddTask.workspace_id == workspace_id).first()
    if not task:
        return False

    checkpoint = (task.task_meta_json or {}).get("initial_workspace_checkpoint")
    if checkpoint:
        from app.domains.task.services import task_session_snapshot_service as snapshots
        from app.domains.local_resource import snapshots as remote
        try:
            if checkpoint.startswith(remote.PREFIX):
                from app.domains.local_resource.service import execute
                _, path = remote.decode(checkpoint)
                execute(db, task, "snapshot", {"action": "cleanup", "checkpoint_root": path})
            else:
                snapshots._cleanup_checkpoint_sync(checkpoint)
        except Exception as exc:
            logger.warning("Failed to clean initial checkpoint for task {}: {}", task.id, exc)

    from app.domains.local_resource.service import is_local, release_or_defer
    if is_local(task):
        release_or_defer(db, task)
        db.delete(task)
        db.commit()
        return True

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    workspace_project_path = str(ws.project_path or "").strip() if ws else ""
    task_repos = task_task_workspace_repositories.get_task_repositories(db, task.id)

    try:
        if task_repos and ws:
            task_task_workspace_repositories.cleanup_task_repositories(db, ws, task, missing_ok=True)
        elif ws and git_worktree_service.should_use_git_worktree(workspace_project_path, ws.git_repo_url or task.git_repo_url):
            git_worktree_service.remove_task_worktree(
                repo_path=workspace_project_path,
                task_id=task.id,
                task_project_path=task.project_path,
                expected_git_repo_url=ws.git_repo_url or task.git_repo_url,
                missing_ok=True,
            )
        else:
            shutil.rmtree(task.project_path, ignore_errors=True)
    except Exception as cleanup_exc:
        logger.warning(f"Failed to cleanup provision task resources {task.id}: {cleanup_exc}")
    finally:
        _prune_empty_parent_dirs(task.project_path, workspace_project_path)

    db.delete(task)
    db.commit()
    return True
