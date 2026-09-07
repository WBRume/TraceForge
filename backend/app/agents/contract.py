"""Agent 适配层统一契约（v0.2.0）。

"""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
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


class ProcessDeathState(str, Enum):
    """单个本地进程的生命周期状态（按不可变身份独立记录）。

    迁移约束（doc 4.2）：
    - 不存在 -> STARTED
    - STARTED -> UNCONFIRMED
    - STARTED -> CONFIRMED_DEAD
    - UNCONFIRMED -> CONFIRMED_DEAD
    - CONFIRMED_DEAD -> CONFIRMED_DEAD（死亡是不可逆事实）

    禁止：CONFIRMED_DEAD -> UNCONFIRMED；不同身份的证据不得互相覆盖。
    """

    STARTED = "STARTED"
    UNCONFIRMED = "UNCONFIRMED"
    CONFIRMED_DEAD = "CONFIRMED_DEAD"


def agent_process_identity_key(identity: "AgentProcessIdentity | None") -> str:
    """Immutable identity key; must never be the PID alone.

    The computation is total: any malformed identity object degrades to a
    stable object-identity key instead of losing termination evidence.
    """
    if identity is None:
        return "unidentified"
    try:
        started_at = identity.started_at
        if started_at is None:
            started_ts = "0"
        else:
            started_ts = f"{float(started_at.timestamp()):.6f}"
        return (
            f"{int(identity.pid)}:{started_ts}:"
            f"{identity.process_group_id}:{identity.containment_id}"
        )
    except Exception:
        return f"identity-object:{id(identity)}"


@dataclass
class ProcessTerminationEvidence:
    """Evidence for one local process identified by an immutable identity."""

    identity: "AgentProcessIdentity | None" = None
    state: ProcessDeathState = ProcessDeathState.STARTED
    failure_code: str | None = None
    error: str | None = None
    remaining_pids: tuple[int, ...] = ()


