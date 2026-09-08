"""统一监管本地 Agent 进程树。

The supervisor deliberately owns the process lifecycle rather than relying on
``Process.terminate`` alone.  Claude Code is commonly launched through a
wrapper (node/cmd) and a wrapper exit is not evidence that the whole agent
tree has exited.
"""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes
import enum
import functools
import os
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Optional, Tuple, Union

try:  # psutil is used for create-time and descendant verification.
    import psutil
except ImportError:  # pragma: no cover - packaging/runtime guard
    psutil = None  # type: ignore[assignment]

from app.core.logging import get_logger
from app.agents.contract import (
    AgentProcessIdentity,
    AgentStopResult,
    EXECUTION_KIND_LOCAL_PROCESS,
    record_attempt_process_started,
    record_attempt_termination,
)

logger = get_logger(__name__, category="agent_process")

RUN_TOKEN_ENV_VAR = "TRACEFORGE_RUN_TOKEN"

# 命令标记：用于 run-token 发现结果的补充身份校验（doc 7.3.4）。
_TOKEN_PROCESS_COMMAND_MARKERS = ("claude", "node", "traceforge")


def containment_id_for_run_token(run_token: Optional[str]) -> Optional[str]:
    """Stable attempt containment id derived from the durable run token.

    The id is available before the child PID exists so it can be persisted at
    job claim time and re-located by the reaper after a worker restart.
    """
    token = str(run_token or "").strip()
    return f"runtoken:{token}" if token else None


def containment_capability() -> Dict[str, Any]:
    """Report this platform's attempt-containment capability (doc 7.4).

    Production Linux relies on run-token /proc discovery until a dedicated
    cgroup provider is deployed; Windows development uses kill-on-close Job
    Objects.  ``available=False`` must make readiness fail instead of
    starting unprotected local CLI processes.
    """
    if os.name == "nt":
        return {
            "platform": "windows",
            "mode": "windows_job_object",
            "available": True,
            "reason": None,
        }
    if psutil is None:
        return {
            "platform": "posix",
            "mode": "proc_token_discovery",
            "available": False,
            "reason": "psutil is required for /proc run-token discovery",
        }
    return {
        "platform": "posix",
        "mode": "proc_token_discovery",
        "available": True,
        "reason": None,
    }


def _require_containment_ready() -> None:
    """Refuse to spawn local Agent processes without containment when required."""
    try:
        from app.config import settings

        required = bool(getattr(settings, "AGENT_REQUIRE_PROCESS_CONTAINMENT", False))
    except Exception:
        required = False
    if not required:
        return
    capability = containment_capability()
    if not capability.get("available"):
        raise RuntimeError(
            "Process containment is required but unavailable on this platform: "
            f"{capability.get('reason')}"
        )


