"""上一轮 boot 遗留进程的回收与验证（reaper / ORPHANED 修复路径）。

worker 重启后 reaper 只持有持久化的 PID + create time + PGID + run token。
本模块在"身份归属未验证之前绝不发送信号"的前提下收回这些进程（doc 修复
方案 §5.4 + 审计 P0-1/P0-3）：

- root identity 探测；root 不存在只表示 root 已死亡，不代表 containment
  为空；
- root 身份已被复用（或探测 UNKNOWN/存活但身份无法核实）时，数字 PGID
  不可信：逐成员验证归属，只对验证过的残留目标用稳定句柄单独发信号；
- 提供持久化 run token 时执行完整 token discovery（与
  :func:`stop_by_run_token_discovery` 共用 discovery 的收敛循环），捕获
  脱离原 PGID 的后代；
- 只有 root/group/token discovery 都明确为空才允许 ``confirmed_dead=True``；
  任一探测 UNKNOWN 返回 ``None`` 并保留结构化 failure code。

:func:`verify_persisted_cleanup` 是纯验证入口（不发信号），供
confirm-cleanup API 使用，避免误杀已复用的 PID。
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
from datetime import datetime
from typing import Callable, Dict, Optional, Tuple

try:  # psutil is used for create-time and descendant verification.
    import psutil
except ImportError:  # pragma: no cover - packaging/runtime guard
    psutil = None  # type: ignore[assignment]

from app.agents.supervision import discovery, identity, persisted, windows
from app.agents.supervision.model import (
    PROCESS_GROUP_UNKNOWN,
    PROCESS_TREE_UNKNOWN,
    TOKEN_DISCOVERY_UNKNOWN,
    ProcessProbeState,
    TerminationResult,
)
from app.agents.supervision.persisted import (
    aggregate_persisted_snapshots,
    expected_started_timestamp,
    group_snapshot,
    root_snapshot,
    wait_group_gone,
    wait_root_gone,
)


async def run_token_containment(
    run_token: str,
    *,
    not_before: Optional[datetime],
    signals: list,
) -> discovery.TokenContainmentOutcome:
    """One token scan + kill/verify convergence (shared persistence fallback)."""
    initial = await discovery.token_snapshot(run_token, not_before)
    return await discovery.converge_token_kill(
        run_token,
        not_before=not_before,
        not_after=None,
        signals=signals,
        initial=initial,
        max_wait=5.0,
    )


def _token_conflict_result(
    conflicts: Tuple[discovery.DiscoveredTokenProcess, ...],
) -> TerminationResult:
    """Identity-conflict termination result (token matches never blindly killed)."""
    return TerminationResult(
        False,
        None,
        elapsed_ms=0,
        error_code="TOKEN_PROCESS_IDENTITY_CONFLICT",
        error_message=(
            f"{len(conflicts)} run-token process(es) failed identity "
            "validation; manual handling required"
        ),
        remaining_pids=tuple(sorted(int(m.pid) for m in conflicts)),
    )


async def stop_reused_group_members(
    member_pids: Tuple[int, ...],
    *,
    old_root_started_at: Optional[datetime],
    reused_create_time: Optional[float],
    signals: list,
) -> persisted.PersistedProcessSnapshot:
    """P0-1: reused/unverifiable-root case — never signal the numeric PGID.

    root PID 复用后，持久化 PGID（通常等于旧 root PID）可能被新进程组
    重新占用：旧组成员与新组成员共存于同一数字组。整组 ``killpg`` 会
    误杀。规则：
    - 身份可验证（create time 落在 [旧 root 起点, PID 复用时刻) 区间）
      的成员是原 attempt 的残留目标，允许用稳定句柄逐个发信号，且
      发送前必须重新比较原身份；
    - 其余成员（create time 不可读 / 落在复用之后 / 早于旧 root）归属
      不明，绝不发信号，聚合为 UNKNOWN 交上层保留 ownership。root
      探测 UNKNOWN（复用与否无法证明）时没有可信上界，同样不允许
      对任何成员发信号。
    """
    expected_root_start = expected_started_timestamp(old_root_started_at)
    verified: Dict[int, Optional[float]] = {}
    ambiguous: set = set()
    for member in member_pids:
        member_identity = await identity.probe_member_identity(int(member))
        if member_identity.gone:
            continue
        ok_bounds = (
            expected_root_start is not None
            and reused_create_time is not None
            and member_identity.create_time is not None
            and member_identity.create_time >= expected_root_start - 2.0
            and member_identity.create_time < reused_create_time
        )
        if ok_bounds:
            verified[int(member)] = float(member_identity.create_time)
        else:
            ambiguous.add(int(member))
    unresolved = await identity.terminate_verified_members(verified, signals)
    if ambiguous or unresolved:
        return persisted.PersistedProcessSnapshot(
            state=ProcessProbeState.UNKNOWN,
            live_pids=tuple(sorted(ambiguous | unresolved)),
            failure_code="PROCESS_GROUP_OWNERSHIP_UNVERIFIED",
            error_message=(
                "Reused PGID group contains member(s) whose ownership could "
                "not be verified; whole-group signaling is forbidden"
            ),
        )
    return persisted.PersistedProcessSnapshot(state=ProcessProbeState.CONFIRMED_DEAD)


async def stop_persisted(
    pid: Optional[int],
    process_started_at: Optional[datetime],
    reason: str,
    process_group_id: Optional[int] = None,
    run_token: Optional[str] = None,
    not_before: Optional[datetime] = None,
) -> TerminationResult:
    """Stop a process from a previous boot only after ownership checks.

    Linux 顺序（doc 修复方案 §5.4 + 审计 P0-1/P0-3）：
    1. 探测 root identity；root 不存在只表示 root 已死亡，不代表
       containment 为空（P0-1）；
    2. root 身份未复用时，PGID 仍存活即使 root 已消失也发送
       SIGTERM/SIGKILL；
    3. root 身份已被复用（或探测 UNKNOWN/存活但身份无法核实）时，数字
       PGID 不可信：逐成员验证归属，只对验证过的残留目标用稳定句柄
       单独发信号（发送前重新比较原身份）；归属不明/混合归属组绝不
       整组发信号，保持 UNKNOWN（doc 审计 P0-1）；
    4. 等待 root 与 PGID 的聚合三态快照收敛；
    5. 提供持久化 run token 时执行完整 token discovery，捕获脱离原
       PGID 的后代；token 的存活/未知证据参与最终 state（P0-3B）；
    6. 只有 group 与 token discovery 都明确为空才允许
       ``confirmed_dead=True``；任一探测 UNKNOWN 返回 ``None`` 并保留
       结构化 failure code。
    """
    started = time.monotonic()
    if not pid:
        return TerminationResult(True, None, elapsed_ms=0)
    if psutil is None:
        return TerminationResult(
            False, None, elapsed_ms=0,
            error_code="PROCESS_INSPECTION_UNAVAILABLE",
            error_message="psutil is required to reclaim persisted process ownership",
        )
    pid = int(pid)

    def _result(
        confirmed_dead: Optional[bool],
        *,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        signals: Tuple[str, ...] = (),
        tree_kill_used: bool = False,
        remaining_pids: Tuple[int, ...] = (),
        root_identity_matches: Optional[bool] = None,
    ) -> TerminationResult:
        return TerminationResult(
            confirmed_dead,
            None,
            signals_sent=tuple(signals),
            tree_kill_used=tree_kill_used,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            error_code=error_code,
            error_message=error_message,
            remaining_pids=tuple(remaining_pids),
            root_identity_matches=root_identity_matches,
        )

    if os.name == "nt":
        return await stop_persisted_windows(pid, process_started_at, _result)

    # ── 1. root identity probe（单次快照，不阻塞事件循环）──
    root = await root_snapshot(pid, process_started_at, check_command_marker=True)
    pid_reused = root.failure_code == "PID_REUSED"
    # 身份无法核实的存活 root（无关命令行/命令行不可读/创建时间不可读）
    # 绝不发信号（与旧行为一致，只是不再把探测错误折叠成 False）。
    may_signal_root = (
        root.state == ProcessProbeState.LIVE and root.failure_code is None
    )
    signals: list = []
    if root.state == ProcessProbeState.CONFIRMED_DEAD and pid_reused:
        # root 身份已被另一个进程占用：禁止把复用 PID 当作 PGID。
        group_id = int(process_group_id) if process_group_id else None
    else:
        group_id = int(process_group_id) if process_group_id else pid

    # ── 2/3. 进程组信号与等待（root 已消失时仍处理 PGID）──
    group = await group_snapshot(
        group_id,
        ignored_pids={pid} if pid_reused else None,
    )
    need_signal = may_signal_root or group.state == ProcessProbeState.LIVE
    root_unverified_live = root.state == ProcessProbeState.LIVE and not may_signal_root
    # P0-1：root 探测 UNKNOWN（探测异常/身份完全不可读）与 LIVE-unverified
    # 同属"身份无法核实"——root 是否被复用无法证明，数字 PGID 不能凭
    # "组非空"获得整组发送资格，必须走逐成员归属验证分支。
    root_unverifiable = root_unverified_live or (
        root.state == ProcessProbeState.UNKNOWN
    )
    if (pid_reused or root_unverifiable) and group.state == ProcessProbeState.LIVE:
        # P0-1：root 身份已被复用（或存活但身份无法核实/探测 UNKNOWN）——
        # 数字 PGID 不能单凭"组非空"获得整组发送资格：复用后的组可能混入
        # 无关新进程组成员。逐成员验证归属，只对验证过的残留目标用稳定
        # 句柄单独发信号（发送前再次比较原身份）；归属不明/混合归属组
        # 绝不发信号，保持 UNKNOWN 交上层保留 ownership/ORPHANED。root
        # 明确消失（未被复用占用）时不受此限：pgid 数字无人占用，killpg
        # 只会命中原组残留成员（正常清理路径，doc §5.4）。
        group = await stop_reused_group_members(
            tuple(group.live_pids),
            old_root_started_at=process_started_at,
            reused_create_time=(
                getattr(root, "pid_create_time", None) if pid_reused else None
            ),
            signals=signals,
        )
    elif need_signal:
        sent_group = False
        if group_id is not None:
            try:
                os.killpg(group_id, signal.SIGTERM)
                sent_group = True
            except (ProcessLookupError, PermissionError, OSError):
                sent_group = False
        if sent_group:
            signals.append("SIGTERM")
        elif may_signal_root:
            try:
                os.kill(pid, signal.SIGTERM)
                signals.append("SIGTERM")
            except (ProcessLookupError, OSError):
                pass
        group = await wait_group_gone(
            group_id,
            3.0,
            ignored_pids={pid} if pid_reused else None,
        )
        if group.state != ProcessProbeState.CONFIRMED_DEAD or may_signal_root:
            # may_signal_root 时即使组已空也必须升级到 SIGKILL：
            # root 的 pgid 可能与持久化 PGID 不一致（陈旧行），组空不代表
            # root 已退出（doc 修复方案 §5.4 的等待/升级语义）。
            if group_id is not None:
                try:
                    os.killpg(group_id, signal.SIGKILL)
                    signals.append("SIGKILL")
                except (ProcessLookupError, PermissionError, OSError):
                    pass
            if may_signal_root:
                try:
                    os.kill(pid, signal.SIGKILL)
                    if "SIGKILL" not in signals:
                        signals.append("SIGKILL")
                except (ProcessLookupError, OSError):
                    pass
            group = await wait_group_gone(
                group_id,
                5.0,
                ignored_pids={pid} if pid_reused else None,
            )
    else:
        # 没有任何可证实的存活目标：取一次最终快照作为聚合证据。
        group = await group_snapshot(
            group_id,
            ignored_pids={pid} if pid_reused else None,
        )
    if may_signal_root:
        # root 在信号前是存活的：必须重新探测获得最终死亡/存活证据，
        # 绝不能把信号前的过期 LIVE 快照当作聚合输入。
        final_root = await root_snapshot(pid, process_started_at)
    else:
        final_root = root

    # ── 4/5. 持久化 run token 的完整 discovery 兜底 ──
    token_unknown: Optional[discovery.TokenDiscoverySnapshot] = None
    token_live_pids: Tuple[int, ...] = ()
    if run_token:
        outcome = await run_token_containment(
            run_token,
            not_before=not_before,
            signals=signals,
        )
        if outcome.conflicts:
            # token 命中但身份冲突：保持未确认，不做盲杀。
            return _token_conflict_result(outcome.conflicts)
        if outcome.unknown is not None:
            token_unknown = outcome.unknown
        else:
            token_live_pids = outcome.live_pids

    state, failure_code, error_message, live_pids = aggregate_persisted_snapshots(
        final_root, group
    )
    if token_unknown is not None:
        # 扫描不完整：UNKNOWN 是独立状态，不依赖未知 PID 是否可填写
        # （doc 审计 P0-3B）；remaining 保留全部未确认身份。
        unconfirmed = set(live_pids) | set(token_unknown.unknown_pids)
        return _result(
            None,
            error_code=token_unknown.failure_code or TOKEN_DISCOVERY_UNKNOWN,
            error_message=token_unknown.error_message,
            signals=tuple(signals),
            tree_kill_used=bool(signals),
            remaining_pids=tuple(sorted(unconfirmed)),
            root_identity_matches=final_root.root_identity_matches,
        )
    # P0-3B：token 的返回值参与最终 state，而不只是诊断字段。任一来源
    # 存活 -> LIVE；没有 LIVE 但存在 UNKNOWN -> UNKNOWN。
    remaining = tuple(sorted(set(live_pids) | set(token_live_pids)))
    if token_live_pids:
        state = ProcessProbeState.LIVE
        failure_code = failure_code or "TOKEN_PROCESS_STILL_ALIVE"
        error_message = error_message or (
            f"Run-token process(es) still alive: {sorted(token_live_pids)}"
        )
    if state == ProcessProbeState.LIVE:
        return _result(
            False,
            error_code=failure_code or "PROCESS_TREE_STILL_ALIVE",
            error_message=error_message
            or f"Persisted process tree {pid} is still alive",
            signals=tuple(signals),
            tree_kill_used=bool(signals),
            remaining_pids=remaining,
            root_identity_matches=final_root.root_identity_matches,
        )
    if state == ProcessProbeState.UNKNOWN:
        return _result(
            None,
            error_code=failure_code or PROCESS_TREE_UNKNOWN,
            error_message=error_message,
            signals=tuple(signals),
            tree_kill_used=bool(signals),
            remaining_pids=remaining,
            root_identity_matches=final_root.root_identity_matches,
        )
    # 确认死亡的返回点：不变量检查——不得携带未决来源或非空 remaining
    # （doc 审计 P0-3B）。防御性分支：任何未决证据都必须保持 UNKNOWN。
    if remaining:
        return _result(
            None,
            error_code=PROCESS_TREE_UNKNOWN,
            error_message=(
                "confirmed-dead aggregation attempted with unconfirmed targets"
            ),
            signals=tuple(signals),
            tree_kill_used=bool(signals),
            remaining_pids=remaining,
            root_identity_matches=final_root.root_identity_matches,
        )
    return _result(
        True,
        error_code="PID_REUSED" if pid_reused else None,
        error_message=(
            f"PID {pid} create time does not match persisted owner"
            if pid_reused
            else None
        ),
        signals=tuple(signals),
        tree_kill_used=bool(signals),
        root_identity_matches=final_root.root_identity_matches,
    )


async def stop_persisted_windows(
    pid: int,
    process_started_at: Optional[datetime],
    _result: Callable[..., TerminationResult],
) -> TerminationResult:
    """Windows persisted stop: taskkill tree + tri-state root verification."""
    root = await root_snapshot(pid, process_started_at, check_command_marker=True)
    if root.failure_code == "PID_REUSED":
        return _result(
            False,
            error_code="PID_REUSED",
            error_message=root.error_message,
            root_identity_matches=False,
        )
    if root.state == ProcessProbeState.UNKNOWN:
        return _result(
            None,
            error_code=root.failure_code or PROCESS_TREE_UNKNOWN,
            error_message=root.error_message,
        )
    if root.state == ProcessProbeState.CONFIRMED_DEAD:
        # Windows 没有 group/token containment 可查；root 身份消失即无
        # 可停止目标。
        return _result(True)
    if root.failure_code:
        # 身份无法核实（无关命令行/命令行不可读）：不发信号。
        return _result(
            False,
            error_code=root.failure_code,
            error_message=root.error_message,
            root_identity_matches=root.root_identity_matches,
        )
    signals = ["TASKKILL_TREE"]
    taskkill_error = await windows.taskkill_tree(pid)
    if taskkill_error is not None:
        return _result(
            False,
            error_code="TASKKILL_FAILED",
            error_message=taskkill_error,
            signals=tuple(signals),
            tree_kill_used=True,
        )
    final = await wait_root_gone(pid, process_started_at, 5.0)
    if final.state == ProcessProbeState.CONFIRMED_DEAD:
        return _result(True, signals=tuple(signals), tree_kill_used=True)
    if final.state == ProcessProbeState.UNKNOWN:
        return _result(
            None,
            error_code=final.failure_code or PROCESS_TREE_UNKNOWN,
            error_message=final.error_message,
            signals=tuple(signals),
            tree_kill_used=True,
        )
    return _result(
        False,
        error_code="PROCESS_TREE_STILL_ALIVE",
        error_message=f"Persisted process tree {pid} is still alive",
        signals=tuple(signals),
        tree_kill_used=True,
        root_identity_matches=final.root_identity_matches,
    )


async def verify_persisted_cleanup(
    pid: Optional[int],
    process_started_at: Optional[datetime],
    process_group_id: Optional[int] = None,
) -> TerminationResult:
    """Verify external cleanup without sending a signal.

    This is separate from ``stop_persisted`` so the confirm-cleanup API
    cannot accidentally terminate a PID that has since been reused.

    权限/探测错误保留为 UNKNOWN（``confirmed_dead=None`` + 结构化
    failure code），绝不被折叠成"组为空"（doc 修复方案 §6.4）。
    """
    started = time.monotonic()
    if not pid or process_started_at is None:
        return TerminationResult(
            False,
            None,
            elapsed_ms=0,
            error_code="PROCESS_IDENTITY_INCOMPLETE",
            error_message="Persisted PID and create time are required",
        )
    if psutil is None:
        return TerminationResult(
            False,
            None,
            elapsed_ms=0,
            error_code="PROCESS_INSPECTION_UNAVAILABLE",
            error_message="psutil is required to verify persisted process cleanup",
        )
    root = await root_snapshot(int(pid), process_started_at)
    if root.failure_code == "PID_REUSED" or (
        root.state == ProcessProbeState.CONFIRMED_DEAD
        and root.root_identity_matches is False
    ):
        group = await group_snapshot(process_group_id, ignored_pids={int(pid)})
        if group.state == ProcessProbeState.LIVE:
            return TerminationResult(
                False,
                None,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                error_code="PROCESS_GROUP_STILL_ALIVE",
                error_message="Persisted process group still has live members",
                root_identity_matches=False,
            )
        if group.state == ProcessProbeState.UNKNOWN:
            return TerminationResult(
                None,
                None,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                error_code=group.failure_code or PROCESS_GROUP_UNKNOWN,
                error_message=group.error_message,
                root_identity_matches=False,
            )
        return TerminationResult(
            True,
            None,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            error_code="PID_REUSED",
            root_identity_matches=False,
        )
    if root.state == ProcessProbeState.UNKNOWN:
        return TerminationResult(
            None,
            None,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            error_code=root.failure_code or PROCESS_TREE_UNKNOWN,
            error_message=root.error_message,
        )
    if root.state == ProcessProbeState.CONFIRMED_DEAD:
        group = await group_snapshot(process_group_id)
        if group.state == ProcessProbeState.LIVE:
            return TerminationResult(
                False,
                None,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                error_code="PROCESS_GROUP_STILL_ALIVE",
                error_message="Persisted process group still has live members",
                root_identity_matches=root.root_identity_matches,
            )
        if group.state == ProcessProbeState.UNKNOWN:
            return TerminationResult(
                None,
                None,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                error_code=group.failure_code or PROCESS_GROUP_UNKNOWN,
                error_message=group.error_message,
                root_identity_matches=root.root_identity_matches,
            )
        return TerminationResult(
            True,
            None,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            root_identity_matches=root.root_identity_matches,
        )
    # root 仍存活且身份匹配：tree 仍然存活（group 无需检查）。
    return TerminationResult(
        False,
        None,
        elapsed_ms=int((time.monotonic() - started) * 1000),
        error_code="PROCESS_TREE_STILL_ALIVE",
        error_message=f"Persisted process tree {pid} is still alive",
        root_identity_matches=root.root_identity_matches,
    )


async def stop_by_run_token_discovery(
    run_token: str,
    reason: str,
    *,
    not_before: Optional[datetime] = None,
    not_after: Optional[datetime] = None,
) -> Optional[TerminationResult]:
    """Reclaim a previous boot's tree via run-token discovery (doc 8.5).

    Returns ``None`` only when discovery is unavailable on this platform
    so callers keep the attempt ORPHANED.  An empty double scan is the
    authoritative "no token-carrying process exists" proof: every local
    CLI and its descendants inherit the exact token at spawn time.

    扫描快照三态语义（doc 修复方案 §6.4）：
    - 权限/IO 错误使扫描不完整 -> ``confirmed_dead=None`` +
      ``TOKEN_DISCOVERY_UNKNOWN``，绝不允许把 double-empty 当死亡证明；
    - 单个 PID 在扫描中消失属正常情况，不会使整个快照 UNKNOWN；
    - identity conflicts（未知命令/超出窗口）保持未确认，不盲杀。
    """
    if os.name == "nt" or psutil is None:
        return None
    started = time.monotonic()

    def _elapsed() -> int:
        return int((time.monotonic() - started) * 1000)

    def _unknown_result(snapshot: discovery.TokenDiscoverySnapshot, *, after_kill: bool) -> TerminationResult:
        return TerminationResult(
            None,
            None,
            signals_sent=tuple(signals) if after_kill else (),
            tree_kill_used=after_kill,
            elapsed_ms=_elapsed(),
            error_code=snapshot.failure_code or TOKEN_DISCOVERY_UNKNOWN,
            error_message=snapshot.error_message,
            remaining_pids=tuple(snapshot.unknown_pids),
        )

    snapshot = await discovery.token_snapshot(run_token, not_before)
    if snapshot.state == ProcessProbeState.UNKNOWN:
        return _unknown_result(snapshot, after_kill=False)
    matches = snapshot.matches
    if not matches:
        # Re-scan once after a short grace period to absorb the fork/exec
        # window before confirming "nothing carries the token".
        await asyncio.sleep(0.5)
        snapshot = await discovery.token_snapshot(run_token, not_before)
        if snapshot.state == ProcessProbeState.UNKNOWN:
            return _unknown_result(snapshot, after_kill=False)
        matches = snapshot.matches
        if not matches:
            return TerminationResult(
                True,
                None,
                elapsed_ms=_elapsed(),
            )
    signals: list = []
    outcome = await discovery.converge_token_kill(
        run_token,
        not_before=not_before,
        not_after=not_after,
        signals=signals,
        initial=snapshot,
        max_wait=5.0,
    )
    if outcome.conflicts:
        return TerminationResult(
            False,
            None,
            elapsed_ms=_elapsed(),
            error_code="TOKEN_PROCESS_IDENTITY_CONFLICT",
            error_message=(
                f"{len(outcome.conflicts)} run-token process(es) failed identity "
                "validation; manual handling required"
            ),
            signals_sent=tuple(signals) if outcome.kill_attempted else (),
            tree_kill_used=outcome.kill_attempted,
            remaining_pids=tuple(sorted(int(m.pid) for m in outcome.conflicts)),
        )
    if outcome.unknown is not None:
        return _unknown_result(outcome.unknown, after_kill=outcome.kill_attempted)
    if outcome.state == ProcessProbeState.CONFIRMED_DEAD:
        return TerminationResult(
            True,
            None,
            signals_sent=tuple(signals),
            tree_kill_used=True,
            elapsed_ms=_elapsed(),
        )
    return TerminationResult(
        False,
        None,
        signals_sent=tuple(signals),
        tree_kill_used=True,
        elapsed_ms=_elapsed(),
        error_code="PROCESS_TREE_STILL_ALIVE",
        error_message=f"Run-token process tree survived after {reason}",
        remaining_pids=tuple(outcome.live_pids),
    )
