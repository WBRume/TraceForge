"""Agent 适配层统一异常。"""


class AgentError(Exception):
    """Agent 适配层基础异常。"""


class AgentTimeoutError(AgentError):
    """Agent 回合超时。"""

    def __init__(
        self,
        message: str,
        *,
        phase: str | None = None,
        limit_seconds: float | None = None,
        termination_confirmed_dead: bool | None = None,
    ):
        super().__init__(message)
        self.phase = phase
        self.limit_seconds = limit_seconds
        self.termination_confirmed_dead = termination_confirmed_dead
        self.failure_code = {
            "startup": "STARTUP_TIMEOUT",
            "idle": "IDLE_TIMEOUT",
            "hard": "HARD_TIMEOUT",
        }.get(str(phase or "").lower(), "AGENT_TIMEOUT")


class AgentCancelledError(AgentError):
    """Agent 回合被取消。"""


class AgentConfigurationError(AgentError):
    """Agent 配置错误（CLI 不存在、缺少凭据、能力声明不合法等）。"""


class AgentProtocolError(AgentError):
    """Agent 协议/事件解析错误。"""


class SessionForkError(AgentError):
    """会话 fork 失败（后端不支持或快照不可用）。"""
