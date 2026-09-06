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

logger = get_logger(__name__, category="agent_process")


@dataclass(frozen=True)
class TerminationResult:
    confirmed_dead: bool
    root_return_code: Optional[int]
    signals_sent: tuple[str, ...] = ()
    tree_kill_used: bool = False
    elapsed_ms: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None


def _windows_job_object() -> Optional[int]:
    """Create a kill-on-close Windows Job Object when available."""
    if os.name != "nt":
        return None
    try:
        kernel32 = ctypes.windll.kernel32
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
        return int(handle)
    except Exception as exc:  # pragma: no cover - platform-specific fallback
        logger.warning("Unable to create Windows Job Object: {}", exc)
        return None


def _close_windows_handle(handle: Optional[int]) -> None:
    if handle and os.name == "nt":
        try:
            ctypes.windll.kernel32.CloseHandle(ctypes.wintypes.HANDLE(handle))
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

    @property
    def pid(self) -> int:
        return int(self.process.pid)

    @property
    def process_started_at(self) -> Optional[float]:
        if psutil is None:
            return self.created_at
        try:
            return float(psutil.Process(self.pid).create_time())
        except (psutil.Error, OSError, ValueError):
            return self.created_at

    def add_reader_task(self, task: asyncio.Task) -> None:
        self.reader_tasks.append(task)

    def _root_matches(self) -> bool:
        if psutil is None:
            return self.process.returncode is None
        try:
            proc = psutil.Process(self.pid)
            if proc.status() == psutil.STATUS_ZOMBIE:
                return False
            return proc.is_running()
        except (psutil.Error, OSError, ValueError):
            return False

    def _windows_job_has_processes(self) -> bool:
        if os.name != "nt" or not self.job_handle:
            return False
        try:
            # JobObjectBasicProcessIdList (class 3): DWORD count fields,
            # followed by an array of DWORD process ids.
            buffer = (ctypes.c_byte * 4096)()
            returned = ctypes.wintypes.DWORD()
            ok = ctypes.windll.kernel32.QueryInformationJobObject(
                ctypes.wintypes.HANDLE(self.job_handle),
                3,
                ctypes.byref(buffer),
                ctypes.sizeof(buffer),
                ctypes.byref(returned),
            )
            if not ok:
                return False
            count = ctypes.cast(ctypes.byref(buffer, 4), ctypes.POINTER(ctypes.wintypes.DWORD))[0]
            ids = ctypes.cast(ctypes.byref(buffer, 8), ctypes.POINTER(ctypes.wintypes.DWORD))
            return any(int(ids[index]) != self.pid for index in range(int(count)))
        except Exception:
            return False

    def _tree_has_live_processes(self) -> bool:
        if self._windows_job_has_processes():
            return True
        if psutil is None:
            return self.process.returncode is None
        if any(psutil.pid_exists(pid) for pid in self.known_descendant_pids):
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
            pgid = self.pid
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
                    ctypes.windll.kernel32.TerminateJobObject(
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
        self.stop_monitor = True
        if self.monitor_task is not None:
            self.monitor_task.cancel()
            await asyncio.gather(self.monitor_task, return_exceptions=True)
            self.monitor_task = None
        await self._reap_readers()
        _close_windows_handle(self.job_handle)
        self.job_handle = None
        self._closed = True
        return result

    async def _reap_readers(self) -> None:
        if not self.reader_tasks:
            return
        await asyncio.gather(*self.reader_tasks, return_exceptions=True)
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
        )

    async def wait(self) -> int:
        try:
            result = await self.process.wait()
            if self._tree_has_live_processes():
                await self.close(reason="root_exit_with_descendants")
            return result
        finally:
            self.stop_monitor = True
            if self.monitor_task is not None:
                self.monitor_task.cancel()
                await asyncio.gather(self.monitor_task, return_exceptions=True)
                self.monitor_task = None
            await self._reap_readers()

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
    ) -> ManagedAgentProcess:
        kwargs: dict[str, Any] = {
            "stdin": asyncio.subprocess.DEVNULL,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        process = await asyncio.create_subprocess_exec(*args, cwd=cwd, env=env, **kwargs)
        managed = ManagedAgentProcess(
            process=process,
            run_token=run_token,
            worker_boot_id=worker_boot_id,
            job_handle=_windows_job_object(),
        )
        if managed.job_handle and os.name == "nt":
            try:
                ok = ctypes.windll.kernel32.AssignProcessToJobObject(
                    ctypes.wintypes.HANDLE(managed.job_handle),
                    ctypes.wintypes.HANDLE(getattr(process, "_handle", 0)),
                )
                if not ok:
                    logger.warning("AssignProcessToJobObject failed for pid {}", process.pid)
            except Exception:
                logger.warning("AssignProcessToJobObject raised for pid {}", process.pid, exc_info=True)
        self._processes.add(managed)
        if psutil is not None:
            managed.monitor_task = asyncio.create_task(self._monitor_tree(managed))
        return managed

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

    async def stop_attempt(self, run_token: str, reason: str) -> Optional[TerminationResult]:
        matches = [item for item in self._processes if item.run_token == run_token]
        if not matches:
            return None
        result = await matches[0].close(reason=reason)
        self._processes.discard(matches[0])
        return result

    def forget(self, managed: ManagedAgentProcess) -> None:
        self._processes.discard(managed)

    async def stop_persisted(
        self,
        pid: Optional[int],
        process_started_at: Optional[datetime],
        reason: str,
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
                children = proc.children(recursive=True)
                for child in children:
                    try:
                        child.terminate()
                    except psutil.Error:
                        pass
                proc.terminate()
                _, alive = psutil.wait_procs([proc, *children], timeout=3.0)
                for child in alive:
                    try:
                        child.kill()
                    except psutil.Error:
                        pass
                if alive:
                    _, alive = psutil.wait_procs(alive, timeout=5.0)
                if alive:
                    return TerminationResult(
                        False, None, signals_sent=("SIGTERM", "SIGKILL"),
                        tree_kill_used=True,
                        elapsed_ms=int((time.monotonic() - started) * 1000),
                        error_code="PROCESS_TREE_STILL_ALIVE",
                        error_message=f"Persisted process tree {pid} is still alive",
                    )
            try:
                psutil.Process(int(pid))
                confirmed = False
            except psutil.NoSuchProcess:
                confirmed = True
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

    async def stop_all(self, reason: str = "worker_shutdown") -> list[TerminationResult]:
        processes = list(self._processes)
        results = await asyncio.gather(
            *(item.close(reason=reason) for item in processes),
            return_exceptions=True,
        )
        self._processes.clear()
        output: list[TerminationResult] = []
        for result in results:
            if isinstance(result, TerminationResult):
                output.append(result)
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


__all__ = ["ManagedAgentProcess", "ProcessSupervisor", "TerminationResult", "process_supervisor"]
