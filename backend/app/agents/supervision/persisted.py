"""持久化身份（上一轮 boot 遗留 PID / 进程组）的三态探测。

worker 重启后，reaper 只持有持久化的 PID + create time + PGID。本模块在
inspection executor 中对这三个证据来源做单次三态探测，并提供固定顺序的
聚合规则（doc 修复方案 §5.4）：

- PID 已消失/僵尸 -> 该 root identity 的 CONFIRMED_DEAD 证据；
- PID 存活但 create time 与持久化身份不符 -> PID_REUSED：原身份已不在
  该 PID 上（绝不对此 PID 发信号）；
- 权限/系统错误 -> UNKNOWN，绝不允许被折叠成"组为空"；
- 聚合：任一来源 LIVE -> LIVE；没有 LIVE 但存在 UNKNOWN -> UNKNOWN；
  全部来源明确死亡 -> CONFIRMED_DEAD。
"""

from __future__ import annotations

import asyncio
import functools
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple

try:  # psutil is used for create-time and descendant verification.
    import psutil
except ImportError:  # pragma: no cover - packaging/runtime guard
    psutil = None  # type: ignore[assignment]

from app.agents.supervision.inspection import (
    InspectionQueueSaturated,
    run_process_probe,
)
from app.agents.supervision.model import (
    PROCESS_GROUP_UNKNOWN,
    PROCESS_TREE_UNKNOWN,
    ProcessProbeState,
)

# 命令标记：用于 run-token 发现结果的补充身份校验（doc 7.3.4）。
_TOKEN_PROCESS_COMMAND_MARKERS = ("claude", "node", "traceforge")


@dataclass(frozen=True)
class PersistedProcessSnapshot:
    """One tri-state probe of a persisted root / POSIX process group.

    聚合规则（doc 修复方案 §5.4）：任一来源 LIVE -> LIVE；没有 LIVE 但任一
    来源 UNKNOWN -> UNKNOWN；所有必需来源 CONFIRMED_DEAD -> CONFIRMED_DEAD。
    权限/系统错误只能产生 UNKNOWN，绝不允许被折叠成"组为空"。
    """

    state: ProcessProbeState = ProcessProbeState.UNKNOWN
    live_pids: Tuple[int, ...] = ()
    root_identity_matches: Optional[bool] = None
    # 当前占用该 PID 的进程 create time（PID_REUSED 时是新占用者的身份
    # 边界，供复用组逐成员验证使用；doc 审计 P0-1）。
    pid_create_time: Optional[float] = None
    failure_code: Optional[str] = None
    error_message: Optional[str] = None


def expected_started_timestamp(
    process_started_at: Optional[datetime],
) -> Optional[float]:
    if process_started_at is None:
        return None
    expected = process_started_at
    if expected.tzinfo is None:
        expected = expected.replace(tzinfo=timezone.utc)
    return float(expected.timestamp())


