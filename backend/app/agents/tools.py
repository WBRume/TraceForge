"""Invocation-scoped tools, independent of provider and transport protocols."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class AgentToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]

    def __post_init__(self):
        from app.protocols.schema import checked_schema

        object.__setattr__(self, "input_schema", checked_schema(self.input_schema))
        object.__setattr__(self, "output_schema", checked_schema(self.output_schema))


@dataclass(frozen=True)
class AgentToolResult:
    data: Any
    is_error: bool = False


class AgentToolContext(Protocol):
    """Only these tools may run; the owner revokes callbacks when the turn ends.

    Adapters must return each result to the same model turn, including validation
    errors, and remove their binding on success, failure, timeout or cancellation.
    They must isolate tools/permissions from other sessions and never persist
    callbacks or credentials in reusable provider configuration.
    """

    @property
    def definitions(self) -> tuple[AgentToolDefinition, ...]: ...

    async def invoke(self, name: str, arguments: dict, call_id: str) -> AgentToolResult: ...
