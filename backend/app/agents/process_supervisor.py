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
import os
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Optional

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
    confirmed_dead: bool
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


@dataclass(frozen=True)
class ProcessTreeSnapshot:
    """One off-loop process-tree inspection sample (doc §12)."""

    live_descendant_pids: tuple[int, ...] = ()
    root_return_code: Optional[int] = None
    error: bool = False


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


def inspect_process_tree_snapshot(managed: "ManagedAgentProcess") -> ProcessTreeSnapshot:
    """Pure synchronous psutil snapshot; never call directly from the event loop."""
    root_return_code = getattr(managed.process, "returncode", None)
    if psutil is None:
        return ProcessTreeSnapshot(root_return_code=root_return_code)
    live: set[int] = set()
    try:
        root = psutil.Process(managed.pid)
        for child in root.children(recursive=True):
            live.add(int(child.pid))
    except (psutil.Error, OSError, ValueError):
        pass
    for pid in managed.known_descendant_pids:
        if pid in live:
            continue
        try:
            proc = psutil.Process(int(pid))
            if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                live.add(int(pid))
        except (psutil.Error, OSError, ValueError):
            continue
    return ProcessTreeSnapshot(
        live_descendant_pids=tuple(sorted(live)),
        root_return_code=root_return_code,
    )


