import asyncio
from unittest.mock import Mock

import pytest

from app.core import background_tasks


@pytest.mark.asyncio
async def test_retains_pending_task_and_releases_completed_task():
    ready = asyncio.Event()
    task = background_tasks.retain_background_task(asyncio.create_task(ready.wait()))
    assert task in background_tasks._pending
    ready.set()
    assert await task is True
    await asyncio.sleep(0)
    assert task not in background_tasks._pending


@pytest.mark.asyncio
async def test_releases_cancelled_task_without_logging_failure(monkeypatch):
    logger = Mock()
    monkeypatch.setattr(background_tasks, "logger", logger)
    task = background_tasks.retain_background_task(asyncio.create_task(asyncio.Event().wait()))
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert task not in background_tasks._pending
    logger.opt.assert_not_called()


@pytest.mark.asyncio
async def test_observes_failure_and_releases_task(monkeypatch):
    logger = Mock()
    monkeypatch.setattr(background_tasks, "logger", logger)
    error = ValueError("failed")

    async def fail():
        raise error

    task = background_tasks.retain_background_task(asyncio.create_task(fail(), name="probe"))
    assert await asyncio.gather(task, return_exceptions=True) == [error]
    assert task not in background_tasks._pending
    logger.opt.assert_called_once_with(exception=error)
    logger.opt.return_value.error.assert_called_once_with("Background task failed: {}", "probe")
