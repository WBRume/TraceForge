"""Provider-independent payloads. Raw provider diagnostics stay outside them."""

from functools import reduce
from operator import or_
from typing import Annotated, Literal

from pydantic import Field, JsonValue, TypeAdapter, create_model

from .base import Contract

Identifier = Annotated[str, Field(min_length=1, max_length=200)]


class TextPayload(Contract):
    text: str
    delta: str | None = None
    provider: str | None = None
    model: str | None = None
    usage: dict[str, JsonValue] | None = None


class DeltaPayload(Contract):
    delta: str
    text: str | None = None
    provider: str | None = None


class ToolUsePayload(Contract):
    tool_use_id: Identifier
    tool_name: Identifier
    tool_input: JsonValue
    provider: str | None = None


class ToolResultPayload(Contract):
    tool_use_id: Identifier
    output: str
    is_error: bool
    content: list[dict[str, JsonValue]] = Field(default_factory=list)
    structured_content: JsonValue = None
    provider_replay: bool = False
    provider: str | None = None


class ToolProgressPayload(Contract):
    tool_use_id: Identifier
    message: str


class SessionPayload(Contract):
    provider_session_id: Identifier
    model: str | None = None
    directory: str | None = None
    provider: str | None = None


class ModelPayload(Contract):
    model: Identifier
    source: str | None = None
    provider: str | None = None


class UsagePayload(Contract):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cache_read_tokens: int | None = Field(default=None, ge=0)
    cache_creation_tokens: int | None = Field(default=None, ge=0)
    thinking_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    tool_io_tokens: int | None = Field(default=None, ge=0)
    tool_output_tokens: int | None = Field(default=None, ge=0)
    raw_usage: JsonValue = None
    provider: str | None = None


class ResultPayload(Contract):
    success: bool
    result: str
    session_id: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    finish_reason: str | None = None
    usage: JsonValue = None
    provider: str | None = None


class LogPayload(Contract):
    level: Literal["trace", "debug", "info", "warning", "warn", "error", "critical"]
    message: str


class QuestionPayload(Contract):
    ask_user_id: Identifier
    kind: str | None = None
    question: str | None = None
    prompt: str | None = None
    fields: JsonValue = None
    options: JsonValue = None
    resource: JsonValue = None
    resources: JsonValue = None
    permission_request: JsonValue = None


class ResolutionPayload(Contract):
    ask_user_id: Identifier
    status: Literal["answered", "cancelled", "approved", "rejected", "closed"]
    answer: JsonValue = None


class CompactionPayload(Contract):
    summary: str | None = None
    subtype: str | None = None
    event_type: str | None = None
    source: str | None = None
    token_before: int | None = None
    token_after: int | None = None


PAYLOADS = {
    "session_started": SessionPayload,
    "model": ModelPayload,
    "text": TextPayload,
    "text_delta": DeltaPayload,
    "thinking": TextPayload,
    "tool_use": ToolUsePayload,
    "tool_result": ToolResultPayload,
    "tool_progress": ToolProgressPayload,
    "result": ResultPayload,
    "error": ResultPayload,
    "usage": UsagePayload,
    "log": LogPayload,
    "ask_user": QuestionPayload,
    "ask_user_resolved": ResolutionPayload,
    "context_compacted": CompactionPayload,
}
EVENT_MODELS = {
    kind: create_model(
        kind.title().replace("_", "") + "Event",
        __base__=Contract,
        type=(Literal[kind], ...),
        payload=(payload, ...),
        provider=(Identifier, ...),
        contract_version=(Literal[2], ...),
    )
    for kind, payload in PAYLOADS.items()
}
AGENT_EVENT = TypeAdapter(Annotated[reduce(or_, EVENT_MODELS.values()), Field(discriminator="type")])
