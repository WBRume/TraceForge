"""常驻 worker：reaper / dispatcher 循环、健康遥测与运行时生命周期。

- 每个 worker 迭代都有操作超时看门狗与指数退避；卡住的迭代等待原操作
  完成后才会启动下一轮（Windows Proactor 上的取消语义保持可观察）。
- ``start_runtime_workers`` 先做一次性恢复（回收孤儿 + 恢复 PENDING 队列），
  再启动两个独立 worker；``shutdown_runtime_workers`` 按固定顺序排空。
"""

from __future__ import annotations

import asyncio
import inspect
import random
import time
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from app.agents.process_supervisor import containment_capability, process_supervisor
from app.config import settings
from app.core.logging import get_logger
from app.core.offload import run_db
from app.domains.ai.services.jobs import reaper
from app.domains.ai.services.jobs import attempts as attempt_ops
from app.domains.ai.services.jobs.publishing import broadcast_job_payload
from app.domains.ai.services.jobs.registry import runtime
from app.domains.ai.services.jobs.store import list_pending_queue_keys_sync

logger = get_logger(__name__, category="ai_session")


# ────────────────────────── 健康遥测 ──────────────────────────

_RUNTIME_WORKER_HEALTH: Dict[str, Dict[str, Any]] = {}


def _set_runtime_worker_health(name: str, **updates: Any) -> None:
    state = _RUNTIME_WORKER_HEALTH.setdefault(name, {})
    state.update(updates)


def _runtime_worker_stale_seconds(name: str) -> float:
    setting_name = (
        "AI_JOB_REAPER_STALE_SECONDS"
        if name == "reaper"
        else "AI_JOB_DISPATCHER_STALE_SECONDS"
    )
    return max(0.1, float(getattr(settings, setting_name, 60.0) or 60.0))


def _runtime_worker_operation_timeout_seconds() -> float:
    return max(
        0.1,
        float(getattr(settings, "AI_JOB_WORKER_OPERATION_TIMEOUT_SECONDS", 30.0) or 30.0),
    )


def _runtime_timestamp_age(value: Any) -> Optional[float]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return max(0.0, (datetime.utcnow() - parsed).total_seconds())
        return max(0.0, (datetime.now(parsed.tzinfo) - parsed).total_seconds())
    except (TypeError, ValueError):
        return None


def runtime_worker_health() -> Dict[str, Any]:
    """Return bounded readiness telemetry for the durable runtime loops."""
    threshold = max(1, int(getattr(settings, "AI_JOB_WORKER_FAILURE_ALERT_THRESHOLD", 3) or 3))
    result: Dict[str, Any] = {}
    overall = True
    now_monotonic = time.monotonic()
    for name in ("reaper", "dispatcher"):
        task = runtime.worker_tasks.get(name)
        state = dict(_RUNTIME_WORKER_HEALTH.get(name, {}))
        alive = bool(task is not None and not task.done())
        failure_count = int(state.get("failure_count") or 0)
        started_monotonic = state.get("iteration_started_monotonic")
        if started_monotonic is None:
            iteration_age = max(
                0.0,
                float(state.get("current_iteration_age_seconds") or 0.0),
            )
        else:
            iteration_age = max(0.0, now_monotonic - float(started_monotonic))
        last_success_monotonic = state.get("last_success_monotonic")
        last_success_age = (
            max(0.0, now_monotonic - float(last_success_monotonic))
            if last_success_monotonic is not None
            else _runtime_timestamp_age(state.get("last_success_at"))
        )
        stalled = iteration_age > _runtime_worker_operation_timeout_seconds()
        stale = last_success_age is None or last_success_age > _runtime_worker_stale_seconds(name)
        healthy = alive and failure_count < threshold and not stalled and not stale
        if stalled:
            state["state"] = "stalled"
            state.setdefault("last_error_type", "WorkerOperationTimeout")
        state.update({
            "alive": alive,
            "running": alive,
            "healthy": healthy,
            "current_iteration_age_seconds": round(iteration_age, 3),
        })
        # Monotonic timestamps are process-local implementation details and
        # should not become part of the public readiness contract.
        state.pop("iteration_started_monotonic", None)
        state.pop("last_success_monotonic", None)
        result[name] = state
        overall = overall and healthy
    result["healthy"] = overall
    return result


