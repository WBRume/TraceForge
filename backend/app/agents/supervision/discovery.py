"""run-token / spawn-token 的 /proc 发现与逐身份终止。

所有本地 CLI 及其后代在 spawn 时继承精确 token（attempt 级
``TRACEFORGE_RUN_TOKEN`` + per-spawn ``TRACEFORGE_SPAWN_TOKEN``），同 UID
进程的 environ 精确 NUL 分隔匹配因此是谱系归属证据（doc 修复方案 §6.4）。

扫描完整性语义：任何"无法检查"（权限/IO 错误）的候选 PID 都会把整个
快照降级为 UNKNOWN——空 ``matches`` 只有在没有任何 UNKNOWN 时才是死亡
证明。归属校验 = 精确 token 匹配 + 受信任的创建时间窗口
（:func:`token_identity_ok`）；create time 不可读的匹配保持冲突，不盲杀。

:func:`converge_token_kill` 是"扫描 → 分区 → 逐身份安全发送 → 重扫"的
唯一收敛循环，被持久化回收（``stop_persisted``）与 token discovery
（``stop_by_run_token_discovery``）共用。
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple

try:  # psutil is used for create-time and descendant verification.
    import psutil
except ImportError:  # pragma: no cover - packaging/runtime guard
    psutil = None  # type: ignore[assignment]

from app.core.logging import get_logger
from app.agents.supervision.identity import signal_after_identity_recheck
from app.agents.supervision.inspection import (
    InspectionQueueSaturated,
    run_process_probe,
)
from app.agents.supervision.model import (
    RUN_TOKEN_ENV_VAR,
    SPAWN_TOKEN_ENV_VAR,
    TOKEN_DISCOVERY_UNKNOWN,
    ProcessProbeState,
)

logger = get_logger(__name__, category="agent_process")

# 默认强杀信号：Windows 没有 SIGKILL，模块导入必须无平台差异；POSIX 路径
# 显式传 SIGKILL 保持不变，非 POSIX 的受保护路径不会走到该发送分支。
_DEFAULT_KILL_SIGNAL: int = getattr(signal, "SIGKILL", signal.SIGTERM)


@dataclass(frozen=True)
class DiscoveredTokenProcess:
    """Identity captured at scan time for one exact-token process match."""

    pid: int
    process_group_id: Optional[int] = None
    create_time: Optional[float] = None
    command: str = ""
    command_readable: bool = False


@dataclass(frozen=True)
class TokenDiscoverySnapshot:
    """One complete run-token /proc discovery sample (doc 修复方案 §6.4).

    ``matches`` 只包含 environ 精确命中且仍在扫描时存活的进程；任何无法
    检查（权限/IO 错误）的 PID 记录在 ``unknown_pids`` 并把整个快照降级为
    UNKNOWN。空 ``matches`` 只有在没有任何 UNKNOWN 时才是死亡证明。
    """

    state: ProcessProbeState = ProcessProbeState.UNKNOWN
    matches: Tuple[DiscoveredTokenProcess, ...] = ()
    unknown_pids: Tuple[int, ...] = ()
    failure_code: Optional[str] = None
    error_message: Optional[str] = None


def candidate_predates_attempt(proc, not_before: Optional[datetime]) -> bool:
    """Narrow, verifiable exclusion for environ-unreadable candidates (P0-2).

    只有``not_before`` 可信且候选 create time 可读、且严格早于 attempt 边界
    时，才能证明该进程不可能继承本 attempt 的 token；命令名不是归属证据，
    任何无法证明的候选都必须保留为 UNKNOWN。
    """
    if not_before is None:
        return False
    try:
        expected = (
            not_before if not_before.tzinfo else not_before.replace(tzinfo=timezone.utc)
        )
        create_time = float(proc.create_time())
    except (psutil.Error, OSError, ValueError, AttributeError, TypeError):
        return False
    return create_time < expected.timestamp() - 2.0


def scan_token_processes_sync(
    run_token: str,
    not_before: Optional[datetime] = None,
    *,
    env_var: str = RUN_TOKEN_ENV_VAR,
) -> TokenDiscoverySnapshot:
    """One complete same-UID exact-token /proc scan (executor-side only).

    仅同 UID 进程、environ 精确 NUL 分隔匹配（``env_var``；默认 attempt 级
    run token，spawn 谱系扫描传 :data:`SPAWN_TOKEN_ENV_VAR`）、排除自身。
    异常语义（doc 修复方案 §6.4 + 审计 P0-2）：
    - 单个 PID NoSuchProcess / zombie -> 该 PID 已消失，继续扫描；
    - environ 不可读的候选：命令名不是归属证据（普通工具子进程同样继承
      token），只有 :func:`candidate_predates_attempt` 的可验证排除成立时
      才跳过；否则记入 ``unknown_pids``，快照 UNKNOWN（正确性优先于收敛，
      绝不静默丢弃可能携带 token 的目标）；
    - ``process_iter`` 本身失败 -> 整个快照 UNKNOWN。
    """
    if os.name == "nt":
        return TokenDiscoverySnapshot(
            state=ProcessProbeState.UNKNOWN,
            failure_code="TOKEN_DISCOVERY_UNAVAILABLE",
            error_message="run-token discovery requires Linux /proc",
        )
    if psutil is None:
        return TokenDiscoverySnapshot(
            state=ProcessProbeState.UNKNOWN,
            failure_code="PROCESS_INSPECTION_UNAVAILABLE",
            error_message="psutil is required for run-token discovery",
        )
    token = str(run_token or "").strip()
    if not token:
        return TokenDiscoverySnapshot(
            state=ProcessProbeState.UNKNOWN,
            failure_code=TOKEN_DISCOVERY_UNKNOWN,
            error_message="run token is empty; discovery cannot be performed",
        )
    try:
        current_uid = os.getuid()
    except AttributeError:
        current_uid = None
    matches: list = []
    unknown: list = []
    error_message: Optional[str] = None

    def _record_unknown(pid: int, exc: BaseException) -> None:
        nonlocal error_message
        unknown.append(int(pid))
        error_message = error_message or (str(exc) or type(exc).__name__)

    try:
        iterator = psutil.process_iter(["pid"])
    except (psutil.Error, OSError) as exc:
        return TokenDiscoverySnapshot(
            state=ProcessProbeState.UNKNOWN,
            failure_code=TOKEN_DISCOVERY_UNKNOWN,
            error_message=str(exc) or type(exc).__name__,
        )
    try:
        for proc in iterator:
            try:
                pid = int(proc.pid)
            except (psutil.Error, ValueError):
                continue
            try:
                if pid == os.getpid():
                    continue
            except OSError:
                pass
            if current_uid is not None:
                try:
                    if proc.uids().real != current_uid:
                        continue
                except psutil.NoSuchProcess:
                    continue
                except (psutil.AccessDenied, psutil.Error, OSError) as exc:
                    _record_unknown(pid, exc)
                    continue
            # P0-2：不再按命令名预过滤。普通工具子进程（sleep/bash/python/
            # git…）与 CLI 一样继承 token，也可能脱离原 PGID；可读取 environ
            # 的同 UID 候选一律执行精确 token 匹配。
            try:
                environ = proc.environ()
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except (psutil.AccessDenied, psutil.Error, OSError) as exc:
                # 僵尸进程正在退出：environ 不可读属于退出语义，不是存活
                # token 目标（与模块内"zombie == 明确退出"语义一致）。
                try:
                    if proc.status() == psutil.STATUS_ZOMBIE:
                        continue
                except (psutil.NoSuchProcess, psutil.ZombieProcess):
                    continue
                except (psutil.AccessDenied, psutil.Error, OSError, AttributeError):
                    # status 不可读（无法核实退出状态）：继续走排除规则。
                    pass
                # environ 不可读：只有"启动时间早于本 attempt"的可验证证据
                # 才允许排除；无法证明时保留 UNKNOWN（不能牺牲正确性换取
                # 收敛）。
                if candidate_predates_attempt(proc, not_before):
                    continue
                _record_unknown(pid, exc)
                continue
            if environ.get(env_var) != token:
                continue
            pgid: Optional[int] = None
            try:
                pgid = os.getpgid(pid)
            except ProcessLookupError:
                # 精确命中却在身份捕获前消失：正常消失，继续扫描。
                continue
            except (PermissionError, OSError):
                pgid = None
            create_time: Optional[float] = None
            try:
                create_time = float(proc.create_time())
            except (psutil.Error, OSError, ValueError):
                create_time = None
            command = ""
            command_readable = False
            try:
                command = " ".join(proc.cmdline()).lower()
                command_readable = True
            except (psutil.Error, OSError, ValueError):
                command_readable = False
            matches.append(
                DiscoveredTokenProcess(
                    pid=pid,
                    process_group_id=pgid,
                    create_time=create_time,
                    command=command,
                    command_readable=command_readable,
                )
            )
    except (psutil.Error, OSError) as exc:
        return TokenDiscoverySnapshot(
            state=ProcessProbeState.UNKNOWN,
            failure_code=TOKEN_DISCOVERY_UNKNOWN,
            error_message=str(exc) or type(exc).__name__,
        )
    if matches:
        return TokenDiscoverySnapshot(
            state=ProcessProbeState.LIVE,
            matches=tuple(matches),
            unknown_pids=tuple(sorted(unknown)),
            failure_code=TOKEN_DISCOVERY_UNKNOWN if unknown else None,
            error_message=error_message,
        )
    if unknown:
        return TokenDiscoverySnapshot(
            state=ProcessProbeState.UNKNOWN,
            unknown_pids=tuple(sorted(unknown)),
            failure_code=TOKEN_DISCOVERY_UNKNOWN,
            error_message=error_message
            or f"{len(unknown)} process(es) could not be inspected",
        )
    return TokenDiscoverySnapshot(state=ProcessProbeState.CONFIRMED_DEAD)


def scan_spawn_token_processes_sync(
    spawn_token: str,
    not_before: Optional[datetime] = None,
) -> TokenDiscoverySnapshot:
    """Spawn-lineage scan: identical rules, keyed on the per-spawn token.

    P0-3：``TRACEFORGE_SPAWN_TOKEN`` 由 spawn 时注入且 uuid4 不可预测，
    任何携带者都可证明属于该次 spawn 的后代树。
    """
    return scan_token_processes_sync(
        spawn_token, not_before, env_var=SPAWN_TOKEN_ENV_VAR
    )


async def token_snapshot(
    run_token: str,
    not_before: Optional[datetime] = None,
    *,
    env_var: str = RUN_TOKEN_ENV_VAR,
) -> TokenDiscoverySnapshot:
    """One complete token scan off the loop (UNKNOWN on queue saturation)."""
    fn = (
        scan_token_processes_sync
        if env_var == RUN_TOKEN_ENV_VAR
        else scan_spawn_token_processes_sync
    )
    try:
        return await run_process_probe(fn, run_token, not_before)
    except InspectionQueueSaturated as exc:
        return TokenDiscoverySnapshot(
            state=ProcessProbeState.UNKNOWN,
            failure_code="INSPECTION_QUEUE_SATURATED",
            error_message=str(exc),
        )


def token_identity_ok(
    match: DiscoveredTokenProcess,
    *,
    not_before: Optional[datetime],
    not_after: Optional[datetime],
) -> bool:
    """Validate a discovered token match against trusted identity bounds.

    P0-2：普通工具命令不能仅因缺少命令名 marker 被排除；归属依据是
    精确 token 匹配加上受信任的创建时间窗口。create time 不可读时
    身份无法核实，保持冲突（不盲杀）。
    """
    if match.create_time is None:
        return False
    if not_before is not None:
        expected = not_before if not_before.tzinfo else not_before.replace(tzinfo=timezone.utc)
        if match.create_time < expected.timestamp() - 2.0:
            return False
    if not_after is not None:
        expected = not_after if not_after.tzinfo else not_after.replace(tzinfo=timezone.utc)
        if match.create_time > expected.timestamp() + 2.0:
            return False
    return True


def partition_token_matches(
    matches: Tuple[DiscoveredTokenProcess, ...],
    *,
    not_before: Optional[datetime],
    not_after: Optional[datetime],
) -> Tuple[Tuple[DiscoveredTokenProcess, ...], Tuple[DiscoveredTokenProcess, ...]]:
    """Split token matches into (killable, identity-conflicts)."""
    good: list = []
    conflicts: list = []
    for match in matches:
        if token_identity_ok(match, not_before=not_before, not_after=not_after):
            good.append(match)
        else:
            conflicts.append(match)
    return tuple(good), tuple(conflicts)


async def kill_token_matches(
    matches: Tuple[DiscoveredTokenProcess, ...],
    signals: list,
    *,
    sig: int = _DEFAULT_KILL_SIGNAL,
    signal_name: str = "SIGKILL",
) -> None:
    """Signal each verified token identity — never the numeric group (P0-2).

    精确 token 命中一个进程不等于取得整个进程组的归属：禁止从单个
    match 无条件升级 ``killpg``（同组可能混入携带其他 token/无 token
    的无关进程）。每个 match 以扫描时捕获的 create time 为原身份，经
    P0-1 的共用安全发送入口重新验证后逐个发送；身份在扫描到发送之间
    变化/不可读时跳过（保持未确认，由调用方的重扫收敛）。谱系清理以
    ``sig``/``signal_name`` 指定 TERM→KILL 升级阶段；默认仍是 SIGKILL。
    """
    for match in matches:
        outcome = await signal_after_identity_recheck(
            int(match.pid),
            match.create_time,
            sig,
            signals,
            signal_name,
        )
        if outcome == "unverified":
            logger.warning(
                "Token process identity changed/unreadable between scan and "
                "send; signal skipped: pid={}",
                match.pid,
            )


@dataclass(frozen=True)
class TokenContainmentOutcome:
    """Structured result of one token kill/verify convergence.

    - ``unknown`` 非 None：扫描不完整，调用方必须返回 UNKNOWN 并保留
      ownership；
    - ``conflicts`` 非 ()：身份冲突的匹配（从未发送），调用方必须保持
      未确认并要求人工处理；
    - 否则 ``live_pids`` 是最终仍存活的 token 进程（空 == 完整扫描无命中，
      CONFIRMED_DEAD）。
    """

    state: ProcessProbeState = ProcessProbeState.CONFIRMED_DEAD
    live_pids: Tuple[int, ...] = ()
    unknown: Optional[TokenDiscoverySnapshot] = None
    conflicts: Tuple[DiscoveredTokenProcess, ...] = ()
    # 收敛过程中是否执行过任何发送尝试（诊断证据：loop 中途发现冲突时，
    # 之前的信号已经发出，调用方必须如实上报 tree_kill_used）。
    kill_attempted: bool = False


def _outcome_of_final(final: TokenDiscoverySnapshot) -> TokenContainmentOutcome:
    if final.state == ProcessProbeState.UNKNOWN:
        return TokenContainmentOutcome(state=ProcessProbeState.UNKNOWN, unknown=final)
    if final.state == ProcessProbeState.LIVE:
        return TokenContainmentOutcome(
            state=ProcessProbeState.LIVE,
            live_pids=tuple(sorted(int(m.pid) for m in final.matches)),
        )
    return TokenContainmentOutcome(state=ProcessProbeState.CONFIRMED_DEAD)


async def converge_token_kill(
    run_token: str,
    *,
    not_before: Optional[datetime],
    not_after: Optional[datetime],
    signals: list,
    initial: TokenDiscoverySnapshot,
    max_wait: float = 5.0,
) -> TokenContainmentOutcome:
    """Scan → partition → per-identity send → rescan, until converged (P0-2).

    ``stop_persisted`` 的 token 兜底与 ``stop_by_run_token_discovery`` 共用
    同一收敛循环；两处差异仅在入口预检（discovery 的 double-scan grace）与
    结果映射，循环体完全一致：

    - 初始快照 UNKNOWN 立即失败（调用方保持 ownership，doc 审计 P0-3B）；
    - 身份冲突绝不发送、绝不盲杀（不盲杀复用后的新进程）；
    - 每轮只对"重探身份一致"的目标发送；``sent`` 不是死亡证明，必须重扫；
    - 截止后取最后一次快照作为结构化证据。
    """
    if initial.state == ProcessProbeState.UNKNOWN:
        return TokenContainmentOutcome(state=ProcessProbeState.UNKNOWN, unknown=initial)
    if not initial.matches:
        # 没有可发送目标：取一次最终快照作为证据（不在收敛循环中追加
        # 杀死迟到匹配——由调用方下次重试时自然覆盖，doc §6.4）。
        final = await token_snapshot(run_token, not_before)
        return _outcome_of_final(final)
    good, conflicts = partition_token_matches(
        initial.matches, not_before=not_before, not_after=not_after
    )
    if conflicts:
        return TokenContainmentOutcome(state=ProcessProbeState.LIVE, conflicts=conflicts)
    if good:
        await kill_token_matches(good, signals)
        kill_attempted = True
    else:
        kill_attempted = False
    deadline = time.monotonic() + max(0.1, max_wait)
    while True:
        snapshot = await token_snapshot(run_token, not_before)
        if snapshot.state == ProcessProbeState.UNKNOWN:
            return TokenContainmentOutcome(
                state=ProcessProbeState.UNKNOWN, unknown=snapshot, kill_attempted=kill_attempted
            )
        if snapshot.state == ProcessProbeState.CONFIRMED_DEAD:
            return TokenContainmentOutcome(
                state=ProcessProbeState.CONFIRMED_DEAD, kill_attempted=kill_attempted
            )
        good, conflicts = partition_token_matches(
            snapshot.matches, not_before=not_before, not_after=not_after
        )
        if conflicts:
            return TokenContainmentOutcome(
                state=ProcessProbeState.LIVE, conflicts=conflicts, kill_attempted=kill_attempted
            )
        if good:
            await kill_token_matches(good, signals)
            kill_attempted = True
        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(0.1)
    # 最终一次快照给出聚合证据。
    final = await token_snapshot(run_token, not_before)
    outcome = _outcome_of_final(final)
    return TokenContainmentOutcome(
        state=outcome.state,
        live_pids=outcome.live_pids,
        unknown=outcome.unknown,
        conflicts=outcome.conflicts,
        kill_attempted=kill_attempted,
    )
