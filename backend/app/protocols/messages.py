"""Typed application payloads inside the existing sequenced room envelope."""

from functools import reduce
from operator import or_
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, JsonValue, TypeAdapter, create_model

from app.domains.ai.schemas import websocket as ws
from app.domains.api_mock.schemas.api_mock import ApiMockJobResponse

from .base import Contract


class ApiMockJobEvent(Contract):
    type: Literal["job_update", "job_done"]
    project_id: str
    job: ApiMockJobResponse


PAYLOADS = {
    "tool_use": ws.WSToolUsePayload,
    "tool_result": ws.WSToolResultPayload,
    "thinking": ws.WSThinkingPayload,
    "result": ws.WSResultPayload,
    "status": ws.WSStatusPayload,
    "chat_message": ws.WSChatPayload,
    "log": ws.WSLogPayload,
    "job_update": ApiMockJobEvent,
    "job_done": ApiMockJobEvent,
}
STRICT_PAYLOADS = {
    kind: type(model.__name__ + "Contract", (model,), {"model_config": ConfigDict(extra="forbid", strict=True)})
    for kind, model in PAYLOADS.items()
}
MESSAGE_MODELS = {
    kind: create_model(
        kind.title().replace("_", "") + "Message",
        __base__=Contract,
        event_type=(Literal[kind], ...),
        payload=(payload, ...),
        contract_version=(Literal[2], ...),
    )
    for kind, payload in STRICT_PAYLOADS.items()
}
APPLICATION_MESSAGE = TypeAdapter(Annotated[reduce(or_, MESSAGE_MODELS.values()), Field(discriminator="event_type")])


class RoomEnvelope(Contract):
    contract_version: Literal[2]
    type: Literal["event"]
    room: str = Field(min_length=1)
    epoch: str = Field(min_length=1)
    sequence: int = Field(ge=1, le=9007199254740991)
    event_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    payload: JsonValue
    aggregate_id: str | None
    aggregate_version: int | None = Field(ge=0, le=9007199254740991)
    created_at: str


class TerminalRecord(Contract):
    contract_version: Literal[2]
    event_type: Literal["tool_use", "tool_result"]
    event_id: str
    payload: JsonValue


def validate_message(kind, payload):
    if kind in STRICT_PAYLOADS:
        STRICT_PAYLOADS[kind].model_validate(payload)
    return payload


def terminal_record(kind, payload, event_id):
    validate_message(kind, payload)
    return TerminalRecord(contract_version=2, event_type=kind, payload=payload, event_id=event_id).model_dump()