def process_containment_readiness() -> Dict[str, Any]:
    """Attempt-containment readiness for local Agent jobs (doc 7.4).

    When the deployment requires containment, an unavailable provider must
    make readiness fail and refuse new local CLI attempts; ordinary
    REST/read-only endpoints may keep serving per the existing readiness
    layering.
    """
    capability = containment_capability()
    required = bool(getattr(settings, "AGENT_REQUIRE_PROCESS_CONTAINMENT", False))
    return {
        **capability,
        "required": required,
        "ok": (not required) or bool(capability.get("available")),
    }


# ────────────────────────── worker 循环框架 ──────────────────────────


def _runtime_worker_done(name: str, task: asyncio.Task) -> None:
    if runtime.worker_tasks.get(name) is not task:
        return
    if task.cancelled():
        _set_runtime_worker_health(name, state="cancelled", alive=False)
        return
    try:
        error = task.exception()
    except asyncio.CancelledError:
        error = None
    if error is not None:
        logger.error("AI runtime worker exited unexpectedly: name={}, error={}", name, error)
        _set_runtime_worker_health(
            name,
            state="exited",
            alive=False,
            running=False,
            last_error_at=datetime.utcnow().isoformat() + "Z",
            last_error_type=type(error).__name__,
            last_error=str(error)[:800],
            failure_count=int(_RUNTIME_WORKER_HEALTH.get(name, {}).get("failure_count") or 0) + 1,
            consecutive_failures=int(_RUNTIME_WORKER_HEALTH.get(name, {}).get("consecutive_failures") or 0) + 1,
        )
        try:
            loop = asyncio.get_running_loop()
            delay = min(
                max(1, int(getattr(settings, "AI_JOB_WORKER_MAX_BACKOFF_SECONDS", 60) or 60)),
                2 ** min(int(_RUNTIME_WORKER_HEALTH.get(name, {}).get("failure_count") or 1), 6),
            )
            loop.call_later(delay, _restart_runtime_worker, name, task)
        except RuntimeError:
            pass


def _restart_runtime_worker(name: str, previous: asyncio.Task) -> None:
    if runtime.shutting_down or runtime.worker_tasks.get(name) is not previous:
        return
    task = asyncio.create_task(_reaper_loop() if name == "reaper" else _dispatcher_loop())
    runtime.worker_tasks[name] = task
    task.add_done_callback(lambda done: _runtime_worker_done(name, done))
    _set_runtime_worker_health(name, state="running", alive=True, restarted=True)


