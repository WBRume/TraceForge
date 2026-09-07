"""Agent 适配层统一契约（v0.2.0）。

"""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Literal

from app.agents.events import AgentEvent
from app.agents.errors import AgentError, AgentConfigurationError

AgentEventSink = Callable[[AgentEvent], Awaitable[None]]
AgentProcessStartedCallback = Callable[["AgentProcessIdentity"], Awaitable[bool] | bool]


@dataclass(frozen=True)
class AgentProcessIdentity:
    """Immutable identity captured before an Agent process can emit events."""

    pid: int
    started_at: datetime
    process_group_id: int | None = None
    containment_id: str | None = None


@dataclass(frozen=True)
class AgentAttemptContext:
    """不可变的执行 attempt 归属，作为所有 Agent 回调的 fence。"""

    job_id: str
    task_id: str | None
    queue_key: str
    run_token: str
    worker_id: str
    worker_boot_id: str
    attempt_count: int


_CURRENT_ATTEMPT: ContextVar[AgentAttemptContext | None] = ContextVar(
    "traceforge_current_agent_attempt", default=None
)


def current_agent_attempt() -> AgentAttemptContext | None:
    return _CURRENT_ATTEMPT.get()


def bind_agent_attempt(attempt: AgentAttemptContext):
    """Bind an attempt for the current asyncio task; caller resets the token."""
    return _CURRENT_ATTEMPT.set(attempt)


def reset_agent_attempt(token) -> None:
    _CURRENT_ATTEMPT.reset(token)


@dataclass
class AgentAttemptRuntimeState:
    """本次 attempt 的进程生命周期证据（attempt-local，随 AgentAttemptContext 绑定）。

    语义约定（三态）：
    - True  : 本地进程树已由 supervisor 确认全部死亡。
    - False : 已确认无法证明进程树死亡，或仍有存活进程。
    - None  : 尚未取得任何终止证据（无本地进程，或证据丢失）。

    多次记录时 False 优先级高于 True；未知结果不得覆盖已有明确结果。
    同一 worker 内不同作业并发运行，因此该状态必须是 attempt-local，
    禁止使用进程级全局“最后一次 termination”变量。
    """

    process_started: bool = False
    termination_confirmed_dead: bool | None = None
    termination_failure_code: str | None = None
    termination_error: str | None = None
    remaining_pids: tuple[int, ...] = ()

    def record_process_started(self) -> None:
        self.process_started = True

    def record_termination(
        self,
        *,
        confirmed_dead: bool | None,
        failure_code: str | None = None,
        error: str | None = None,
        remaining_pids: tuple[int, ...] = (),
    ) -> None:
        if confirmed_dead is None:
            # 未知结果不得覆盖已有明确结果。
            return
        if confirmed_dead is False:
            self.termination_confirmed_dead = False
            self.termination_failure_code = failure_code or self.termination_failure_code
            self.termination_error = error or self.termination_error
            if remaining_pids:
                self.remaining_pids = tuple(remaining_pids)
            return
        if self.termination_confirmed_dead is False:
            # False 更保守，不能被后续成功证据降级。
            return
        self.termination_confirmed_dead = True
        self.termination_failure_code = self.termination_failure_code or failure_code
        self.termination_error = self.termination_error or error
        if not self.remaining_pids and remaining_pids:
            self.remaining_pids = tuple(remaining_pids)


_CURRENT_ATTEMPT_RUNTIME: ContextVar[AgentAttemptRuntimeState | None] = ContextVar(
    "traceforge_current_agent_attempt_runtime", default=None
)


def current_agent_attempt_runtime() -> AgentAttemptRuntimeState | None:
    return _CURRENT_ATTEMPT_RUNTIME.get()


def bind_agent_attempt_runtime(state: AgentAttemptRuntimeState):
    """Bind attempt-local runtime evidence; caller resets the token."""
    return _CURRENT_ATTEMPT_RUNTIME.set(state)


def reset_agent_attempt_runtime(token) -> None:
    _CURRENT_ATTEMPT_RUNTIME.reset(token)


def record_attempt_process_started() -> None:
    """Mark that a local Agent process has started within the bound attempt."""
    state = _CURRENT_ATTEMPT_RUNTIME.get()
    if state is not None:
        state.record_process_started()


def record_attempt_termination(termination: Any) -> None:
    """Record a TerminationResult-like object into the bound attempt state."""
    if termination is None:
        return
    confirmed_dead = getattr(termination, "confirmed_dead", None)
    if confirmed_dead is None:
        return
    state = _CURRENT_ATTEMPT_RUNTIME.get()
    if state is None:
        return
    state.record_termination(
        confirmed_dead=bool(confirmed_dead),
        failure_code=getattr(termination, "error_code", None),
        error=getattr(termination, "error_message", None),
        remaining_pids=tuple(getattr(termination, "remaining_pids", ()) or ()),
    )


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
    on_process_started: AgentProcessStartedCallback | None = None


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
    # For locally supervised processes this is the supervisor's authoritative
    # process-tree death result.  Server backends leave it unset.
    termination_confirmed_dead: bool | None = None
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
