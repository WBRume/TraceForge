"""Agent 适配层统一契约（v0.2.0）。

"""

from __future__ import annotations

import uuid
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


ExecutionKind = Literal["LOCAL_PROCESS", "REMOTE_SESSION"]

EXECUTION_KIND_LOCAL_PROCESS: ExecutionKind = "LOCAL_PROCESS"
EXECUTION_KIND_REMOTE_SESSION: ExecutionKind = "REMOTE_SESSION"


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
    # 显式执行类别（doc 6.3/C4）：必须来自 durable job 行声明的
    # process_execution_kind，禁止通过“PID 是否为空”推断。
    execution_kind: ExecutionKind = EXECUTION_KIND_LOCAL_PROCESS


@dataclass(frozen=True)
class AgentStopResult:
    """唯一停止结果协议（doc 5）。

    - LOCAL_PROCESS：``stop_acknowledged`` 仅表示停止流程已执行；能否终态
      取决于 ``local_process_confirmed_dead``。
    - REMOTE_SESSION：``stop_acknowledged=True`` 必须来自服务端明确成功
      响应；禁止把方法未抛异常或返回 ``None`` 推断为成功。
    - 所有失败必须返回结构化结果；adapter 禁止吞掉异常后返回 ``None``。
    """

    execution_kind: ExecutionKind
    stop_acknowledged: bool
    local_process_started: bool = False
    local_process_confirmed_dead: bool | None = None
    failure_code: str | None = None
    error_message: str | None = None
    remaining_pids: tuple[int, ...] = ()


@dataclass(frozen=True)
class AttemptFinalizerEvidence:
    """唯一收敛输入（doc 6.1）：所有 finalizer 只接收该对象。

    ``termination_confirmed_dead`` 只对 LOCAL_PROCESS 有意义；
    ``remote_stop_acknowledged`` 只对 REMOTE_SESSION 有意义。
    failure code / remaining PIDs 仅作诊断，不得反向改变死亡状态。
    """

    execution_kind: ExecutionKind
    process_started: bool
    termination_confirmed_dead: bool | None
    remote_stop_acknowledged: bool | None
    failure_code: str | None
    error_message: str | None
    remaining_pids: tuple[int, ...]
    source: str
    remote_session_started: bool = False
    provider_outcome_seen: bool = False


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


class ProviderCallState(str, Enum):
    """单次 provider 调用的生命周期状态（doc 审计 07e04775 §4.2）。

    证据必须在 result 事件到达时登记（早于 JSON 解析、业务落库、错误转换
    和广播），而不是 helper 函数返回后补记。禁止把 ENDED 改回 STARTED：
    某些 bridge 的 session_id 晚于 result 到达。STARTED/UNKNOWN 是未决
    状态；ENDED 是唯一的终局结果证明。
    """

    NOT_STARTED = "NOT_STARTED"
    STARTED = "STARTED"
    ENDED = "ENDED"
    UNKNOWN = "UNKNOWN"


@dataclass
class ProviderCallEvidence:
    """一次 provider 调用的证据，按 call 身份登记、按 attempt 归属隔离。

    - ``call_id``：本次调用的唯一 id；typed 异常与返回值携带它，防止同
      attempt 的重试/多次调用相互冒用结果。
    - ``attempt_key``：(job_id, run_token, worker_boot_id)；解析证据时
      必须按 key 过滤，跨 attempt 的调用不得互相兜底。
    """

    call_id: str
    attempt_key: tuple = ()
    state: ProviderCallState = ProviderCallState.NOT_STARTED
    provider_session_id: str | None = None
    result_success: bool | None = None

    @property
    def resolved(self) -> bool:
        return self.state is ProviderCallState.ENDED

    @property
    def unresolved(self) -> bool:
        return self.state in (ProviderCallState.STARTED, ProviderCallState.UNKNOWN)


def agent_attempt_key(attempt: "AgentAttemptContext | None") -> tuple:
    """(job_id, run_token, worker_boot_id) 归属键；没有 attempt 时为空元组。

    空元组不与任何已登记 call 匹配：无 attempt 上下文的调用方不得消费
    attempt-local 的 provider 调用证据。
    """
    if attempt is None:
        return ()
    return (
        str(getattr(attempt, "job_id", "") or ""),
        str(getattr(attempt, "run_token", "") or ""),
        str(getattr(attempt, "worker_boot_id", "") or ""),
    )


