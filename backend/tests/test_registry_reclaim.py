"""进程内注册表/锁表回收：

- TaskAgentEngine 注册表：正常收口后立即摘除；可恢复态保留并按 TTL 收割；
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
from app.agents import AgentBackend, AgentRunRequest, AgentRunResult, AgentTimeoutError  # noqa: E402
from app.core import distributed_lock as dl  # noqa: E402
from app.domains.ai.services.jobs import (
    attempts as ai_attempts,
    constants as ai_constants,
    executors as ai_executors,
    publishing as ai_publishing,
    provider_turn as ai_provider_turn,
    queue_runner as ai_queue_runner,
    reaper as ai_reaper,
    registry as ai_registry,
    state as ai_state,
    store as ai_store,
    workers as ai_workers,
)
from app.domains.ai.services.jobs.executors import (
    diagnosis_summary as ai_diagnosis_summary,
    task_chat as ai_task_chat,
)
from app.domains.ai.services.jobs.registry import runtime as ai_runtime
from app.domains.ai.services.jobs.fencing import AgentAttemptFencedError
from app.engine.session import engine as session_engine  # noqa: E402
from app.engine.session import persistence as session_persistence  # noqa: E402
from app.engine.session import registry as engine_registry  # noqa: E402
from app.engine.session.engine import TaskAgentEngine  # noqa: E402


def _make_engine(task_id: str = "task-reclaim-1") -> TaskAgentEngine:
    with patch.object(TaskAgentEngine, "_create_engine_backend", return_value=MagicMock()):
        engine = TaskAgentEngine(task_id, "ws-1", "user-1")
    engine.frontend.push = AsyncMock()
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
        raise AgentTimeoutError("request timed out")
    if backend.outcome == "failure":
        engine.last_result_success = False
        engine.last_result_text = "boom"
    else:
        engine.last_result_success = True
    return AgentRunResult(session_id="sid-1", success=(backend.outcome == "success"), finish_reason="completed")


class EngineRegistryReclaimTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        engine_registry._active_engines.clear()
        engine_registry._idle_sweeper_task = None
        self._orig_ttl = settings.ENGINE_IDLE_TTL_SECONDS
        self._orig_interval = engine_registry.ENGINE_IDLE_SWEEP_INTERVAL_SECONDS

    async def asyncTearDown(self) -> None:
        task = engine_registry._idle_sweeper_task
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        engine_registry._active_engines.clear()
        engine_registry._idle_sweeper_task = None
        settings.ENGINE_IDLE_TTL_SECONDS = self._orig_ttl
        engine_registry.ENGINE_IDLE_SWEEP_INTERVAL_SECONDS = self._orig_interval

    async def _run_engine(self, engine, outcome: str) -> None:
        engine.cli = _OutcomeBackend(outcome)
        with patch.object(session_engine, "run_db", new=AsyncMock()), \
                patch.object(session_engine, "run_git_job", new=AsyncMock()), \
                patch.object(session_engine, "run_agent_backend_with_logging", new=_run_with_logging_stub), \
                patch.object(session_persistence, "run_db", new=AsyncMock()), \
                patch("app.domains.auth.services.auth_service.create_access_token", return_value="tok"):
            await engine.run("hello")

    async def test_successful_run_unregisters_engine(self):
        engine = _make_engine("task-reclaim-ok")
        await self._run_engine(engine, "success")
        self.assertEqual(engine.last_result_success, True)
        self.assertNotIn(engine.task_id, engine_registry._active_engines)

    async def test_timeout_run_keeps_engine_for_resume(self):
        engine = _make_engine("task-reclaim-timeout")
        await self._run_engine(engine, "timeout")
        self.assertIsNone(engine.last_result_success)
        self.assertIn(engine.task_id, engine_registry._active_engines)
        self.assertFalse(engine.running)

    async def test_failed_run_keeps_engine_for_resume(self):
        engine = _make_engine("task-reclaim-fail")
        await self._run_engine(engine, "failure")
        self.assertEqual(engine.last_result_success, False)
        self.assertIn(engine.task_id, engine_registry._active_engines)
        self.assertFalse(engine.running)

    async def test_sweep_evicts_only_stale_idle_engines(self):
        stale = _make_engine("task-reclaim-stale")
        fresh = _make_engine("task-reclaim-fresh")
        running = _make_engine("task-reclaim-running")
        engine_registry.register_engine(stale)
        engine_registry.register_engine(fresh)
        engine_registry.register_engine(running)
        stale.running = False
        fresh.running = False
        running.running = True
        stale._last_idle_since = time.monotonic() - 2.0
        fresh._last_idle_since = time.monotonic()
        settings.ENGINE_IDLE_TTL_SECONDS = 1

        evicted = engine_registry.sweep_idle_engines()

        self.assertEqual(evicted, 1)
        self.assertNotIn(stale.task_id, engine_registry._active_engines)
        self.assertIn(fresh.task_id, engine_registry._active_engines)
        self.assertIn(running.task_id, engine_registry._active_engines)

    async def test_idle_sweeper_loop_evicts_and_exits(self):
        engine = _make_engine("task-reclaim-loop")
        engine_registry.register_engine(engine)
        engine.running = False
        engine._last_idle_since = time.monotonic() - 2.0
        settings.ENGINE_IDLE_TTL_SECONDS = 1
        engine_registry.ENGINE_IDLE_SWEEP_INTERVAL_SECONDS = 0.02

        engine_registry._ensure_idle_sweeper()
        self.assertIsNotNone(engine_registry._idle_sweeper_task)
        await asyncio.sleep(0.2)

        self.assertNotIn(engine.task_id, engine_registry._active_engines)
        self.assertIsNone(engine_registry._idle_sweeper_task)


class QueueRunnerReclaimTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        ai_runtime.queue_runners.clear()
        ai_runtime.queue_locks.clear()

    def tearDown(self) -> None:
        ai_runtime.queue_runners.clear()
        ai_runtime.queue_locks.clear()

    async def _settle(self) -> None:
        for _ in range(6):
            await asyncio.sleep(0)

    async def test_runner_and_lock_reaped_after_queue_drain(self):
        with patch.object(ai_queue_runner, "claim_next_pending_job_id", new=AsyncMock(return_value=None)):
            ai_runtime.schedule_queue("TESTQ:task-drain")
            runner = ai_runtime.queue_runners.get("TESTQ:task-drain")
            self.assertIsNotNone(runner)
            await asyncio.sleep(0)
            self.assertIn("TESTQ:task-drain", ai_runtime.queue_locks)
            await runner
            await self._settle()

        self.assertNotIn("TESTQ:task-drain", ai_runtime.queue_runners)
        self.assertNotIn("TESTQ:task-drain", ai_runtime.queue_locks)

    async def test_runner_reaped_after_error_and_exception_consumed(self):
        async def _boom(queue_key):
            raise RuntimeError("queue boom")

        with patch.object(ai_queue_runner, "claim_next_pending_job_id", new=_boom):
            ai_runtime.schedule_queue("TESTQ:task-error")
            runner = ai_runtime.queue_runners.get("TESTQ:task-error")
            self.assertIsNotNone(runner)
            # 异常由回调消费；此处仅等待完成，不重复 raise
            while not runner.done():
                await asyncio.sleep(0)
            await self._settle()

        self.assertNotIn("TESTQ:task-error", ai_runtime.queue_runners)
        self.assertNotIn("TESTQ:task-error", ai_runtime.queue_locks)
        # 异常已被回调消费，不会残留未检视告警
        self.assertTrue(runner.done())

    async def test_reaper_skips_entry_owned_by_successor(self):
        successor = MagicMock()
        ai_runtime.queue_runners["TESTQ:task-race"] = successor
        ai_runtime.queue_locks["TESTQ:task-race"] = asyncio.Lock()
        done_task = MagicMock()

        ai_runtime.reap_queue_runner("TESTQ:task-race", done_task)

        self.assertIs(ai_runtime.queue_runners.get("TESTQ:task-race"), successor)
        self.assertIn("TESTQ:task-race", ai_runtime.queue_locks)


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


class _FakeRedisClient:
    """最小异步 Redis 替身：覆盖队列实现用到的命令。"""

    def __init__(self) -> None:
        self.lists: dict = {}
        self.kv: dict = {}
        self.deleted_keys: list = []

    async def set(self, key, value, ex=None, xx=False):
        if xx and key not in self.kv:
            return None
        self.kv[key] = value
        return True

    async def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    async def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        if end == -1:
            return list(items[start:])
        return list(items[start : end + 1])

    async def llen(self, key):
        return len(self.lists.get(key, []))

    async def lrem(self, key, count, value):
        items = self.lists.get(key, [])
        removed = 0
        remaining = []
        for item in items:
            if removed < count and item == value:
                removed += 1
                continue
            remaining.append(item)
        if remaining:
            self.lists[key] = remaining
        else:
            self.lists.pop(key, None)
        return removed

    async def exists(self, key):
        return 1 if key in self.kv else 0

    async def delete(self, *keys):
        removed = 0
        for key in keys:
            self.deleted_keys.append(key)
            if key in self.kv:
                del self.kv[key]
                removed += 1
            if key in self.lists:
                del self.lists[key]
                removed += 1
        return removed


class RedisQueueTokenReclaimTest(unittest.IsolatedAsyncioTestCase):
    """Redis 队列令牌自愈：孤儿令牌回收、活跃令牌保护、等待可取消。"""

    def setUp(self) -> None:
        self._orig_provider = dl._PROVIDER
        dl._PROVIDER = dl.RedisLockProvider()
        self.client = _FakeRedisClient()
        self._client_patcher = patch(
            "app.core.distributed_lock.get_redis_client",
            new=AsyncMock(return_value=self.client),
        )
        self._client_patcher.start()

    def tearDown(self) -> None:
        self._client_patcher.stop()
        dl._PROVIDER = self._orig_provider

    async def test_stale_token_is_reclaimed_and_waiter_proceeds(self):
        queue_key = dl._background_queue_key("unit:redis-stale")
        # 模拟 Redis 中断/进程崩溃后残留的孤儿令牌：无心跳键
        self.client.lists[queue_key] = [b"orphan-token"]

        entered = False
        async with dl.queue_background_job(
            queue_name="unit:redis-stale",
            max_concurrent=1,
            wait_timeout=1.0,
            poll_interval=0.01,
        ):
            entered = True

        self.assertTrue(entered)
        self.assertNotIn(queue_key, self.client.lists)
        # 不再显式 DEL 队列键（避免误删并发 RPUSH 的新令牌）
        self.assertNotIn(queue_key, self.client.deleted_keys)

    async def test_live_token_is_not_reclaimed(self):
        queue_key = dl._background_queue_key("unit:redis-live")
        holder = b"live-holder-token"
        self.client.lists[queue_key] = [holder]
        self.client.kv[dl._queue_heartbeat_key(queue_key, holder)] = b"1"

        with self.assertRaises(dl.LockAcquireTimeout):
            async with dl.queue_background_job(
                queue_name="unit:redis-live",
                max_concurrent=1,
                wait_timeout=0.2,
                poll_interval=0.01,
            ):
                self.fail("waiter must not enter while holder token is live")

        self.assertEqual(self.client.lists.get(queue_key), [holder])

    async def test_reclaimed_token_is_requeued(self):
        with patch.object(settings, "BACKGROUND_QUEUE_TOKEN_TTL_SECONDS", 0.3):
            queue_key = dl._background_queue_key("unit:redis-requeue")
            holder = b"live-holder-token"
            self.client.lists[queue_key] = [holder]
            self.client.kv[dl._queue_heartbeat_key(queue_key, holder)] = b"1"

            entered = asyncio.Event()

            async def _waiter() -> None:
                async with dl.queue_background_job(
                    queue_name="unit:redis-requeue",
                    max_concurrent=1,
                    wait_timeout=2.0,
                    poll_interval=0.02,
                ):
                    entered.set()

            waiter_task = asyncio.create_task(_waiter())
            try:
                await asyncio.sleep(0.2)
                waiter_tokens = [t for t in self.client.lists.get(queue_key, []) if t != holder]
                self.assertEqual(len(waiter_tokens), 1)
                waiter_token = waiter_tokens[0]
                # 模拟心跳过期后被其他等待者误回收（令牌与心跳键同时消失）
                self.client.lists[queue_key] = [holder]
                self.client.kv.pop(dl._queue_heartbeat_key(queue_key, waiter_token), None)

                await asyncio.sleep(0.6)
                self.assertIn(waiter_token, self.client.lists.get(queue_key, []))

                self.client.lists[queue_key].remove(holder)
                await asyncio.wait_for(entered.wait(), timeout=2.0)
            finally:
                if not waiter_task.done():
                    waiter_task.cancel()
                await asyncio.gather(waiter_task, return_exceptions=True)

    async def test_redis_queue_wait_is_cancellable(self):
        queue_key = dl._background_queue_key("unit:redis-cancel")
        holder = b"live-holder-token"
        self.client.lists[queue_key] = [holder]
        self.client.kv[dl._queue_heartbeat_key(queue_key, holder)] = b"1"

        with self.assertRaises(dl.QueueWaitCancelled):
            async with dl.queue_background_job(
                queue_name="unit:redis-cancel",
                max_concurrent=1,
                wait_timeout=5.0,
                poll_interval=0.01,
                cancel_check=lambda: True,
            ):
                self.fail("cancelled waiter must not enter")

        self.assertEqual(self.client.lists.get(queue_key), [holder])

    async def test_local_queue_wait_is_cancellable(self):
        dl._PROVIDER = dl.LocalLockProvider()
        hold = asyncio.Event()
        holder_entered = asyncio.Event()

        async def _holder() -> None:
            async with dl.queue_background_job(
                queue_name="unit:local-cancel",
                max_concurrent=1,
                wait_timeout=2.0,
                poll_interval=0.01,
            ):
                holder_entered.set()
                await hold.wait()

        holder_task = asyncio.create_task(_holder())
        try:
            await asyncio.wait_for(holder_entered.wait(), timeout=1.0)
            with self.assertRaises(dl.QueueWaitCancelled):
                async with dl.queue_background_job(
                    queue_name="unit:local-cancel",
                    max_concurrent=1,
                    wait_timeout=2.0,
                    poll_interval=0.01,
                    cancel_check=lambda: True,
                ):
                    self.fail("cancelled waiter must not enter")
        finally:
            hold.set()
            await asyncio.gather(holder_task, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
