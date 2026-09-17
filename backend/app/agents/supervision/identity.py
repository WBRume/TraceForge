"""身份绑定与安全信号发送（P0 安全路径的唯一归属）。

审计 P0-1/P0-2 的核心不变量：任何凭"数字 PID"发送的信号都是 PID 复用
误杀窗口；只有"重探身份 + pidfd 绑定校验（同一 /proc starttime 的两次
读取精确一致，禁止容差放宽）"之后的发送才被允许。

- :class:`MemberBindingState` / :class:`MemberIdentity` —— 显式绑定状态：
  只有 :attr:`BOUND` 携带已验证绑定句柄并授予 Linux 信号发送资格。
- :func:`probe_member_identity` —— 离环身份探测（含 ``want_pidfd`` 绑定）。
- :func:`signal_verified_member` —— 仅经绑定句柄发送；句柄缺失、平台
  不支持或发送失败一律按"未确认"处理，禁止退回 ``os.kill`` 数字 PID。
- :func:`signal_after_identity_recheck` —— 发送前重验证的唯一安全入口。
- :func:`terminate_verified_members` —— 已验证身份集合的 TERM→KILL 逐个
  终止引擎（绝不整组 killpg）。

迟到的身份探测结果（等待方已取消）由强引用回收任务接收并恰好关闭一次
pidfd，避免 fd 泄漏耗尽 inspection worker（doc 审计 P1-2）。
"""

from __future__ import annotations

import asyncio
import enum
import functools
import os
import signal
import time
from dataclasses import dataclass
from typing import Dict, Optional

try:  # psutil is used for create-time and descendant verification.
    import psutil
except ImportError:  # pragma: no cover - packaging/runtime guard
    psutil = None  # type: ignore[assignment]

from app.core.logging import get_logger
from app.agents.supervision.inspection import (
    InspectionQueueSaturated,
    submit_process_probe,
)

logger = get_logger(__name__, category="agent_process")


class MemberBindingState(str, enum.Enum):
    """身份探测/绑定结果的显式状态（doc 审计 07e04775 P0-2.2）。

    ``pidfd=None`` 不再同时表达"不支持""打开失败""绑定失败"：只有
    :attr:`BOUND` 携带已验证绑定句柄并授予 Linux 信号发送资格；其余状态
    一律禁止发送。
    """

    BOUND = "BOUND"                # 身份已验证且持有绑定句柄
    GONE = "GONE"                  # 已验证原目标消失
    UNVERIFIED = "UNVERIFIED"      # 身份读取/绑定失败，归属不明
    UNSUPPORTED = "UNSUPPORTED"    # 平台不支持安全句柄操作


@dataclass(frozen=True)
class MemberIdentity:
    """One executor-side identity probe of a candidate group member (P0-1).

    P0（07e04775）：绑定校验失败的探测绝不再返回"旧 create_time +
    pidfd=None"——那种形状会被发送路径重新解释成"无句柄但可按数字 PID
    发送"。任何非 BOUND 状态都不授予发送资格。
    """

    state: MemberBindingState = MemberBindingState.UNVERIFIED
    create_time: Optional[float] = None
    pidfd: Optional[int] = None
    error_code: Optional[str] = None

    @property
    def gone(self) -> bool:
        return self.state == MemberBindingState.GONE

    @property
    def bound(self) -> bool:
        return (
            self.state == MemberBindingState.BOUND and self.pidfd is not None
        )


# 迟到身份探测结果的回收任务强引用集（doc 审计 P1-2）：取消的等待方离开
# 后，工作线程仍会完成并交回打开的 pidfd；必须有人接收结果并恰好关闭
# 一次，否则 fd 泄漏会耗尽 inspection worker 的文件描述符。
_LATE_IDENTITY_REAPER_TASKS: set = set()


