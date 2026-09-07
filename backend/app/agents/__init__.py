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
    AgentStopResult,
    AttemptFinalizerEvidence,
    ExecutionKind,
    EXECUTION_KIND_LOCAL_PROCESS,
    EXECUTION_KIND_REMOTE_SESSION,
    ProcessDeathState,
    ProcessTerminationEvidence,
    SkillRef,
    TokenUsage,
    agent_process_identity_key,
    current_agent_attempt,
    bind_agent_attempt,
    reset_agent_attempt,
    current_agent_attempt_runtime,
    bind_agent_attempt_runtime,
    reset_agent_attempt_runtime,
    record_attempt_process_started,
    record_attempt_termination,
    record_attempt_remote_stop,
    record_attempt_remote_session_started,
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
    "AgentStopResult",
    "AttemptFinalizerEvidence",
    "ExecutionKind",
    "EXECUTION_KIND_LOCAL_PROCESS",
    "EXECUTION_KIND_REMOTE_SESSION",
    "ProcessDeathState",
    "ProcessTerminationEvidence",
    "agent_process_identity_key",
    "current_agent_attempt",
    "bind_agent_attempt",
    "reset_agent_attempt",
    "current_agent_attempt_runtime",
    "bind_agent_attempt_runtime",
    "reset_agent_attempt_runtime",
    "record_attempt_process_started",
    "record_attempt_termination",
    "record_attempt_remote_stop",
    "record_attempt_remote_session_started",
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
