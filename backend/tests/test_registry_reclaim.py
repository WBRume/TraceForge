"""进程内注册表/锁表回收：

- WorkflowEngine 注册表：正常收口后立即摘除；可恢复态保留并按 TTL 收割；
- AI 队列：runner 结束后回收 _QUEUE_RUNNERS/_QUEUE_LOCKS 条目；
- LocalLockProvider：锁条目按引用计数回收；
- 本地队列信号量表 _LOCAL_QUEUE_SLOTS 按引用计数回收。
"""

import asyncio
import os
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.config import settings  # noqa: E402
from app.agents import AgentBackend, AgentRunRequest, AgentRunResult  # noqa: E402
from app.core import distributed_lock as dl  # noqa: E402
from app.domains.ai.services import ai_job_service  # noqa: E402
from app.engine import workflow_engine as we  # noqa: E402


def _make_engine(task_id: str = "task-reclaim-1") -> "we.WorkflowEngine":
    with patch.object(we.WorkflowEngine, "_create_engine_backend", return_value=MagicMock()):
        engine = we.WorkflowEngine(task_id, "ws-1", "user-1")
    engine._ws_push = AsyncMock()
    return engine


class _OutcomeBackend(AgentBackend):
    name = "fake"

    def __init__(self, outcome: str = "success"):
        self.outcome = outcome

    async def run(self, request: AgentRunRequest, on_event) -> AgentRunResult:
        return AgentRunResult(session_id="sid-1", success=(self.outcome == "success"), finish_reason="completed")

    async def interrupt(self, run_id=None) -> None:
        return None

    async def cancel(self, run_id=None) -> None:
        return None

    async def cancel_persisted_session(self, session_id: str) -> None:
        return None

    def is_running(self, run_id=None) -> bool:
        return False

    async def close(self) -> None:
        return None


async def _run_with_logging_stub(backend, request, handler) -> AgentRunResult:
    engine = handler.__self__
    if backend.outcome == "timeout":
        raise we.AgentTimeoutError("request timed out")
    if backend.outcome == "failure":
        engine.last_result_success = False
        engine.last_result_text = "boom"
    else:
        engine.last_result_success = True
    return AgentRunResult(session_id="sid-1", success=(backend.outcome == "success"), finish_reason="completed")


class EngineRegistryReclaimTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        we._active_engines.clear()
        we._idle_sweeper_task = None
        self._orig_ttl = settings.ENGINE_IDLE_TTL_SECONDS
        self._orig_interval = we.ENGINE_IDLE_SWEEP_INTERVAL_SECONDS

    async def asyncTearDown(self) -> None:
        task = we._idle_sweeper_task
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        we._active_engines.clear()
        we._idle_sweeper_task = None
        settings.ENGINE_IDLE_TTL_SECONDS = self._orig_ttl
        we.ENGINE_IDLE_SWEEP_INTERVAL_SECONDS = self._orig_interval

    async def _run_engine(self, engine, outcome: str) -> None:
        engine.cli = _OutcomeBackend(outcome)
        with patch.object(we, "run_db", new=AsyncMock()), \
                patch.object(we, "run_git_job", new=AsyncMock()), \
                patch.object(we, "run_agent_backend_with_logging", new=_run_with_logging_stub), \
                patch("app.domains.auth.services.auth_service.create_access_token", return_value="tok"):
            await engine.run("hello")

    async def test_successful_run_unregisters_engine(self):
        engine = _make_engine("task-reclaim-ok")
        await self._run_engine(engine, "success")
        self.assertEqual(engine.last_result_success, True)
        self.assertNotIn(engine.task_id, we._active_engines)

    async def test_timeout_run_keeps_engine_for_resume(self):
        engine = _make_engine("task-reclaim-timeout")
        await self._run_engine(engine, "timeout")
        self.assertIsNone(engine.last_result_success)
        self.assertIn(engine.task_id, we._active_engines)
        self.assertFalse(engine.running)

    async def test_failed_run_keeps_engine_for_resume(self):
        engine = _make_engine("task-reclaim-fail")
        await self._run_engine(engine, "failure")
        self.assertEqual(engine.last_result_success, False)
        self.assertIn(engine.task_id, we._active_engines)
        self.assertFalse(engine.running)

    async def test_sweep_evicts_only_stale_idle_engines(self):
        stale = _make_engine("task-reclaim-stale")
        fresh = _make_engine("task-reclaim-fresh")
        running = _make_engine("task-reclaim-running")
        we.register_engine(stale)
        we.register_engine(fresh)
        we.register_engine(running)
        stale.running = False
        fresh.running = False
        running.running = True
        stale._last_idle_since = time.monotonic() - 2.0
        fresh._last_idle_since = time.monotonic()
        settings.ENGINE_IDLE_TTL_SECONDS = 1

        evicted = we._sweep_idle_engines()

        self.assertEqual(evicted, 1)
        self.assertNotIn(stale.task_id, we._active_engines)
        self.assertIn(fresh.task_id, we._active_engines)
        self.assertIn(running.task_id, we._active_engines)

    async def test_idle_sweeper_loop_evicts_and_exits(self):
        engine = _make_engine("task-reclaim-loop")
        we.register_engine(engine)
        engine.running = False
        engine._last_idle_since = time.monotonic() - 2.0
        settings.ENGINE_IDLE_TTL_SECONDS = 1
        we.ENGINE_IDLE_SWEEP_INTERVAL_SECONDS = 0.02

        we._ensure_idle_sweeper()
        self.assertIsNotNone(we._idle_sweeper_task)
        await asyncio.sleep(0.2)

        self.assertNotIn(engine.task_id, we._active_engines)
        self.assertIsNone(we._idle_sweeper_task)


class QueueRunnerReclaimTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        ai_job_service._QUEUE_RUNNERS.clear()
        ai_job_service._QUEUE_LOCKS.clear()

    def tearDown(self) -> None:
        ai_job_service._QUEUE_RUNNERS.clear()
        ai_job_service._QUEUE_LOCKS.clear()

    async def _settle(self) -> None:
        for _ in range(6):
            await asyncio.sleep(0)

    async def test_runner_and_lock_reaped_after_queue_drain(self):
        with patch.object(ai_job_service, "_take_next_pending_job_id", new=AsyncMock(return_value=None)):
            ai_job_service.schedule_queue("TESTQ:task-drain")
            runner = ai_job_service._QUEUE_RUNNERS.get("TESTQ:task-drain")
            self.assertIsNotNone(runner)
            await asyncio.sleep(0)
            self.assertIn("TESTQ:task-drain", ai_job_service._QUEUE_LOCKS)
            await runner
            await self._settle()

        self.assertNotIn("TESTQ:task-drain", ai_job_service._QUEUE_RUNNERS)
        self.assertNotIn("TESTQ:task-drain", ai_job_service._QUEUE_LOCKS)

    async def test_runner_reaped_after_error_and_exception_consumed(self):
        async def _boom(queue_key):
            raise RuntimeError("queue boom")

        with patch.object(ai_job_service, "_take_next_pending_job_id", new=_boom):
            ai_job_service.schedule_queue("TESTQ:task-error")
            runner = ai_job_service._QUEUE_RUNNERS.get("TESTQ:task-error")
            self.assertIsNotNone(runner)
            # 异常由回调消费；此处仅等待完成，不重复 raise
            while not runner.done():
                await asyncio.sleep(0)
            await self._settle()

        self.assertNotIn("TESTQ:task-error", ai_job_service._QUEUE_RUNNERS)
        self.assertNotIn("TESTQ:task-error", ai_job_service._QUEUE_LOCKS)
        # 异常已被回调消费，不会残留未检视告警
        self.assertTrue(runner.done())

    async def test_reaper_skips_entry_owned_by_successor(self):
        successor = MagicMock()
        ai_job_service._QUEUE_RUNNERS["TESTQ:task-race"] = successor
        ai_job_service._QUEUE_LOCKS["TESTQ:task-race"] = asyncio.Lock()
        done_task = MagicMock()

        ai_job_service._reap_queue_runner("TESTQ:task-race", done_task)

        self.assertIs(ai_job_service._QUEUE_RUNNERS.get("TESTQ:task-race"), successor)
        self.assertIn("TESTQ:task-race", ai_job_service._QUEUE_LOCKS)


