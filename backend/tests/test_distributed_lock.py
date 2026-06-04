import os
import sys
import unittest
from unittest import mock


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
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

    async def acquire(self, **kwargs):
        self.acquire_calls.append(kwargs)
        return self.acquire_result

    async def release(self):
        self.release_calls += 1
        if self.release_error:
            raise self.release_error


class DistributedLockTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._orig = {
            "REDIS_ENABLED": settings.REDIS_ENABLED,
            "DISTRIBUTED_LOCK_BACKEND": settings.DISTRIBUTED_LOCK_BACKEND,
            "DISTRIBUTED_LOCK_ALLOW_LOCAL_FALLBACK": settings.DISTRIBUTED_LOCK_ALLOW_LOCAL_FALLBACK,
            "DISTRIBUTED_LOCK_BLOCKING_TIMEOUT_SECONDS": settings.DISTRIBUTED_LOCK_BLOCKING_TIMEOUT_SECONDS,
            "DISTRIBUTED_LOCK_SLEEP_SECONDS": settings.DISTRIBUTED_LOCK_SLEEP_SECONDS,
            "DISTRIBUTED_LOCK_DEFAULT_TTL_SECONDS": settings.DISTRIBUTED_LOCK_DEFAULT_TTL_SECONDS,
        }
        dl._PROVIDER = None

    def tearDown(self) -> None:
        settings.REDIS_ENABLED = self._orig["REDIS_ENABLED"]
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
        settings.REDIS_ENABLED = True
        settings.DISTRIBUTED_LOCK_ALLOW_LOCAL_FALLBACK = True
        dl._PROVIDER = None

        with mock.patch("app.core.distributed_lock.ping_redis_client", new=mock.AsyncMock(side_effect=RuntimeError("redis down"))):
            provider = await dl.get_lock_provider()
        self.assertIsInstance(provider, dl.LocalLockProvider)

    async def test_get_provider_raises_when_redis_unavailable_and_fallback_disabled(self):
        settings.DISTRIBUTED_LOCK_BACKEND = "redis"
        settings.REDIS_ENABLED = True
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


if __name__ == "__main__":
    unittest.main()
