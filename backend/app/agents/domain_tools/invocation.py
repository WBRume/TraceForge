"""Bind business tools through the provider-independent Agent contract."""

from contextlib import asynccontextmanager
from contextvars import ContextVar

from .runtime import DomainToolRun

active_domain_run: ContextVar[DomainToolRun | None] = ContextVar("active_domain_run", default=None)


@asynccontextmanager
async def bound_request(backend, request):
    run = active_domain_run.get()
    if run is None:
        yield request
        return
    async with backend.bind_tools(request, run) as scoped:
        yield scoped


async def invoke_domain(run, operation, *, project_path):
    run_token = active_domain_run.set(run)
    run.project_path = project_path
    try:
        await run.emit("started", run.tool.description)
        try:
            result = await operation()
            return result, run.require_result()
        except Exception:
            await run.emit("failed", "本次业务产物未能完成")
            raise
    finally:
        run.close()
        active_domain_run.reset(run_token)