def _windows_kernel32():
    """Return kernel32 with explicit pointer-width-safe signatures."""
    kernel32 = ctypes.windll.kernel32
    handle = ctypes.wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [handle, ctypes.wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = handle
    kernel32.SetInformationJobObject.argtypes = [
        handle,
        ctypes.wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = ctypes.wintypes.BOOL
    kernel32.QueryInformationJobObject.argtypes = [
        handle,
        ctypes.wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(ctypes.wintypes.DWORD),
    ]
    kernel32.QueryInformationJobObject.restype = ctypes.wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [handle, handle]
    kernel32.AssignProcessToJobObject.restype = ctypes.wintypes.BOOL
    kernel32.TerminateJobObject.argtypes = [handle, ctypes.wintypes.UINT]
    kernel32.TerminateJobObject.restype = ctypes.wintypes.BOOL
    kernel32.CloseHandle.argtypes = [handle]
    kernel32.CloseHandle.restype = ctypes.wintypes.BOOL
    kernel32.ResumeThread.argtypes = [handle]
    kernel32.ResumeThread.restype = ctypes.wintypes.DWORD
    return kernel32


_ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class _WindowsJobProcessIdList(ctypes.Structure):
    _fields_ = [
        ("NumberOfAssignedProcesses", ctypes.wintypes.DWORD),
        ("NumberOfProcessIdsInList", ctypes.wintypes.DWORD),
    ]


def _resume_windows_process(process_handle: int) -> None:
    """Resume a suspended process after Job Object assignment.

    CPython closes the primary thread handle after CreateProcess, so
    ResumeThread cannot be used through asyncio's public subprocess object.
    NtResumeProcess is the pointer-width-safe equivalent for this narrow
    hand-off and is configured explicitly before use.
    """
    ntdll = ctypes.windll.ntdll
    handle = ctypes.wintypes.HANDLE
    ntdll.NtResumeProcess.argtypes = [handle]
    ntdll.NtResumeProcess.restype = ctypes.wintypes.LONG
    result = int(ntdll.NtResumeProcess(handle(process_handle)))
    if result != 0:
        raise OSError(result, "NtResumeProcess failed")


@dataclass(frozen=True)
class TerminationResult:
    """终止结果（doc §5.4.4）。

    ``confirmed_dead`` 三态语义：
    - ``True``  ：根进程明确退出 + 所有已登记 identity 明确不存在 +
      containment 明确为空 + 本轮没有 UNKNOWN 探测；
    - ``False`` ：存在明确存活进程；
    - ``None``  ：无法确认（探测错误/未知），failure code 使用
      ``PROCESS_TREE_UNKNOWN`` 或具体探测错误码。禁止把 None 当成死亡证明。
    """

    confirmed_dead: Optional[bool]
    root_return_code: Optional[int]
    signals_sent: tuple[str, ...] = ()
    tree_kill_used: bool = False
    elapsed_ms: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    remaining_pids: tuple[int, ...] = ()
    root_identity_matches: Optional[bool] = None


@dataclass(frozen=True)
class ProcessWaitResult:
    """Result of waiting for a root process and its complete process tree."""

    root_return_code: Optional[int]
    termination: TerminationResult


def agent_stop_result_from_termination(
    termination: Optional[TerminationResult],
) -> AgentStopResult:
    """Convert a local supervisor termination result to the unified stop protocol.

    ``None`` 表示没有可停止的本地进程（从未启动）：stop_acknowledged=True 仅
    表示停止流程已执行；终态判定仍取决于 death 证据（此处为 None）。
    """
    if termination is None:
        return AgentStopResult(
            execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
            stop_acknowledged=True,
            local_process_started=False,
            local_process_confirmed_dead=None,
        )
    confirmed = getattr(termination, "confirmed_dead", None)
    return AgentStopResult(
        execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
        stop_acknowledged=True,
        local_process_started=True,
        local_process_confirmed_dead=None if confirmed is None else bool(confirmed),
        failure_code=getattr(termination, "error_code", None),
        error_message=getattr(termination, "error_message", None),
        remaining_pids=tuple(getattr(termination, "remaining_pids", ()) or ()),
    )


class ProcessProbeState(str, enum.Enum):
    """三态进程探测结果（doc §5.4.1）。

    禁止让调用方通过“空 PID 集”或 ``False`` 自行推断死亡；所有检查异常
    必须映射为 ``UNKNOWN``，而不是制造假死亡证明。
    """

    LIVE = "LIVE"
    CONFIRMED_DEAD = "CONFIRMED_DEAD"
    UNKNOWN = "UNKNOWN"


PROCESS_TREE_UNKNOWN = "PROCESS_TREE_UNKNOWN"


@dataclass(frozen=True)
class ProcessTreeSnapshot:
    """One off-loop process-tree inspection sample (doc §5.4.1/§12)."""

    state: ProcessProbeState = ProcessProbeState.UNKNOWN
    live_descendant_pids: Tuple[int, ...] = ()
    root_return_code: Optional[int] = None
    root_identity_matches: Optional[bool] = None
    remaining_pids: Tuple[int, ...] = ()
    failure_code: Optional[str] = None
    error_message: Optional[str] = None


# 独立的小型 inspection executor：高频 psutil 树扫描绝不运行在主事件循环
# 中，也不复用 DB executor（doc §12.2）。
_INSPECTION_EXECUTOR: Optional[ThreadPoolExecutor] = None
_INSPECTION_EXECUTOR_LOCK = threading.Lock()


def _monitor_interval_seconds() -> float:
    try:
        from app.config import settings

        return max(
            0.05,
            float(getattr(settings, "AGENT_PROCESS_MONITOR_INTERVAL_SECONDS", 0.25) or 0.25),
        )
    except Exception:
        return 0.25


def _inspection_executor() -> ThreadPoolExecutor:
    global _INSPECTION_EXECUTOR
    with _INSPECTION_EXECUTOR_LOCK:
        if _INSPECTION_EXECUTOR is None:
            try:
                from app.config import settings

                workers = max(1, int(getattr(settings, "AGENT_PROCESS_INSPECTION_WORKERS", 2) or 2))
            except Exception:
                workers = 2
            _INSPECTION_EXECUTOR = ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="agent-process-inspection",
            )
    return _INSPECTION_EXECUTOR


def _windows_job_probe(managed: "ManagedAgentProcess") -> Tuple[ProcessProbeState, set]:
    """Probe Windows Job Object containment (executor-side only).

    - 查询成功且为空集合：该 containment 的明确空证据（CONFIRMED_DEAD）；
    - 查询失败：UNKNOWN，绝不返回 False（doc §5.4.2）；
    - 没有 Job Object：无 containment 可查，返回 CONFIRMED_DEAD（空证据，
      死亡证明由 root returncode + known identities + group probe 决定）。
    """
    if os.name != "nt" or not managed.job_handle:
        return (ProcessProbeState.CONFIRMED_DEAD, set())
    try:
        # JOB_OBJECT_BASIC_PROCESS_ID_LIST stores ULONG_PTR PIDs.  A
        # DWORD array truncates handles/PIDs on 64-bit Windows.
        capacity = 256
        buffer_size = ctypes.sizeof(_WindowsJobProcessIdList) + ctypes.sizeof(_ULONG_PTR) * capacity
        buffer = (ctypes.c_byte * buffer_size)()
        returned = ctypes.wintypes.DWORD()
        ok = _windows_kernel32().QueryInformationJobObject(
            ctypes.wintypes.HANDLE(managed.job_handle),
            3,
            ctypes.byref(buffer),
            buffer_size,
            ctypes.byref(returned),
        )
        if not ok:
            return (ProcessProbeState.UNKNOWN, set())
        header = _WindowsJobProcessIdList.from_buffer(buffer)
        count = min(int(header.NumberOfProcessIdsInList), capacity)
        ids = (_ULONG_PTR * capacity).from_buffer(buffer, ctypes.sizeof(_WindowsJobProcessIdList))
        pids = {int(ids[index]) for index in range(count)}
        pids.discard(int(managed.pid))
        return (ProcessProbeState.LIVE, pids) if pids else (ProcessProbeState.CONFIRMED_DEAD, set())
    except Exception:
        return (ProcessProbeState.UNKNOWN, set())


def _posix_group_probe(managed: "ManagedAgentProcess") -> Tuple[ProcessProbeState, set]:
    """Probe the POSIX process group containment (executor-side only)."""
    if os.name == "nt" or not managed.process_group_id:
        return (ProcessProbeState.CONFIRMED_DEAD, set())
    group_id = int(managed.process_group_id)
    try:
        os.killpg(group_id, 0)
    except ProcessLookupError:
        return (ProcessProbeState.CONFIRMED_DEAD, set())
    except (PermissionError, OSError, ValueError):
        # The group may still exist; a permission failure is never a death proof.
        return (ProcessProbeState.UNKNOWN, set())
    if psutil is None:
        return (ProcessProbeState.LIVE, {group_id})
    pids: set = set()
    try:
        for proc in psutil.process_iter(["pid", "status"]):
            try:
                if proc.status() == psutil.STATUS_ZOMBIE:
                    continue
                if os.getpgid(proc.pid) == group_id:
                    pids.add(int(proc.pid))
            except (psutil.Error, OSError, ValueError):
                continue
    except (psutil.Error, OSError, ValueError):
        return (ProcessProbeState.UNKNOWN, set())
    return (ProcessProbeState.LIVE, pids)


def _probe_known_pid(pid: int) -> ProcessProbeState:
    """Three-state probe of one known immutable identity (doc §5.4.2)."""
    if psutil is None:
        return ProcessProbeState.UNKNOWN
    try:
        proc = psutil.Process(int(pid))
    except psutil.NoSuchProcess:
        # 该特定 identity 明确不存在。
        return ProcessProbeState.CONFIRMED_DEAD
    except psutil.ZombieProcess:
        # 明确的已退出语义（doc §5.4.2）。
        return ProcessProbeState.CONFIRMED_DEAD
    except psutil.AccessDenied:
        return ProcessProbeState.UNKNOWN
    except (psutil.Error, OSError, ValueError):
        return ProcessProbeState.UNKNOWN
    try:
        if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
            return ProcessProbeState.LIVE
        return ProcessProbeState.CONFIRMED_DEAD
    except psutil.ZombieProcess:
        return ProcessProbeState.CONFIRMED_DEAD
    except (psutil.Error, OSError, ValueError):
        return ProcessProbeState.UNKNOWN


def inspect_process_tree_snapshot(managed: "ManagedAgentProcess") -> ProcessTreeSnapshot:
    """Pure synchronous psutil snapshot; never call directly from the event loop.

    三态聚合规则（doc §5.4.3）：
    - 任一 identity 明确存活 -> LIVE；
    - 无存活但存在 UNKNOWN（探测异常/Job Object 查询失败/无 psutil 能力）
      -> UNKNOWN，known_descendant_pids 必须全部保留；
    - 仅当 root 明确退出、所有已登记 identity 明确不存在且 containment
      明确为空时 -> CONFIRMED_DEAD。
    """
    root_return_code = getattr(managed.process, "returncode", None)
    root_alive = root_return_code is None
    root_pid = int(managed.pid)
    live: set = set()
    unknown: set = set()
    failure_code: Optional[str] = None
    error_message: Optional[str] = None
    root_identity_matches: Optional[bool] = None

    if psutil is None:
        if root_alive:
            return ProcessTreeSnapshot(
                state=ProcessProbeState.LIVE,
                root_return_code=None,
                remaining_pids=(root_pid,),
            )
        return ProcessTreeSnapshot(
            state=ProcessProbeState.UNKNOWN,
            root_return_code=root_return_code,
            failure_code="PROCESS_INSPECTION_UNAVAILABLE",
            error_message="psutil is unavailable; descendant death cannot be confirmed",
        )

    # 1. Windows Job Object containment。
    job_state, job_pids = _windows_job_probe(managed)
    if job_state == ProcessProbeState.LIVE:
        live.update(job_pids)
    elif job_state == ProcessProbeState.UNKNOWN:
        failure_code = failure_code or "JOB_OBJECT_QUERY_FAILED"
        error_message = error_message or "Windows Job Object query failed; containment unknown"

    # 2. POSIX process group containment。
    group_state, group_pids = _posix_group_probe(managed)
    if group_state == ProcessProbeState.LIVE:
        live.update(group_pids)
    elif group_state == ProcessProbeState.UNKNOWN:
        failure_code = failure_code or "PROCESS_GROUP_UNKNOWN"
        error_message = error_message or "POSIX process group probe failed; containment unknown"

    # 3. Root liveness（asyncio returncode 是 root 存活/退出的权威来源）。
    if root_alive:
        live.add(root_pid)
        try:
            proc = psutil.Process(root_pid)
            if managed.process_start_time is not None:
                root_identity_matches = (
                    abs(float(proc.create_time()) - managed.process_start_time) <= 2.0
                )
            else:
                root_identity_matches = True
        except (psutil.Error, OSError, ValueError):
            root_identity_matches = None

    # 4. 已登记 immutable identities。
    for pid in list(managed.known_descendant_pids):
        if pid == root_pid or pid in live:
            continue
        probe = _probe_known_pid(int(pid))
        if probe == ProcessProbeState.LIVE:
            live.add(int(pid))
        elif probe == ProcessProbeState.UNKNOWN:
            unknown.add(int(pid))
            failure_code = failure_code or "PROCESS_TREE_UNKNOWN"
            error_message = error_message or f"Descendant pid {int(pid)} could not be probed"

    # 5. Root 存活时枚举后代（root 已退出时无法枚举，包含关系由上面两项决定）。
    if root_alive:
        try:
            root = psutil.Process(root_pid)
            for child in root.children(recursive=True):
                live.add(int(child.pid))
        except psutil.NoSuchProcess:
            pass
        except (psutil.Error, OSError, ValueError):
            failure_code = failure_code or "PROCESS_TREE_UNKNOWN"
            error_message = error_message or "Root child enumeration failed"

    if live:
        state = ProcessProbeState.LIVE
    elif unknown:
        state = ProcessProbeState.UNKNOWN
    else:
        state = ProcessProbeState.CONFIRMED_DEAD
    return ProcessTreeSnapshot(
        state=state,
        live_descendant_pids=tuple(sorted(p for p in live if p != root_pid)),
        root_return_code=root_return_code,
        root_identity_matches=root_identity_matches,
        remaining_pids=tuple(sorted(live)),
        failure_code=failure_code if state != ProcessProbeState.CONFIRMED_DEAD else None,
        error_message=error_message if state != ProcessProbeState.CONFIRMED_DEAD else None,
    )


async def run_process_inspection(
    fn: Callable[["ManagedAgentProcess"], ProcessTreeSnapshot],
    managed: "ManagedAgentProcess",
) -> ProcessTreeSnapshot:
    """Run one tree inspection in the bounded executor (never on the loop).

    The monitor awaits the result, so a single managed process can never have
    more than one outstanding inspection and samples do not queue up.
    """
    return await run_process_probe(fn, managed)


PROCESS_GROUP_UNKNOWN = "PROCESS_GROUP_UNKNOWN"
TOKEN_DISCOVERY_UNKNOWN = "TOKEN_DISCOVERY_UNKNOWN"


class InspectionQueueSaturated(RuntimeError):
    """The bounded inspection queue is full; callers must degrade to UNKNOWN.

    有界 gate（doc 修复方案 §7.4）：探测请求饱和时立刻拒绝并把调用方降级为
    UNKNOWN 稍后重试，而不是在进程表压力下继续无界排队拖垮 inspection
    worker。
    """


# 一次探测 = 一个工作项；提交前必须取得许可，探测完成后在 executor 内释放。
# 队列深度因此有硬上界，饱和提交直接失败（绝不静默排队）。
_INSPECTION_QUEUE_MAX_PENDING = 64
_INSPECTION_QUEUE_PERMITS = threading.BoundedSemaphore(_INSPECTION_QUEUE_MAX_PENDING)


def _probe_and_release(fn: Callable[..., Any], args: Tuple[Any, ...]) -> Any:
    try:
        return fn(*args)
    finally:
        _INSPECTION_QUEUE_PERMITS.release()


async def run_process_probe(fn: Callable[..., Any], *args: Any) -> Any:
    """Run one synchronous process probe in the bounded inspection executor.

    所有 psutil / ``/proc`` / cmdline / environ / 进程组成员访问都必须经本
    入口 offload；事件循环上只做信号发送与三态结果聚合（doc 修复方案
    §7.4）。队列饱和时抛出 :class:`InspectionQueueSaturated`，由调用方转成
    UNKNOWN 快照稍后重试。
    """
    loop = asyncio.get_running_loop()
    if not _INSPECTION_QUEUE_PERMITS.acquire(blocking=False):
        raise InspectionQueueSaturated(
            "process inspection queue is saturated; retry later"
        )
    try:
        return await loop.run_in_executor(
            _inspection_executor(), _probe_and_release, fn, args
        )
    except RuntimeError:
        # The work item was never scheduled (executor shutdown race): the
        # permit would otherwise leak and permanently shrink the queue.
        _INSPECTION_QUEUE_PERMITS.release()
        raise


@dataclass(frozen=True)
class PersistedProcessSnapshot:
    """One tri-state probe of a persisted root / POSIX process group.

    聚合规则（doc 修复方案 §5.4）：任一来源 LIVE -> LIVE；没有 LIVE 但任一
    来源 UNKNOWN -> UNKNOWN；所有必需来源 CONFIRMED_DEAD -> CONFIRMED_DEAD。
    权限/系统错误只能产生 UNKNOWN，绝不允许被折叠成“组为空”。
    """

    state: ProcessProbeState = ProcessProbeState.UNKNOWN
    live_pids: Tuple[int, ...] = ()
    root_identity_matches: Optional[bool] = None
    failure_code: Optional[str] = None
    error_message: Optional[str] = None


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


def _expected_started_timestamp(
    process_started_at: Optional[datetime],
) -> Optional[float]:
    if process_started_at is None:
        return None
    expected = process_started_at
    if expected.tzinfo is None:
        expected = expected.replace(tzinfo=timezone.utc)
    return float(expected.timestamp())


def _probe_persisted_root_sync(
    pid: int,
    process_started_at: Optional[datetime],
    *,
    check_command_marker: bool = False,
) -> PersistedProcessSnapshot:
    """Single executor-side probe of one persisted root identity.

    - PID 已消失/僵尸 -> 该 root identity 的 CONFIRMED_DEAD 证据；
    - PID 存活但 create time 与持久化身份不符 -> PID_REUSED：原身份已不在
      该 PID 上（绝不对此 PID 发信号），原树是否存在由 group/token 探测回答；
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
    identity_required = _expected_started_timestamp(process_started_at) is not None
    try:
        create_time = float(proc.create_time())
        expected = _expected_started_timestamp(process_started_at)
        if expected is not None:
            identity_matches = abs(create_time - expected) <= 2.0
            if not identity_matches:
                # PID 被复用：绝不能对该 PID 发信号；原树的生死由
                # process-group / run-token 探测独立回答（doc §5.4）。
                return PersistedProcessSnapshot(
                    state=ProcessProbeState.CONFIRMED_DEAD,
                    root_identity_matches=False,
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
        )
    return PersistedProcessSnapshot(
        state=ProcessProbeState.CONFIRMED_DEAD,
        root_identity_matches=identity_matches,
    )


def _probe_persisted_group_sync(
    process_group_id: Optional[int],
    *,
    ignored_pids: Optional[set[int]] = None,
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


def _scan_token_processes_sync(run_token: str) -> TokenDiscoverySnapshot:
    """One complete same-UID exact-token /proc scan (executor-side only).

    约束与旧 ``_iter_token_processes`` 一致：仅同 UID 进程、environ 精确
    NUL 分隔匹配、排除自身。差异在于异常语义（doc 修复方案 §6.4）：
    - 单个 PID NoSuchProcess / zombie -> 该 PID 已消失，继续扫描；
    - 可识别命令（marker 命中）或 cmdline 不可读的同 UID 进程，其
      environ 不可读 -> 记入 ``unknown_pids``，快照 UNKNOWN（绝不静默丢弃
      可能携带 token 的目标）；
    - cmdline 可读且无 marker 的同 UID 系统进程（sd-pam 等）不可能成为
      匹配目标，直接跳过（否则它们的永久 AccessDenied 会让 discovery 在
      systemd Linux 上永远无法收敛）；
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
    matches: list[DiscoveredTokenProcess] = []
    unknown: list[int] = []
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
            # Marker 预过滤（doc 修复方案 §6.4 的收敛性要求）：token 只会随
            # TraceForge Agent 树继承；cmdline 可读且不含任何已识别命令标记
            # 的同 UID 进程（systemd --user / sd-pam 等）不可能成为匹配目标，
            # 其 environ 不可读不影响扫描完整性。marker 命中或 cmdline 不可
            # 读时仍必须读 environ，后者不可读 → UNKNOWN（绝不静默丢弃）。
            marker_candidates = True
            try:
                command = " ".join(proc.cmdline()).lower()
                marker_candidates = any(
                    marker in command for marker in _TOKEN_PROCESS_COMMAND_MARKERS
                )
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except (psutil.AccessDenied, psutil.Error, OSError):
                marker_candidates = True
            if not marker_candidates:
                continue
            try:
                environ = proc.environ()
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except (psutil.AccessDenied, psutil.Error, OSError) as exc:
                _record_unknown(pid, exc)
                continue
            if environ.get(RUN_TOKEN_ENV_VAR) != token:
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


def _aggregate_persisted_snapshots(
    *snapshots: PersistedProcessSnapshot,
) -> Tuple[ProcessProbeState, Optional[str], Optional[str], Tuple[int, ...]]:
    """Fixed tri-state aggregation across probe sources (doc 修复方案 §5.4)."""
    live: list[int] = []
    failure_code: Optional[str] = None
    error_message: Optional[str] = None
    unknown = False
    for snapshot in snapshots:
        if snapshot.state == ProcessProbeState.LIVE:
            live.extend(int(p) for p in snapshot.live_pids)
        elif snapshot.state == ProcessProbeState.UNKNOWN:
            unknown = True
        if snapshot.failure_code and failure_code is None:
            failure_code = snapshot.failure_code
            error_message = snapshot.error_message
    if live:
        return (
            ProcessProbeState.LIVE,
            failure_code,
            error_message,
            tuple(sorted(set(live))),
        )
    if unknown:
        return (
            ProcessProbeState.UNKNOWN,
            failure_code or PROCESS_TREE_UNKNOWN,
            error_message,
            (),
        )
    return (ProcessProbeState.CONFIRMED_DEAD, None, None, ())


def _combine_persisted_snapshots(
    *snapshots: PersistedProcessSnapshot,
) -> PersistedProcessSnapshot:
    state, code, message, live_pids = _aggregate_persisted_snapshots(*snapshots)
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


def _windows_job_object() -> Optional[int]:
    """Create a kill-on-close Windows Job Object when available."""
    if os.name != "nt":
        return None
    try:
        kernel32 = _windows_kernel32()
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None

        class _IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class _BasicLimitInfo(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", ctypes.wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.wintypes.DWORD),
                ("SchedulingClass", ctypes.wintypes.DWORD),
            ]

        class _ExtendedLimitInfo(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimitInfo),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        info = _ExtendedLimitInfo()
        # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        info.BasicLimitInformation.LimitFlags = 0x2000
        if not kernel32.SetInformationJobObject(
            ctypes.wintypes.HANDLE(handle),
            9,  # JobObjectExtendedLimitInformation
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            kernel32.CloseHandle(ctypes.wintypes.HANDLE(handle))
            return None
        return int(handle.value if hasattr(handle, "value") else handle)
    except Exception as exc:  # pragma: no cover - platform-specific fallback
        logger.warning("Unable to create Windows Job Object: {}", exc)
        return None


def _close_windows_handle(handle: Optional[int]) -> None:
    if handle and os.name == "nt":
        try:
            _windows_kernel32().CloseHandle(ctypes.wintypes.HANDLE(handle))
        except Exception:
            logger.debug("Failed to close Windows Job Object handle", exc_info=True)


@dataclass(eq=False)
class ManagedAgentProcess:
    process: asyncio.subprocess.Process
    run_token: Optional[str] = None
    worker_boot_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    job_handle: Optional[int] = None
    reader_tasks: list[asyncio.Task] = field(default_factory=list)
    known_descendant_pids: set[int] = field(default_factory=set)
    monitor_task: Optional[asyncio.Task] = None
    stop_monitor: bool = False
    _closed: bool = False
    process_start_time: Optional[float] = None
    process_group_id: Optional[int] = None
    containment_id: Optional[str] = None
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

        合并规则（doc §5.4.3）：
        - LIVE        ：更新已知 PID 集合；
        - CONFIRMED_DEAD：identity 明确不存在后才移除；
        - UNKNOWN     ：保留全部 known_descendant_pids，只更新错误诊断。
        """
        if snapshot is None or snapshot.state == ProcessProbeState.UNKNOWN:
            # An unknown sample must never erase known descendants.
            return
        self.known_descendant_pids = set(snapshot.live_descendant_pids)

    async def inspect_tree(self) -> ProcessTreeSnapshot:
        """唯一异步树检查入口（doc §9.4）。

        所有 psutil / Job Object / 进程 identity 检查只在 inspection
        executor 中执行；同一 managed process 同时最多一个在飞采样，取消
        等待不会排队新的采样。
        """
        async with self._inspection_lock:
            snapshot = await run_process_inspection(inspect_process_tree_snapshot, self)
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
                await asyncio.wait_for(asyncio.shield(self.process.wait()), timeout=max(0.01, timeout))
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

    async def _taskkill_tree(self, signals: list[str]) -> None:
        if os.name != "nt":
            return
        signals.append("TASKKILL_TREE")
        try:
            taskkill = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(self.pid), "/T", "/F",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(asyncio.shield(taskkill.wait()), timeout=5.0)
        except Exception as exc:
            logger.warning("taskkill failed for pid {}: {}", self.pid, exc)

    async def _force_kill(self, signals: list[str]) -> None:
        if os.name == "nt":
            if self.job_handle:
                try:
                    _windows_kernel32().TerminateJobObject(
                        ctypes.wintypes.HANDLE(self.job_handle), 1
                    )
                    signals.append("TERMINATE_JOB_OBJECT")
                except Exception:
                    logger.debug("TerminateJobObject failed", exc_info=True)
            await self._taskkill_tree(signals)
            for pid in list(self.known_descendant_pids):
                try:
                    taskkill = await asyncio.create_subprocess_exec(
                        "taskkill", "/PID", str(pid), "/F",
                        stdin=asyncio.subprocess.DEVNULL,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await asyncio.wait_for(asyncio.shield(taskkill.wait()), timeout=5.0)
                except Exception:
                    logger.debug("Fallback descendant taskkill failed: pid={}", pid, exc_info=True)
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
            _close_windows_handle(self.job_handle)
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
        signals: list[str] = []
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
        """Build the termination result from the last completed tri-state snapshot.

        本方法绝不再次同步扫描进程树（doc §9.4）；没有快照时先通过
        inspection executor 取一次三态采样。
        """
        if snapshot is None:
            snapshot = await self.inspect_tree()
        if confirmed_dead is None:
            if snapshot.state == ProcessProbeState.CONFIRMED_DEAD:
                confirmed_dead = True
            elif snapshot.state == ProcessProbeState.LIVE:
                confirmed_dead = False
            else:
                confirmed_dead = None
                error_code = error_code or snapshot.failure_code or PROCESS_TREE_UNKNOWN
        return TerminationResult(
            confirmed_dead=confirmed_dead,
            root_return_code=self.process.returncode,
            signals_sent=tuple(signals),
            tree_kill_used=tree_kill_used,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            error_code=error_code,
            error_message=error_message,
            remaining_pids=snapshot.remaining_pids,
            root_identity_matches=snapshot.root_identity_matches,
        )

    async def wait(self) -> ProcessWaitResult:
        try:
            root_return_code = await self.process.wait()
            snapshot = await self.inspect_tree()
            confirmed_dead = snapshot.state == ProcessProbeState.CONFIRMED_DEAD
            termination = TerminationResult(
                confirmed_dead=confirmed_dead,
                root_return_code=root_return_code,
                root_identity_matches=snapshot.root_identity_matches,
                remaining_pids=snapshot.remaining_pids,
                error_code=None if confirmed_dead else snapshot.failure_code,
                error_message=None if confirmed_dead else snapshot.error_message,
            )
            if snapshot.state != ProcessProbeState.CONFIRMED_DEAD:
                # The root's exit is not the end of the attempt.  Preserve the
                # actual tree-cleanup result so callers cannot report SUCCESS
                # while descendants are still alive (or their state unknown).
                termination = await self.close(reason="root_exit_with_descendants")
            elif termination.confirmed_dead:
                # Cache the authoritative proof under the same serialization
                # rules as close()/terminate().
                async with self._termination_lock:
                    cached = self._last_termination
                    if cached is None or not cached.confirmed_dead:
                        self._last_termination = termination
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


class ProcessSupervisor:
    """Tracks every locally spawned Agent process in this worker."""

    def __init__(self) -> None:
        self._processes: set[ManagedAgentProcess] = set()
        # Strong references for uncancellable cleanup tasks: they must not be
        # garbage-collected while a caller cancellation storm is in progress.
        self._cleanup_tasks: set[asyncio.Task] = set()

    @property
    def active_count(self) -> int:
        """Approximate active count from cached state (never scans the tree on-loop).

        树检查只能在 inspection executor 中执行；本计数以 asyncio returncode
        与缓存的已知后代为准，仅供诊断展示。
        """
        return sum(
            1
            for item in self._processes
            if item.process.returncode is None or item.known_descendant_pids
        )

    def forget(self, managed: ManagedAgentProcess) -> None:
        cached = managed._last_termination
        if managed._closed or (
            managed.process.returncode is not None
            and bool(cached is not None and cached.confirmed_dead)
        ):
            self._processes.discard(managed)

    async def spawn(
        self,
        args: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        run_token: Optional[str] = None,
        worker_boot_id: Optional[str] = None,
        on_process_started: Optional[Any] = None,
        containment_id: Optional[str] = None,
        process_attach_timeout_seconds: Optional[float] = None,
    ) -> ManagedAgentProcess:
        # Doc 7.4: when the deployment requires attempt containment, a
        # missing provider must refuse new local Agent jobs instead of
        # starting an unprotected CLI.
        _require_containment_ready()
        kwargs: dict[str, Any] = {
            "stdin": asyncio.subprocess.DEVNULL,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        if os.name == "nt":
            # Keep the process suspended until it is assigned to the
            # kill-on-close Job Object.  This closes the spawn escape window.
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | int(getattr(subprocess, "CREATE_SUSPENDED", 0x00000004))
            )
        else:
            kwargs["start_new_session"] = True
        process = await asyncio.create_subprocess_exec(*args, cwd=cwd, env=env, **kwargs)
        # I1 (doc 3): the process is owned by the supervisor from this instant.
        # Construct + register the managed handle before any cancellable
        # callback await so no unowned window can exist.
        managed = ManagedAgentProcess(
            process=process,
            run_token=run_token,
            worker_boot_id=worker_boot_id,
            job_handle=_windows_job_object() if os.name == "nt" else None,
            containment_id=(
                containment_id
                or (containment_id_for_run_token(run_token) if os.name != "nt" else None)
            ),
        )
        managed.process_start_time = managed.process_started_at
        if os.name != "nt":
            try:
                managed.process_group_id = os.getpgid(process.pid)
            except (ProcessLookupError, OSError):
                managed.process_group_id = process.pid
        if os.name == "nt":
            try:
                if not managed.job_handle:
                    raise RuntimeError("CreateJobObjectW failed")
                process_handle, _thread_handle = self._windows_process_handles(process)
                if not process_handle:
                    # A test double or an extremely short-lived process may
                    # already be dead before asyncio exposes its Popen
                    # handle.  There is no live process left to escape, so
                    # release the unused job object.  A live process still
                    # fails closed below instead of running unsupervised.
                    if process.returncode is not None:
                        _close_windows_handle(managed.job_handle)
                        managed.job_handle = None
                    else:
                        raise RuntimeError("Suspended subprocess process handle is unavailable")
                if process_handle:
                    kernel32 = _windows_kernel32()
                    assigned = kernel32.AssignProcessToJobObject(
                        ctypes.wintypes.HANDLE(managed.job_handle),
                        ctypes.wintypes.HANDLE(process_handle),
                    )
                    if not assigned:
                        raise RuntimeError("AssignProcessToJobObject failed")
                    _resume_windows_process(process_handle)
            except Exception as exc:
                logger.error("Windows supervised spawn failed for pid {}: {}", process.pid, exc)
                managed.stop_monitor = True
                try:
                    process.kill()
                    await asyncio.wait_for(asyncio.shield(process.wait()), timeout=5.0)
                except Exception:
                    logger.exception("Failed to terminate unsupervised Windows process: pid={}", process.pid)
                _close_windows_handle(managed.job_handle)
                managed.job_handle = None
                raise RuntimeError(f"Could not establish Windows process supervision: {exc}") from exc
        self._processes.add(managed)
        # The identity is frozen once here: every evidence record for this
        # process uses the same immutable key.
        identity = managed.process_identity
        record_attempt_process_started(identity)
        if psutil is not None:
            managed.monitor_task = asyncio.create_task(self._monitor_tree(managed))
        if on_process_started is not None:
            attach_error: Optional[BaseException] = None
            accepted = False
            try:
                accepted = await self._invoke_attach_callback(
                    managed,
                    on_process_started,
                    process_attach_timeout_seconds,
                )
            except BaseException as exc:  # cancellation must also clean up (I1)
                attach_error = exc
            if attach_error is not None or not accepted:
                if attach_error is None:
                    reason = "attempt_fence_rejected"
                elif isinstance(attach_error, asyncio.CancelledError):
                    reason = "process_attach_cancelled"
                elif isinstance(attach_error, asyncio.TimeoutError):
                    reason = "process_attach_timeout"
                else:
                    reason = "attempt_fence_callback_failed"
                # Cleanup is executed inside an uncancellable task; only after
                # it finished (or was reliably handed to the background task)
                # does the original exception propagate.
                result = await self._cleanup_before_reraise(managed, reason=reason)
                if attach_error is None:
                    raise RuntimeError(
                        "Agent process could not be attached to the current job attempt"
                    ) from None
                if isinstance(attach_error, asyncio.TimeoutError):
                    raise TimeoutError(
                        f"Agent process attach did not finish within "
                        f"{float(process_attach_timeout_seconds or 0):.1f}s; "
                        f"process tree cleanup confirmed_dead={result.confirmed_dead}"
                    ) from attach_error
                raise attach_error
        return managed

    @staticmethod
    async def _invoke_attach_callback(
        managed: ManagedAgentProcess,
        callback: Any,
        timeout_seconds: Optional[float],
    ) -> bool:
        """Invoke the attach callback, bounded by the supervisor-side timeout.

        The timeout covers the real DB attach work, not a bridge-forwarded
        future; the adapter watchdog remains an additional outer guard only.
        """

        async def _invoke() -> bool:
            accepted = callback(managed.process_identity)
            if asyncio.iscoroutine(accepted):
                accepted = await accepted
            return bool(accepted)

        effective_timeout = float(timeout_seconds) if timeout_seconds else 0.0
        if effective_timeout > 0:
            return bool(await asyncio.wait_for(_invoke(), timeout=effective_timeout))
        return bool(await _invoke())

    async def _cleanup_before_reraise(
        self,
        managed: ManagedAgentProcess,
        *,
        reason: str,
    ) -> TerminationResult:
        """Close the spawned tree without being interrupted by cancellation.

        The cleanup task is strongly referenced and never cancelled by the
        caller; repeated caller cancellations keep it running.  The original
        CancelledError still propagates from the spawn caller afterwards.
        """
        async def _safe_close() -> TerminationResult:
            try:
                return await managed.close(reason=reason)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Cleanup failures must become structured evidence, never a
                # lost death proof (UNKNOWN, not a manufactured death).
                logger.exception("Supervised cleanup failed: pid={}, reason={}", managed.pid, reason)
                return TerminationResult(
                    confirmed_dead=None,
                    root_return_code=getattr(managed.process, "returncode", None),
                    error_code="TERMINATION_EXCEPTION",
                    error_message=str(exc),
                )

        cleanup_task = asyncio.create_task(_safe_close())
        self._cleanup_tasks.add(cleanup_task)
        cleanup_task.add_done_callback(self._cleanup_tasks.discard)

        while True:
            try:
                await asyncio.shield(cleanup_task)
                break
            except asyncio.CancelledError:
                # Preserve the cancellation request but never cancel the
                # cleanup task itself.
                if cleanup_task.done():
                    break
                continue

        if cleanup_task.cancelled():
            result = TerminationResult(
                confirmed_dead=None,
                root_return_code=getattr(managed.process, "returncode", None),
                error_code="CLEANUP_CANCELLED",
                error_message="Cleanup task was cancelled before confirming process death",
            )
        else:
            cleanup_exc = cleanup_task.exception()
            if cleanup_exc is not None:
                result = TerminationResult(
                    confirmed_dead=None,
                    root_return_code=getattr(managed.process, "returncode", None),
                    error_code="TERMINATION_EXCEPTION",
                    error_message=str(cleanup_exc),
                )
            else:
                result = cleanup_task.result()
        record_attempt_termination(result, managed.process_identity)
        if result.confirmed_dead:
            self._processes.discard(managed)
        return result

    async def drain_cleanup_tasks(self, timeout: float = 10.0) -> None:
        """Wait for background cleanup tasks (used during graceful shutdown)."""
        tasks = [task for task in list(self._cleanup_tasks) if not task.done()]
        if not tasks:
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=max(0.1, timeout),
            )
        except asyncio.TimeoutError:
            pass

    @staticmethod
    def _windows_process_handles(process: asyncio.subprocess.Process) -> tuple[Optional[int], Optional[int]]:
        """Extract Popen process/thread handles from asyncio's Windows transport."""
        transport = getattr(process, "_transport", None)
        popen = None
        if transport is not None:
            get_extra_info = getattr(transport, "get_extra_info", None)
            if callable(get_extra_info):
                popen = get_extra_info("subprocess")
            popen = popen or getattr(transport, "_proc", None)
        popen = popen or getattr(process, "_proc", None)
        process_handle = getattr(popen, "_handle", None) if popen is not None else None
        thread_handle = getattr(popen, "_thread", None) if popen is not None else None
        process_handle = process_handle or getattr(process, "_handle", None)
        return (int(process_handle) if process_handle else None, int(thread_handle) if thread_handle else None)

    @staticmethod
    async def _monitor_tree(managed: ManagedAgentProcess) -> None:
        """Periodic tree sampling in the bounded inspection executor.

        psutil 的 recursive children / pid_exists 扫描绝不在事件循环上执行；
        每个受管进程同一时刻最多一个在飞 inspection，上一次采样未结束时不
        排队累积下一次（doc §12）。
        """
        interval = _monitor_interval_seconds()
        try:
            while not managed.stop_monitor:
                try:
                    snapshot = await run_process_inspection(
                        inspect_process_tree_snapshot, managed
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

    @staticmethod
    async def _persisted_root_snapshot(
        pid: int,
        process_started_at: Optional[datetime],
        *,
        check_command_marker: bool = False,
    ) -> PersistedProcessSnapshot:
        """One root identity probe off the loop (UNKNOWN on queue saturation)."""
        try:
            return await run_process_probe(
                functools.partial(
                    _probe_persisted_root_sync,
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

    @staticmethod
    async def _persisted_group_snapshot(
        process_group_id: Optional[int],
        *,
        ignored_pids: Optional[set[int]] = None,
    ) -> PersistedProcessSnapshot:
        """One process-group probe off the loop (UNKNOWN on queue saturation)."""
        try:
            return await run_process_probe(
                functools.partial(
                    _probe_persisted_group_sync,
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

    @staticmethod
    async def _token_snapshot(run_token: str) -> TokenDiscoverySnapshot:
        """One complete token scan off the loop (UNKNOWN on queue saturation)."""
        try:
            return await run_process_probe(_scan_token_processes_sync, run_token)
        except InspectionQueueSaturated as exc:
            return TokenDiscoverySnapshot(
                state=ProcessProbeState.UNKNOWN,
                failure_code="INSPECTION_QUEUE_SATURATED",
                error_message=str(exc),
            )

    @staticmethod
    async def _wait_persisted_snapshot_gone(
        probe: Callable[[], Any],
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

    async def _wait_persisted_root_gone(
        self,
        pid: int,
        process_started_at: Optional[datetime],
        timeout: float,
    ) -> PersistedProcessSnapshot:
        async def probe() -> PersistedProcessSnapshot:
            return await self._persisted_root_snapshot(pid, process_started_at)

        return await ProcessSupervisor._wait_persisted_snapshot_gone(probe, timeout)

    async def _wait_persisted_group_gone(
        self,
        process_group_id: Optional[int],
        timeout: float,
        *,
        ignored_pids: Optional[set[int]] = None,
    ) -> PersistedProcessSnapshot:
        async def probe() -> PersistedProcessSnapshot:
            return await self._persisted_group_snapshot(
                process_group_id, ignored_pids=ignored_pids
            )

        return await ProcessSupervisor._wait_persisted_snapshot_gone(probe, timeout)

    async def _wait_persisted_tree_gone(
        self,
        pid: int,
        process_started_at: Optional[datetime],
        process_group_id: Optional[int],
        timeout: float,
        *,
        ignored_pids: Optional[set[int]] = None,
    ) -> PersistedProcessSnapshot:
        """Wait until the persisted root and its group tri-state converge.

        root 消失只代表 root 已死亡，不代表 containment 为空（doc 修复方案
        §5.4）；组合快照在所有必需来源 CONFIRMED_DEAD 之前绝不返回死亡。
        """
        async def probe() -> PersistedProcessSnapshot:
            root = await self._persisted_root_snapshot(pid, process_started_at)
            group = await self._persisted_group_snapshot(
                process_group_id, ignored_pids=ignored_pids
            )
            return _combine_persisted_snapshots(root, group)

        return await ProcessSupervisor._wait_persisted_snapshot_gone(probe, timeout)

    async def stop_attempt(self, run_token: str, reason: str) -> Optional[TerminationResult]:
        """Stop every process registered under this run token (doc 10).

        Must not stop only the first match: a retry or a spawn race can leave
        more than one live tree under the same durable token.
        """
        matches = [item for item in self._processes if item.run_token == run_token]
        if not matches:
            return None
        results: list[TerminationResult] = []
        for managed in matches:
            result = await managed.close(reason=reason)
            record_attempt_termination(result, managed.process_identity)
            if result.confirmed_dead or result.error_code == "PID_REUSED":
                self._processes.discard(managed)
            results.append(result)
        if len(results) == 1:
            return results[0]
        failed = next((item for item in results if not item.confirmed_dead), None)
        if failed is not None:
            return failed
        return TerminationResult(
            confirmed_dead=True,
            root_return_code=next(
                (item.root_return_code for item in results if item.root_return_code is not None),
                None,
            ),
            signals_sent=tuple(
                signal for item in results for signal in item.signals_sent
            ),
            tree_kill_used=any(item.tree_kill_used for item in results),
        )

    def forget(self, managed: ManagedAgentProcess) -> None:
        cached = managed._last_termination
        if managed._closed or (
            managed.process.returncode is not None
            and bool(cached is not None and cached.confirmed_dead)
        ):
            self._processes.discard(managed)

    async def stop_persisted(
        self,
        pid: Optional[int],
        process_started_at: Optional[datetime],
        reason: str,
        process_group_id: Optional[int] = None,
        run_token: Optional[str] = None,
        not_before: Optional[datetime] = None,
    ) -> TerminationResult:
        """Stop a process from a previous boot only after ownership checks.

        Linux 顺序（doc 修复方案 §5.4）：
        1. 探测 root identity；root 不存在只表示 root 已死亡，不代表
           containment 为空（P0-1）；
        2. PGID 仍存活时即使 root 已消失也发送 SIGTERM/SIGKILL；
        3. 等待 root 与 PGID 的聚合三态快照收敛；
        4. 提供持久化 run token 时执行完整 token discovery，捕获脱离原
           PGID 的后代；
        5. 只有 group 与 token discovery 都明确为空才允许
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
            return await self._stop_persisted_windows(
                pid, process_started_at, _result
            )

        # ── 1. root identity probe（单次快照，不阻塞事件循环）──
        root = await self._persisted_root_snapshot(
            pid, process_started_at, check_command_marker=True
        )
        pid_reused = root.failure_code == "PID_REUSED"
        # 身份无法核实的存活 root（无关命令行/命令行不可读/创建时间不可读）
        # 绝不发信号（与旧行为一致，只是不再把探测错误折叠成 False）。
        may_signal_root = (
            root.state == ProcessProbeState.LIVE and root.failure_code is None
        )
        signals: list[str] = []
        if root.state == ProcessProbeState.CONFIRMED_DEAD and pid_reused:
            # root 身份已被另一个进程占用：禁止把复用 PID 当作 PGID。
            group_id = int(process_group_id) if process_group_id else None
        else:
            group_id = int(process_group_id) if process_group_id else pid

        # ── 2/3. 进程组信号与等待（root 已消失时仍处理 PGID）──
        group = await self._persisted_group_snapshot(
            group_id,
            ignored_pids={pid} if pid_reused else None,
        )
        need_signal = may_signal_root or group.state == ProcessProbeState.LIVE
        if need_signal:
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
            group = await self._wait_persisted_group_gone(
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
                group = await self._wait_persisted_group_gone(
                    group_id,
                    5.0,
                    ignored_pids={pid} if pid_reused else None,
                )
        else:
            # 没有任何可证实的存活目标：取一次最终快照作为聚合证据。
            group = await self._persisted_group_snapshot(
                group_id,
                ignored_pids={pid} if pid_reused else None,
            )
        if may_signal_root:
            # root 在信号前是存活的：必须重新探测获得最终死亡/存活证据，
            # 绝不能把信号前的过期 LIVE 快照当作聚合输入。
            final_root = await self._persisted_root_snapshot(pid, process_started_at)
        else:
            final_root = root

        # ── 4/5. 持久化 run token 的完整 discovery 兜底 ──
        token_unknown: Optional[TokenDiscoverySnapshot] = None
        token_live_pids: Tuple[int, ...] = ()
        if run_token:
            token_result, token_unknown = await self._run_token_containment(
                run_token,
                not_before=not_before,
                not_after=None,
                signals=signals,
            )
            if isinstance(token_result, TerminationResult):
                # token 命中但身份冲突：保持未确认，不做盲杀。
                return token_result
            if token_unknown is None:
                token_live_pids = tuple(token_result)
            else:
                token_live_pids = tuple(token_unknown.unknown_pids)

        state, failure_code, error_message, live_pids = _aggregate_persisted_snapshots(
            final_root, group
        )
        if token_unknown is not None:
            return _result(
                None,
                error_code=token_unknown.failure_code or TOKEN_DISCOVERY_UNKNOWN,
                error_message=token_unknown.error_message,
                signals=tuple(signals),
                tree_kill_used=bool(signals),
                remaining_pids=tuple(token_unknown.unknown_pids),
                root_identity_matches=final_root.root_identity_matches,
            )
        remaining = tuple(sorted(set(live_pids) | set(token_live_pids)))
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

    async def _run_token_containment(
        self,
        run_token: str,
        *,
        not_before: Optional[datetime],
        not_after: Optional[datetime],
        signals: list[str],
        max_wait: float = 5.0,
    ) -> Tuple[Union[Tuple[int, ...], TerminationResult], Optional[TokenDiscoverySnapshot]]:
        """Kill and verify every process carrying the exact run token.

        返回 ``(live_pids, unknown_snapshot)``：
        - ``unknown_snapshot`` 非 None：扫描不完整，调用方必须返回 UNKNOWN；
        - 否则 ``live_pids`` 是最终仍存活的 token 进程（空 == 完整扫描无命中）。
        身份冲突时返回 ``(TerminationResult, None)``，由调用方直接透传。
        """
        snapshot = await self._token_snapshot(run_token)
        if snapshot.state == ProcessProbeState.UNKNOWN:
            return (), snapshot
        matches = snapshot.matches
        if matches:
            good, conflicts = self._partition_token_matches(
                matches, not_before=not_before, not_after=not_after
            )
            if conflicts:
                return (
                    TerminationResult(
                        False,
                        None,
                        elapsed_ms=0,
                        error_code="TOKEN_PROCESS_IDENTITY_CONFLICT",
                        error_message=(
                            f"{len(conflicts)} run-token process(es) failed identity "
                            "validation; manual handling required"
                        ),
                        remaining_pids=tuple(sorted(int(m.pid) for m in conflicts)),
                    ),
                    None,
                )
            if good:
                self._kill_token_matches(good, signals)
                deadline = time.monotonic() + max(0.1, max_wait)
                while True:
                    snapshot = await self._token_snapshot(run_token)
                    if snapshot.state == ProcessProbeState.UNKNOWN:
                        return (), snapshot
                    if snapshot.state == ProcessProbeState.CONFIRMED_DEAD:
                        return (), None
                    good, conflicts = self._partition_token_matches(
                        snapshot.matches,
                        not_before=not_before,
                        not_after=not_after,
                    )
                    if conflicts:
                        return (
                            TerminationResult(
                                False,
                                None,
                                elapsed_ms=0,
                                error_code="TOKEN_PROCESS_IDENTITY_CONFLICT",
                                error_message=(
                                    f"{len(conflicts)} run-token process(es) failed "
                                    "identity validation; manual handling required"
                                ),
                                remaining_pids=tuple(
                                    sorted(int(m.pid) for m in conflicts)
                                ),
                            ),
                            None,
                        )
                    if good:
                        self._kill_token_matches(good, signals)
                    if time.monotonic() >= deadline:
                        break
                    await asyncio.sleep(0.1)
        # 最终一次快照给出聚合证据。
        final = await self._token_snapshot(run_token)
        if final.state == ProcessProbeState.UNKNOWN:
            return (), final
        if final.state == ProcessProbeState.LIVE:
            return tuple(sorted(int(m.pid) for m in final.matches)), None
        return (), None

    @staticmethod
    def _partition_token_matches(
        matches: Tuple[DiscoveredTokenProcess, ...],
        *,
        not_before: Optional[datetime],
        not_after: Optional[datetime],
    ) -> Tuple[Tuple[DiscoveredTokenProcess, ...], Tuple[DiscoveredTokenProcess, ...]]:
        """Split token matches into (killable, identity-conflicts)."""
        good: list[DiscoveredTokenProcess] = []
        conflicts: list[DiscoveredTokenProcess] = []
        for match in matches:
            if ProcessSupervisor._token_identity_ok(
                match, not_before=not_before, not_after=not_after
            ):
                good.append(match)
            else:
                conflicts.append(match)
        return tuple(good), tuple(conflicts)

    @staticmethod
    def _token_identity_ok(
        match: DiscoveredTokenProcess,
        *,
        not_before: Optional[datetime],
        not_after: Optional[datetime],
    ) -> bool:
        """Validate create-time window and command markers for a discovered process."""
        if match.create_time is None or not match.command_readable:
            return False
        if not_before is not None:
            expected = not_before if not_before.tzinfo else not_before.replace(tzinfo=timezone.utc)
            if match.create_time < expected.timestamp() - 2.0:
                return False
        if not_after is not None:
            expected = not_after if not_after.tzinfo else not_after.replace(tzinfo=timezone.utc)
            if match.create_time > expected.timestamp() + 2.0:
                return False
        return any(
            marker in match.command for marker in _TOKEN_PROCESS_COMMAND_MARKERS
        )

    @staticmethod
    def _kill_token_matches(
        matches: Tuple[DiscoveredTokenProcess, ...],
        signals: list[str],
    ) -> None:
        """SIGKILL the captured token process identities (executor data, loop kill)."""
        for match in matches:
            killed = False
            if match.process_group_id:
                try:
                    os.killpg(int(match.process_group_id), signal.SIGKILL)
                    killed = True
                except (ProcessLookupError, PermissionError, OSError):
                    killed = False
            if not killed:
                try:
                    os.kill(int(match.pid), signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    continue
            signals.append("SIGKILL")

    async def _stop_persisted_windows(
        self,
        pid: int,
        process_started_at: Optional[datetime],
        _result: Callable[..., TerminationResult],
    ) -> TerminationResult:
        """Windows persisted stop: taskkill tree + tri-state root verification."""
        root = await self._persisted_root_snapshot(
            pid, process_started_at, check_command_marker=True
        )
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
        try:
            taskkill = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(pid), "/T", "/F",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(asyncio.shield(taskkill.wait()), timeout=5.0)
        except Exception as exc:
            return _result(
                False,
                error_code="TASKKILL_FAILED",
                error_message=str(exc),
                signals=tuple(signals),
                tree_kill_used=True,
            )
        final = await self._wait_persisted_root_gone(pid, process_started_at, 5.0)
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
        self,
        pid: Optional[int],
        process_started_at: Optional[datetime],
        process_group_id: Optional[int] = None,
    ) -> TerminationResult:
        """Verify external cleanup without sending a signal.

        This is separate from ``stop_persisted`` so the confirm-cleanup API
        cannot accidentally terminate a PID that has since been reused.

        权限/探测错误保留为 UNKNOWN（``confirmed_dead=None`` + 结构化
        failure code），绝不被折叠成“组为空”（doc 修复方案 §6.4）。
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
        root = await self._persisted_root_snapshot(int(pid), process_started_at)
        if root.failure_code == "PID_REUSED" or (
            root.state == ProcessProbeState.CONFIRMED_DEAD
            and root.root_identity_matches is False
        ):
            group = await self._persisted_group_snapshot(
                process_group_id, ignored_pids={int(pid)}
            )
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
            group = await self._persisted_group_snapshot(process_group_id)
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
        self,
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

        snapshot = await self._token_snapshot(run_token)
        if snapshot.state == ProcessProbeState.UNKNOWN:
            return TerminationResult(
                None,
                None,
                elapsed_ms=_elapsed(),
                error_code=snapshot.failure_code or TOKEN_DISCOVERY_UNKNOWN,
                error_message=snapshot.error_message,
                remaining_pids=tuple(snapshot.unknown_pids),
            )
        matches = snapshot.matches
        if not matches:
            # Re-scan once after a short grace period to absorb the fork/exec
            # window before confirming "nothing carries the token".
            await asyncio.sleep(0.5)
            snapshot = await self._token_snapshot(run_token)
            if snapshot.state == ProcessProbeState.UNKNOWN:
                return TerminationResult(
                    None,
                    None,
                    elapsed_ms=_elapsed(),
                    error_code=snapshot.failure_code or TOKEN_DISCOVERY_UNKNOWN,
                    error_message=snapshot.error_message,
                    remaining_pids=tuple(snapshot.unknown_pids),
                )
            matches = snapshot.matches
            if not matches:
                return TerminationResult(
                    True,
                    None,
                    elapsed_ms=_elapsed(),
                )
        good, conflicts = self._partition_token_matches(
            matches, not_before=not_before, not_after=not_after
        )
        if conflicts:
            return TerminationResult(
                False,
                None,
                elapsed_ms=_elapsed(),
                error_code="TOKEN_PROCESS_IDENTITY_CONFLICT",
                error_message=(
                    f"{len(conflicts)} run-token process(es) failed identity "
                    "validation; manual handling required"
                ),
                remaining_pids=tuple(sorted(int(m.pid) for m in conflicts)),
            )
        signals: list[str] = []
        self._kill_token_matches(good, signals)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            snapshot = await self._token_snapshot(run_token)
            if snapshot.state == ProcessProbeState.UNKNOWN:
                return TerminationResult(
                    None,
                    None,
                    signals_sent=tuple(signals),
                    tree_kill_used=True,
                    elapsed_ms=_elapsed(),
                    error_code=snapshot.failure_code or TOKEN_DISCOVERY_UNKNOWN,
                    error_message=snapshot.error_message,
                    remaining_pids=tuple(snapshot.unknown_pids),
                )
            if snapshot.state == ProcessProbeState.CONFIRMED_DEAD:
                return TerminationResult(
                    True,
                    None,
                    signals_sent=tuple(signals),
                    tree_kill_used=True,
                    elapsed_ms=_elapsed(),
                )
            good, conflicts = self._partition_token_matches(
                snapshot.matches, not_before=not_before, not_after=not_after
            )
            if conflicts:
                return TerminationResult(
                    False,
                    None,
                    signals_sent=tuple(signals),
                    tree_kill_used=True,
                    elapsed_ms=_elapsed(),
                    error_code="TOKEN_PROCESS_IDENTITY_CONFLICT",
                    error_message=(
                        f"{len(conflicts)} run-token process(es) failed identity "
                        "validation; manual handling required"
                    ),
                    remaining_pids=tuple(sorted(int(m.pid) for m in conflicts)),
                )
            if good:
                self._kill_token_matches(good, signals)
            await asyncio.sleep(0.1)
        snapshot = await self._token_snapshot(run_token)
        if snapshot.state == ProcessProbeState.UNKNOWN:
            return TerminationResult(
                None,
                None,
                signals_sent=tuple(signals),
                tree_kill_used=True,
                elapsed_ms=_elapsed(),
                error_code=snapshot.failure_code or TOKEN_DISCOVERY_UNKNOWN,
                error_message=snapshot.error_message,
                remaining_pids=tuple(snapshot.unknown_pids),
            )
        remaining = tuple(sorted(int(m.pid) for m in snapshot.matches))
        return TerminationResult(
            False,
            None,
            signals_sent=tuple(signals),
            tree_kill_used=True,
            elapsed_ms=_elapsed(),
            error_code="PROCESS_TREE_STILL_ALIVE",
            error_message=f"Run-token process tree survived after {reason}",
            remaining_pids=remaining,
        )

    async def stop_all(self, reason: str = "worker_shutdown") -> list[TerminationResult]:
        processes = list(self._processes)
        results = await asyncio.gather(
            *(item.close(reason=reason) for item in processes),
            return_exceptions=True,
        )
        output: list[TerminationResult] = []
        for managed, result in zip(processes, results):
            if isinstance(result, TerminationResult):
                record_attempt_termination(result, managed.process_identity)
                output.append(result)
                if result.confirmed_dead:
                    self._processes.discard(managed)
            else:
                output.append(
                    TerminationResult(
                        confirmed_dead=False,
                        root_return_code=None,
                        error_code="TERMINATION_EXCEPTION",
                        error_message=str(result),
                    )
                )
        return output


process_supervisor = ProcessSupervisor()


__all__ = [
    "DiscoveredTokenProcess",
    "InspectionQueueSaturated",
    "ManagedAgentProcess",
    "PersistedProcessSnapshot",
    "ProcessProbeState",
    "ProcessSupervisor",
    "ProcessTreeSnapshot",
    "ProcessWaitResult",
    "PROCESS_GROUP_UNKNOWN",
    "PROCESS_TREE_UNKNOWN",
    "TOKEN_DISCOVERY_UNKNOWN",
    "TerminationResult",
    "TokenDiscoverySnapshot",
    "agent_stop_result_from_termination",
    "containment_capability",
    "containment_id_for_run_token",
    "inspect_process_tree_snapshot",
    "process_supervisor",
    "run_process_inspection",
    "run_process_probe",
]
