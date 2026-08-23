"""Agent 适配层统一异常。"""


class AgentError(Exception):
    """Agent 适配层基础异常。"""


class AgentTimeoutError(AgentError):
    """Agent 回合超时。"""


class AgentCancelledError(AgentError):
    """Agent 回合被取消。"""


class AgentConfigurationError(AgentError):
    """Agent 配置错误（CLI 不存在、缺少凭据、能力声明不合法等）。"""


class AgentProtocolError(AgentError):
    """Agent 协议/事件解析错误。"""


class SessionForkError(AgentError):
    """会话 fork 失败（后端不支持或快照不可用）。"""