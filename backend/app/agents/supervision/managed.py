"""受管 Agent 进程：状态归属、生命周期与终止引擎。

:class:`ManagedAgentProcess` 是一次 spawn 的唯一状态归属点：

- 不可变进程身份（``process_identity``，证据记录的稳定 key）；
- containment 句柄（Windows Job Object / POSIX 进程组）与 per-spawn
  谱系 token；
- 终止串行化与权威死亡证明缓存（doc 4.4：同一进程的终止操作串行化，
  已确认死亡的结果被缓存，重复 close/interrupt 直接返回）；
- 终止阶梯：graceful（CTRL_BREAK / SIGINT）→ TERM/taskkill tree →
  force kill，每步之后用三态树采样确认；
- 全树完成检查：本地快照与 per-spawn 谱系扫描是两个必需证据来源
  （doc 审计 07e04775 §3.4），聚合规则"任一 LIVE -> 未死；无 LIVE 但有
  UNKNOWN -> 未确认；全部 DEAD -> 已死"。

:func:`monitor_tree` 是周期采样循环：psutil 的 recursive children 扫描
绝不在事件循环上执行；每个受管进程同一时刻最多一个在飞 inspection
（doc §12 有界 gate）。
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

try:  # psutil is used for create-time and descendant verification.
    import psutil
except ImportError:  # pragma: no cover - packaging/runtime guard
    psutil = None  # type: ignore[assignment]

from app.core.logging import get_logger
from app.agents.contract import AgentProcessIdentity
from app.agents.supervision import lineage, tree, windows
from app.agents.supervision.inspection import (
    monitor_interval_seconds,
    run_process_inspection,
)
from app.agents.supervision.model import (
    DETACHED_DESCENDANTS_UNRESOLVED,
    PROCESS_TREE_UNKNOWN,
    ProcessProbeState,
    ProcessTreeSnapshot,
    ProcessWaitResult,
    TerminationResult,
)

logger = get_logger(__name__, category="agent_process")


@dataclass(eq=False)
class ManagedAgentProcess:
    process: asyncio.subprocess.Process
    run_token: Optional[str] = None
    worker_boot_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    job_handle: Optional[int] = None
    reader_tasks: list = field(default_factory=list)
    known_descendant_pids: set = field(default_factory=set)
    # P1（doc 审计 0c381413 §3.2）：最近一轮谱系扫描"无法检查"的候选 PID
    # （从未证明携带本 spawn token）。仅诊断；每轮以最新扫描替换，绝不
    # 累加过期候选，也绝不混入 known_descendant_pids。
    last_uninspected_candidates: tuple = field(default_factory=tuple)
    monitor_task: Optional[asyncio.Task] = None
    stop_monitor: bool = False
    _closed: bool = False
    process_start_time: Optional[float] = None
    process_group_id: Optional[int] = None
    containment_id: Optional[str] = None
    # P0-3：本 spawn 专属谱系 token（uuid4，spawn 时注入子进程 env）。任何
    # 携带者都可证明属于本 spawn 的后代树；wait/close 的全树完成检查用它
    # 精确归属脱组后代，绝不误伤同 attempt 其他 managed 的进程。
    spawn_token: Optional[str] = None
    _identity: Optional[AgentProcessIdentity] = None
    # 同一进程的终止操作必须串行化；已确认死亡的结果会被缓存，
    # 重复 close/interrupt 直接返回权威死亡证明（doc 4.4）。
    _termination_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # 同一进程同一时刻最多一个在飞树采样（doc §9.4 有界 gate）。
    _inspection_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _last_termination: Optional[TerminationResult] = None
    _monitor_wake: Optional[asyncio.Event] = None

    @property
    def pid(self) -> int:
        return int(self.process.pid)

    @property
    def monitor_wake_event(self) -> asyncio.Event:
        """Lazily-created wake event (must be created inside the loop)."""
        if self._monitor_wake is None:
            self._monitor_wake = asyncio.Event()
        return self._monitor_wake

    def request_immediate_inspection(self) -> None:
        """Ask the monitor for an out-of-band tree inspection (termination flow)."""
        if self._monitor_wake is not None:
            self._monitor_wake.set()

    def apply_snapshot(self, snapshot: Optional[ProcessTreeSnapshot]) -> None:
        """Merge one executor-produced tree sample into tracked descendants.

        合并规则（doc §5.4.3 + 审计 P0-3A）：
        - LIVE        ：已知集合 = 本次 LIVE 身份 ∪ 本次 UNKNOWN 身份；
                        混合 LIVE/UNKNOWN 后代不能因 LIVE 替换被遗忘；
        - CONFIRMED_DEAD：identity 明确不存在后才移除；
        - UNKNOWN     ：保留全部 known_descendant_pids，只更新错误诊断。
        """
        if snapshot is None or snapshot.state == ProcessProbeState.UNKNOWN:
            # An unknown sample must never erase known descendants.
            return
        merged = set(snapshot.live_descendant_pids) | set(
            getattr(snapshot, "unknown_descendant_pids", ()) or ()
        )
        self.known_descendant_pids = merged

    async def inspect_tree(self) -> ProcessTreeSnapshot:
        """唯一异步树检查入口（doc §9.4）。

        所有 psutil / Job Object / 进程 identity 检查只在 inspection
        executor 中执行；同一 managed process 同时最多一个在飞采样，取消
        等待不会排队新的采样。
        """
        async with self._inspection_lock:
            snapshot = await run_process_inspection(
                tree.inspect_process_tree_snapshot, self
            )
            self.apply_snapshot(snapshot)
            return snapshot

    @property
    def process_started_at(self) -> Optional[float]:
        if self.process_start_time is not None:
            return self.process_start_time
        if psutil is None:
            return self.created_at
        try:
            return float(psutil.Process(self.pid).create_time())
        except (psutil.Error, OSError, ValueError):
            return self.created_at

    @property
    def process_identity(self) -> AgentProcessIdentity:
        """Immutable process identity; computed once so the evidence key is stable."""
        if self._identity is None:
            started = self.process_started_at or self.created_at
            group_id = self.process_group_id if os.name != "nt" else None
            containment = self.containment_id or (
                f"job:{self.job_handle:x}" if self.job_handle else None
            )
            self._identity = AgentProcessIdentity(
                pid=self.pid,
                started_at=datetime.fromtimestamp(started, tz=timezone.utc),
                process_group_id=group_id,
                containment_id=containment,
            )
        return self._identity

    def add_reader_task(self, task: asyncio.Task) -> None:
        self.reader_tasks.append(task)

    async def _wait_for_exit(self, timeout: float) -> bool:
        """等待根进程退出，并通过 inspect_tree() 获得三态树快照（doc §9.4）。"""
        if self.process.returncode is None:
            try:
                await asyncio.wait_for(
                    asyncio.shield(self.process.wait()), timeout=max(0.01, timeout)
                )
            except asyncio.TimeoutError:
                return False
            except ProcessLookupError:
                pass
        # A wrapper may have exited while a descendant is still alive.
        snapshot = await self.inspect_tree()
        return snapshot.state == ProcessProbeState.CONFIRMED_DEAD

    def _send_posix_group(self, sig: signal.Signals) -> bool:
        try:
            # start_new_session=True makes the root PID the process-group ID;
            # retaining it also lets us kill descendants after the root exits.
            pgid = self.process_group_id or self.pid
            if not self.process_group_id:
                try:
                    pgid = os.getpgid(self.pid)
                except ProcessLookupError:
                    pass
            os.killpg(pgid, sig)
            return True
        except ProcessLookupError:
            return True
        except (OSError, ValueError):
            try:
                os.kill(self.pid, sig)
                return True
            except (ProcessLookupError, OSError):
                return False

    async def _taskkill_tree(self, signals: list) -> None:
        if os.name != "nt":
            return
        signals.append("TASKKILL_TREE")
        await windows.taskkill_tree(self.pid)

    async def _force_kill(self, signals: list) -> None:
        if os.name == "nt":
            if self.job_handle:
                if windows.terminate_job(self.job_handle):
                    signals.append("TERMINATE_JOB_OBJECT")
            await self._taskkill_tree(signals)
            for pid in list(self.known_descendant_pids):
                await windows.taskkill_pid(pid)
            return
        if self._send_posix_group(signal.SIGKILL):
            signals.append("SIGKILL")

    async def interrupt(self, reason: str = "interrupt") -> TerminationResult:
        return await self._terminate(reason=reason, graceful=True)

    async def terminate(self, reason: str = "terminate") -> TerminationResult:
        return await self._terminate(reason=reason, graceful=False)

    async def close(self, reason: str = "close") -> TerminationResult:
        if (
            self._closed
            and self._last_termination is not None
            and self._last_termination.confirmed_dead
        ):
            # Already-authoritative death proof for this identity: repeated
            # close calls must be idempotent and cheap.
            return self._last_termination
        result = await self._terminate(reason=reason, graceful=True)
        if result.confirmed_dead:
            await self._reap_readers(timeout=2.0)
            self.stop_monitor = True
            if self.monitor_task is not None:
                self.monitor_task.cancel()
                await asyncio.gather(self.monitor_task, return_exceptions=True)
                self.monitor_task = None
            windows.close_handle(self.job_handle)
            self.job_handle = None
            self._closed = True
        else:
            logger.error(
                "Keeping unsafely terminated Agent process tracked: pid={}, remaining_pids={}",
                self.pid,
                result.remaining_pids,
            )
        return result

    async def _reap_readers(self, timeout: float = 2.0) -> None:
        if not self.reader_tasks:
            return
        tasks = list(self.reader_tasks)
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=max(0.1, timeout),
            )
        except asyncio.TimeoutError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self.reader_tasks.clear()

    async def _terminate(self, *, reason: str, graceful: bool) -> TerminationResult:
        """Serialize every termination check for this one process (doc 4.4).

        - Concurrent wait/close/interrupt/terminate calls never mutate the
          cached evidence concurrently.
        - A confirmed death is cached and returned directly by later calls.
        - An unconfirmed result allows a later kill/verify to run again; a
          later True converges the identity to CONFIRMED_DEAD.
        - A late unconfirmed completion can never overwrite an authoritative
          death proof (the early return guarantees that).
        """
        async with self._termination_lock:
            cached = self._last_termination
            if cached is not None and cached.confirmed_dead:
                return cached
            result = await self._terminate_locked(reason=reason, graceful=graceful)
            self._last_termination = result
            return result

    async def _terminate_locked(self, *, reason: str, graceful: bool) -> TerminationResult:
        started = time.monotonic()
        signals: list = []
        tree_kill_used = False
        error_code: Optional[str] = None
        error_message: Optional[str] = None
        # 终止流程立即触发一次树采样，不必等待普通监控周期（doc §12.2）。
        self.request_immediate_inspection()
        try:
            snapshot = await self.inspect_tree()
            root_alive = self.process.returncode is None
            if root_alive or snapshot.state != ProcessProbeState.CONFIRMED_DEAD:
                if graceful and root_alive:
                    if os.name == "nt":
                        ctrl_break = getattr(signal, "CTRL_BREAK_EVENT", None)
                        if ctrl_break is not None:
                            self.process.send_signal(ctrl_break)
                            signals.append("CTRL_BREAK_EVENT")
                    elif self._send_posix_group(signal.SIGINT):
                        signals.append("SIGINT")
                    if await self._wait_for_exit(3.0):
                        return await self._result(signals, tree_kill_used, started)

                if os.name == "nt":
                    tree_kill_used = True
                    await self._taskkill_tree(signals)
                elif self._send_posix_group(signal.SIGTERM):
                    signals.append("SIGTERM")
                if await self._wait_for_exit(3.0):
                    return await self._result(signals, tree_kill_used, started)

                tree_kill_used = tree_kill_used or os.name == "nt"
                await self._force_kill(signals)
                if not await self._wait_for_exit(5.0):
                    error_code = "PROCESS_TREE_STILL_ALIVE"
                    error_message = f"Agent process tree did not exit after {reason}"
                snapshot = await self.inspect_tree()
            confirmed_dead = (
                snapshot.state == ProcessProbeState.CONFIRMED_DEAD
                and self.process.returncode is not None
            )
            return await self._result(
                signals,
                tree_kill_used,
                started,
                snapshot=snapshot,
                confirmed_dead=confirmed_dead,
                error_code=error_code if not confirmed_dead else None,
                error_message=error_message if not confirmed_dead else None,
            )
        except Exception as exc:
            logger.exception("Agent process termination failed: pid={}, reason={}", self.pid, reason)
            # 终止流程自身的异常是 UNKNOWN，不是存活证明，也绝不是死亡证明。
            return await self._result(
                signals,
                tree_kill_used,
                started,
                confirmed_dead=None,
                error_code="TERMINATION_EXCEPTION",
                error_message=str(exc),
            )

    async def _cleanup_spawn_lineage(self, signals: list) -> lineage.SpawnLineageCleanup:
        """Defer to the per-spawn lineage engine (see :mod:`...lineage`)."""
        return await lineage.cleanup_spawn_lineage(
            spawn_token=self.spawn_token,
            created_at=self.created_at,
            signals=signals,
        )

    async def _result(
        self,
        signals: Iterable[str],
        tree_kill_used: bool,
        started: float,
        *,
        snapshot: Optional[ProcessTreeSnapshot] = None,
        confirmed_dead: Optional[bool] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> TerminationResult:
        """Build the termination result from local snapshot + lineage evidence.

        本方法绝不再次同步扫描进程树（doc §9.4）；没有快照时先通过
        inspection executor 取一次三态采样。P1（07e04775 §3.4）：本地快照
        与 per-spawn 谱系扫描是两个必需证据来源，脱组后代清理不再以"本地
        快照已死"为前置条件——已被采样登记的脱组后代会让本地快照一直
        LIVE，而组 killpg 打不到它。聚合规则：任一来源 LIVE -> 未死；无
        LIVE 但有 UNKNOWN -> 未确认；全部来源 DEAD -> 已死。正常返回、
        异常、取消、重启后的清理路径共用同一"全树完成"标准。
        """
        if snapshot is None:
            snapshot = await self.inspect_tree()
        signal_list = list(signals)
        lineage_result: Optional[lineage.SpawnLineageCleanup] = None
        if os.name != "nt" and psutil is not None and self.spawn_token:
            lineage_result = await self._cleanup_spawn_lineage(signal_list)
            # P1（doc 审计 0c381413 §3.2）：归属证据与扫描完整性分离。只有
            # "已验证 token/谱系归属"的 remaining PID 才进入已知后代集合；
            # ``unknown_pids`` 只是 environ 暂时不可读的任意进程（从未证明
            # 归属），绝不能按数字 PID 提升为 owned descendant——否则无关
            # 长命进程会让后续本地快照永远 LIVE/UNKNOWN，作业无法收敛。
            proven_stragglers = set(lineage_result.remaining_pids)
            if proven_stragglers:
                self.known_descendant_pids |= proven_stragglers
            # 候选只进入诊断（每轮以最新扫描替换，不累加）；展示时标注
            # "无法检查"，绝不显示为"确认仍有子进程"。
            self.last_uninspected_candidates = tuple(lineage_result.unknown_pids)
            if snapshot.state != ProcessProbeState.CONFIRMED_DEAD:
                # 清理可能已终止本地快照中的存活者：聚合前重新采样，不能
                # 用过期快照否决谱系清理成果。
                snapshot = await self.inspect_tree()
        # 本地快照三态。
        if snapshot.state == ProcessProbeState.CONFIRMED_DEAD:
            local_dead: Optional[bool] = True
        elif snapshot.state == ProcessProbeState.LIVE:
            local_dead = False
        else:
            local_dead = None
            error_code = error_code or snapshot.failure_code or PROCESS_TREE_UNKNOWN
        if lineage_result is None:
            confirmed_dead = local_dead
        else:
            # 结构化聚合（doc 审计 07e04775 §3.2/§3.4）。
            if ProcessProbeState.LIVE in (snapshot.state, lineage_result.state):
                confirmed_dead = False
                if lineage_result.state == ProcessProbeState.LIVE:
                    error_code = error_code or lineage_result.failure_code or (
                        "TOKEN_PROCESS_STILL_ALIVE"
                    )
                    error_message = (
                        error_message
                        or lineage_result.error_message
                        or "Spawn-token process(es) still alive after cleanup"
                    )
            elif ProcessProbeState.UNKNOWN in (snapshot.state, lineage_result.state):
                confirmed_dead = None
                error_code = error_code or lineage_result.failure_code or (
                    DETACHED_DESCENDANTS_UNRESOLVED
                )
                error_message = error_message or lineage_result.error_message or (
                    "Spawn-token containment unresolved after local tree termination"
                )
            else:
                # 全部必需来源明确死亡：干净的死亡证明，清除过期诊断。
                confirmed_dead = True
                error_code = None
                error_message = None
        if confirmed_dead is not True:
            remaining = tuple(
                sorted(set(snapshot.remaining_pids) | set(lineage_result.remaining_pids or ()))
                if lineage_result is not None
                else snapshot.remaining_pids
            )
        else:
            remaining = snapshot.remaining_pids
        return TerminationResult(
            confirmed_dead=confirmed_dead,
            root_return_code=self.process.returncode,
            signals_sent=tuple(signal_list),
            tree_kill_used=tree_kill_used,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            error_code=error_code,
            error_message=error_message,
            remaining_pids=remaining,
            root_identity_matches=snapshot.root_identity_matches,
            inspection_unknown_pids=(
                tuple(lineage_result.unknown_pids) if lineage_result is not None else ()
            ),
        )

    async def wait(self) -> ProcessWaitResult:
        """等待 root 退出并按唯一收尾入口收敛全树（07e04775 §3.4）。

        root 退出不是全树死亡证明：wait 与 close 共用同一串行化收尾
        （``close`` → ``_terminate`` → ``_result``），避免两份不同的条件表。
        """
        try:
            root_return_code = await self.process.wait()
            termination = await self.close(reason="root_exited")
            return ProcessWaitResult(
                root_return_code=root_return_code,
                termination=termination,
            )
        finally:
            self.stop_monitor = True
            if self.monitor_task is not None:
                self.monitor_task.cancel()
                await asyncio.gather(self.monitor_task, return_exceptions=True)
                self.monitor_task = None
            await self._reap_readers(timeout=2.0)

    async def __aenter__(self) -> "ManagedAgentProcess":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await asyncio.shield(self.close(reason="context_exit"))


async def monitor_tree(managed: ManagedAgentProcess) -> None:
    """Periodic tree sampling in the bounded inspection executor.

    psutil 的 recursive children / pid_exists 扫描绝不在事件循环上执行；
    每个受管进程同一时刻最多一个在飞 inspection，上一次采样未结束时不
    排队累积下一次（doc §12）。
    """
    interval = monitor_interval_seconds()
    try:
        while not managed.stop_monitor:
            try:
                snapshot = await run_process_inspection(
                    tree.inspect_process_tree_snapshot, managed
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                snapshot = ProcessTreeSnapshot(
                    state=ProcessProbeState.UNKNOWN,
                    failure_code=PROCESS_TREE_UNKNOWN,
                    error_message="Periodic tree inspection raised an unexpected error",
                )
            managed.apply_snapshot(snapshot)
            if (
                getattr(managed.process, "returncode", None) is not None
                and not managed.known_descendant_pids
            ):
                return
            wake = managed.monitor_wake_event
            try:
                await asyncio.wait_for(wake.wait(), timeout=interval)
                wake.clear()
            except asyncio.TimeoutError:
                pass
    except asyncio.CancelledError:
        raise
