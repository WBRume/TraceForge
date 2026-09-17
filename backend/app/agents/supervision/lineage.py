"""per-spawn 谱系清理：通过 ``TRACEFORGE_SPAWN_TOKEN`` 收回脱组后代。

本地快照（root returncode + 原组 + 已采样后代）无法覆盖在一次采样
间隔内启动并 ``setsid`` 脱组的后代——它不在原组里，``killpg`` 打不到；
即使已被采样登记，本地快照也只会一直报 LIVE。spawn 时注入的
``TRACEFORGE_SPAWN_TOKEN`` 是本 spawn 专属谱系标记（uuid4 仅注入本次
子进程 env）：任何携带者都可证明属于本 spawn 的后代，因此无论本地
快照是否已经报死，都必须按本 token 清理谱系（doc 审计 07e04775 §3.2：
清理不再以 local DEAD 为前置条件）。

语义（结构化返回，绝不只给 bool）：
- 完整扫描且无携带者 -> ``CONFIRMED_DEAD``（全树完成证据闭合）；
- 携带者经验证身份后逐个发送（TERM 宽限后升级 KILL）、重扫为空
  -> ``CONFIRMED_DEAD``；``sent`` 不是死亡证明，必须重扫确认；
- 扫描 UNKNOWN / 携带者身份冲突（create time 不可读或早于 spawn）
  / 超时未收敛 -> ``UNKNOWN``/``LIVE`` 结构化快照（调用方必须保持
  ownership，绝不出具不可撤销的 confirmed_dead=True）。

只扫描 per-spawn token，绝不触碰同 attempt 其他 managed 的进程；
Windows（Job Object containment）或无 spawn token 时无事可查，返回
空死亡快照保持原语义。
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

from app.agents.supervision import discovery
from app.agents.supervision.model import (
    DETACHED_DESCENDANTS_UNRESOLVED,
    SPAWN_TOKEN_ENV_VAR,
    ProcessProbeState,
)

# P1（07e04775）：谱系清理的 TERM 宽限秒数；拒绝 TERM 的后代在此之后升级
# SIGKILL（升级粒度以身份验证发送为单位，绝不整组 killpg）。
_SPAWN_LINEAGE_TERM_GRACE_SECONDS = 1.5


@dataclass(frozen=True)
class SpawnLineageCleanup:
    """One structured per-spawn lineage cleanup result (doc 审计 07e04775 §3.2).

    清理必须返回结构化快照而不是 bool：本地快照与谱系扫描是两个必需证据
    来源，调用方按"任一 LIVE -> 未死；无 LIVE 但有 UNKNOWN -> 未确认；全部
    DEAD -> 已死"聚合。``signals_sent`` 保留诊断；失败码绝不反向伪造死亡。
    """

    state: ProcessProbeState = ProcessProbeState.CONFIRMED_DEAD
    remaining_pids: Tuple[int, ...] = ()
    unknown_pids: Tuple[int, ...] = ()
    signals_sent: Tuple[str, ...] = ()
    failure_code: Optional[str] = None
    error_message: Optional[str] = None


async def cleanup_spawn_lineage(
    *,
    spawn_token: Optional[str],
    created_at: float,
    signals: list,
    max_wait: float = 6.0,
) -> SpawnLineageCleanup:
    """P0-3/P1：本 spawn 谱系后代的结构化清理（07e04775 §3.3）。"""
    if os.name == "nt" or psutil is None or not spawn_token:
        return SpawnLineageCleanup()
    not_before = datetime.fromtimestamp(
        max(0.0, float(created_at) - 2.0), tz=timezone.utc
    )
    deadline = time.monotonic() + max(0.1, max_wait)
    kill_at = min(deadline, time.monotonic() + _SPAWN_LINEAGE_TERM_GRACE_SECONDS)
    phase = signal.SIGTERM
    phase_name = "SIGTERM"
    signals_sent: list = []
    # P1（doc 审计 0c381413 §3.3）：候选集合不跨轮累加——新的完整扫描
    # 能解除"暂时未知"，deadline 结果只取最终一次扫描；``proven_pids``
    # 记录曾经验证过 token 归属的身份，它们随后不可读时仍保留 owned
    # 归属，绝不能降级为"从未证明"的候选。
    proven_pids: set = set()
    failure_code: Optional[str] = None
    error_message: Optional[str] = None

    def _conflict_result(conflicts: Tuple[discovery.DiscoveredTokenProcess, ...]) -> SpawnLineageCleanup:
        # 携带者身份无法核实（不可读/早于 spawn）：不盲杀，保持未确认。
        return SpawnLineageCleanup(
            state=ProcessProbeState.UNKNOWN,
            unknown_pids=tuple(sorted(int(m.pid) for m in conflicts)),
            signals_sent=tuple(signals_sent),
            failure_code="TOKEN_PROCESS_IDENTITY_CONFLICT",
            error_message=(
                "Spawn-token process(es) failed identity validation; "
                "manual handling required"
            ),
        )

    while True:
        scan = await discovery.token_snapshot(
            spawn_token, not_before, env_var=SPAWN_TOKEN_ENV_VAR
        )
        if scan.state == ProcessProbeState.UNKNOWN:
            # 扫描不完整：UNKNOWN 保留 ownership（doc 审计 P0-3）。
            # 候选 PID 不跨轮累加（0c381413 §3.3），只保留失败诊断。
            failure_code = failure_code or scan.failure_code
            error_message = error_message or scan.error_message
        good, conflicts = discovery.partition_token_matches(
            scan.matches, not_before=not_before, not_after=None
        )
        if conflicts:
            return _conflict_result(conflicts)
        proven_pids.update(int(m.pid) for m in good)
        # 混合 LIVE + UNKNOWN 也可以清理已验证的 LIVE 身份；但不完整
        # 扫描最终绝不产生死亡证明。
        if good:
            await discovery.kill_token_matches(
                good, signals_sent, sig=phase, signal_name=phase_name
            )
        # 不能根据"信号发完"返回死亡证明，必须重扫。
        final = await discovery.token_snapshot(
            spawn_token, not_before, env_var=SPAWN_TOKEN_ENV_VAR
        )
        if final.state == ProcessProbeState.CONFIRMED_DEAD:
            signals.extend(
                name for name in signals_sent if name not in signals
            )
            return SpawnLineageCleanup(
                state=ProcessProbeState.CONFIRMED_DEAD,
                signals_sent=tuple(signals_sent),
            )
        good, conflicts = discovery.partition_token_matches(
            final.matches, not_before=not_before, not_after=None
        )
        if conflicts:
            return _conflict_result(conflicts)
        proven_pids.update(int(m.pid) for m in good)
        if final.state == ProcessProbeState.UNKNOWN:
            failure_code = failure_code or final.failure_code
            error_message = error_message or final.error_message
        if time.monotonic() >= deadline:
            # 截止仍未收敛：返回最后一次扫描的结构化快照（LIVE/UNKNOWN），
            # 绝不折叠成死亡证明。归属（owned）= 本轮已验证存活 + 曾
            # 证明归属、随后不可读的身份；``unknown_pids`` 只保留最终
            # 扫描中"从未证明属于本 spawn"的候选，过期候选不累加。
            signals.extend(
                name for name in signals_sent if name not in signals
            )
            final_alive = {int(m.pid) for m in good}
            final_unknown = {int(pid) for pid in final.unknown_pids}
            owned = final_alive | (proven_pids & final_unknown)
            return SpawnLineageCleanup(
                state=(
                    ProcessProbeState.UNKNOWN
                    if final.state == ProcessProbeState.UNKNOWN
                    else ProcessProbeState.LIVE
                ),
                remaining_pids=tuple(sorted(owned)),
                unknown_pids=tuple(sorted(final_unknown - proven_pids)),
                signals_sent=tuple(signals_sent),
                failure_code=failure_code or (
                    DETACHED_DESCENDANTS_UNRESOLVED
                    if final.state == ProcessProbeState.UNKNOWN
                    else "TOKEN_PROCESS_STILL_ALIVE"
                ),
                error_message=error_message
                or "Spawn-token lineage did not converge before deadline",
            )
        if time.monotonic() >= kill_at:
            # 拒绝 TERM 的后代升级 KILL（按已验证身份逐个发送）。
            phase = signal.SIGKILL
            phase_name = "SIGKILL"
        await asyncio.sleep(0.1)
