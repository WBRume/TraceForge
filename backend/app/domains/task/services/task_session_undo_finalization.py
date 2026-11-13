"""Retry delivery and checkpoint cleanup for committed session undos."""

from datetime import datetime, timedelta

from app.core.distributed_lock import LockAcquireTimeout, lock_task
from app.core.logging import get_logger
from app.core.offload import run_db_txn
from app.domains.task.models.session_turn import (
    TaskSessionOperation,
    TaskSessionOperationStatus,
    TaskSessionTurn,
    TaskSessionTurnStatus,
)
from app.domains.task.services import task_session_snapshot_service
from app.domains.workspace_collaboration import hooks

logger = get_logger(__name__, category="task_session_undo")


def _load_checkpoints(db, task_id: str, operation_id: str) -> list[str] | None:
    pending = (
        db.query(TaskSessionOperation.id)
        .filter_by(task_id=task_id, operation_id=operation_id, status=TaskSessionOperationStatus.REVERTED)
        .filter(TaskSessionOperation.finalize_after <= datetime.utcnow())
        .first()
    )
    if pending is None:
        return None
    paths = (
        db.query(TaskSessionTurn.checkpoint_path)
        .filter_by(task_id=task_id, operation_id=operation_id, status=TaskSessionTurnStatus.REVERTED)
        .filter(TaskSessionTurn.checkpoint_path.isnot(None))
        .distinct()
    )
    return [path.strip() for (path,) in paths if path.strip()]


def _set_next_attempt(db, task_id: str, operation_id: str, when: datetime | None) -> None:
    operation = (
        db.query(TaskSessionOperation)
        .filter_by(task_id=task_id, operation_id=operation_id, status=TaskSessionOperationStatus.REVERTED)
        .filter(TaskSessionOperation.finalize_after.isnot(None))
        .first()
    )
    if operation:
        operation.finalize_after = when


async def finalize_undo(task_id: str, operation_id: str, run_txn) -> None:
    """Run under the task lock. Each step can be retried after a process restart."""
    try:
        checkpoints = await run_txn(lambda db: _load_checkpoints(db, task_id, operation_id))
        if checkpoints is None:
            return
        await hooks.finish_restore(task_id, operation_id, run_txn)
        for path in checkpoints:
            await task_session_snapshot_service.cleanup_checkpoint(path)
        await run_txn(lambda db: _set_next_attempt(db, task_id, operation_id, None))
    except Exception as exc:
        logger.warning(
            "Task session undo finalization deferred: task={}, operation={}, error={}",
            task_id,
            operation_id,
            type(exc).__name__,
        )
        try:
            retry_at = datetime.utcnow() + timedelta(seconds=10)
            await run_txn(lambda db: _set_next_attempt(db, task_id, operation_id, retry_at))
        except Exception:
            logger.exception("Could not defer pending undo finalization: task={}, operation={}", task_id, operation_id)


def _pending(db) -> list[tuple[str, str]]:
    return [
        (task_id, operation_id)
        for task_id, operation_id in db.query(TaskSessionOperation.task_id, TaskSessionOperation.operation_id)
        .filter(
            TaskSessionOperation.status == TaskSessionOperationStatus.REVERTED,
            TaskSessionOperation.finalize_after <= datetime.utcnow(),
        )
        .order_by(TaskSessionOperation.finalize_after, TaskSessionOperation.id)
        .limit(10)
    ]


async def recover_pending_undos() -> None:
    for task_id, operation_id in await run_db_txn(_pending):
        await finalize_pending_undo(task_id, operation_id, run_db_txn)


async def finalize_pending_undo(task_id: str, operation_id: str, run_txn) -> None:
    try:
        async with lock_task(task_id, ttl=120, blocking_timeout=0.5):
            await finalize_undo(task_id, operation_id, run_txn)
    except LockAcquireTimeout:
        return
