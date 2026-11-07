"""Propagate scoped MCP bindings through the existing supervised agent lifecycle."""

from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import replace

from app.agents.errors import AgentConfigurationError

from .runtime import DomainToolRun
from .server import serve_tools

active_domain_run: ContextVar[DomainToolRun | None] = ContextVar("active_domain_run", default=None)
active_domain_binding: ContextVar[dict | None] = ContextVar("active_domain_binding", default=None)


@asynccontextmanager
async def bound_request(backend, request):
    binding = active_domain_binding.get()
    if binding is None:
        yield request
        return
    if backend.name == "opencode":
        from .opencode import scoped_request

        async with scoped_request(backend, request, binding) as scoped:
            yield scoped
        return
    if backend.name != "claude-code":
        raise AgentConfigurationError(
            f"DOMAIN_TOOLS_UNSUPPORTED: {backend.name} does not provide invocation-scoped MCP injection"
        )
    from .claude import provider_environment

    yield replace(
        request,
        env={**provider_environment(), **request.env},
        provider_options={**request.provider_options, "domain_mcp": binding},
    )


async def invoke_domain(run, operation, *, project_path):
    run_token = active_domain_run.set(run)
    run.project_path = project_path
    try:
        async with serve_tools(run) as binding:
            binding_token = active_domain_binding.set(binding)
            try:
                await run.emit("started", run.tool.description)
                try:
                    result = await operation()
                    value = run.require_result()
                    return result, value
                except Exception:
                    await run.emit("failed", "本次业务产物未能完成")
                    raise
            finally:
                active_domain_binding.reset(binding_token)
    finally:
        active_domain_run.reset(run_token)
