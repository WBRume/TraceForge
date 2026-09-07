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
    AgentAttemptRuntimeState,
    AgentProcessIdentity,
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
    current_agent_attempt_runtime,
    bind_agent_attempt_runtime,
    reset_agent_attempt_runtime,
    record_attempt_process_started,
    record_attempt_termination,
)
from app.agents.events import AgentEvent
from app.agents.errors import (
    AgentCancelledError,
    AgentConfigurationError,
    AgentError,
    AgentProtocolError,
    AgentProviderError,
    AgentTimeoutError,
)

__all__ = [
    "AgentBackend",
    "AgentAttemptContext",
    "AgentAttemptRuntimeState",
    "AgentProcessIdentity",
    "AgentCapabilities",
    "AgentEvent",
    "AgentEventSink",
    "current_agent_attempt",
    "bind_agent_attempt",
    "reset_agent_attempt",
    "current_agent_attempt_runtime",
    "bind_agent_attempt_runtime",
    "reset_agent_attempt_runtime",
    "record_attempt_process_started",
    "record_attempt_termination",
    "AgentRunRequest",
    "AgentRunResult",
    "AgentCancelledError",
    "AgentConfigurationError",
    "AgentError",
    "AgentProtocolError",
    "AgentProviderError",
    "AgentTimeoutError",
    "SkillRef",
    "TokenUsage",
]