def pidfd_send_supported() -> bool:
    """Whether this platform supports the safe pidfd open+send pair.

    两者缺一都不允许安全发送：只有 ``pidfd_open`` 而没有
    ``pidfd_send_signal`` 时退回数字 PID 会重新打开 P0 的误杀窗口。
    """
    return hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal")


def close_pidfd(pidfd: Optional[int]) -> None:
    """Close one pidfd exactly once; tolerate already-closed descriptors."""
    if pidfd is None:
        return
    try:
        os.close(int(pidfd))
    except (OSError, ValueError):
        pass


def probe_member_identity_sync(pid: int, *, want_pidfd: bool = False) -> MemberIdentity:
    """Probe one candidate group member's identity off the loop.

    - NoSuchProcess / zombie -> ``GONE``（明确的该身份死亡证据）；
    - create time 不可读 / 其他错误 -> ``UNVERIFIED``（归属不明），并且
      不打开任何句柄（没有可验证的绑定对象，doc 审计 P0-1）；
    - ``want_pidfd`` 时同时返回 ``pidfd_open`` 稳定句柄：发送路径用它消除
      身份验证到信号发送之间的 PID 复用窗口（doc 审计 P0-1/P1-2）。句柄
      在同一探测流程内取得并做绑定校验：打开后立即重读 create time，
      两次读取必须精确一致（同一 /proc starttime 的同一浮点值；禁止
      容差放宽，doc 审计 07e04775 P0-2.1）。不一致/不可读说明探测期间
      PID 已被复用，句柄无法证明绑定到已验证身份 → 关闭句柄并返回
      ``UNVERIFIED``（绝不退回"旧身份 + fd=None"）。调用方负责在发送
      完成后关闭 BOUND 句柄。
    """
    pid = int(pid)
    if psutil is None:
        return MemberIdentity(error_code="PROCESS_INSPECTION_UNAVAILABLE")
    try:
        proc = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return MemberIdentity(state=MemberBindingState.GONE)
    except (psutil.Error, OSError, ValueError):
        return MemberIdentity(error_code="IDENTITY_PROBE_FAILED")
    create_time: Optional[float] = None
    try:
        create_time = float(proc.create_time())
    except (psutil.Error, OSError, ValueError):
        create_time = None
    if create_time is None:
        # 身份不可读：调用方绝不能凭此发送；也不交出未绑定句柄。
        return MemberIdentity(error_code="IDENTITY_PROBE_FAILED")
    if not want_pidfd:
        # 身份可读但未取得绑定句柄：该探测不授予发送资格（只有 BOUND
        # 状态允许发送）。
        return MemberIdentity(state=MemberBindingState.UNVERIFIED, create_time=create_time)
    if not pidfd_send_supported():
        # 平台不支持安全句柄操作：明确 UNSUPPORTED，由上层按"未确认"
        # 保留 ownership，绝不悄悄退回数字 PID 发送。
        return MemberIdentity(
            state=MemberBindingState.UNSUPPORTED,
            error_code="PIDFD_UNAVAILABLE",
        )
    pidfd: Optional[int] = None
    try:
        pidfd = os.pidfd_open(pid)
    except ProcessLookupError:
        # 打开时目标已消失：明确的该身份死亡证据。
        return MemberIdentity(state=MemberBindingState.GONE)
    except (OSError, ValueError):
        return MemberIdentity(error_code="PIDFD_OPEN_FAILED")
    try:
        rebinding = float(psutil.Process(pid).create_time())
    except (psutil.Error, OSError, ValueError):
        # 绑定后身份不可读：句柄无法证明绑定到已验证身份。
        close_pidfd(pidfd)
        return MemberIdentity(error_code="IDENTITY_PROBE_FAILED")
    if rebinding != create_time:
        # 探测期间 PID 被复用（或身份读取漂移）：句柄不能证明绑定到已
        # 验证身份。关闭句柄并返回 UNVERIFIED——绝不交回旧 create_time
        # 让发送路径误判为"身份已确认"。
        close_pidfd(pidfd)
        return MemberIdentity(error_code="IDENTITY_CHANGED")
    return MemberIdentity(
        state=MemberBindingState.BOUND, create_time=create_time, pidfd=pidfd
    )