@dataclass
class AgentAttemptRuntimeState:
    """本次 attempt 的进程生命周期证据（attempt-local，随 AgentAttemptContext 绑定）。

    证据按不可变进程身份（pid/started_at/pgid/containment）逐个保存，
    聚合语义（doc 4.1）：
    - True  : 所有已登记身份均为 CONFIRMED_DEAD。
    - False : 任一身份处于 UNCONFIRMED（无法证明死亡或仍有存活进程）。
    - None  : 无身份死亡未确认但有 STARTED 未决，或 attempt 无本地进程。

    同一 worker 内不同作业并发运行，因此该状态必须是 attempt-local，
    禁止使用进程级全局“最后一次 termination”变量。
    """

    processes: dict[str, ProcessTerminationEvidence] = field(default_factory=dict)
    # 非 supervisor 登记进程（stub/legacy bridge）的证据槽：这类来源无法
    # 提供不可变进程身份，且单进程语义下 STARTED -> UNCONFIRMED ->
    # CONFIRMED_DEAD 的迁移仍然适用。只有显式 record_process_started(None)
    # 才会把它计入 process_started；孤立的终止结果不得伪造“启动过进程”。
    unidentified: ProcessTerminationEvidence | None = None
    _unidentified_started: bool = False

    def record_process_started(
        self, identity: "AgentProcessIdentity | None" = None
    ) -> None:
        if identity is None:
            self._unidentified_started = True
            if self.unidentified is None:
                self.unidentified = ProcessTerminationEvidence(
                    identity=None,
                    state=ProcessDeathState.STARTED,
                )
            return
        key = agent_process_identity_key(identity)
        existing = self.processes.get(key)
        if existing is None:
            self.processes[key] = ProcessTerminationEvidence(
                identity=identity,
                state=ProcessDeathState.STARTED,
            )
        # STARTED/UNCONFIRMED/CONFIRMED_DEAD 均保持既有状态（幂等登记）。

    def record_termination(
        self,
        *,
        confirmed_dead: bool | None,
        identity: "AgentProcessIdentity | None" = None,
        failure_code: str | None = None,
        error: str | None = None,
        remaining_pids: tuple[int, ...] = (),
    ) -> None:
        key = agent_process_identity_key(identity)
        evidence = self.processes.get(key) if identity is not None else self.unidentified
        if evidence is None:
            if identity is None:
                # 未登记进程的孤立证据：单独保存，不得伪造 process_started。
                self.unidentified = ProcessTerminationEvidence(
                    identity=None,
                    state=(
                        ProcessDeathState.CONFIRMED_DEAD
                        if confirmed_dead is True
                        else ProcessDeathState.UNCONFIRMED
                        if confirmed_dead is False
                        else ProcessDeathState.STARTED
                    ),
                    failure_code=failure_code,
                    error=error,
                    remaining_pids=tuple(remaining_pids) if remaining_pids else (),
                )
                return
            if confirmed_dead is None:
                # 未知结果不得为未知身份制造证据。
                return
            evidence = ProcessTerminationEvidence(
                identity=identity,
                state=ProcessDeathState.STARTED,
            )
            self.processes[key] = evidence
        if confirmed_dead is None:
            # 未知结果不得覆盖已有明确结果；STARTED -> UNCONFIRMED 允许。
            if evidence.state == ProcessDeathState.STARTED:
                evidence.state = ProcessDeathState.UNCONFIRMED
                evidence.failure_code = failure_code or evidence.failure_code
                evidence.error = error or evidence.error
                if remaining_pids:
                    evidence.remaining_pids = tuple(remaining_pids)
            return
        if confirmed_dead is False:
            if evidence.state == ProcessDeathState.CONFIRMED_DEAD:
                # 死亡是不可逆事实；迟到的旧回调不能恢复成未确认状态。
                return
            evidence.state = ProcessDeathState.UNCONFIRMED
            evidence.failure_code = failure_code or evidence.failure_code
            evidence.error = error or evidence.error
            if remaining_pids:
                evidence.remaining_pids = tuple(remaining_pids)
            return
        # confirmed_dead is True：同一身份后续 True 收敛先前的
        # STARTED/UNCONFIRMED（doc 情况 A），并保持 CONFIRMED_DEAD 幂等。
        evidence.state = ProcessDeathState.CONFIRMED_DEAD
        evidence.failure_code = evidence.failure_code or failure_code
        evidence.error = evidence.error or error
        if not evidence.remaining_pids and remaining_pids:
            evidence.remaining_pids = tuple(remaining_pids)

    @property
    def process_started(self) -> bool:
        return bool(self.processes) or self._unidentified_started

    @property
    def termination_confirmed_dead(self) -> bool | None:
        states = [item.state for item in self.processes.values()]
        if self.unidentified is not None:
            states.append(self.unidentified.state)
        if not states:
            return None
        if all(state == ProcessDeathState.CONFIRMED_DEAD for state in states):
            return True
        if any(state == ProcessDeathState.UNCONFIRMED for state in states):
            return False
        return None

    @property
    def termination_failure_code(self) -> str | None:
        """Failure code of the first identity that blocks a clean death proof."""
        candidates = list(self.processes.values())
        if self.unidentified is not None:
            candidates.append(self.unidentified)
        for evidence in candidates:
            if evidence.state == ProcessDeathState.UNCONFIRMED and evidence.failure_code:
                return evidence.failure_code
        for evidence in candidates:
            if evidence.failure_code:
                return evidence.failure_code
        return None

    @property
    def termination_error(self) -> str | None:
        candidates = list(self.processes.values())
        if self.unidentified is not None:
            candidates.append(self.unidentified)
        for evidence in candidates:
            if evidence.state == ProcessDeathState.UNCONFIRMED and evidence.error:
                return evidence.error
        for evidence in candidates:
            if evidence.error:
                return evidence.error
        return None

    @property
    def remaining_pids(self) -> tuple[int, ...]:
        pids: list[int] = []
        candidates = list(self.processes.values())
        if self.unidentified is not None:
            candidates.append(self.unidentified)
        for evidence in candidates:
            if evidence.state != ProcessDeathState.CONFIRMED_DEAD:
                pids.extend(evidence.remaining_pids)
        return tuple(sorted(set(pids)))

    @property
    def unconfirmed_identities(self) -> list[ProcessTerminationEvidence]:
        """Identities whose death has not been confirmed (for diagnostics)."""
        candidates = list(self.processes.values())
        if self.unidentified is not None:
            candidates.append(self.unidentified)
        return [
            evidence
            for evidence in candidates
            if evidence.state != ProcessDeathState.CONFIRMED_DEAD
        ]


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


def record_attempt_process_started(identity: "AgentProcessIdentity | None" = None) -> None:
    """Mark that a local Agent process has started within the bound attempt.

    The identity is mandatory for supervisor-owned processes: evidence is
    keyed by the immutable process identity, never by the attempt alone.
    """
    state = _CURRENT_ATTEMPT_RUNTIME.get()
    if state is not None:
        state.record_process_started(identity)


def record_attempt_termination(
    termination: Any,
    identity: "AgentProcessIdentity | None" = None,
) -> None:
    """Record a TerminationResult-like object into the bound attempt state.

    The evidence is written for ``identity`` exactly; callers must not let a
    "last bridge" field guess which process a result belongs to.
    """
    if termination is None:
        return
    confirmed_dead = getattr(termination, "confirmed_dead", None)
    if confirmed_dead is not None:
        confirmed_dead = bool(confirmed_dead)
    state = _CURRENT_ATTEMPT_RUNTIME.get()
    if state is None:
        return
    state.record_termination(
        confirmed_dead=confirmed_dead,
        identity=identity,
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
    # Supervisor-side attach timeout for on_process_started (covers the real
    # DB attach, not just a bridge-forwarded future).  None keeps the legacy
    # behaviour where only the adapter's outer startup watchdog applies.
    process_attach_timeout_seconds: float | None = None
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
    # 执行类别声明（doc 6.3）：本地会创建受监管子进程的 backend 必须声明
    # LOCAL_PROCESS；服务端/远程会话 backend 必须显式声明 REMOTE_SESSION，
    # 不得通过“PID 为空”被推断。
    execution_kind: Literal["LOCAL_PROCESS", "REMOTE_SESSION"] = "LOCAL_PROCESS"


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
