"""Windows 进程 containment 内核原语。

本模块是全部 Win32 进程句柄访问的唯一出口（ctypes 签名集中声明一次）：

- kill-on-close Job Object 的创建 / 分配 / 终止 / 查询 / 关闭；
- CREATE_SUSPENDED 子进程的恢复（NtResumeProcess，指针宽度安全）；
- asyncio transport 中的 Popen 进程/线程句柄提取；
- ``taskkill /T /F`` 树终止的统一拉起。

POSIX 代码绝不能 import 本模块；其余模块通过这些函数操作 Windows
containment，不直接接触 ctypes。
"""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes
import os
from typing import Optional, Tuple

from app.core.logging import get_logger

logger = get_logger(__name__, category="agent_process")


def windows_kernel32():
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


def resume_process(process_handle: int) -> None:
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


def create_kill_on_close_job() -> Optional[int]:
    """Create a kill-on-close Windows Job Object when available."""
    if os.name != "nt":
        return None
    try:
        kernel32 = windows_kernel32()
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


def close_handle(handle: Optional[int]) -> None:
    if handle and os.name == "nt":
        try:
            windows_kernel32().CloseHandle(ctypes.wintypes.HANDLE(handle))
        except Exception:
            logger.debug("Failed to close Windows Job Object handle", exc_info=True)


def assign_process_to_job(job_handle: int, process_handle: int) -> None:
    """Assign one suspended process to a Job Object; raise on failure."""
    assigned = windows_kernel32().AssignProcessToJobObject(
        ctypes.wintypes.HANDLE(job_handle),
        ctypes.wintypes.HANDLE(process_handle),
    )
    if not assigned:
        raise RuntimeError("AssignProcessToJobObject failed")


def terminate_job(job_handle: Optional[int]) -> bool:
    """Terminate every process assigned to the Job Object."""
    if not job_handle:
        return False
    try:
        windows_kernel32().TerminateJobObject(ctypes.wintypes.HANDLE(job_handle), 1)
        return True
    except Exception:
        logger.debug("TerminateJobObject failed", exc_info=True)
        return False


def query_job_process_ids(
    job_handle: Optional[int],
    *,
    exclude_pid: Optional[int] = None,
) -> Optional[set]:
    """PID set assigned to one Job Object; ``None`` when the query fails.

    JOB_OBJECT_BASIC_PROCESS_ID_LIST stores ULONG_PTR PIDs.  A DWORD array
    truncates handles/PIDs on 64-bit Windows.  查询失败（API 返回 False 或
    任何异常）返回 None，由调用方映射为 UNKNOWN，绝不当作"组为空"。
    """
    if not job_handle or os.name != "nt":
        return None
    try:
        capacity = 256
        buffer_size = ctypes.sizeof(_WindowsJobProcessIdList) + ctypes.sizeof(_ULONG_PTR) * capacity
        buffer = (ctypes.c_byte * buffer_size)()
        returned = ctypes.wintypes.DWORD()
        ok = windows_kernel32().QueryInformationJobObject(
            ctypes.wintypes.HANDLE(job_handle),
            3,
            ctypes.byref(buffer),
            buffer_size,
            ctypes.byref(returned),
        )
        if not ok:
            return None
        header = _WindowsJobProcessIdList.from_buffer(buffer)
        count = min(int(header.NumberOfProcessIdsInList), capacity)
        ids = (_ULONG_PTR * capacity).from_buffer(buffer, ctypes.sizeof(_WindowsJobProcessIdList))
        pids = {int(ids[index]) for index in range(count)}
        if exclude_pid is not None:
            pids.discard(int(exclude_pid))
        return pids
    except Exception:
        return None


def windows_process_handles(
    process: asyncio.subprocess.Process,
) -> Tuple[Optional[int], Optional[int]]:
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
    return (
        int(process_handle) if process_handle else None,
        int(thread_handle) if thread_handle else None,
    )


async def taskkill_tree(pid: int, *, timeout: float = 5.0) -> Optional[str]:
    """Force-kill one PID and its whole descendant tree via taskkill.

    返回 None 表示成功；失败返回错误描述（供调用方写入结构化诊断）。
    """
    try:
        taskkill = await asyncio.create_subprocess_exec(
            "taskkill", "/PID", str(pid), "/T", "/F",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(asyncio.shield(taskkill.wait()), timeout=timeout)
        return None
    except Exception as exc:
        logger.warning("taskkill failed for pid {}: {}", pid, exc)
        return str(exc)


async def taskkill_pid(pid: int, *, timeout: float = 5.0) -> bool:
    """Force-kill one PID via taskkill (no tree)."""
    try:
        taskkill = await asyncio.create_subprocess_exec(
            "taskkill", "/PID", str(pid), "/F",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(asyncio.shield(taskkill.wait()), timeout=timeout)
        return True
    except Exception:
        logger.debug("Fallback descendant taskkill failed: pid={}", pid, exc_info=True)
        return False