class LocalLockProviderReclaimTest(unittest.IsolatedAsyncioTestCase):
    async def test_lock_entry_removed_after_release(self):
        provider = dl.LocalLockProvider()
        async with provider.lock(resource_type="task", resource_id="r-reclaim-1"):
            self.assertEqual(len(provider._locks), 1)
        self.assertEqual(provider._locks, {})
        self.assertEqual(provider._lock_refs, {})

    async def test_entry_kept_while_waiter_pending(self):
        provider = dl.LocalLockProvider()
        holder_entered = asyncio.Event()

        async def holder():
            async with provider.lock(resource_type="task", resource_id="r-reclaim-2", blocking_timeout=1.0):
                holder_entered.set()
                await asyncio.sleep(0.05)

        async def waiter():
            async with provider.lock(resource_type="task", resource_id="r-reclaim-2", blocking_timeout=1.0):
                pass

        holder_task = asyncio.create_task(holder())
        await holder_entered.wait()
        waiter_task = asyncio.create_task(waiter())
        await asyncio.sleep(0.02)
        # 等待者已计入引用，条目必须保留（否则会新建锁破坏互斥）
        self.assertEqual(len(provider._locks), 1)
        await asyncio.gather(holder_task, waiter_task)

        self.assertEqual(provider._locks, {})
        self.assertEqual(provider._lock_refs, {})

    async def test_timeout_keeps_entry_until_holder_exits(self):
        provider = dl.LocalLockProvider()
        async with provider.lock(resource_type="task", resource_id="r-reclaim-3", blocking_timeout=0.5):
            with self.assertRaises(dl.LockAcquireTimeout):
                async with provider.lock(resource_type="task", resource_id="r-reclaim-3", blocking_timeout=0.05):
                    self.fail("second acquire should timeout")
            # 超时者已离开，但持有者仍在：条目保留
            self.assertEqual(len(provider._locks), 1)
        self.assertEqual(provider._locks, {})
        self.assertEqual(provider._lock_refs, {})


class LocalQueueSlotReclaimTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._orig_provider = dl._PROVIDER
        dl._PROVIDER = dl.LocalLockProvider()
        dl._LOCAL_QUEUE_SLOTS.clear()
        dl._LOCAL_QUEUE_SLOT_REFS.clear()

    def tearDown(self) -> None:
        dl._PROVIDER = self._orig_provider
        dl._LOCAL_QUEUE_SLOTS.clear()
        dl._LOCAL_QUEUE_SLOT_REFS.clear()

    async def test_slot_removed_after_job_finishes(self):
        async with dl.queue_background_job(queue_name="unit:slot-1", max_concurrent=1, wait_timeout=0.5):
            self.assertEqual(len(dl._LOCAL_QUEUE_SLOTS), 1)
        self.assertEqual(dl._LOCAL_QUEUE_SLOTS, {})
        self.assertEqual(dl._LOCAL_QUEUE_SLOT_REFS, {})

    async def test_slot_kept_while_second_job_waits(self):
        release = asyncio.Event()

        async def first():
            async with dl.queue_background_job(queue_name="unit:slot-2", max_concurrent=1, wait_timeout=1.0):
                await release.wait()

        async def second():
            async with dl.queue_background_job(queue_name="unit:slot-2", max_concurrent=1, wait_timeout=1.0):
                pass

        first_task = asyncio.create_task(first())
        await asyncio.sleep(0.01)
        second_task = asyncio.create_task(second())
        await asyncio.sleep(0.05)
        # 后继 job 仍在等待：信号量条目必须保留
        self.assertEqual(len(dl._LOCAL_QUEUE_SLOTS), 1)
        release.set()
        await asyncio.gather(first_task, second_task)

        self.assertEqual(dl._LOCAL_QUEUE_SLOTS, {})
        self.assertEqual(dl._LOCAL_QUEUE_SLOT_REFS, {})

    async def test_timeout_job_still_releases_slot(self):
        hold = asyncio.Event()

        async def holder():
            async with dl.queue_background_job(queue_name="unit:slot-3", max_concurrent=1, wait_timeout=1.0):
                await hold.wait()

        holder_task = asyncio.create_task(holder())
        await asyncio.sleep(0.01)
        with self.assertRaises(dl.LockAcquireTimeout):
            async with dl.queue_background_job(queue_name="unit:slot-3", max_concurrent=1, wait_timeout=0.05):
                self.fail("queued job should timeout")
        # 超时者已离开但持有者仍在：条目保留
        self.assertEqual(len(dl._LOCAL_QUEUE_SLOTS), 1)
        hold.set()
        await holder_task
        self.assertEqual(dl._LOCAL_QUEUE_SLOTS, {})
        self.assertEqual(dl._LOCAL_QUEUE_SLOT_REFS, {})


if __name__ == "__main__":
    unittest.main()