def probe_persisted_root_sync(
    pid: int,
    process_started_at: Optional[datetime],
    *,
    check_command_marker: bool = False,
) -> PersistedProcessSnapshot:
    """Single executor-side probe of one persisted root identity.

    - PID 已消失/僵尸 -> 该 root identity 的 CONFIRMED_DEAD 证据；
    - PID 存活但 create time 与持久化身份不符 -> PID_REUSED：原身份已不在
      该 PID 上（绝不对此 PID 发信号），原树是否存在由 group/token 探测
      回答；
    - 存活且身份匹配 -> LIVE（``check_command_marker`` 时要求可识别的
      TraceForge Agent 命令行，防止对身份相近的无关进程发信号）；
    - 存活但 create time 不可读 -> LIVE 但身份未证实（不得发信号）；
    - AccessDenied / 其他 psutil 或系统错误 -> UNKNOWN。
    """
    if psutil is None:
        return PersistedProcessSnapshot(
            state=ProcessProbeState.UNKNOWN,
            failure_code="PROCESS_INSPECTION_UNAVAILABLE",
            error_message="psutil is unavailable",
        )
    pid = int(pid)
    try:
        proc = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return PersistedProcessSnapshot(state=ProcessProbeState.CONFIRMED_DEAD)
    except psutil.AccessDenied as exc:
        return PersistedProcessSnapshot(
            state=ProcessProbeState.UNKNOWN,
            failure_code=PROCESS_TREE_UNKNOWN,
            error_message=str(exc) or f"pid {pid} access denied",
        )
    except (psutil.Error, OSError, ValueError) as exc:
        return PersistedProcessSnapshot(
            state=ProcessProbeState.UNKNOWN,
            failure_code=PROCESS_TREE_UNKNOWN,
            error_message=str(exc) or type(exc).__name__,
        )
    identity_matches: Optional[bool] = None
    identity_required = expected_started_timestamp(process_started_at) is not None
    occupant_create_time: Optional[float] = None
    try:
        create_time = float(proc.create_time())
        occupant_create_time = create_time
        expected = expected_started_timestamp(process_started_at)
        if expected is not None:
            identity_matches = abs(create_time - expected) <= 2.0
            if not identity_matches:
                # PID 被复用：绝不能对该 PID 发信号；原树的生死由
                # process-group / run-token 探测独立回答（doc §5.4）。
                return PersistedProcessSnapshot(
                    state=ProcessProbeState.CONFIRMED_DEAD,
                    root_identity_matches=False,
                    pid_create_time=create_time,
                    failure_code="PID_REUSED",
                    error_message=(
                        f"PID {pid} create time does not match persisted owner"
                    ),
                )
    except (psutil.Error, OSError, ValueError):
        identity_matches = None
    try:
        alive = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except psutil.ZombieProcess:
        return PersistedProcessSnapshot(
            state=ProcessProbeState.CONFIRMED_DEAD,
            root_identity_matches=identity_matches,
        )
    except (psutil.Error, OSError, ValueError) as exc:
        return PersistedProcessSnapshot(
            state=ProcessProbeState.UNKNOWN,
            failure_code=PROCESS_TREE_UNKNOWN,
            error_message=str(exc) or type(exc).__name__,
        )
    if alive:
        if identity_required and identity_matches is not True:
            # create time 不可读：存活 PID 的身份未证实，绝不发信号。
            return PersistedProcessSnapshot(
                state=ProcessProbeState.LIVE,
                live_pids=(pid,),
                root_identity_matches=None,
                failure_code=PROCESS_TREE_UNKNOWN,
                error_message=(
                    f"PID {pid} is alive but its create time could not be verified"
                ),
            )
        if check_command_marker:
            try:
                command = " ".join(proc.cmdline()).lower()
            except (psutil.Error, OSError, ValueError) as exc:
                # 命令行不可读：无法核实该存活 PID 属于 TraceForge，禁止发信号。
                return PersistedProcessSnapshot(
                    state=ProcessProbeState.LIVE,
                    live_pids=(pid,),
                    root_identity_matches=identity_matches,
                    failure_code=PROCESS_TREE_UNKNOWN,
                    error_message=str(exc) or "persisted root cmdline is unreadable",
                )
            if not any(marker in command for marker in _TOKEN_PROCESS_COMMAND_MARKERS):
                return PersistedProcessSnapshot(
                    state=ProcessProbeState.LIVE,
                    live_pids=(pid,),
                    root_identity_matches=identity_matches,
                    failure_code="PID_OWNERSHIP_UNVERIFIED",
                    error_message=(
                        f"PID {pid} is not an identifiable TraceForge Agent process"
                    ),
                )
        return PersistedProcessSnapshot(
            state=ProcessProbeState.LIVE,
            live_pids=(pid,),
            root_identity_matches=identity_matches,
            pid_create_time=occupant_create_time,
        )
    return PersistedProcessSnapshot(
        state=ProcessProbeState.CONFIRMED_DEAD,
        root_identity_matches=identity_matches,
        pid_create_time=occupant_create_time,
    )


