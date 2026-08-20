"""OpenCode Agent backend。

Spike 结论：`opencode run --format json` 在 Windows 当前环境因 shell 探测失败，
`opencode serve` 可稳定提供 SSE/HTTP API，因此 OpenCode 采用 **server 模式**接入。
本文件先提供 AgentBackend 骨架，事件映射已完成（见 event_mapper.py）。
"""

from __future__ import annotations

from typing import Any, Optional

from app.agents.contract import (
    AgentBackend,
    AgentCapabilities,
    AgentEventSink,
    AgentRunRequest,
    AgentRunResult,
)
from app.agents.errors import AgentError


class OpenCodeAdapter(AgentBackend):
    name = "opencode"
    capabilities = AgentCapabilities(
        supports_resume=True,
        supports_streaming_text=True,
        supports_tool_events=True,
        hitl_modes=["turn_based", "long_connection"],
        supports_usage=True,
        skill_layouts=["opencode"],
        preferred_mode="server",
    )

    def __init__(self, server_url: str = "http://127.0.0.1:4097") -> None:
        self.server_url = server_url.rstrip("/")
        self._running = False
        self._run_id: Optional[str] = None

    async def run(self, request: AgentRunRequest, on_event: AgentEventSink) -> AgentRunResult:
        # 骨架：Server 模式 HTTP 驱动将在下一轮基于实测 SSE/HTTP 组装。
        raise AgentError(
            "OpenCodeAdapter.run() is a spike skeleton; "
            "wire it to `opencode serve` HTTP/SSE after contract review"
        )

    async def interrupt(self, run_id: str | None = None) -> None:
        # TODO: POST /api/session/{sessionID}/interrupt
        self._running = False

    async def cancel(self, run_id: str | None = None) -> None:
        # TODO: POST /api/session/{sessionID}/abort
        self._running = False

    def is_running(self, run_id: str | None = None) -> bool:
        return self._running

    async def close(self) -> None:
        self._running = False
        self._run_id = None

    async def respond_to_ask_user(self, ask_user_id: str, response: str) -> None:
        # TODO: POST /api/session/{sessionID}/permission/.../reply 或 /question/.../reply
        raise AgentError("OpenCodeAdapter HITL response is not wired yet")