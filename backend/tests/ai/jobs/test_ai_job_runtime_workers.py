"""Durable AI job ownership 状态机检查（原 test_ai_job_reliability.py）。

覆盖：runtime worker 单次迭代失败恢复、健康检查拒绝过期 success、
stalled 检测、不重叠迭代、start_runtime_workers 幂等。
"""

from __future__ import annotations

import asyncio
import time

from app.config import settings
from app.domains.ai.services.jobs import reaper as ai_reaper
from app.domains.ai.services.jobs import workers as ai_workers
from app.domains.ai.services.jobs.registry import runtime as ai_runtime


def test_runtime_worker_survives_one_iteration_failure_and_honors_cancel(monkeypatch):
    calls = 0
    holder = {}
    monkeypatch.setattr(ai_workers, "_RUNTIME_WORKER_HEALTH", {})
    monkeypatch.setattr(ai_runtime, "shutting_down", False)

    async def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary database outage")
        asyncio.get_running_loop().call_soon(holder["task"].cancel)

    async def run():
        task = asyncio.create_task(ai_workers.run_runtime_worker_loop("test", operation, 1))
        holder["task"] = task
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())

    health = ai_workers._RUNTIME_WORKER_HEALTH["test"]
    assert calls == 2
    assert health["consecutive_failures"] == 0
    assert health["last_success_at"]
    assert health["iteration_duration_ms"] >= 0
    assert health["last_scan_count"] == 0


def test_runtime_worker_health_rejects_stale_last_success(monkeypatch):
    class _LiveTask:
        def done(self):
            return False

    now = time.monotonic()
    monkeypatch.setitem(ai_runtime.worker_tasks, "reaper", _LiveTask())
    monkeypatch.setitem(ai_runtime.worker_tasks, "dispatcher", _LiveTask())
    monkeypatch.setattr(ai_workers, "_RUNTIME_WORKER_HEALTH", {
        "reaper": {
            "state": "healthy",
            "failure_count": 0,
            "last_success_monotonic": now - 10,
        },
        "dispatcher": {
            "state": "healthy",
            "failure_count": 0,
            "last_success_monotonic": now,
        },
    })
    monkeypatch.setattr(settings, "AI_JOB_REAPER_STALE_SECONDS", 1)

    health = ai_workers.runtime_worker_health()

    assert health["reaper"]["healthy"] is False
    assert health["reaper"]["alive"] is True
    assert health["healthy"] is False


def test_runtime_worker_reports_stalled_live_task(monkeypatch):
    class _LiveTask:
        def done(self):
            return False

    now = time.monotonic()
    monkeypatch.setitem(ai_runtime.worker_tasks, "reaper", _LiveTask())
    monkeypatch.setitem(ai_runtime.worker_tasks, "dispatcher", _LiveTask())
    monkeypatch.setattr(ai_workers, "_RUNTIME_WORKER_HEALTH", {
        "reaper": {
            "state": "running",
            "failure_count": 0,
            "last_success_monotonic": now,
            "iteration_started_monotonic": now - 10,
        },
        "dispatcher": {
            "state": "healthy",
            "failure_count": 0,
            "last_success_monotonic": now,
        },
    })
    monkeypatch.setattr(settings, "AI_JOB_WORKER_OPERATION_TIMEOUT_SECONDS", 1)

    health = ai_workers.runtime_worker_health()

    assert health["reaper"]["state"] == "stalled"
    assert health["reaper"]["healthy"] is False
    assert health["reaper"]["alive"] is True
    assert health["reaper"]["current_iteration_age_seconds"] >= 10
    assert health["reaper"]["last_error_type"] == "WorkerOperationTimeout"


def test_stalled_operation_does_not_spawn_overlapping_iterations(monkeypatch):
    calls = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def operation():
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return 1

    async def run():
        worker = asyncio.create_task(ai_workers.run_runtime_worker_loop("reaper", operation, 1))
        monkeypatch.setitem(ai_runtime.worker_tasks, "reaper", worker)
        await started.wait()
        await asyncio.sleep(0.2)
        assert calls == 1
        stalled = ai_workers.runtime_worker_health()
        assert stalled["reaper"]["healthy"] is False
        assert stalled["reaper"]["state"] == "stalled"

        release.set()
        await asyncio.sleep(0.05)
        recovered = ai_workers.runtime_worker_health()
        assert recovered["reaper"]["healthy"] is True
        assert calls == 1
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass

    monkeypatch.setattr(ai_runtime, "shutting_down", False)
    monkeypatch.setattr(ai_workers, "_RUNTIME_WORKER_HEALTH", {
        "dispatcher": {
            "state": "healthy",
            "failure_count": 0,
            "last_success_monotonic": time.monotonic(),
        },
    })
    monkeypatch.setattr(settings, "AI_JOB_WORKER_OPERATION_TIMEOUT_SECONDS", 0.1)
    asyncio.run(run())


def test_start_runtime_workers_is_idempotent(monkeypatch):
    stop = asyncio.Event()

    async def idle_loop():
        await stop.wait()

    async def recover():
        return 0

    monkeypatch.setitem(ai_runtime.worker_tasks, "reaper", None)
    monkeypatch.setitem(ai_runtime.worker_tasks, "dispatcher", None)
    monkeypatch.setattr(ai_runtime, "shutting_down", False)
    monkeypatch.setattr(ai_workers, "_reaper_loop", idle_loop)
    monkeypatch.setattr(ai_workers, "_dispatcher_loop", idle_loop)
    monkeypatch.setattr(ai_workers, "recover_pending_queues", recover)
    monkeypatch.setattr(ai_reaper, "mark_worker_jobs_terminating_sync", lambda reason: [])

    async def run():
        await ai_workers.start_runtime_workers()
        first = (ai_runtime.worker_tasks.get("reaper"), ai_runtime.worker_tasks.get("dispatcher"))
        await ai_workers.start_runtime_workers()
        second = (ai_runtime.worker_tasks.get("reaper"), ai_runtime.worker_tasks.get("dispatcher"))
        assert first == second
        await ai_workers.shutdown_runtime_workers()

    asyncio.run(run())