def probe_persisted_group_sync(
    process_group_id: Optional[int],
    *,
    ignored_pids: Optional[set] = None,
) -> PersistedProcessSnapshot:
    """Single executor-side tri-state probe of one POSIX process group.

    - ``os.killpg`` ProcessLookupError -> 组明确不存在的直接证据；
    - PermissionError / 其他 OSError -> UNKNOWN（组可能仍然存在）；
    - 成员枚举中单个 PID 不可检查 -> 记入 unknown 并降级 UNKNOWN；
    - 有存活成员 -> LIVE（剩余 PID 包含 live 与 unknown，供保留追踪）。
    """
    if os.name == "nt" or not process_group_id:
        # Windows 没有进程组 containment；无 PGID 时组来源无事可证。
        return PersistedProcessSnapshot(state=ProcessProbeState.CONFIRMED_DEAD)
    if psutil is None:
        return PersistedProcessSnapshot(
            state=ProcessProbeState.UNKNOWN,
            failure_code="PROCESS_INSPECTION_UNAVAILABLE",
            error_message="psutil is required for process-group inspection",
        )
    group_id = int(process_group_id)
    ignored = set(ignored_pids or ())
    try:
        os.killpg(group_id, 0)
    except ProcessLookupError:
        return PersistedProcessSnapshot(state=ProcessProbeState.CONFIRMED_DEAD)
    except (PermissionError, OSError, ValueError) as exc:
        return PersistedProcessSnapshot(
            state=ProcessProbeState.UNKNOWN,
            failure_code=PROCESS_GROUP_UNKNOWN,
            error_message=str(exc) or type(exc).__name__,
        )
    live: set = set()
    unknown: set = set()
    error_message: Optional[str] = None
    try:
        for proc in psutil.process_iter(["pid", "status"]):
            try:
                pid = int(proc.pid)
            except (psutil.Error, ValueError):
                continue
            try:
                if pid in ignored:
                    continue
                try:
                    status = proc.status()
                except psutil.NoSuchProcess:
                    continue
                except (psutil.AccessDenied, psutil.Error, OSError) as exc:
                    unknown.add(pid)
                    error_message = error_message or (str(exc) or type(exc).__name__)
                    continue
                if status == psutil.STATUS_ZOMBIE:
                    continue
                try:
                    if os.getpgid(pid) == group_id:
                        live.add(pid)
                except ProcessLookupError:
                    continue
                except (PermissionError, OSError, ValueError) as exc:
                    unknown.add(pid)
                    error_message = error_message or (str(exc) or type(exc).__name__)
            except psutil.NoSuchProcess:
                continue
    except (psutil.Error, OSError) as exc:
        # process_iter 本身失败：整次扫描不完整，绝不能当作组为空。
        return PersistedProcessSnapshot(
            state=ProcessProbeState.UNKNOWN,
            failure_code=PROCESS_GROUP_UNKNOWN,
            error_message=str(exc) or type(exc).__name__,
        )
    if live:
        return PersistedProcessSnapshot(
            state=ProcessProbeState.LIVE,
            live_pids=tuple(sorted(live | unknown)),
            failure_code=PROCESS_GROUP_UNKNOWN if unknown else None,
            error_message=error_message,
        )
    if unknown:
        return PersistedProcessSnapshot(
            state=ProcessProbeState.UNKNOWN,
            live_pids=tuple(sorted(unknown)),
            failure_code=PROCESS_GROUP_UNKNOWN,
            error_message=error_message
            or f"{len(unknown)} group member(s) could not be inspected",
        )
    return PersistedProcessSnapshot(state=ProcessProbeState.CONFIRMED_DEAD)


async def root_snapshot(
    pid: int,
    process_started_at: Optional[datetime],
    *,
    check_command_marker: bool = False,
) -> PersistedProcessSnapshot:
    """One root identity probe off the loop (UNKNOWN on queue saturation)."""
    try:
        return await run_process_probe(
            functools.partial(
                probe_persisted_root_sync,
                int(pid),
                process_started_at,
                check_command_marker=check_command_marker,
            )
        )
    except InspectionQueueSaturated as exc:
        return PersistedProcessSnapshot(
            state=ProcessProbeState.UNKNOWN,
            failure_code="INSPECTION_QUEUE_SATURATED",
            error_message=str(exc),
        )


