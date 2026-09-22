import os
import asyncio
import sys
import unittest
from unittest import mock
from types import SimpleNamespace

from redis.exceptions import AuthenticationError, LockNotOwnedError, TimeoutError as RedisTimeoutError


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.config import settings  # noqa: E402
from app.core import distributed_lock as dl  # noqa: E402


class _FakeRedisLock:
    def __init__(self, *, acquire_result: bool = True, release_error: Exception | None = None):
        self.acquire_result = acquire_result
        self.release_error = release_error
        self.acquire_calls = []
        self.release_calls = 0
        self.local = SimpleNamespace(token=None)

    async def acquire(self, **kwargs):
        self.acquire_calls.append(kwargs)
        return self.acquire_result

    async def release(self):
        self.release_calls += 1
        if self.release_error:
            raise self.release_error


class DistributedLockTest(unittest.IsolatedAsyncioTestCase):
    async def test_redis_renews_while_owner_is_working(self):
        fake_lock = _FakeRedisLock()
        renewed = asyncio.Event()
        async def extend(*args, **kwargs):
            renewed.set()
            return True
        fake_lock.extend = mock.AsyncMock(side_effect=extend)
        client = mock.Mock()
        client.lock.return_value = fake_lock
        with mock.patch.object(dl, "get_redis_client", new=mock.AsyncMock(return_value=client)):
            async with dl.RedisLockProvider().lock(resource_type="task", resource_id="slow", ttl=1):
                await asyncio.wait_for(renewed.wait(), 2)
                self.assertEqual(fake_lock.release_calls, 0)
        fake_lock.extend.assert_awaited_with(1, replace_ttl=True)
        self.assertEqual(fake_lock.release_calls, 1)

    async def test_redis_ownership_loss_interrupts_owner_before_publication(self):
        fake_lock = _FakeRedisLock()
        fake_lock.extend = mock.AsyncMock(side_effect=RuntimeError("token lost"))
        client = mock.Mock()
        client.lock.return_value = fake_lock
        with mock.patch.object(dl, "get_redis_client", new=mock.AsyncMock(return_value=client)):
            with self.assertRaises(dl.LockAcquireTimeout):
                async with dl.RedisLockProvider().lock(resource_type="task", resource_id="lost", ttl=1):
                    await asyncio.sleep(2)
                    self.fail("owner must stop on lease loss")
        self.assertEqual(fake_lock.release_calls, 1)

    async def test_external_cancellation_remains_cancellation(self):
        fake_lock = _FakeRedisLock()
        client = mock.Mock()
        client.lock.return_value = fake_lock
        with mock.patch.object(dl, "get_redis_client", new=mock.AsyncMock(return_value=client)):
            with self.assertRaises(asyncio.CancelledError):
                async with dl.RedisLockProvider().lock(resource_type="task", resource_id="cancel"):
                    raise asyncio.CancelledError()
        self.assertEqual(fake_lock.release_calls, 1)

    def setUp(self) -> None:
        self._orig = {
            "DISTRIBUTED_LOCK_BACKEND": settings.DISTRIBUTED_LOCK_BACKEND,
            "DISTRIBUTED_LOCK_ALLOW_LOCAL_FALLBACK": settings.DISTRIBUTED_LOCK_ALLOW_LOCAL_FALLBACK,
            "DISTRIBUTED_LOCK_BLOCKING_TIMEOUT_SECONDS": settings.DISTRIBUTED_LOCK_BLOCKING_TIMEOUT_SECONDS,
            "DISTRIBUTED_LOCK_SLEEP_SECONDS": settings.DISTRIBUTED_LOCK_SLEEP_SECONDS,
            "DISTRIBUTED_LOCK_DEFAULT_TTL_SECONDS": settings.DISTRIBUTED_LOCK_DEFAULT_TTL_SECONDS,
        }
        dl._PROVIDER = None

    def tearDown(self) -> None:
        settings.DISTRIBUTED_LOCK_BACKEND = self._orig["DISTRIBUTED_LOCK_BACKEND"]
        settings.DISTRIBUTED_LOCK_ALLOW_LOCAL_FALLBACK = self._orig["DISTRIBUTED_LOCK_ALLOW_LOCAL_FALLBACK"]
        settings.DISTRIBUTED_LOCK_BLOCKING_TIMEOUT_SECONDS = self._orig["DISTRIBUTED_LOCK_BLOCKING_TIMEOUT_SECONDS"]
        settings.DISTRIBUTED_LOCK_SLEEP_SECONDS = self._orig["DISTRIBUTED_LOCK_SLEEP_SECONDS"]
        settings.DISTRIBUTED_LOCK_DEFAULT_TTL_SECONDS = self._orig["DISTRIBUTED_LOCK_DEFAULT_TTL_SECONDS"]
        dl._PROVIDER = None

    async def test_local_provider_respects_blocking_timeout(self):
        provider = dl.LocalLockProvider()
        async with provider.lock(resource_type="task", resource_id="task-1", blocking_timeout=0.5):
            with self.assertRaises(dl.LockAcquireTimeout):
                async with provider.lock(resource_type="task", resource_id="task-1", blocking_timeout=0.05):
                    self.fail("second lock acquire should timeout")

    async def test_get_provider_fallbacks_to_local_when_redis_unavailable(self):
        settings.DISTRIBUTED_LOCK_BACKEND = "redis"
        settings.DISTRIBUTED_LOCK_ALLOW_LOCAL_FALLBACK = True
        dl._PROVIDER = None

        with mock.patch("app.core.distributed_lock.ping_redis_client", new=mock.AsyncMock(side_effect=RuntimeError("redis down"))):
            provider = await dl.get_lock_provider()
        self.assertIsInstance(provider, dl.LocalLockProvider)

    async def test_get_provider_raises_when_redis_unavailable_and_fallback_disabled(self):
        settings.DISTRIBUTED_LOCK_BACKEND = "redis"
        settings.DISTRIBUTED_LOCK_ALLOW_LOCAL_FALLBACK = False
        dl._PROVIDER = None

        with mock.patch("app.core.distributed_lock.ping_redis_client", new=mock.AsyncMock(side_effect=RuntimeError("redis down"))):
            with self.assertRaises(RuntimeError):
                await dl.get_lock_provider()

    async def test_redis_provider_uses_official_lock_and_raises_on_acquire_timeout(self):
        provider = dl.RedisLockProvider()
        fake_lock = _FakeRedisLock(acquire_result=False)
        fake_client = mock.Mock()
        fake_client.lock.return_value = fake_lock

        with mock.patch("app.core.distributed_lock.get_redis_client", new=mock.AsyncMock(return_value=fake_client)):
            with self.assertRaises(dl.LockAcquireTimeout):
                async with provider.lock(
                    resource_type="task",
                    resource_id="task-2",
                    ttl=11,
                    blocking_timeout=0.12,
                    sleep=0.09,
                ):
                    self.fail("acquire should timeout")

        fake_client.lock.assert_called_once_with(
            name=mock.ANY,
            timeout=11,
            sleep=0.09,
            thread_local=False,
        )
        self.assertEqual(len(fake_lock.acquire_calls), 1)
        self.assertEqual(fake_lock.acquire_calls[0]["blocking"], True)
        self.assertAlmostEqual(float(fake_lock.acquire_calls[0]["blocking_timeout"]), 0.12)
        self.assertNotIn("sleep", fake_lock.acquire_calls[0])

    async def test_redis_provider_release_error_does_not_escape(self):
        provider = dl.RedisLockProvider()
        fake_lock = _FakeRedisLock(acquire_result=True, release_error=RuntimeError("release failed"))
        fake_client = mock.Mock()
        fake_client.lock.return_value = fake_lock

        with mock.patch("app.core.distributed_lock.get_redis_client", new=mock.AsyncMock(return_value=fake_client)):
            async with provider.lock(resource_type="task", resource_id="task-3", blocking_timeout=0.1):
                pass

        self.assertEqual(fake_lock.release_calls, 1)

    async def test_timeout_before_set_retries_with_same_token(self):
        lock = _FakeRedisLock()
        lock.acquire = mock.AsyncMock(side_effect=[RedisTimeoutError("read timeout"), True])
        lock.reacquire = mock.AsyncMock(side_effect=LockNotOwnedError("absent"))
        client = mock.Mock()
        client.lock.return_value = lock
        with mock.patch.object(dl, "get_redis_client", new=mock.AsyncMock(return_value=client)):
            async with dl.RedisLockProvider().lock(resource_type="task", resource_id="retry"):
                pass
        self.assertEqual(lock.acquire.await_count, 2)
        self.assertEqual(lock.acquire.call_args_list[0].kwargs["token"],
                         lock.acquire.call_args_list[1].kwargs["token"])
        self.assertEqual(lock.release_calls, 1)

    async def test_lost_set_response_recovers_lease_without_second_set(self):
        lock = _FakeRedisLock()
        lock.acquire = mock.AsyncMock(side_effect=RedisTimeoutError("response lost"))
        lock.reacquire = mock.AsyncMock(return_value=True)
        client = mock.Mock()
        client.lock.return_value = lock
        executions = 0
        with mock.patch.object(dl, "get_redis_client", new=mock.AsyncMock(return_value=client)):
            async with dl.RedisLockProvider().lock(resource_type="task", resource_id="committed"):
                executions += 1
                self.assertEqual(lock.local.token, lock.acquire.call_args.kwargs["token"])
        self.assertEqual(executions, 1)
        lock.acquire.assert_awaited_once()
        lock.reacquire.assert_awaited_once()
        self.assertEqual(lock.release_calls, 1)

    async def test_other_owner_does_not_allow_entry_after_timeout(self):
        lock = _FakeRedisLock()
        lock.acquire = mock.AsyncMock(side_effect=[RedisTimeoutError("lost"), False])
        lock.reacquire = mock.AsyncMock(side_effect=LockNotOwnedError("other owner"))
        client = mock.Mock()
        client.lock.return_value = lock
        with mock.patch.object(dl, "get_redis_client", new=mock.AsyncMock(return_value=client)):
            with self.assertRaises(dl.LockAcquireTimeout):
                async with dl.RedisLockProvider().lock(resource_type="task", resource_id="busy"):
                    self.fail("must not enter another owner's critical section")
        self.assertEqual(lock.release_calls, 0)

    async def test_persistent_timeout_has_bounded_retries(self):
        lock = _FakeRedisLock()
        lock.acquire = mock.AsyncMock(side_effect=RedisTimeoutError("unavailable"))
        lock.reacquire = mock.AsyncMock(side_effect=RedisTimeoutError("unavailable"))
        client = mock.Mock()
        client.lock.return_value = lock
        with mock.patch.object(dl, "get_redis_client", new=mock.AsyncMock(return_value=client)):
            with self.assertRaises(dl.LockAcquireTimeout):
                async with dl.RedisLockProvider().lock(resource_type="task", resource_id="down"):
                    self.fail("must fail closed")
        lock.acquire.assert_awaited_once()
        self.assertEqual(lock.reacquire.await_count, 2)
        self.assertEqual(lock.release_calls, 1)

    async def test_authentication_failure_is_not_retried(self):
        lock = _FakeRedisLock()
        lock.acquire = mock.AsyncMock(side_effect=AuthenticationError("invalid credentials"))
        client = mock.Mock()
        client.lock.return_value = lock
        with mock.patch.object(dl, "get_redis_client", new=mock.AsyncMock(return_value=client)):
            with self.assertRaises(dl.LockAcquireTimeout):
                async with dl.RedisLockProvider().lock(resource_type="task", resource_id="auth"):
                    self.fail("must not enter")
        lock.acquire.assert_awaited_once()

    async def test_hanging_acquire_respects_overall_deadline(self):
        lock = _FakeRedisLock()
        async def hang(**kwargs):
            await asyncio.Event().wait()
        lock.acquire = mock.AsyncMock(side_effect=hang)
        client = mock.Mock()
        client.lock.return_value = lock
        with mock.patch.object(dl, "get_redis_client", new=mock.AsyncMock(return_value=client)):
            with self.assertRaises(dl.LockAcquireTimeout):
                async with asyncio.timeout(0.5):
                    async with dl.RedisLockProvider().lock(
                        resource_type="task", resource_id="hang", blocking_timeout=0.03,
                    ):
                        self.fail("deadline must prevent entry")
        self.assertEqual(lock.release_calls, 1)

    async def test_cancel_during_acquire_cleans_uncertain_lock(self):
        lock = _FakeRedisLock()
        lock.acquire = mock.AsyncMock(side_effect=asyncio.CancelledError())
        client = mock.Mock()
        client.lock.return_value = lock
        with mock.patch.object(dl, "get_redis_client", new=mock.AsyncMock(return_value=client)):
            with self.assertRaises(asyncio.CancelledError):
                async with dl.RedisLockProvider().lock(resource_type="task", resource_id="cancel-acquire"):
                    self.fail("must preserve cancellation")
        self.assertEqual(lock.release_calls, 1)

    async def test_body_timeout_does_not_reexecute_critical_section(self):
        lock = _FakeRedisLock()
        client = mock.Mock()
        client.lock.return_value = lock
        executions = 0
        with mock.patch.object(dl, "get_redis_client", new=mock.AsyncMock(return_value=client)):
            with self.assertRaises(RedisTimeoutError):
                async with dl.RedisLockProvider().lock(resource_type="task", resource_id="body"):
                    executions += 1
                    raise RedisTimeoutError("business operation timed out")
        self.assertEqual(executions, 1)
        self.assertEqual(len(lock.acquire_calls), 1)
        self.assertEqual(lock.release_calls, 1)


if __name__ == "__main__":
    unittest.main()
