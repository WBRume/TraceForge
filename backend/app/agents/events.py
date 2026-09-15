"""统一 Agent 事件模型（v0.2.0）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

AgentEventType = Literal[
    "session_started",
    "model",
    "text",
    "text_delta",
    "thinking",
    "tool_use",
    "tool_result",
    "ask_user",
    "result",
    "error",
    "usage",
    "context_compacted",
    "log",
]


@dataclass
class AgentEvent:
    """归一化 Agent 事件。raw 必须保留 provider 原始事件用于审计。"""

    type: AgentEventType
    payload: dict[str, Any]
    provider: str
    raw: dict[str, Any] | None = None
    seq: int | None = None
    time: str | None = None
