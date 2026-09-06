"""
Agent 适配层。

阶段 2 契约骨架：
- contract.py   : AgentBackend / AgentRunRequest / AgentRunResult / AgentCapabilities
- events.py     : 统一 AgentEvent
- errors.py     : 统一异常
- registry.py   : Agent backend 注册与创建
- adapters/     : claude-code / opencode / dsh / mock 等实现
"""

from app.agents.contract import (
    AgentAttemptContext,
    AgentBackend,
    AgentCapabilities,
    AgentRunRequest,
    AgentRunResult,
    AgentEventSink,
    SkillRef,
    TokenUsage,
    current_agent_attempt,
    bind_agent_attempt,
    reset_agent_attempt,
)
from app.agents.events import AgentEvent
from app.agents.errors import (
    AgentCancelledError,
    AgentConfigurationError,
    AgentError,
    AgentProtocolError,
    AgentTimeoutError,
)

__all__ = [
    "AgentBackend",
    "AgentAttemptContext",
    "AgentCapabilities",
    "AgentEvent",
    "AgentEventSink",
    "current_agent_attempt",
    "bind_agent_attempt",
    "reset_agent_attempt",
    "AgentRunRequest",
    "AgentRunResult",
    "AgentCancelledError",
    "AgentConfigurationError",
    "AgentError",
    "AgentProtocolError",
    "AgentTimeoutError",
    "SkillRef",
    "TokenUsage",
]
