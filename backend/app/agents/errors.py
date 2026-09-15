"""Agent 适配层统一异常。

typed 异常是跨 service 边界的兜底：任何包装/重试/回调都不得丢失
attempt 级终止证据（``termination_confirmed_dead`` / ``process_started``）。
attempt-local runtime state（见 contract.AgentAttemptRuntimeState）仍是最终权威。
"""


class AgentError(RuntimeError):
    """Agent 适配层基础异常。

    继承 RuntimeError 以保持既有 `except RuntimeError` 调用点的兼容
    （typed 异常替代裸 RuntimeError/TimeoutError 时不得破坏捕获语义）。

    只读终止证据字段：
    - termination_confirmed_dead: 进程树死亡证明（True/False/None 三态）。
    - process_started: 本地进程是否已启动（None 表示未知/无本地进程）。
    - failure_code: 结构化失败码；禁止通过 error message 字符串推断。
    - provider_call_id: 产生本异常的 provider 调用 id（doc 审计
      07e04775 §4.2）；证据必须按 call 身份归属，禁止跨调用冒用。
    """

    def __init__(
        self,
        message: str,
        *,
        termination_confirmed_dead: bool | None = None,
        process_started: bool | None = None,
        failure_code: str | None = None,
        provider_call_id: str | None = None,
    ):
        super().__init__(message)
        self.termination_confirmed_dead = termination_confirmed_dead
        self.process_started = process_started
        self.failure_code = failure_code
        self.provider_call_id = provider_call_id


class AgentTimeoutError(AgentError):
    """Agent 回合超时。"""

    def __init__(
        self,
        message: str,
        *,
        phase: str | None = None,
        limit_seconds: float | None = None,
        termination_confirmed_dead: bool | None = None,
        process_started: bool | None = None,
    ):
        super().__init__(
            message,
            termination_confirmed_dead=termination_confirmed_dead,
            process_started=process_started,
            failure_code={
                "startup": "STARTUP_TIMEOUT",
                "idle": "IDLE_TIMEOUT",
                "hard": "HARD_TIMEOUT",
            }.get(str(phase or "").lower(), "AGENT_TIMEOUT"),
        )
        self.phase = phase
        self.limit_seconds = limit_seconds


class AgentCancelledError(AgentError):
    """Agent 回合被取消。"""


class AgentProviderError(AgentError):
    """Agent provider 返回错误结果 / 非零退出（区别于超时与取消）。"""


class AgentConfigurationError(AgentError):
    """Agent 配置错误（CLI 不存在、缺少凭据、能力声明不合法等）。"""


class AgentProtocolError(AgentError):
    """Agent 协议/事件解析错误。"""


class SessionForkError(AgentError):
    """会话 fork 失败（后端不支持或快照不可用）。"""
