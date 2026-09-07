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
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

try:  # psutil is used for create-time and descendant verification.
    import psutil
except ImportError:  # pragma: no cover - packaging/runtime guard
    psutil = None  # type: ignore[assignment]

from app.core.logging import get_logger
from app.agents.contract import AgentProcessIdentity

logger = get_logger(__name__, category="agent_process")


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

    @property
    def pid(self) -> int:
        return int(self.process.pid)

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
        started = self.process_started_at or self.created_at
        group_id = self.process_group_id if os.name != "nt" else None
        containment_id = f"job:{self.job_handle:x}" if self.job_handle else None
        return AgentProcessIdentity(
            pid=self.pid,
            started_at=datetime.fromtimestamp(started, tz=timezone.utc),
            process_group_id=group_id,
            containment_id=containment_id,
        )

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
        result = await self._terminate(reason=reason, graceful=True)
        await self._reap_readers(timeout=2.0)
        if result.confirmed_dead:
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
        started = time.monotonic()
        signals: list[str] = []
        tree_kill_used = False
        error_code: Optional[str] = None
        error_message: Optional[str] = None
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
    ) -> ManagedAgentProcess:
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
        managed = ManagedAgentProcess(
            process=process,
            run_token=run_token,
            worker_boot_id=worker_boot_id,
            job_handle=_windows_job_object() if os.name == "nt" else None,
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
        if psutil is not None:
            managed.monitor_task = asyncio.create_task(self._monitor_tree(managed))
        if on_process_started is not None:
            try:
                accepted = on_process_started(managed.process_identity)
                if asyncio.iscoroutine(accepted):
                    accepted = await accepted
            except Exception:
                # A failed durable attach is indistinguishable from a
                # rejected attempt: close the tree before propagating the
                # callback error, while retaining it if death is unconfirmed.
                result = await managed.close(reason="attempt_fence_callback_failed")
                if result.confirmed_dead:
                    self._processes.discard(managed)
                raise
            if not accepted:
                result = await managed.close(reason="attempt_fence_rejected")
                if result.confirmed_dead:
                    self._processes.discard(managed)
                raise RuntimeError("Agent process could not be attached to the current job attempt")
        return managed

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
        try:
            while not managed.stop_monitor:
                try:
                    root = psutil.Process(managed.pid) if psutil is not None else None
                    if root is not None:
                        for child in root.children(recursive=True):
                            managed.known_descendant_pids.add(int(child.pid))
                    managed.known_descendant_pids = {
                        pid for pid in managed.known_descendant_pids if psutil.pid_exists(pid)
                    }
                    if managed.process.returncode is not None and not managed.known_descendant_pids:
                        return
                except Exception:
                    pass
                await asyncio.sleep(0.05)
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
        matches = [item for item in self._processes if item.run_token == run_token]
        if not matches:
            return None
        result = await matches[0].close(reason=reason)
        if result.confirmed_dead or result.error_code == "PID_REUSED":
            self._processes.discard(matches[0])
        return result

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

    async def stop_all(self, reason: str = "worker_shutdown") -> list[TerminationResult]:
        processes = list(self._processes)
        results = await asyncio.gather(
            *(item.close(reason=reason) for item in processes),
            return_exceptions=True,
        )
        output: list[TerminationResult] = []
        for managed, result in zip(processes, results):
            if isinstance(result, TerminationResult):
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
    "ProcessWaitResult",
    "TerminationResult",
    "process_supervisor",
]