async def _reap_late_identity_result(wrapped: "asyncio.Future") -> None:
    """Await a late identity-probe result and close its pidfd exactly once."""
    try:
        identity = await wrapped
    except asyncio.CancelledError:
        return
    except Exception as exc:
        logger.warning("Late identity probe result failed: {}", exc)
        return
    close_pidfd(getattr(identity, "pidfd", None))


def _schedule_late_identity_reaper(wrapped: "asyncio.Future") -> None:
    """Keep a strong reference to the recovery task; never GC mid-recovery."""
    try:
        task = asyncio.create_task(_reap_late_identity_result(wrapped))
    except RuntimeError:  # loop closing; nothing more can be done
        return
    _LATE_IDENTITY_REAPER_TASKS.add(task)
    task.add_done_callback(_LATE_IDENTITY_REAPER_TASKS.discard)


async def probe_member_identity(
    pid: int,
    *,
    want_pidfd: bool = False,
) -> MemberIdentity:
    """One member-identity probe off the loop (UNKNOWN on queue saturation).

    P1-2：``want_pidfd=True`` 的探测在工作线程中打开 pidfd 并把句柄作为
    结果移交事件循环。若等待方在工作线程已启动后取消，线程仍会完成并
    打开句柄——取消路径必须安排强引用的回收任务接收迟到结果并恰好
    关闭一次句柄，绝不能假设 semaphore 释放就代表资源已释放。
    """
    loop = asyncio.get_running_loop()
    try:
        raw_future = submit_process_probe(
            functools.partial(
                probe_member_identity_sync, int(pid), want_pidfd=want_pidfd
            )
        )
    except InspectionQueueSaturated:
        # 队列饱和：身份无法核实，按"归属不明"处理，绝不发信号。
        return MemberIdentity()
    wrapped = asyncio.futures.wrap_future(raw_future, loop=loop)
    try:
        # shield：调用方取消时绝不把取消传播到 wrapped future——
        # 底层线程的完成结果（可能持有 pidfd）必须仍可被回收任务接收。
        return await asyncio.shield(wrapped)
    except asyncio.CancelledError:
        _schedule_late_identity_reaper(wrapped)
        raise


def signal_verified_member(pidfd: Optional[int], sig: int) -> bool:
    """Send one signal through the verified pidfd binding only (P0-1).

    P0（07e04775）：只有已绑定的 pidfd 允许发送。句柄缺失、平台缺
    ``pidfd_send_signal``、或发送失败都按"未确认"处理——禁止退回
    ``os.kill(数字 PID)``，那会把"校验明确失败"重新解释成"无句柄但
    可发送"，在 PID 复用窗口内误杀无关进程。句柄由调用方
    （``signal_after_identity_recheck``）恰好关闭一次。
    """
    if pidfd is None:
        return False
    send = getattr(signal, "pidfd_send_signal", None)
    if send is None:
        return False
    try:
        send(int(pidfd), sig)
        return True
    except ProcessLookupError:
        # 句柄绑定在已验证实例上：ESRCH 说明该实例在发送时已退出，
        # 这是明确的死亡证据（交由调用方映射为 dead 并重扫确认）。
        raise
    except (PermissionError, OSError):
        return False


