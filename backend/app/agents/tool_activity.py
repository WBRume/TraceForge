"""Correlate and label normalized tool events within an agent attempt."""

import uuid
from datetime import datetime, timezone

from app.agents.events import AgentEvent
from app.protocols.tool_activity import ToolActivity, ToolKind

_NAMED_TOOLS: dict[str, ToolKind] = {
    "skill": "skill",
    "websearch": "web_search",
    "web_search": "web_search",
    "webfetch": "web_fetch",
    "web_fetch": "web_fetch",
}
_KNOWN_AGENTS = {"claude-code", "opencode", "dsh"}
_OPENCODE_MCP_SERVERS = ("traceforge_domain", "traceforge_playbook")


def mcp_tool_fields(server: object) -> dict[str, str]:
    """Adapt an explicit MCP server name without inferring one from tool input."""
    name = server.strip()[:200] if isinstance(server, str) else ""
    return {"mcp_server": name} if name else {}


def wire_event_time(value: object) -> str | None:
    """Accept ISO timestamps and epoch milliseconds from provider events."""
    if isinstance(value, str):
        return value or None
    if isinstance(value, (int, float)) and value >= 1_000_000_000_000:
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            pass
    return None


def _tool_identity(event: AgentEvent, name: str | None, skill_match: bool) -> tuple[ToolKind, str | None]:
    server = event.payload.get("mcp_server")
    explicit = event.payload.get("tool_kind")
    if server:
        return "mcp", server
    tool = (name or "").lower()
    if name and event.provider == "claude-code" and tool.startswith("mcp__"):
        parts = name.split("__", 2)
        if len(parts) == 3 and parts[1] and parts[2]:
            return "mcp", parts[1]
    if event.provider == "opencode":
        for server_name in _OPENCODE_MCP_SERVERS:
            if tool.startswith(f"{server_name}_"):
                return "mcp", server_name
    if explicit and explicit != "tool":
        return explicit, None
    if skill_match:
        return "skill", None
    kind = _NAMED_TOOLS.get(tool, "tool") if event.provider in _KNOWN_AGENTS else "tool"
    return kind, None


def event_time(value: str | None, received_at: datetime) -> datetime:
    """Use a timezone-aware event timestamp when the adapter supplies one."""
    if isinstance(value, str) and value:
        try:
            value = value[:-1] + "+00:00" if value.endswith("Z") else value
            occurred_at = datetime.fromisoformat(value)
            if occurred_at.tzinfo is not None:
                return occurred_at.astimezone(timezone.utc)
        except (ValueError, OverflowError):
            pass
    return received_at


class ToolActivityTracker:
    """Remember call metadata for providers whose results contain only a call ID."""

    def __init__(self) -> None:
        self._calls: dict[tuple[str, str], tuple[str | None, ToolKind, str | None]] = {}

    def reset(self) -> None:
        self._calls.clear()

    def record(
        self,
        event: AgentEvent,
        *,
        received_at: datetime,
        ai_job_id: str | None,
        session_turn_id: str | None,
        attempt: int | None,
        skill_match: bool = False,
    ) -> ToolActivity:
        key = (event.provider, event.payload["tool_use_id"])
        name = event.payload.get("tool_name")
        kind, server = _tool_identity(event, name, skill_match)
        previous = self._calls.get(key)
        if previous is not None:
            previous_name, previous_kind, previous_server = previous
            name = name or previous_name
            if kind == "tool":
                kind = previous_kind
            server = server or previous_server
        self._calls[key] = (name, kind, server)
        occurred_at = event_time(event.time, received_at)
        return ToolActivity(
            event_id=str(uuid.uuid4()),
            agent=event.provider,
            kind=kind,
            tool_name=name,
            mcp_server=server,
            ai_job_id=ai_job_id,
            session_turn_id=session_turn_id,
            attempt=attempt,
            occurred_at=occurred_at.isoformat(),
            received_at=received_at.isoformat(),
            time_source="server" if occurred_at is received_at else "agent_event",
        )
