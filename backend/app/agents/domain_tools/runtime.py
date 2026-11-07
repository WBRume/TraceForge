"""Validate inside the model's tool loop; never interpret assistant prose as data."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agents.tools import AgentToolDefinition, AgentToolResult

T = TypeVar("T", bound=BaseModel)


class DomainToolError(ValueError):
    """A correctable business validation error, safe to return to the agent."""


class DomainRunUnavailable(DomainToolError):
    """This invocation has ended; changing tool arguments cannot recover it."""


class Milestone(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    call_id: str
    sequence: int
    tool: str
    stage: Literal["started", "validating", "repairing", "accepted", "persisted", "failed"]
    message: str
    timestamp: float
    issues: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class DomainTool(Generic[T]):
    name: str
    description: str
    input_model: type[T]
    validate: Callable[[T], Awaitable[None] | None] | None = None

    def definition(self) -> AgentToolDefinition:
        return AgentToolDefinition(
            self.name,
            self.description + " 成功后本次提交结束；校验失败时依据工具错误修正并再次调用。",
            self.input_model.model_json_schema(),
        )


def tool_reply(*, error: bool = False, **payload) -> AgentToolResult:
    return AgentToolResult(data=payload, is_error=error)


class DomainToolRun(Generic[T]):
    """One terminal submission. Scope IDs and credentials are platform-owned.

    Acceptance is distinct from persistence: callers commit only after the
    provider has stopped and the existing attempt/version fences still hold.
    Repeated identical submissions return the same receipt without side effects.
    """

    def __init__(self, tool: DomainTool[T], *, on_milestone=None, should_cancel=None):
        self.tool = tool
        self.run_id = uuid.uuid4().hex
        self.on_milestone = on_milestone
        self.should_cancel = should_cancel
        self.value: T | None = None
        self.failure: Exception | None = None
        self.events: list[Milestone] = []
        self._digest: str | None = None
        self._receipt: AgentToolResult | None = None
        self._lock = asyncio.Lock()
        self._closed = False
        self.project_path: str = ""

    @property
    def definitions(self) -> tuple[AgentToolDefinition, ...]:
        from .workspace import READ_TOOL

        return READ_TOOL, self.tool.definition()

    async def emit(self, stage, message, *, call_id="", issues=None):
        event = Milestone(
            run_id=self.run_id,
            call_id=call_id,
            sequence=len(self.events) + 1,
            tool=self.tool.name,
            stage=stage,
            message=message,
            timestamp=time.time(),
            issues=issues or [],
        )
        self.events.append(event)
        if self.on_milestone:
            result = self.on_milestone(event)
            if inspect.isawaitable(result):
                await result

    def ensure_active(self):
        if self._closed or (self.should_cancel and self.should_cancel()):
            raise DomainRunUnavailable("DOMAIN_RUN_REVOKED")
        if self.failure:
            raise DomainRunUnavailable("DOMAIN_RUN_FAILED")

    async def invoke(self, name: str, arguments: dict, call_id: str) -> AgentToolResult:
        async with self._lock:
            try:
                self.ensure_active()
                if name == "read_workspace":
                    from .workspace import read_workspace

                    return tool_reply(**await asyncio.to_thread(read_workspace, self.project_path, arguments))
                if name != self.tool.name:
                    raise DomainToolError("UNKNOWN_DOMAIN_TOOL")
                digest = hashlib.sha256(json.dumps(arguments, sort_keys=True).encode()).hexdigest()
                if self._receipt:
                    if digest == self._digest:
                        return self._receipt
                    raise DomainToolError("DOMAIN_RESULT_ALREADY_ACCEPTED")
                if len(self.events) >= 100:
                    self.failure = DomainRunUnavailable("DOMAIN_TOOL_CALL_LIMIT")
                    raise self.failure
                await self.emit("validating", "正在校验业务产物", call_id=call_id)
                value = self.tool.input_model.model_validate(arguments, strict=True)
                if self.tool.validate:
                    checked = self.tool.validate(value)
                    if inspect.isawaitable(checked):
                        await checked
                self.ensure_active()
                self.value = value
                self._digest = digest
                self._receipt = tool_reply(accepted=True, run_id=self.run_id, call_id=call_id)
                await self.emit("accepted", "业务产物已通过校验，等待保存", call_id=call_id)
                return self._receipt
            except DomainRunUnavailable as exc:
                return tool_reply(error=True, code=str(exc), retryable=False)
            except (ValidationError, DomainToolError) as exc:
                issues = (
                    [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors(include_input=False)]
                    if isinstance(exc, ValidationError)
                    else [str(exc)]
                )
                await self.emit("repairing", "产物校验未通过，正在修正", call_id=call_id, issues=issues)
                return tool_reply(error=True, code="VALIDATION_FAILED", issues=issues)
            except Exception as exc:
                # Operational/programming failures must fail the turn, never be
                # downgraded to a valid artifact or an endless model repair loop.
                self.failure = exc
                await self.emit("failed", "业务工具执行失败", call_id=call_id)
                return tool_reply(error=True, code="DOMAIN_EXECUTION_FAILED", retryable=False)

    def require_result(self) -> T:
        if self.failure:
            raise self.failure
        self.ensure_active()
        if self.value is None:
            raise DomainToolError(f"DOMAIN_RESULT_MISSING: call {self.tool.name} before finishing")
        return self.value

    def close(self):
        self._closed = True
