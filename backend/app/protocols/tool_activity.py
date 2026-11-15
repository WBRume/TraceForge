"""Tool event metadata shared by the live terminal and history replay."""

from typing import Literal

from pydantic import Field

from .base import Contract

ToolKind = Literal["tool", "mcp", "skill", "web_search", "web_fetch"]


class ToolActivity(Contract):
    event_id: str
    agent: str
    kind: ToolKind
    tool_name: str | None = None
    mcp_server: str | None = None
    ai_job_id: str | None = None
    session_turn_id: str | None = None
    attempt: int | None = None
    occurred_at: str
    received_at: str
    time_source: Literal["agent_event", "server"]
    truncated: bool = Field(default=False)
