"""统一 Agent 事件模型（v0.2.0）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

AgentEventType = Literal[
    "session_started",
    "model",
    "text",
    "text_delta",
    "thinking",
    "tool_use",
    "tool_result",
    "tool_progress",
    "ask_user",
    "ask_user_resolved",
    "result",
    "error",
    "usage",
    "context_compacted",
    "log",
]


@dataclass
class AgentEvent:
    """归一化 Agent 事件。raw 必须保留 provider 原始事件用于审计。

    ask_user_resolved 的 payload 使用 ask_user_id 关联原提问，status 为
    answered/cancelled/approved/rejected/closed，answer 为可选的 JSON 答案。
    closed 表示交互已结束但具体处理结果不可用。原生事件和状态由适配器
    归一化；通用引擎只消费这些字段，不依赖提供方名称或其协议。
    """

    type: AgentEventType
    payload: dict[str, Any]
    provider: str
    raw: dict[str, Any] | None = None
    seq: int | None = None
    time: str | None = None