async def signal_after_identity_recheck(
    pid: int,
    expected_create_time: Optional[float],
    sig: int,
    signals: list,
    signal_name: str,
) -> str:
    """P0-1/P0-2 共用的唯一安全发送入口：发送前重新验证并绑定目标身份。

    - 重新探测目标身份并在同一流程内取得绑定句柄（pidfd 指向已验证的
      进程实例，消除验证到发送之间的 PID 复用窗口）；
    - 只有 ``BOUND`` 状态（句柄绑定成功 + 身份精确一致）才允许发送；
      ``expected_create_time`` 为 None（原身份从未验证）、重探身份不可读、
      与原身份不完全相等、或平台不支持安全句柄时，绝不发送，返回
      ``"unverified"`` 交上层保留 ownership（doc 审计 07e04775 P0-2.4：
      绑定失败禁止 fallback 到 os.kill/killpg 数字 PID）；
    - 返回 ``"dead"``（目标已消失或绑定句柄发送时已退出）/ ``"sent"`` /
      ``"unverified"``。``sent`` 不是死亡证明，调用方仍必须重扫确认。
    """
    identity = await probe_member_identity(int(pid), want_pidfd=True)
    try:
        if identity.state == MemberBindingState.GONE:
            return "dead"
        if not identity.bound:
            # UNVERIFIED / UNSUPPORTED：无绑定句柄，绝不退回数字 PID。
            return "unverified"
        if (
            expected_create_time is None
            or identity.create_time is None
            or float(identity.create_time) != float(expected_create_time)
        ):
            # 身份无法在发送前重新确认（不可读或不符）：绝不发送。
            return "unverified"
        if signal_verified_member(identity.pidfd, sig):
            if signal_name not in signals:
                signals.append(signal_name)
            return "sent"
        # 发送失败（权限拒绝等）：绝不折叠成死亡证据，按未确认处理，由
        # 重扫/重探收敛。
        return "unverified"
    except ProcessLookupError:
        # 绑定句柄指向已验证实例；ESRCH 说明该实例在发送时已退出。
        return "dead"
    finally:
        # 句柄所有权归本入口：无论发送成功与否恰好关闭一次。
        close_pidfd(identity.pidfd)


async def terminate_verified_members(
    member_identities: Dict[int, Optional[float]],
    signals: list,
    *,
    term_wait: float = 3.0,
    kill_wait: float = 5.0,
) -> set:
    """SIGTERM → wait → SIGKILL per verified identity (never whole-group).

    保存 immutable identity（PID -> 已验证 create time）而不是 PID 集合；
    每次发送前都重新探测目标身份并比较原身份（doc 审计 P0-1）：身份
    不可读、与原身份不符时绝不发送。返回"未确认死亡"的成员集合
    （仍存活、身份变化或身份不可读）。
    """
    pending = {
        int(pid): (None if create_time is None else float(create_time))
        for pid, create_time in (member_identities or {}).items()
    }
    if not pending:
        return set()
    unresolved: set = set()

    async def _prune_dead() -> None:
        for member_pid in sorted(pending):
            identity = await probe_member_identity(member_pid)
            if identity.gone:
                pending.pop(member_pid, None)

    for member_pid in sorted(pending):
        outcome = await signal_after_identity_recheck(
            member_pid, pending[member_pid], signal.SIGTERM, signals, "SIGTERM"
        )
        if outcome == "sent":
            # 已发送：保留在 pending 中等待退出，未退出则升级 SIGKILL。
            continue
        pending.pop(member_pid, None)
        if outcome == "unverified":
            unresolved.add(member_pid)
    deadline = time.monotonic() + max(0.05, term_wait)
    while pending and time.monotonic() < deadline:
        await _prune_dead()
        if not pending:
            return unresolved
        await asyncio.sleep(0.1)
    for member_pid in sorted(pending):
        outcome = await signal_after_identity_recheck(
            member_pid, pending[member_pid], signal.SIGKILL, signals, "SIGKILL"
        )
        if outcome == "sent":
            continue
        pending.pop(member_pid, None)
        if outcome == "unverified":
            unresolved.add(member_pid)
    deadline = time.monotonic() + max(0.05, kill_wait)
    while pending and time.monotonic() < deadline:
        await _prune_dead()
        if not pending:
            return unresolved
        await asyncio.sleep(0.1)
    return unresolved | set(pending)
