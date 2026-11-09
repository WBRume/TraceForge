"""Do not release a provisioning lock while its synchronous worker still writes."""

import asyncio
from collections.abc import Callable
from contextvars import copy_context
from typing import Any, TypeVar

from app.core.offload import run_git_job

T = TypeVar("T")


async def run_provision_io(fn: Callable[..., T], **kwargs: Any) -> T:
    context = copy_context()
    worker = asyncio.create_task(run_git_job(lambda: context.run(fn, **kwargs)))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        # Cancelling run_in_executor cannot stop the thread or Git subprocess.
        # Drain it before compensation or releasing any surrounding lock.
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not worker.cancelled():
            worker.exception()
        raise
