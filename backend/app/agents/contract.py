"""Agent 适配层统一契约（v0.2.0）。

"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from app.agents.events import AgentEvent
from app.agents.errors import AgentError, AgentConfigurationError

AgentEventSink = Callable[[AgentEvent], Awaitable[None]]


@dataclass
class SkillRef:
    """平台 Skill 引用。materialize_to 只是 hint，由 adapter 决定实际布局。"""

    name: str
    source_dir: str
    materialize_to: str | None = None


@dataclass
class AgentRunRequest:
    """一次 Agent 回合的输入。"""

    run_id: str | None = None
    prompt: str = ""
    project_path: str = ""
    session_id: str | None = None
    model: str | None = None
    provider_options: dict[str, Any] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    skills: list[SkillRef] = field(default_factory=list)
    # Backward-compatible hard runtime ceiling.  Liveness is governed primarily
    # by startup/idle activity timeouts so a productive long turn is not killed.
    timeout_seconds: float = 7200.0
    startup_timeout_seconds: float = 60.0
    idle_timeout_seconds: float = 600.0
    permission_mode: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenUsage:
    """统一 token 用量。"""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None
    total_tokens: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRunResult:
    """一次 Agent 回合的最终结果。"""

    run_id: str | None = None
    session_id: str = ""
    success: bool = False
    result_text: str = ""
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    return_code: int | None = None
    raw_trace: str | None = None
    # Provider-specific identifiers/checkpoint facts.  Values must be
    # metadata only; prompt/result text belongs to the normal job/message rows.
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentCapabilities:
    """adapter 能力声明。"""

    supports_resume: bool = True
    supports_streaming_text: bool = False
    supports_tool_events: bool = True
    # 是否支持把既有会话 fork 成独立新会话（baseline 复制上下文给评审线程）
    supports_fork: bool = False
    hitl_modes: list[Literal["turn_based", "long_connection"]] = field(default_factory=list)
    supports_usage: bool = True
    skill_layouts: list[str] = field(default_factory=list)
    preferred_mode: Literal["subprocess", "server", "sdk", "acp"] = "subprocess"


class AgentBackend(ABC):
    """TraceForge 统一 Agent 后端接口。"""

    name: str
    capabilities: AgentCapabilities

    @abstractmethod
    async def run(
        self,
        request: AgentRunRequest,
        on_event: AgentEventSink,
    ) -> AgentRunResult:
        """执行一个 Agent 回合。"""
        raise NotImplementedError

    @abstractmethod
    async def interrupt(self, run_id: str | None = None) -> None:
        """中断当前回合，尽量保留会话。"""
        raise NotImplementedError

    @abstractmethod
    async def cancel(self, run_id: str | None = None) -> None:
        """取消当前回合。"""
        raise NotImplementedError

    @abstractmethod
    def is_running(self, run_id: str | None = None) -> bool:
        """当前是否有未结束的回合。"""
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        """释放长驻资源；必须幂等。"""
        raise NotImplementedError

    async def respond_to_ask_user(self, ask_user_id: str, response: str) -> None:
        """可选：长连接 HITL 模式下回传用户回复。"""
        raise AgentError("HITL response not supported")

    async def probe(self) -> str:
        """轻量连通性探测：确认 Agent 底座可接入。

        adapter 应尽量提供免实际模型调用的连通性检查；
        默认未实现时由测试端点给出“后端实例创建成功”的降级结果。
        """
        raise AgentError(f"{self.name} backend does not implement probe")

    async def fork_session(
        self,
        session_id: str,
        *,
        source_dir: str,
        target_dir: str,
    ) -> str:
        """可选：把 source_dir 中已存在的会话 fork 成 target_dir 下的独立新会话。

        返回新会话 id；原会话必须保持只读不被污染。
        baseline → 评审线程的上下文复用依赖该方法。
        """
        from app.agents.errors import SessionForkError

        raise SessionForkError(f"{self.name} does not support session fork")

    def _validate_request(self, request: AgentRunRequest) -> None:
        if not self.capabilities.supports_resume and request.session_id:
            raise AgentConfigurationError(
                f"{self.name} does not support resume but got session_id={request.session_id}"
            )
        if "long_connection" in self.capabilities.hitl_modes and type(self).respond_to_ask_user is AgentBackend.respond_to_ask_user:
            raise AgentConfigurationError(
                f"{self.name} declares long_connection HITL but does not implement respond_to_ask_user"
            )
