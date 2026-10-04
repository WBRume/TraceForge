"""Keep detached tasks alive until completion and observe their failures."""

import asyncio
from typing import Any, TypeVar

from app.core.logging import get_logger

logger = get_logger(__name__)
_pending: set[asyncio.Task[Any]] = set()
_Result = TypeVar("_Result")


def retain_background_task(task: asyncio.Task[_Result]) -> asyncio.Task[_Result]:
    """Transfer a detached task's lifetime to the process-local registry."""
    _pending.add(task)
    task.add_done_callback(_completed)
    return task


def _completed(task: asyncio.Task[Any]) -> None:
    _pending.discard(task)
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.opt(exception=error).error("Background task failed: {}", task.get_name())
