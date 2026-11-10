"""MCP 2026 request metadata and HTTP mirroring; no session handshake."""

import base64
import uuid
from typing import Literal

from mcp.types import ClientCapabilities
from pydantic import Field

from app.protocols.base import Contract

MCP_VERSION = "2026-07-28"
VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
CAPABILITIES_KEY = "io.modelcontextprotocol/clientCapabilities"
CALL_KEY = "io.traceforge/callId"


class ProtocolError(ValueError):
    def __init__(self, code: int, message: str, data=None):
        super().__init__(message)
        self.code, self.data = code, data


class RpcRequest(Contract):
    jsonrpc: Literal["2.0"]
    id: str | int
    method: str = Field(min_length=1, max_length=100)
    params: dict


def decode_header(value: str | None):
    if value is None or any(ord(c) < 32 and c != "\t" or ord(c) > 126 for c in value):
        raise ProtocolError(-32020, "Missing or malformed MCP header")
    if value.startswith("=?base64?") and value.endswith("?="):
        try:
            return base64.b64decode(value[9:-2], validate=True).decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise ProtocolError(-32020, "Invalid Base64 MCP header") from exc
    if value != value.strip():
        raise ProtocolError(-32020, "Unencoded whitespace in MCP header")
    return value


def validate_request(message: RpcRequest, headers):
    meta = message.params.get("_meta")
    if not isinstance(meta, dict) or VERSION_KEY not in meta or CAPABILITIES_KEY not in meta:
        raise ProtocolError(-32602, "Required per-request protocol metadata missing")
    if not isinstance(meta[VERSION_KEY], str):
        raise ProtocolError(-32602, "Invalid protocol version metadata")
    if meta[VERSION_KEY] != MCP_VERSION:
        raise ProtocolError(
            -32022, "Unsupported protocol version", {"supported": [MCP_VERSION], "requested": meta[VERSION_KEY]}
        )
    try:
        ClientCapabilities.model_validate(meta[CAPABILITIES_KEY], strict=True)
    except ValueError as exc:
        raise ProtocolError(-32602, "Invalid client capabilities") from exc
    if headers.get("mcp-protocol-version") != meta[VERSION_KEY] or headers.get("mcp-method") != message.method:
        raise ProtocolError(-32020, "MCP headers do not match request")
    if message.method == "tools/call" and decode_header(headers.get("mcp-name")) != message.params.get("name"):
        raise ProtocolError(-32020, "Mcp-Name does not match tool")
    accept = headers.get("accept", "")
    if not all(mime in accept for mime in ("application/json", "text/event-stream")):
        raise ProtocolError(-32600, "Accept must include JSON and SSE")


class ListParams(Contract):
    meta: dict = Field(alias="_meta")


class CallParams(ListParams):
    name: str = Field(min_length=1)
    arguments: dict = Field(default_factory=dict)


def logical_call_id(meta: dict) -> str:
    if CALL_KEY not in meta:
        return uuid.uuid4().hex
    key = meta[CALL_KEY]
    if not isinstance(key, str) or not 1 <= len(key) <= 128:
        raise ProtocolError(-32602, "Invalid tool call identifier")
    return key
