"""受管进程的 spawn 编排。

从"进程被创建"到"进程被监管"之间存在逃逸窗口；本模块的职责是让该
窗口在两个平台上都关闭：

- Windows：以 ``CREATE_NEW_PROCESS_GROUP | CREATE_SUSPENDED`` 挂起启动，
  分配进 kill-on-close Job Object 后再 ``NtResumeProcess`` 恢复；
- POSIX：``start_new_session=True``（root PID 即进程组 ID），并注入
  attempt 级 run token 与 per-spawn 谱系 token。

同时承担：

- containment 门禁（doc 7.4：部署要求 containment 而平台不支持时，
  拒绝启动本地 Agent 进程）；
- attach 回调（``on_process_started``）的超时/拒绝/异常/取消处理——
  任何失败都在不可取消的清理任务中终止整棵进程树后再向调用方抛出
  （I1：不存在无人管理的窗口）。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from typing import Any, Optional

try:  # psutil is used for create-time and descendant verification.
    import psutil
except ImportError:  # pragma: no cover - packaging/runtime guard
    psutil = None  # type: ignore[assignment]

from app.core.logging import get_logger
from app.agents.contract import record_attempt_process_started
from app.agents.supervision import windows
from app.agents.supervision.managed import ManagedAgentProcess, monitor_tree
from app.agents.supervision.model import (
    RUN_TOKEN_ENV_VAR,
    SPAWN_TOKEN_ENV_VAR,
    TerminationResult,
    containment_id_for_run_token,
)

logger = get_logger(__name__, category="agent_process")


def containment_capability() -> dict:
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


def require_containment_ready() -> None:
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


async def invoke_attach_callback(
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


async def cleanup_before_reraise(
    supervisor,
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
    supervisor.register_cleanup_task(cleanup_task)

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
    from app.agents.contract import record_attempt_termination

    record_attempt_termination(result, managed.process_identity)
    if result.confirmed_dead:
        supervisor.unregister(managed)
    return result


async def spawn_supervised(
    supervisor,
    args: list,
    *,
    cwd: str,
    env: dict,
    run_token: Optional[str] = None,
    worker_boot_id: Optional[str] = None,
    on_process_started: Optional[Any] = None,
    containment_id: Optional[str] = None,
    process_attach_timeout_seconds: Optional[float] = None,
) -> ManagedAgentProcess:
    """Create one supervised local Agent process and attach it to the attempt."""
    # Doc 7.4: when the deployment requires attempt containment, a
    # missing provider must refuse new local Agent jobs instead of
    # starting an unprotected CLI.
    require_containment_ready()
    kwargs: dict = {
        "stdin": asyncio.subprocess.DEVNULL,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
    }
    child_env = dict(env)
    spawn_token: Optional[str] = None
    if os.name != "nt":
        # P0-3：per-spawn 谱系 token —— uuid4 仅注入本次子进程 env，后代
        # 继承，使 wait/close 能把脱组后代精确归属到本 spawn。attempt 级
        # run token 同时注入，保证 reaper 的 token discovery 覆盖全部后代
        # （doc：every local CLI and its descendants inherit the exact token
        # at spawn time）。
        spawn_token = uuid.uuid4().hex
        child_env[SPAWN_TOKEN_ENV_VAR] = spawn_token
        if run_token:
            child_env[RUN_TOKEN_ENV_VAR] = str(run_token)
    if os.name == "nt":
        # Keep the process suspended until it is assigned to the
        # kill-on-close Job Object.  This closes the spawn escape window.
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | int(getattr(subprocess, "CREATE_SUSPENDED", 0x00000004))
        )
    else:
        kwargs["start_new_session"] = True
    process = await asyncio.create_subprocess_exec(*args, cwd=cwd, env=child_env, **kwargs)
    # I1 (doc 3): the process is owned by the supervisor from this instant.
    # Construct + register the managed handle before any cancellable
    # callback await so no unowned window can exist.
    managed = ManagedAgentProcess(
        process=process,
        run_token=run_token,
        worker_boot_id=worker_boot_id,
        job_handle=windows.create_kill_on_close_job() if os.name == "nt" else None,
        containment_id=(
            containment_id
            or (containment_id_for_run_token(run_token) if os.name != "nt" else None)
        ),
        spawn_token=spawn_token,
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
            process_handle, _thread_handle = windows.windows_process_handles(process)
            if not process_handle:
                # A test double or an extremely short-lived process may
                # already be dead before asyncio exposes its Popen
                # handle.  There is no live process left to escape, so
                # release the unused job object.  A live process still
                # fails closed below instead of running unsupervised.
                if process.returncode is not None:
                    windows.close_handle(managed.job_handle)
                    managed.job_handle = None
                else:
                    raise RuntimeError("Suspended subprocess process handle is unavailable")
            if process_handle:
                windows.assign_process_to_job(managed.job_handle, process_handle)
                windows.resume_process(process_handle)
        except Exception as exc:
            logger.error("Windows supervised spawn failed for pid {}: {}", process.pid, exc)
            managed.stop_monitor = True
            try:
                process.kill()
                await asyncio.wait_for(asyncio.shield(process.wait()), timeout=5.0)
            except Exception:
                logger.exception("Failed to terminate unsupervised Windows process: pid={}", process.pid)
            windows.close_handle(managed.job_handle)
            managed.job_handle = None
            raise RuntimeError(f"Could not establish Windows process supervision: {exc}") from exc
    supervisor.register(managed)
    # The identity is frozen once here: every evidence record for this
    # process uses the same immutable key.
    identity = managed.process_identity
    record_attempt_process_started(identity)
    if psutil is not None:
        managed.monitor_task = asyncio.create_task(monitor_tree(managed))
    if on_process_started is not None:
        attach_error: Optional[BaseException] = None
        accepted = False
        try:
            accepted = await invoke_attach_callback(
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
            result = await cleanup_before_reraise(supervisor, managed, reason=reason)
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