async def run_runtime_worker_loop(name: str, operation: Callable[[], Any], interval: int) -> None:
    failures = 0
    _set_runtime_worker_health(name, state="starting", alive=True, running=True, failure_count=0, consecutive_failures=0)
    while not runtime.shutting_down:
        started_at = datetime.utcnow()
        started_monotonic = time.monotonic()
        _set_runtime_worker_health(
            name,
            state="running",
            alive=True,
            running=True,
            last_started_at=started_at.isoformat() + "Z",
            iteration_started_monotonic=started_monotonic,
        )
        operation_task = asyncio.create_task(_await_runtime_operation(operation))
        cancel_after_completion = False
        try:
            # asyncio.wait leaves the operation task untouched on timeout.
            # That matters for sync DB work running in a worker thread: the
            # watchdog may report a stall, but the next iteration must not
            # start until this exact operation has finished.  It also keeps
            # cancellation of the outer worker task observable on Windows'
            # Proactor event loop.
            try:
                done, _ = await asyncio.wait(
                    {operation_task},
                    timeout=_runtime_worker_operation_timeout_seconds(),
                )
            except asyncio.CancelledError:
                # If the operation completed in the same loop turn as the
                # cancellation request, record that completed iteration before
                # re-raising.  This keeps readiness telemetry truthful while
                # still allowing the worker task to stop promptly.
                if not operation_task.done():
                    raise
                result = operation_task.result()
                done = {operation_task}
                cancel_after_completion = True
            if operation_task not in done:
                _set_runtime_worker_health(
                    name,
                    state="stalled",
                    alive=True,
                    running=True,
                    last_error_at=datetime.utcnow().isoformat() + "Z",
                    last_error_type="WorkerOperationTimeout",
                    last_error=(
                        f"{name} operation exceeded "
                        f"{_runtime_worker_operation_timeout_seconds():g}s"
                    ),
                )
                # Do not launch a replacement scan.  The same operation owns
                # the worker until it genuinely completes or the process is
                # shut down.
                result = await operation_task
            else:
                result = operation_task.result()
            failures = 0
            duration_ms = max(0, int((time.monotonic() - started_monotonic) * 1000))
            _set_runtime_worker_health(
                name,
                state="healthy",
                alive=True,
                running=True,
                failure_count=0,
                consecutive_failures=0,
                last_success_at=datetime.utcnow().isoformat() + "Z",
                last_error=None,
                last_error_type=None,
                iteration_duration_ms=duration_ms,
                last_scan_count=int(result) if isinstance(result, int) else 0,
                iteration_started_monotonic=None,
                last_success_monotonic=time.monotonic(),
            )
            delay = max(1, interval)
        except asyncio.CancelledError:
            if not operation_task.done():
                operation_task.cancel()
            _set_runtime_worker_health(name, state="cancelled", alive=False, running=False)
            raise
        except Exception as exc:
            if not operation_task.done():
                operation_task.cancel()
            failures += 1
            duration_ms = max(0, int((time.monotonic() - started_monotonic) * 1000))
            _set_runtime_worker_health(
                name,
                state="degraded",
                alive=True,
                running=True,
                failure_count=failures,
                consecutive_failures=failures,
                last_error_at=datetime.utcnow().isoformat() + "Z",
                last_error_type=type(exc).__name__,
                last_error=str(exc)[:800],
                iteration_duration_ms=duration_ms,
                iteration_started_monotonic=None,
            )
            logger.exception("AI runtime worker iteration failed: name={}, failure_count={}", name, failures)
            base = min(
                max(1, int(getattr(settings, "AI_JOB_WORKER_MAX_BACKOFF_SECONDS", 60) or 60)),
                max(1, interval) * (2 ** min(failures - 1, 6)),
            )
            jitter = random.uniform(
                0.0,
                max(0.0, float(getattr(settings, "AI_JOB_WORKER_JITTER_SECONDS", 0.5) or 0.5)),
            )
            delay = base + jitter
        if cancel_after_completion:
            raise asyncio.CancelledError
        await asyncio.sleep(delay)


async def _await_runtime_operation(operation: Callable[[], Any]) -> Any:
    result = operation()
    if inspect.isawaitable(result):
        return await result
    return result


# ────────────────────────── 循环体 ──────────────────────────


async def _reaper_loop() -> None:
    await run_runtime_worker_loop(
        "reaper",
        reaper.reap_stale_jobs,
        max(1, int(getattr(settings, "AI_JOB_REAPER_INTERVAL_SECONDS", 10) or 10)),
    )


async def _dispatcher_loop() -> None:
    await run_runtime_worker_loop(
        "dispatcher",
        recover_pending_queues,
        max(1, int(getattr(settings, "AI_JOB_DISPATCH_INTERVAL_SECONDS", 2) or 2)),
    )


# ────────────────────────── 生命周期 ──────────────────────────


async def recover_pending_queues() -> int:
    """Schedule durable PENDING jobs after an API process restart."""
    await reaper.reap_stale_jobs()
    from app.domains.task.services import chat_submission_service

    await chat_submission_service.recover()
    queue_keys = await run_db(list_pending_queue_keys_sync)
    for queue_key in queue_keys:
        runtime.schedule_queue(queue_key)
    return len(queue_keys)