async def run_process_inspection(
    fn: Callable[["ManagedAgentProcess"], ProcessTreeSnapshot],
    managed: "ManagedAgentProcess",
) -> ProcessTreeSnapshot:
    """Run one tree inspection in the bounded executor (never on the loop).

    The monitor awaits the result, so a single managed process can never have
    more than one outstanding inspection and samples do not queue up.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_inspection_executor(), fn, managed)


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

    def apply_snapshot(self, snapshot: ProcessTreeSnapshot) -> None:
        """Merge one executor-produced tree sample into tracked descendants."""
        if snapshot is None or snapshot.error:
            # A failed sample must never erase known descendants.
            return
        self.known_descendant_pids = set(snapshot.live_descendant_pids)

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

    def _root_matches(self) -> bool:
        if psutil is None:
            return self.process.returncode is None
        try:
            proc = psutil.Process(self.pid)
            if proc.status() == psutil.STATUS_ZOMBIE:
                return False
            if self.process_start_time is not None:
                if abs(float(proc.create_time()) - self.process_start_time) > 2.0:
                    return False
            return proc.is_running()
        except (psutil.Error, OSError, ValueError):
            return False

    def _windows_job_has_processes(self) -> bool:
        if os.name != "nt" or not self.job_handle:
            return False
        try:
            # JOB_OBJECT_BASIC_PROCESS_ID_LIST stores ULONG_PTR PIDs.  A
            # DWORD array truncates handles/PIDs on 64-bit Windows.
            capacity = 256
            buffer_size = ctypes.sizeof(_WindowsJobProcessIdList) + ctypes.sizeof(_ULONG_PTR) * capacity
            buffer = (ctypes.c_byte * buffer_size)()
            returned = ctypes.wintypes.DWORD()
            ok = _windows_kernel32().QueryInformationJobObject(
                ctypes.wintypes.HANDLE(self.job_handle),
                3,
                ctypes.byref(buffer),
                buffer_size,
                ctypes.byref(returned),
            )
            if not ok:
                return False
            header = _WindowsJobProcessIdList.from_buffer(buffer)
            count = min(int(header.NumberOfProcessIdsInList), capacity)
            ids = (_ULONG_PTR * capacity).from_buffer(buffer, ctypes.sizeof(_WindowsJobProcessIdList))
            return any(int(ids[index]) != self.pid for index in range(count))
        except Exception:
            return False

    def _tree_has_live_processes(self) -> bool:
        if self._windows_job_has_processes():
            return True
        if psutil is None:
            return self.process.returncode is None
        if any(self._pid_is_live(pid) for pid in self.known_descendant_pids):
            return True
        if os.name != "nt" and self._posix_group_has_live_processes():
            return True
        try:
            root = psutil.Process(self.pid)
            descendants = root.children(recursive=True)
            return any(child.is_running() and child.status() != psutil.STATUS_ZOMBIE for child in descendants)
        except (psutil.Error, OSError, ValueError):
            if os.name != "nt":
                try:
                    os.killpg(self.pid, 0)
                    return True
                except (ProcessLookupError, PermissionError, OSError):
                    pass
            return self._root_matches()

    @staticmethod
    def _pid_is_live(pid: int) -> bool:
        if psutil is None:
            return False
        try:
            proc = psutil.Process(int(pid))
            return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
        except (psutil.Error, OSError, ValueError):
            return False

    def _posix_group_pids(self) -> set[int]:
        if os.name == "nt" or not self.process_group_id:
            return set()
        try:
            os.killpg(int(self.process_group_id), 0)
        except (ProcessLookupError, PermissionError, OSError):
            return set()
        if psutil is None:
            return {self.pid}
        pids: set[int] = set()
        try:
            for proc in psutil.process_iter(["pid", "status"]):
                try:
                    if proc.status() == psutil.STATUS_ZOMBIE:
                        continue
                    if os.getpgid(proc.pid) == int(self.process_group_id):
                        pids.add(int(proc.pid))
                except (psutil.Error, OSError, ValueError):
                    continue
        except (psutil.Error, OSError, ValueError):
            return {self.pid}
        return pids

    def _posix_group_has_live_processes(self) -> bool:
        return bool(self._posix_group_pids())

    async def _wait_for_exit(self, timeout: float) -> bool:
        if self.process.returncode is None:
            try:
                await asyncio.wait_for(asyncio.shield(self.process.wait()), timeout=max(0.01, timeout))
            except asyncio.TimeoutError:
                return False
            except ProcessLookupError:
                pass
        # A wrapper may have exited while a descendant is still alive.
        if self._tree_has_live_processes():
            await asyncio.sleep(0)
            return False
        return True

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
            root_alive = self.process.returncode is None
            tree_alive = self._tree_has_live_processes()
            if root_alive or tree_alive:
                if graceful and root_alive:
                    if os.name == "nt":
                        ctrl_break = getattr(signal, "CTRL_BREAK_EVENT", None)
                        if ctrl_break is not None:
                            self.process.send_signal(ctrl_break)
                            signals.append("CTRL_BREAK_EVENT")
                    elif self._send_posix_group(signal.SIGINT):
                        signals.append("SIGINT")
                    if await self._wait_for_exit(3.0):
                        return self._result(signals, tree_kill_used, started)

                if os.name == "nt":
                    tree_kill_used = True
                    await self._taskkill_tree(signals)
                elif self._send_posix_group(signal.SIGTERM):
                    signals.append("SIGTERM")
                if await self._wait_for_exit(3.0):
                    return self._result(signals, tree_kill_used, started)

                tree_kill_used = tree_kill_used or os.name == "nt"
                await self._force_kill(signals)
                if not await self._wait_for_exit(5.0):
                    error_code = "PROCESS_TREE_STILL_ALIVE"
                    error_message = f"Agent process tree did not exit after {reason}"
            confirmed_dead = not self._tree_has_live_processes() and self.process.returncode is not None
            return self._result(
                signals,
                tree_kill_used,
                started,
                confirmed_dead=confirmed_dead,
                error_code=error_code if not confirmed_dead else None,
                error_message=error_message if not confirmed_dead else None,
            )
        except Exception as exc:
            logger.exception("Agent process termination failed: pid={}, reason={}", self.pid, reason)
            return self._result(
                signals,
                tree_kill_used,
                started,
                confirmed_dead=False,
                error_code="TERMINATION_EXCEPTION",
                error_message=str(exc),
            )

    def _result(
        self,
        signals: Iterable[str],
        tree_kill_used: bool,
        started: float,
        *,
        confirmed_dead: Optional[bool] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> TerminationResult:
        if confirmed_dead is None:
            confirmed_dead = not self._tree_has_live_processes() and self.process.returncode is not None
        return TerminationResult(
            confirmed_dead=bool(confirmed_dead),
            root_return_code=self.process.returncode,
            signals_sent=tuple(signals),
            tree_kill_used=tree_kill_used,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            error_code=error_code,
            error_message=error_message,
            remaining_pids=self._remaining_pids(),
            root_identity_matches=self._root_identity_matches(),
        )

    def _root_identity_matches(self) -> Optional[bool]:
        if psutil is None:
            return None
        try:
            proc = psutil.Process(self.pid)
            if self.process_start_time is None:
                return True
            return abs(float(proc.create_time()) - self.process_start_time) <= 2.0
        except (psutil.Error, OSError, ValueError):
            return False

    def _remaining_pids(self) -> tuple[int, ...]:
        pids = {pid for pid in self.known_descendant_pids if self._pid_is_live(pid)}
        pids.update(self._posix_group_pids())
        if self._root_matches():
            pids.add(self.pid)
        return tuple(sorted(pids))

    async def wait(self) -> ProcessWaitResult:
        try:
            root_return_code = await self.process.wait()
            termination = TerminationResult(
                confirmed_dead=not self._tree_has_live_processes(),
                root_return_code=root_return_code,
                root_identity_matches=self._root_identity_matches(),
                remaining_pids=self._remaining_pids(),
            )
            if self._tree_has_live_processes():
                # The root's exit is not the end of the attempt.  Preserve the
                # actual tree-cleanup result so callers cannot report SUCCESS
                # while descendants are still alive.
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
        return sum(1 for item in self._processes if item.process.returncode is None or item._tree_has_live_processes())

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
                # lost death proof.
                logger.exception("Supervised cleanup failed: pid={}, reason={}", managed.pid, reason)
                return TerminationResult(
                    confirmed_dead=False,
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
                confirmed_dead=False,
                root_return_code=getattr(managed.process, "returncode", None),
                error_code="CLEANUP_CANCELLED",
                error_message="Cleanup task was cancelled before confirming process death",
            )
        else:
            cleanup_exc = cleanup_task.exception()
            if cleanup_exc is not None:
                result = TerminationResult(
                    confirmed_dead=False,
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
                    snapshot = ProcessTreeSnapshot(error=True)
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
    async def _wait_persisted_pid_gone(pid: int, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + max(0.1, timeout)
        while time.monotonic() < deadline:
            try:
                proc = psutil.Process(pid) if psutil is not None else None
                if proc is None or not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                    return True
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                return True
            except (psutil.Error, OSError, ValueError):
                pass
            await asyncio.sleep(0.1)
        try:
            proc = psutil.Process(pid)
            return not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return True
        except (psutil.Error, OSError, ValueError):
            return False

    @staticmethod
    async def _wait_persisted_tree_gone(
        pid: int,
        process_group_id: Optional[int],
        timeout: float = 5.0,
    ) -> bool:
        """Wait for the persisted root and its POSIX process group to exit.

        The root can disappear before a wrapper-spawned child.  A PID-only
        check would therefore incorrectly report a successful reclaim while
        the agent still owns live descendants.
        """
        if os.name == "nt" or not process_group_id:
            return await ProcessSupervisor._wait_persisted_pid_gone(pid, timeout)

        deadline = time.monotonic() + max(0.1, timeout)
        group_id = int(process_group_id)
        while time.monotonic() < deadline:
            root_gone = await ProcessSupervisor._wait_persisted_pid_gone(pid, timeout=0.1)
            group_alive = False
            try:
                os.killpg(group_id, 0)
                if psutil is not None:
                    for proc in psutil.process_iter(["pid", "status"]):
                        try:
                            if proc.status() == psutil.STATUS_ZOMBIE:
                                continue
                            if os.getpgid(proc.pid) == group_id:
                                group_alive = True
                                break
                        except (psutil.Error, OSError, ValueError):
                            continue
                else:
                    group_alive = True
            except (ProcessLookupError, PermissionError, OSError):
                group_alive = False
            if root_gone and not group_alive:
                return True
            await asyncio.sleep(0.1)
        return False

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
        if managed._closed or (
            managed.process.returncode is not None and not managed._tree_has_live_processes()
        ):
            self._processes.discard(managed)

    async def stop_persisted(
        self,
        pid: Optional[int],
        process_started_at: Optional[datetime],
        reason: str,
        process_group_id: Optional[int] = None,
    ) -> TerminationResult:
        """Stop a process from a previous boot only after ownership checks."""
        started = time.monotonic()
        if not pid:
            return TerminationResult(True, None, elapsed_ms=0)
        if psutil is None:
            return TerminationResult(
                False, None, elapsed_ms=0,
                error_code="PROCESS_INSPECTION_UNAVAILABLE",
                error_message="psutil is required to reclaim persisted process ownership",
            )
        try:
            proc = psutil.Process(int(pid))
            actual_started = float(proc.create_time())
            if process_started_at is not None:
                expected_started = process_started_at
                if expected_started.tzinfo is None:
                    expected_started = expected_started.replace(tzinfo=timezone.utc)
                if abs(actual_started - expected_started.timestamp()) > 2.0:
                    return TerminationResult(
                        False, None, elapsed_ms=int((time.monotonic() - started) * 1000),
                        error_code="PID_REUSED",
                        error_message=f"PID {pid} create time does not match persisted owner",
                    )
            command = " ".join(proc.cmdline()).lower()
            if not any(marker in command for marker in ("claude", "node", "traceforge")):
                return TerminationResult(
                    False, None, elapsed_ms=int((time.monotonic() - started) * 1000),
                    error_code="PID_OWNERSHIP_UNVERIFIED",
                    error_message=f"PID {pid} is not an identifiable TraceForge Agent process",
                )
            if os.name == "nt":
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
                    return TerminationResult(
                        False, None, signals_sent=tuple(signals), tree_kill_used=True,
                        elapsed_ms=int((time.monotonic() - started) * 1000),
                        error_code="TASKKILL_FAILED", error_message=str(exc),
                    )
                if not await self._wait_persisted_pid_gone(int(pid)):
                    return TerminationResult(
                        False, None, signals_sent=tuple(signals), tree_kill_used=True,
                        elapsed_ms=int((time.monotonic() - started) * 1000),
                        error_code="PROCESS_TREE_STILL_ALIVE",
                        error_message=f"Persisted process tree {pid} is still alive",
                    )
            else:
                group_id = int(process_group_id or pid)
                try:
                    os.killpg(group_id, signal.SIGTERM)
                except (ProcessLookupError, PermissionError, OSError):
                    proc.terminate()
                if not await self._wait_persisted_tree_gone(
                    int(pid), group_id, timeout=3.0
                ):
                    try:
                        os.killpg(group_id, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError, OSError):
                        try:
                            proc.kill()
                        except psutil.Error:
                            pass
                alive = [] if await self._wait_persisted_tree_gone(
                    int(pid), group_id, timeout=5.0
                ) else [proc]
                if alive:
                    return TerminationResult(
                        False, None, signals_sent=("SIGTERM", "SIGKILL"),
                        tree_kill_used=True,
                        elapsed_ms=int((time.monotonic() - started) * 1000),
                        error_code="PROCESS_TREE_STILL_ALIVE",
                        error_message=f"Persisted process tree {pid} is still alive",
                    )
            confirmed = await self._wait_persisted_tree_gone(
                int(pid), process_group_id, timeout=0.1
            )
            return TerminationResult(
                confirmed,
                None,
                signals_sent=("TASKKILL_TREE",) if os.name == "nt" else ("SIGTERM", "SIGKILL"),
                tree_kill_used=True,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                error_code=None if confirmed else "PROCESS_STILL_ALIVE",
                error_message=None if confirmed else f"PID {pid} is still alive",
            )
        except psutil.NoSuchProcess:
            return TerminationResult(True, None, elapsed_ms=int((time.monotonic() - started) * 1000))
        except Exception as exc:
            return TerminationResult(
                False, None,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                error_code="PERSISTED_TERMINATION_EXCEPTION",
                error_message=str(exc),
            )

    @staticmethod
    def _persisted_group_has_live_processes(
        process_group_id: Optional[int],
        *,
        ignored_pids: Optional[set[int]] = None,
    ) -> bool:
        """Return whether a persisted POSIX process group still has members.

        The check is intentionally conservative for manual cleanup: seeing a
        live member means the original ownership cannot be proven gone.  A
        reused root PID may be ignored because its create time has already
        proven that it is a different process and must never be terminated.
        """
        if os.name == "nt" or not process_group_id or psutil is None:
            return False
        ignored = ignored_pids or set()
        group_id = int(process_group_id)
        try:
            os.killpg(group_id, 0)
        except (ProcessLookupError, PermissionError, OSError):
            return False
        for item in psutil.process_iter(["pid", "status"]):
            try:
                pid = int(item.pid)
                if pid in ignored or item.status() == psutil.STATUS_ZOMBIE:
                    continue
                if os.getpgid(pid) == group_id:
                    return True
            except (psutil.Error, OSError, ValueError):
                continue
        return False

    async def verify_persisted_cleanup(
        self,
        pid: Optional[int],
        process_started_at: Optional[datetime],
        process_group_id: Optional[int] = None,
    ) -> TerminationResult:
        """Verify external cleanup without sending a signal.

        This is separate from ``stop_persisted`` so the confirm-cleanup API
        cannot accidentally terminate a PID that has since been reused.
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
        try:
            proc = psutil.Process(int(pid))
            actual_started = float(proc.create_time())
            expected_started = process_started_at
            if expected_started.tzinfo is None:
                expected_started = expected_started.replace(tzinfo=timezone.utc)
            if abs(actual_started - expected_started.timestamp()) > 2.0:
                group_alive = self._persisted_group_has_live_processes(
                    process_group_id,
                    ignored_pids={int(pid)},
                )
                if group_alive:
                    return TerminationResult(
                        False,
                        None,
                        elapsed_ms=int((time.monotonic() - started) * 1000),
                        error_code="PROCESS_GROUP_STILL_ALIVE",
                        error_message="Persisted process group still has live members",
                        root_identity_matches=False,
                    )
                return TerminationResult(
                    True,
                    None,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                    error_code="PID_REUSED",
                    root_identity_matches=False,
                )

            if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                group_alive = self._persisted_group_has_live_processes(
                    process_group_id,
                    ignored_pids={int(pid)},
                )
                if not group_alive:
                    return TerminationResult(
                        True,
                        None,
                        elapsed_ms=int((time.monotonic() - started) * 1000),
                        root_identity_matches=True,
                    )
            return TerminationResult(
                False,
                None,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                error_code="PROCESS_TREE_STILL_ALIVE",
                error_message=f"Persisted process tree {pid} is still alive",
                root_identity_matches=True,
            )
        except psutil.NoSuchProcess:
            if self._persisted_group_has_live_processes(process_group_id):
                return TerminationResult(
                    False,
                    None,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                    error_code="PROCESS_GROUP_STILL_ALIVE",
                    error_message="Persisted process group still has live members",
                )
            return TerminationResult(
                True,
                None,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        except Exception as exc:
            return TerminationResult(
                False,
                None,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                error_code="PERSISTED_VERIFICATION_EXCEPTION",
                error_message=str(exc),
            )

    def _iter_token_processes(self, run_token: str) -> list["psutil.Process"]:
        """Constrained /proc discovery of processes carrying the exact run token.

        Linux fallback when no in-memory registration or persisted PID exists
        (doc 7.3).  Constraints enforced here:
        - same-UID processes only;
        - exact NUL-separated environ match of TRACEFORGE_RUN_TOKEN — never a
          cmdline substring match;
        - our own worker process is always excluded.
        """
        if os.name == "nt" or psutil is None:
            return []
        token = str(run_token or "").strip()
        if not token:
            return []
        try:
            current_uid = os.getuid()
        except AttributeError:
            current_uid = None
        matches: list["psutil.Process"] = []
        for proc in psutil.process_iter(["pid"]):
            try:
                if int(proc.pid) == os.getpid():
                    continue
                if current_uid is not None:
                    try:
                        if proc.uids().real != current_uid:
                            continue
                    except (psutil.Error, OSError):
                        continue
                environ = proc.environ()
                if environ.get(RUN_TOKEN_ENV_VAR) != token:
                    continue
                matches.append(proc)
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.Error, OSError, ValueError):
                continue
        return matches

    @staticmethod
    def _token_process_identity_ok(proc: "psutil.Process", *, not_before, not_after) -> bool:
        """Validate create-time window and command markers for a discovered process."""
        try:
            create_time = float(proc.create_time())
        except (psutil.Error, OSError, ValueError):
            return False
        if not_before is not None:
            expected = not_before if not_before.tzinfo else not_before.replace(tzinfo=timezone.utc)
            if create_time < expected.timestamp() - 2.0:
                return False
        if not_after is not None:
            expected = not_after if not_after.tzinfo else not_after.replace(tzinfo=timezone.utc)
            if create_time > expected.timestamp() + 2.0:
                return False
        try:
            command = " ".join(proc.cmdline()).lower()
        except (psutil.Error, OSError, ValueError):
            return False
        return any(marker in command for marker in _TOKEN_PROCESS_COMMAND_MARKERS)

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
        Identity conflicts (unknown command, out-of-window create time) keep
        the attempt unconfirmed instead of blindly killing.
        """
        if os.name == "nt" or psutil is None:
            return None
        started = time.monotonic()

        def _scan() -> list["psutil.Process"]:
            return self._iter_token_processes(run_token)

        matches = _scan()
        if not matches:
            # Re-scan once after a short grace period to absorb the fork/exec
            # window before confirming "nothing carries the token".
            await asyncio.sleep(0.5)
            matches = _scan()
            if not matches:
                return TerminationResult(
                    confirmed_dead=True,
                    root_return_code=None,
                    signals_sent=(),
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )
        conflicts = [
            proc
            for proc in matches
            if not self._token_process_identity_ok(proc, not_before=not_before, not_after=not_after)
        ]
        if conflicts:
            return TerminationResult(
                confirmed_dead=False,
                root_return_code=None,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                error_code="TOKEN_PROCESS_IDENTITY_CONFLICT",
                error_message=(
                    f"{len(conflicts)} run-token process(es) failed identity validation; "
                    "manual handling required"
                ),
                remaining_pids=tuple(sorted(int(proc.pid) for proc in conflicts)),
            )
        signals: list[str] = []
        for proc in matches:
            try:
                pgid = os.getpgid(int(proc.pid))
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.kill()
                except (psutil.Error, OSError, ValueError):
                    continue
            signals.append("SIGKILL")
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if not _scan():
                return TerminationResult(
                    confirmed_dead=True,
                    root_return_code=None,
                    signals_sent=tuple(signals),
                    tree_kill_used=True,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )
            await asyncio.sleep(0.1)
        remaining = tuple(sorted(int(proc.pid) for proc in _scan()))
        return TerminationResult(
            confirmed_dead=False,
            root_return_code=None,
            signals_sent=tuple(signals),
            tree_kill_used=True,
            elapsed_ms=int((time.monotonic() - started) * 1000),
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
    "ManagedAgentProcess",
    "ProcessSupervisor",
    "ProcessTreeSnapshot",
    "ProcessWaitResult",
    "TerminationResult",
    "agent_stop_result_from_termination",
    "containment_capability",
    "containment_id_for_run_token",
    "inspect_process_tree_snapshot",
    "process_supervisor",
    "run_process_inspection",
]
