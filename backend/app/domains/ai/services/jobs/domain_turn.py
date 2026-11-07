"""Typed business turn with durable milestones on the existing job WS channel."""

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from typing import Any, Generic, NotRequired, TypedDict, TypeVar

from pydantic import BaseModel

from app.agents import current_agent_attempt
from app.agents.domain_tools import DomainTool, DomainToolRun
from app.agents.domain_tools.invocation import invoke_domain
from app.agents.domain_tools.runtime import Milestone

T = TypeVar("T", bound=BaseModel)


class DomainTurnResult(TypedDict, Generic[T]):
    artifact: T
    domain_milestones: list[dict[str, Any]]
    session_id: NotRequired[str | None]
    text: NotRequired[str]
    provider_call_id: NotRequired[str | None]
    process_started: NotRequired[bool | None]
    termination_confirmed_dead: NotRequired[bool | None]


async def run_domain_turn(
    prompt: str,
    project_path: str,
    *,
    tool: DomainTool[T],
    on_milestone: Callable[[Milestone], Awaitable[None] | None] | None = None,
    timeout_seconds: float | None = None,
    **kwargs: Any,
) -> DomainTurnResult[T]:
    from . import provider_turn, state

    attempt = current_agent_attempt()
    milestones = []

    async def publish(event):
        milestones.append(event.model_dump())
        if on_milestone:
            outcome = on_milestone(event)
            if inspect.isawaitable(outcome):
                await outcome
        elif attempt:
            await state.update_job_state(
                attempt.job_id,
                message=event.message,
                context_patch={"domain_milestones": milestones[-100:]},
                run_token=attempt.run_token,
            )

    run = DomainToolRun(tool, on_milestone=publish, should_cancel=kwargs.get("should_cancel"))
    instructions = (
        prompt + f"\n\n必须调用 {tool.name} 工具提交业务产物。聊天文本不作为提交结果。"
        "工具会返回具体校验错误，请在当前会话中修正参数后重新调用；成功后结束本回合。"
    )
    kwargs.pop("max_attempts", None)

    async def operation():
        from app.agents.selection import default_backend_name

        options = {**kwargs, "backend_name": kwargs.get("backend_name") or default_backend_name()}
        return await provider_turn.run_cli_single_turn(instructions, project_path, max_attempts=1, **options)

    async with asyncio.timeout(timeout_seconds):
        result, value = await invoke_domain(run, operation, project_path=project_path)
    return {**result, "artifact": value, "domain_milestones": milestones}


def persisted_milestones(events: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    events = list(events or [])
    if events:
        events.append(
            {
                **events[-1],
                "sequence": events[-1]["sequence"] + 1,
                "stage": "persisted",
                "message": "业务产物已保存",
                "timestamp": time.time(),
                "issues": [],
            }
        )
    return events


async def mark_domain_persisted(job_id: str, result: DomainTurnResult) -> None:
    """Call only after the business transaction has committed."""
    from . import state

    events = persisted_milestones(result.get("domain_milestones"))
    if not events:
        return
    await state.update_job_state(job_id, context_patch={"domain_milestones": events})
