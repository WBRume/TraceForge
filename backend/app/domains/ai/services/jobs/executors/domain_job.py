"""Dispatch durable domain work under the queue's bound attempt."""

import asyncio

from app.core.offload import run_db
from app.database import SessionLocal
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.ai.services.jobs import state


def load(job_id):
    with SessionLocal() as db:
        receipt = db.get(SddAiJob, job_id)
        return dict(receipt.context_json or {}), (receipt.completion_json or {}).get("outcome")


async def run_sync(fn, *args, **kwargs):
    # asyncio cancellation cannot stop a worker thread. Keep its attempt alive
    # until it has observed cancellation and drained its provider/filesystem IO.
    worker = asyncio.create_task(asyncio.to_thread(fn, *args, **kwargs))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
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


async def dispatch(job_id: str, context: dict, status: str) -> None:
    kind = context["job_kind"]
    inputs = context.get("inputs") or {}
    if status not in {"SUCCESS", "FAILED", "CANCELLED"}:
        if kind == "SKILL_ANALYSIS":
            from app.domains.skill.services import skill_analysis_service

            await skill_analysis_service._run_analysis_in_thread(job_id)
        elif kind == "API_MOCK":
            from app.domains.api_mock.services import api_mock_service

            handlers = {
                "SYNC_TASK_SOURCE": api_mock_service.run_sync_job_background,
                "IMPORT_SWAGGER": api_mock_service.run_import_job_background,
                "AUTO_GENERATE_MOCK_CASES": api_mock_service.run_auto_mock_job_background,
            }
            params = dict(inputs)
            job_type = params.pop("job_type")
            await run_sync(handlers[job_type], job_id, **params)
        elif kind == "PROVISION":
            from app.domains.workflow.services import provision_job_service

            handlers = {
                "CREATE_TASK": provision_job_service.run_create_task_job,
                "CREATE_WORKSPACE": provision_job_service.run_create_workspace_job,
                "IMPORT_SKILL": provision_job_service.run_import_skill_job,
            }
            # Redis locks and resource clients belong to the application loop.
            # Filesystem work is offloaded by run_provision_io inside the workflow.
            await handlers[inputs["job_type"]](job_id)
        else:
            raise ValueError(f"Unsupported domain job kind: {kind}")


async def finalize_cancel(job_id: str) -> bool:
    # run_db deliberately does not propagate context; carry the attempt for the
    # token-checked cancellation transition explicitly through a context copy.
    from contextvars import copy_context

    from app.domains.ai.services.jobs import domain_jobs

    context_copy = copy_context()
    return await run_db(lambda: context_copy.run(domain_jobs.begin_cancel_finalization, job_id))


async def execute(job_id: str) -> None:
    context, status = await run_db(load, job_id)
    try:
        await dispatch(job_id, context, status)
    except Exception:
        if await finalize_cancel(job_id):
            return
        raise
    if await finalize_cancel(job_id):
        return
    _, status = await run_db(load, job_id)
    await state.update_job_state(
        job_id,
        status=AiJobStatus(status) if status else AiJobStatus.FAILED,
        progress=100,
        finalize=True,
    )