def current_agent_attempt_key() -> tuple:
    """当前绑定 attempt 的归属键。"""
    return agent_attempt_key(_CURRENT_ATTEMPT.get())


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
    # REMOTE_SESSION 停止证据（attempt-local，唯一槽位，最新覆盖）。
    remote_stop_result: "AgentStopResult | None" = None
    # 远程会话是否已经建立（session_started 已发生）；用于把“从未建立远程
    # 会话”的取消与“会话存在但停止未被确认”区分开。
    remote_session_started: bool = False
    # provider 调用证据（doc 审计 07e04775 §4.2）：按 call_id 登记、按
    # attempt_key 隔离。终局 result 事件到达时必须立即写 ENDED，早于任何
    # 解析/落库/错误转换；异常路径只允许 STARTED -> UNKNOWN，已 ENDED 的
    # 证据绝不能被异常覆盖。进程重启后内存证据丢失仍按 durable locator /
    # reaper 流程处理，空 runtime 不等于“从未开始”。
    provider_calls: dict[str, ProviderCallEvidence] = field(default_factory=dict)

    def begin_provider_call(self, attempt_key: tuple) -> ProviderCallEvidence:
        """Register a brand-new provider call for this attempt.

        每次调用（含重试）都必须新建记录：begin 绝不复用上一轮 ENDED 的
        记录，否则前一次的终局证据会被冒用为本次的放行依据。
        """
        call = ProviderCallEvidence(
            call_id=uuid.uuid4().hex,
            attempt_key=tuple(attempt_key or ()),
        )
        self.provider_calls[call.call_id] = call
        return call

    def calls_for(self, attempt_key: tuple) -> list[ProviderCallEvidence]:
        """All provider calls registered for one attempt key (insertion order)."""
        key = tuple(attempt_key or ())
        if not key:
            return []
        return [
            call
            for call in self.provider_calls.values()
            if tuple(call.attempt_key or ()) == key
        ]

    def matches_current_attempt(self, call: ProviderCallEvidence) -> bool:
        """Whether the currently bound attempt still owns this call's events.

        迟到的回调（fence 变更/attempt 切换后）不得再写证据。
        """
        if call is None:
            return False
        return agent_attempt_key(_CURRENT_ATTEMPT.get()) == tuple(
            call.attempt_key or ()
        )

    def record_remote_stop(self, stop_result: "AgentStopResult | None") -> None:
        """Record the attempt's remote stop acknowledgement (latest wins)."""
        if stop_result is None:
            return
        self.remote_stop_result = stop_result

    @property
    def remote_stop_acknowledged(self) -> bool | None:
        stop = self.remote_stop_result
        if stop is None:
            return None
        return bool(stop.stop_acknowledged)

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
    def has_process_evidence(self) -> bool:
        """Whether this runtime carries any process/stop evidence at all.

        不能仅通过 ``process_started`` 判断：兼容 bridge 可能只有停止证据
        （孤立 termination 记录）而没有 STARTED 登记。
        """
        return bool(self.processes) or self.unidentified is not None

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


def record_attempt_remote_stop(stop_result: "AgentStopResult | None") -> None:
    """Record a REMOTE_SESSION stop acknowledgement into the bound attempt.

    Only a structured ``AgentStopResult`` is accepted: a bare ``None`` (the
    old "cancel returned nothing" shape) must never be read as success.
    """
    if stop_result is None:
        return
    state = _CURRENT_ATTEMPT_RUNTIME.get()
    if state is not None:
        state.record_remote_stop(stop_result)


def record_attempt_remote_session_started() -> None:
    """Mark that the remote session for this attempt has been established."""
    state = _CURRENT_ATTEMPT_RUNTIME.get()
    if state is not None:
        state.remote_session_started = True


def record_provider_call_session_started(
    call: "ProviderCallEvidence | None", session_id: Any = None
) -> None:
    """Register the provider session id on one call (NOT_STARTED -> STARTED).

    某些 bridge 的 session_id 晚于 result 到达：ENDED 是终局状态，绝不
    回退为 STARTED（doc 审计 07e04775 §4.3）。
    """
    if call is None:
        return
    session = str(session_id or "").strip()
    if session:
        call.provider_session_id = session
    if call.state == ProviderCallState.NOT_STARTED:
        call.state = ProviderCallState.STARTED


def record_provider_call_result(
    call: "ProviderCallEvidence | None", *, is_error: bool
) -> None:
    """Record a terminal provider result event on one call (-> ENDED).

    必须在 result 事件到达时立即调用：早于 JSON 解析、业务落库、错误
    转换和广播。ENDED 之后的重复 result / 迟到 session_id 不回退状态。
    """
    if call is None:
        return
    if call.state == ProviderCallState.ENDED:
        return
    call.state = ProviderCallState.ENDED
    call.result_success = not bool(is_error)


def mark_provider_call_unresolved(
    call: "ProviderCallEvidence | None",
) -> None:
    """Exception path: an in-flight call becomes UNKNOWN, never ENDED.

    已收到 result 的 ENDED 不能被异常覆盖；NOT_STARTED（从未建立会话）
    保持原状，不得伪造“已开始”。
    """
    if call is None:
        return
    if call.state == ProviderCallState.STARTED:
        call.state = ProviderCallState.UNKNOWN


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
    # 显式执行类别（doc 7 数据流链路）：与 backend capability 声明一致，
    # 由 bridge/engine 填充；不得通过“是否有本地 PID”推断。
    execution_kind: ExecutionKind = EXECUTION_KIND_LOCAL_PROCESS


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
    async def interrupt(self, run_id: str | None = None) -> "AgentStopResult":
        """中断当前回合，尽量保留会话；必须返回唯一停止结果。"""
        raise NotImplementedError

    @abstractmethod
    async def cancel(self, run_id: str | None = None) -> "AgentStopResult":
        """取消当前回合；必须返回唯一停止结果（doc 5）。"""
        raise NotImplementedError

    @abstractmethod
    async def cancel_persisted_session(self, session_id: str) -> "AgentStopResult":
        """按持久化 provider session id 停止远程会话（doc 修复方案 §9.3）。

        供 reaper 等无内存 runtime 的调用方使用：目标必须是显式传入的
        durable session id，禁止用 attempt ``run_id`` 或 adapter 内存的
        ``self._session_id`` 混淆。只有服务端明确成功响应才算
        ``stop_acknowledged=True``；本地执行类别（claude-code）不应被远程
        reaper 调用，若被调用必须返回结构化 capability 错误而不是 ACK。
        """
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