async def group_snapshot(
    process_group_id: Optional[int],
    *,
    ignored_pids: Optional[set] = None,
) -> PersistedProcessSnapshot:
    """One process-group probe off the loop (UNKNOWN on queue saturation)."""
    try:
        return await run_process_probe(
            functools.partial(
                probe_persisted_group_sync,
                process_group_id,
                ignored_pids=ignored_pids,
            )
        )
    except InspectionQueueSaturated as exc:
        return PersistedProcessSnapshot(
            state=ProcessProbeState.UNKNOWN,
            failure_code="INSPECTION_QUEUE_SATURATED",
            error_message=str(exc),
        )


def aggregate_persisted_snapshots(
    *snapshots: PersistedProcessSnapshot,
) -> Tuple[ProcessProbeState, Optional[str], Optional[str], Tuple[int, ...]]:
    """Fixed tri-state aggregation across probe sources (doc 修复方案 §5.4).

    任一来源 LIVE -> LIVE；没有 LIVE 但存在 UNKNOWN -> UNKNOWN（UNKNOWN
    快照携带的未确认 PID 一并保留在 live_pids 中，绝不因聚合丢弃身份，
    doc 审计 P0-3B）；全部来源明确死亡 -> CONFIRMED_DEAD。
    """
    live: list = []
    unconfirmed: list = []
    failure_code: Optional[str] = None
    error_message: Optional[str] = None
    unknown = False
    for snapshot in snapshots:
        if snapshot.state == ProcessProbeState.LIVE:
            live.extend(int(p) for p in snapshot.live_pids)
        elif snapshot.state == ProcessProbeState.UNKNOWN:
            unknown = True
            unconfirmed.extend(int(p) for p in snapshot.live_pids)
        if snapshot.failure_code and failure_code is None:
            failure_code = snapshot.failure_code
            error_message = snapshot.error_message
    if live:
        return (
            ProcessProbeState.LIVE,
            failure_code,
            error_message,
            tuple(sorted(set(live) | set(unconfirmed))),
        )
    if unknown:
        return (
            ProcessProbeState.UNKNOWN,
            failure_code or PROCESS_TREE_UNKNOWN,
            error_message,
            tuple(sorted(set(unconfirmed))),
        )
    return (ProcessProbeState.CONFIRMED_DEAD, None, None, ())


def combine_persisted_snapshots(
    *snapshots: PersistedProcessSnapshot,
) -> PersistedProcessSnapshot:
    state, code, message, live_pids = aggregate_persisted_snapshots(*snapshots)
    root_identity_matches: Optional[bool] = None
    for snapshot in snapshots:
        if snapshot.root_identity_matches is not None:
            root_identity_matches = snapshot.root_identity_matches
            break
    return PersistedProcessSnapshot(
        state=state,
        live_pids=live_pids,
        root_identity_matches=root_identity_matches,
        failure_code=code,
        error_message=message,
    )


async def wait_snapshot_gone(
    probe,
    timeout: float,
    *,
    poll_interval: float = 0.1,
) -> PersistedProcessSnapshot:
    """Poll a tri-state probe until CONFIRMED_DEAD or the deadline.

    UNKNOWN 快照会继续重试直到超时；返回最后一次快照，由调用方聚合
    （UNKNOWN 永远不会被压成死亡证明，doc 修复方案 §7.4）。
    """
    deadline = time.monotonic() + max(0.05, timeout)
    last = await probe()
    while (
        last.state != ProcessProbeState.CONFIRMED_DEAD
        and time.monotonic() < deadline
    ):
        await asyncio.sleep(poll_interval)
        last = await probe()
    return last


async def wait_root_gone(
    pid: int,
    process_started_at: Optional[datetime],
    timeout: float,
) -> PersistedProcessSnapshot:
    async def probe() -> PersistedProcessSnapshot:
        return await root_snapshot(pid, process_started_at)

    return await wait_snapshot_gone(probe, timeout)


async def wait_group_gone(
    process_group_id: Optional[int],
    timeout: float,
    *,
    ignored_pids: Optional[set] = None,
) -> PersistedProcessSnapshot:
    async def probe() -> PersistedProcessSnapshot:
        return await group_snapshot(process_group_id, ignored_pids=ignored_pids)

    return await wait_snapshot_gone(probe, timeout)
