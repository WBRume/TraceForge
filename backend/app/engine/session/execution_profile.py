"""Neutral opt-in execution boundaries; legacy requests are passed unchanged."""
from dataclasses import dataclass
import asyncio
import time
from typing import Protocol
from app.agents.contract import AgentRunRequest, AgentRunResult


class ExecutionProfile(Protocol):
    scope: "ExecutionScope"

    async def prepare_turn(self, engine, prompt: str) -> AgentRunRequest: ...
    async def before_dispatch(self, request: AgentRunRequest) -> None: ...
    async def on_event(self, event) -> None: ...
    async def after_provider_settled(self, result: AgentRunResult) -> None: ...
    async def on_error(self, error: BaseException) -> None: ...
    async def cancel(self, engine): ...


@dataclass(frozen=True)
class ExecutionScope:
    task_id: str
    scope_id: str = "main"
    parent_scope_id: str | None = None


class LegacyExecutionProfile:
    async def prepare_turn(self, request):
        return request

    async def before_dispatch(self, prepared):
        return None

    async def after_provider_settled(self, outcome):
        return None

    async def on_cancel(self):
        return None


async def run_profiled_turn(engine, prompt):
    """One shared provider entry; correctness hooks intentionally propagate errors.

The profile owns scope persistence and presentation. It cannot accidentally call
the main task's result/status projection through a best-effort legacy hook.
"""
    from app.agents.run_logging import run_agent_backend_with_logging
    from app.engine.session.registry import register_engine, unregister_engine
    profile = engine.execution_profile
    engine._run_task = asyncio.current_task()
    engine.running = True
    engine._reset_turn_state()
    registered = False
    try:
        request = await profile.prepare_turn(engine, prompt)
        register_engine(engine)
        registered = True
        await profile.before_dispatch(request)
        result = await run_agent_backend_with_logging(engine.cli, request, profile.on_event)
        engine.last_result = result
        engine.last_result_success = result.success
        engine.last_result_text = result.result_text
        engine.last_termination_confirmed_dead = result.termination_confirmed_dead
        engine.session_id = result.session_id or engine.session_id
        await profile.after_provider_settled(result)
        return result
    except BaseException as exc:
        await profile.on_error(exc)
        raise
    finally:
        engine.running = False
        engine._last_idle_since = time.monotonic()
        engine._run_task = None
        if registered:
            unregister_engine(engine.task_id, engine.scope_id)
