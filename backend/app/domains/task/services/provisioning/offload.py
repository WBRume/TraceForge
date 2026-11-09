"""Do not release a provisioning lock while its synchronous worker still writes."""

import asyncio
from collections.abc import Callable
from contextvars import copy_context
from typing import Any, TypeVar

from app.core.offload import run_db, run_git_job

T = TypeVar("T")


async def run_provision_io(fn: Callable[..., T], **kwargs: Any) -> T:
    context = copy_context()
    worker = asyncio.create_task(run_git_job(lambda: context.run(fn, **kwargs)))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        from app.agents import current_agent_attempt
        from app.domains.ai.services.jobs.registry import runtime

        attempt = current_agent_attempt()
        if attempt and not runtime.shutdown_in_progress():
            # Persist intent while the thread still runs, so its final artifact
            # transaction can arbitrate cancellation before publishing readiness.
            cancel = asyncio.create_task(run_db(_request_cancel, attempt.job_id))
            await _drain(cancel)
        # Cancelling run_in_executor cannot stop the thread or Git subprocess.
        # Drain it before compensation or releasing any surrounding lock.
        await _drain(worker)
        raise


def _request_cancel(job_id):
    from app.database import SessionLocal
    from app.domains.ai.services.jobs.domain_jobs import request_cancel

    with SessionLocal() as db:
        request_cancel(db, job_id)
        db.commit()


async def _drain(task):
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    if not task.cancelled():
        task.exception()
