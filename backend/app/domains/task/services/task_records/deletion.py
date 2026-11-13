"""Shared task cleanup for task deletion and workspace deletion."""

import asyncio
import errno
import os
import re
import shutil
import stat
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.distributed_lock import LockAcquireTimeout, lock_task
from app.core.logging import get_logger
from app.core.offload import run_db_txn, run_db_txn_with_bind, run_file_job
from app.domains.ai.models.ai_job import AiJobChannel, SddAiJob
from app.domains.ai.services.jobs.attempts import mark_task_chat_jobs_cancelled
from app.domains.ai.services.jobs.constants import FINAL_STATUSES
from app.domains.ai.services.jobs.registry import runtime
from app.domains.local_resource import service as local_resources
from app.domains.local_resource.client import ResourceClient
from app.domains.task.models.deletion import TaskDeletionCleanup
from app.domains.task.models.task import SddTask
from app.domains.task.services.task_cli_paths import _safe_rmtree, _task_state_root

logger = get_logger(__name__, category="task_execution")


def enqueue(db: Session, task: SddTask) -> None:
    profile = None
    if local_resources.is_local(task):
        binding = local_resources.binding(db, task.id)
        profile = local_resources.runtime_profile(db, binding, require_access=False)
        profile = {key: profile[key] for key in ("id", "host_id", "resource_service_url", "encrypted_credentials")}
    db.add(
        TaskDeletionCleanup(
            task_id=task.id, workspace_id=task.workspace_id, resource_profile=profile, retry_at=datetime.utcnow()
        )
    )


def ensure_execution_stopped(db: Session, task_id: str) -> None:
    if (
        db.query(SddAiJob.id)
        .filter(
            SddAiJob.task_id == task_id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
            SddAiJob.status.notin_(FINAL_STATUSES),
        )
        .with_for_update()
        .first()
    ):
        raise ValueError("任务执行正在停止，请稍后重试删除")


async def stop_task_execution(db_bind, workspace_id: str, task_id: str) -> None:
    from app.engine.session.registry import list_task_engines

    cancelled_ids = await run_db_txn_with_bind(
        db_bind,
        lambda db: mark_task_chat_jobs_cancelled(
            db, workspace_id=workspace_id, task_id=task_id, message="Task deletion requested"
        ),
    )
    for engine in list_task_engines(task_id):
        await engine.stop()

    # A worker on another process can still own an attempt. Keep the task and
    # its binding available for cancellation to converge before deleting them.
    await run_db_txn_with_bind(db_bind, lambda db: ensure_execution_stopped(db, task_id))
    for job_id in cancelled_ids:
        runtime.clear_cancel(job_id)


def _rmdir_if_empty(path: Path) -> None:
    try:
        path.rmdir()
    except OSError as exc:
        if exc.errno not in (errno.ENOENT, errno.ENOTEMPTY, errno.EEXIST):
            raise


def _remove_owned_directory(path: Path) -> None:
    if path.is_symlink() or path.resolve() != path:
        raise ValueError(f"Cleanup path resolves outside its expected location: {path}")

    def remove_readonly_file(remove, filename, exc_info):
        error = exc_info[1]
        if os.name != "nt" or not isinstance(error, PermissionError) or remove != os.unlink:
            raise error
        info = os.stat(filename, follow_symlinks=False)
        if getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise error
        os.chmod(filename, info.st_mode | stat.S_IWRITE)
        os.unlink(filename)

    try:
        shutil.rmtree(path, onerror=remove_readonly_file)
    except FileNotFoundError:
        if path.exists():
            raise


def _cleanup_files(workspace_id: str, task_id: str) -> None:
    if not all(re.fullmatch(r"[a-zA-Z0-9_-]+", identity) for identity in (workspace_id, task_id)):
        raise ValueError("Invalid task or workspace identity")
    cli = Path(_task_state_root(workspace_id, task_id))
    if cli.parent.resolve() != cli.parent.parent.resolve() / cli.parent.name:
        raise ValueError("CLI workspace directory resolves outside the CLI state root")
    _safe_rmtree(str(cli))
    _rmdir_if_empty(cli.parent)
    _remove_owned_directory(Path(settings.TASK_EVIDENCE_ATTACHMENT_ROOT).resolve() / task_id)

    snapshots = Path(settings.TASK_SESSION_SNAPSHOT_ROOT).resolve()
    collaboration = Path(settings.COLLABORATION_SNAPSHOT_ROOT or snapshots / "collaboration").resolve()
    _remove_owned_directory(collaboration / task_id)
    # Names can change. The ID prefix identifies the task's snapshot stores.
    for workspace_dir in snapshots.iterdir() if snapshots.is_dir() else ():
        if not workspace_dir.name.startswith(f"{workspace_id}_") or workspace_dir.resolve() != workspace_dir:
            continue
        for task_dir in workspace_dir.iterdir():
            if task_dir.name.startswith(f"{task_id}_"):
                _remove_owned_directory(task_dir)
        _rmdir_if_empty(workspace_dir)


def _pending(db: Session) -> list[str]:
    return list(
        db.scalars(
            select(TaskDeletionCleanup.task_id)
            .where(TaskDeletionCleanup.retry_at <= datetime.utcnow())
            .order_by(TaskDeletionCleanup.retry_at, TaskDeletionCleanup.task_id)
            .limit(20)
        )
    )


def _load(db: Session, task_id: str) -> tuple[str, dict | None] | None:
    row = db.get(TaskDeletionCleanup, task_id)
    return (row.workspace_id, row.resource_profile) if row and row.retry_at <= datetime.utcnow() else None


def _finish(db: Session, task_id: str, *, retry: bool) -> None:
    row = db.get(TaskDeletionCleanup, task_id)
    if row:
        if retry:
            row.retry_at = datetime.utcnow() + timedelta(seconds=10)
        else:
            db.delete(row)


def _release_desktop(task_id: str, profile: dict) -> None:
    ResourceClient(profile, timeout=15).operation(task_id, "release", {}, f"release-{task_id}")


async def _finalize(task_id: str) -> None:
    try:
        async with lock_task(task_id, blocking_timeout=0.5):
            intent = await run_db_txn(lambda db: _load(db, task_id))
            if intent is None:
                return
            workspace_id, profile = intent
            try:
                await run_file_job(_cleanup_files, workspace_id, task_id)
                if profile:
                    await run_file_job(_release_desktop, task_id, profile)
            except Exception as exc:
                logger.warning("Task deletion cleanup deferred: task={}, error={}", task_id, str(exc))
                await run_db_txn(lambda db: _finish(db, task_id, retry=True))
            else:
                await run_db_txn(lambda db: _finish(db, task_id, retry=False))
    except LockAcquireTimeout:
        return


async def run_worker() -> None:
    while True:
        try:
            task_ids = await run_db_txn(_pending)
            # Bound concurrency so unreachable desktop hosts do not delay local cleanup.
            for offset in range(0, len(task_ids), 4):
                await asyncio.gather(*(_finalize(task_id) for task_id in task_ids[offset : offset + 4]))
        except Exception:
            logger.exception("Task deletion cleanup scan failed")
        await asyncio.sleep(2)