async def start_runtime_workers() -> int:
    """Run recovery before readiness, then start independent durable workers."""
    runtime.shutting_down = False
    reaper_task = runtime.worker_tasks.get("reaper")
    dispatcher_task = runtime.worker_tasks.get("dispatcher")
    already_running = bool(
        reaper_task is not None
        and not reaper_task.done()
        and dispatcher_task is not None
        and not dispatcher_task.done()
    )
    count = 0
    if not already_running:
        try:
            count = await recover_pending_queues()
            recovered_at = datetime.utcnow().isoformat() + "Z"
            for name in ("reaper", "dispatcher"):
                _set_runtime_worker_health(
                    name,
                    state="starting",
                    last_success_at=recovered_at,
                    last_success_monotonic=time.monotonic(),
                    last_error=None,
                    last_error_type=None,
                    failure_count=0,
                    consecutive_failures=0,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Initial AI runtime recovery failed")
            for name in ("reaper", "dispatcher"):
                _set_runtime_worker_health(
                    name,
                    state="degraded",
                    last_error_at=datetime.utcnow().isoformat() + "Z",
                    last_error_type=type(exc).__name__,
                    last_error=str(exc)[:800],
                    failure_count=1,
                    consecutive_failures=1,
                )
    if reaper_task is None or reaper_task.done():
        task = asyncio.create_task(_reaper_loop())
        runtime.worker_tasks["reaper"] = task
        task.add_done_callback(lambda done: _runtime_worker_done("reaper", done))
    if dispatcher_task is None or dispatcher_task.done():
        task = asyncio.create_task(_dispatcher_loop())
        runtime.worker_tasks["dispatcher"] = task
        task.add_done_callback(lambda done: _runtime_worker_done("dispatcher", done))
    from app.domains.task.services import task_event_publisher

    task_event_publisher.start()
    return count


async def shutdown_runtime_workers() -> None:
    """Stop dispatch/queue/heartbeat tasks before infrastructure shutdown."""
    runtime.shutting_down = True
    from app.domains.task.services import chat_submission_service
    from app.domains.task.services import task_event_publisher

    await chat_submission_service.shutdown()
    await task_event_publisher.shutdown()
    background = [task for task in runtime.worker_tasks.values() if task is not None]
    for task in background:
        task.cancel()
    if background:
        await asyncio.gather(*background, return_exceptions=True)
    runners = list(runtime.queue_runners.values())
    for task in runners:
        task.cancel()
    if runners:
        await asyncio.gather(*runners, return_exceptions=True)
    runtime.queue_runners.clear()
    runtime.worker_tasks.clear()
    owned_attempts = await run_db(reaper.mark_worker_jobs_terminating_sync, "WORKER_SHUTDOWN")
    heartbeats = list(runtime.heartbeat_tasks.values())
    for task in heartbeats:
        task.cancel()
    if heartbeats:
        await asyncio.gather(*heartbeats, return_exceptions=True)
    runtime.heartbeat_tasks.clear()
    for row in owned_attempts:
        token = str(row.get("run_token") or "")
        result = await process_supervisor.stop_attempt(token, "WORKER_SHUTDOWN") if token else None
        if result is None and row.get("process_pid"):
            result = await process_supervisor.stop_persisted(
                row["process_pid"],
                row.get("process_started_at"),
                "WORKER_SHUTDOWN",
                process_group_id=row.get("process_group_id"),
                run_token=token or None,
                not_before=row.get("job_started_at"),
            )
        if result is None and token:
            result = await process_supervisor.stop_by_run_token_discovery(
                token,
                "WORKER_SHUTDOWN",
                not_before=row.get("job_started_at"),
            )
        confirmed_dead = bool(result is not None and result.confirmed_dead)
        payload = await run_db(
            attempt_ops.finish_termination_sync,
            row["job_id"],
            token,
            confirmed_dead=confirmed_dead,
            reason=(result.error_message if result and result.error_message else "WORKER_SHUTDOWN"),
            failure_code=(result.error_code if result and result.error_code else "WORKER_SHUTDOWN"),
        ) if token else None
        if payload:
            runtime.clear_cancel_for_payload(payload)
            await broadcast_job_payload(payload)
    # Catch any process whose owner row was not visible during the durable
    # snapshot (for example a spawn race); ProcessSupervisor remains the final
    # in-memory safety net.
    await process_supervisor.stop_all("WORKER_SHUTDOWN")
