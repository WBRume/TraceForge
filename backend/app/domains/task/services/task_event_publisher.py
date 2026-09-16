"""Background publisher: committed task events out of the database into the WS rooms.

The transactional outbox closes the "committed but never broadcast" crash gap;
RoomHub still owns per-connection replay/live hand-off after the event is in
its journal.  Publishing never checks subscribers: an event must land in the
journal so a later reconnect can replay it.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from uuid import uuid4

from app.config import settings
from app.core.logging import get_logger
from app.core.offload import run_db_txn
from app.domains.task.models.task_event_outbox import TaskEventOutbox

logger = get_logger(__name__, category="task_execution")

_TASK: asyncio.Task | None = None
_WAKE: asyncio.Event | None = None
_SHUTTING_DOWN = False

_BATCH_LIMIT = 100
_MAX_ATTEMPTS = 8
_RETENTION_HOURS = 24


def wake() -> None:
    """Prompt the publisher loop; safe from any thread or before startup."""
    event = _WAKE
    if event is None:
        return
    event.set()


def _backoff_seconds(attempts: int) -> float:
    return min(300.0, 2.0 ** max(0, attempts))


def _pending_sync(db, now: datetime):
    """Lease one page of pending rows for this process; returns scalar tuples."""
    rows = (
        db.query(TaskEventOutbox)
        .filter(TaskEventOutbox.status == "pending", TaskEventOutbox.available_at <= now)
        .order_by(TaskEventOutbox.id)
        .limit(_BATCH_LIMIT)
        .all()
    )
    # Lease the page so a second API process cannot double-publish.
    token = str(uuid4())
    lease_until = now + timedelta(seconds=max(5, int(getattr(settings, "TASK_EVENT_PUBLISH_INTERVAL_SECONDS", 2) or 2) * 4))
    for row in rows:
        row.status = "leasing"
        row.lease_token = token
        row.lease_until = lease_until
    return [(row.id, row.event_id, row.task_id, row.payload_json, int(row.attempts or 0)) for row in rows]


def _finalize_sync(db, event_id: str, *, error_code: str | None, attempts: int) -> None:
    row = db.query(TaskEventOutbox).filter(TaskEventOutbox.event_id == event_id).one_or_none()
    if row is None:
        return
    if error_code is None:
        row.status = "published"
        row.finished_at = datetime.utcnow()
        row.last_error_code = None
        return
    row.status = "pending"
    row.attempts = attempts + 1
    row.last_error_code = error_code[:80]
    row.available_at = datetime.utcnow() + timedelta(seconds=_backoff_seconds(row.attempts))


def _reclaim_sync(db, now: datetime) -> int:
    """Return abandoned leases to pending and drop old published rows."""
    stale = (
        db.query(TaskEventOutbox)
        .filter(TaskEventOutbox.status == "leasing", TaskEventOutbox.lease_until < now)
        .all()
    )
    for row in stale:
        row.status = "pending"
        row.lease_until = None
    cutoff = now - timedelta(hours=_RETENTION_HOURS)
    db.query(TaskEventOutbox).filter(
        TaskEventOutbox.status == "published", TaskEventOutbox.finished_at < cutoff,
    ).delete(synchronize_session=False)
    return len(stale)


async def publish_once() -> int:
    """Publish one batch; returns the number of events published."""
    from app.domains.ai.schemas.websocket import WSMessage
    from app.domains.websocket.ws.manager import manager

    published = 0
    for _row_id, event_id, task_id, payload, attempts in await run_db_txn(
        lambda db: _pending_sync(db, datetime.utcnow())
    ):
        error_code: str | None = None
        try:
            # Sequenced publish into the room journal; delivered==0 with no
            # subscribers still counts as success because the journal keeps it.
            await manager.send_message_to_room(
                task_id,
                WSMessage(type="chat_submission_update", payload=payload),
            )
            published += 1
        except Exception as exc:
            logger.warning(
                "Task event publish deferred: event_id={}, task_id={}, error={}",
                event_id, task_id, exc,
            )
            error_code = type(exc).__name__
        await run_db_txn(lambda db: _finalize_sync(
            db, event_id, error_code=error_code, attempts=attempts))
    return published


async def run_publisher() -> None:
    """Wake-driven loop with a bounded idle poll as the safety net."""
    global _WAKE
    _WAKE = asyncio.Event()
    interval = max(1, int(getattr(settings, "TASK_EVENT_PUBLISH_INTERVAL_SECONDS", 2) or 2))
    while not _SHUTTING_DOWN:
        try:
            await asyncio.wait_for(_WAKE.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
        _WAKE.clear()
        try:
            await publish_once()
            await run_db_txn(lambda db: _reclaim_sync(db, datetime.utcnow()))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Task event publisher iteration failed")


def start() -> None:
    global _TASK, _SHUTTING_DOWN
    if _TASK is not None and not _TASK.done():
        return
    _SHUTTING_DOWN = False
    _TASK = asyncio.create_task(run_publisher())
    _TASK.add_done_callback(_publisher_done)


def _publisher_done(task: asyncio.Task) -> None:
    global _TASK
    if _TASK is not task:
        return
    _TASK = None
    if task.cancelled():
        return
    try:
        error = task.exception()
    except asyncio.CancelledError:
        return
    if error is not None and not _SHUTTING_DOWN:
        logger.error("Task event publisher exited unexpectedly: {}", error)
        # Best-effort self-restart; the interval poll also recovers after restart.
        try:
            start()
        except RuntimeError:
            pass


async def shutdown() -> None:
    global _TASK, _SHUTTING_DOWN
    _SHUTTING_DOWN = True
    wake()
    task = _TASK
    _TASK = None
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
