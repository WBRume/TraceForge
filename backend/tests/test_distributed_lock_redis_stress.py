import asyncio
import os
import sys
from typing import List

import pytest


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.config import settings  # noqa: E402
from app.core import distributed_lock as dl  # noqa: E402
from app.core import redis_client as redis_client_module  # noqa: E402


def _skip_unless_redis_lock_mode() -> None:
    if not bool(settings.REDIS_ENABLED):
        pytest.skip("REDIS_ENABLED is false; skip redis lock stress tests")
    if str(settings.DISTRIBUTED_LOCK_BACKEND or "").strip().lower() != "redis":
        pytest.skip("DISTRIBUTED_LOCK_BACKEND is not redis; skip redis lock stress tests")
    if bool(settings.DISTRIBUTED_LOCK_ALLOW_LOCAL_FALLBACK):
        pytest.skip("DISTRIBUTED_LOCK_ALLOW_LOCAL_FALLBACK is true; skip strict redis lock stress tests")


async def _ensure_redis_provider() -> None:
    dl._PROVIDER = None
    provider = await dl.get_lock_provider()
    assert provider.backend_name == "redis"


def _reset_redis_runtime_cache() -> None:
    dl._PROVIDER = None
    redis_client_module._REDIS_CLIENT = None


def test_redis_lock_same_key_exclusive_under_concurrency():
    _skip_unless_redis_lock_mode()
    _reset_redis_runtime_cache()

    async def _run() -> None:
        try:
            await _ensure_redis_provider()
            active = 0
            max_active = 0
            violations: List[int] = []
            guard = asyncio.Lock()

            async def _worker(worker_id: int) -> None:
                nonlocal active, max_active
                for _ in range(5):
                    async with dl.lock_task(
                        "stress-task-shared",
                        ttl=10,
                        blocking_timeout=3.0,
                    ):
                        async with guard:
                            active += 1
                            max_active = max(max_active, active)
                            if active > 1:
                                violations.append(worker_id)
                        await asyncio.sleep(0.01)
                        async with guard:
                            active -= 1

            await asyncio.gather(*[_worker(index) for index in range(24)])
            assert max_active == 1
            assert not violations
        finally:
            await redis_client_module.close_redis_client()
            dl._PROVIDER = None

    asyncio.run(_run())


def test_redis_lock_timeout_when_same_key_contended():
    _skip_unless_redis_lock_mode()
    _reset_redis_runtime_cache()

    async def _run() -> None:
        try:
            await _ensure_redis_provider()
            holder_entered = asyncio.Event()

            async def _holder() -> None:
                async with dl.lock_skill(
                    "stress-skill-timeout",
                    ttl=5,
                    blocking_timeout=1.5,
                ):
                    holder_entered.set()
                    await asyncio.sleep(0.35)

            async def _contender() -> None:
                await holder_entered.wait()
                with pytest.raises(dl.LockAcquireTimeout):
                    async with dl.lock_skill(
                        "stress-skill-timeout",
                        ttl=5,
                        blocking_timeout=0.05,
                    ):
                        raise AssertionError("Contender should not acquire lock")

            await asyncio.gather(_holder(), _contender())
        finally:
            await redis_client_module.close_redis_client()
            dl._PROVIDER = None

    asyncio.run(_run())


def test_redis_lock_different_keys_can_progress_in_parallel():
    _skip_unless_redis_lock_mode()
    _reset_redis_runtime_cache()

    async def _run() -> None:
        try:
            await _ensure_redis_provider()
            active = 0
            max_active = 0
            guard = asyncio.Lock()

            async def _worker(index: int) -> None:
                nonlocal active, max_active
                async with dl.lock_task(
                    f"stress-task-{index}",
                    ttl=5,
                    blocking_timeout=2.0,
                ):
                    async with guard:
                        active += 1
                        max_active = max(max_active, active)
                    await asyncio.sleep(0.03)
                    async with guard:
                        active -= 1

            await asyncio.gather(*[_worker(index) for index in range(16)])
            assert max_active >= 2
        finally:
            await redis_client_module.close_redis_client()
            dl._PROVIDER = None

    asyncio.run(_run())


def test_workspace_task_create_queue_serializes_in_fifo_order():
    _skip_unless_redis_lock_mode()
    _reset_redis_runtime_cache()

    async def _run() -> None:
        try:
            await _ensure_redis_provider()
            events: List[str] = []

            async def _worker(name: str, delay_inside: float) -> None:
                async with dl.queue_workspace_task_creation("ws-queue-stress", wait_timeout=5.0, poll_interval=0.02):
                    events.append(f"{name}:enter")
                    await asyncio.sleep(delay_inside)
                    events.append(f"{name}:exit")

            first = asyncio.create_task(_worker("first", 0.12))
            await asyncio.sleep(0.02)
            second = asyncio.create_task(_worker("second", 0.01))
            await asyncio.gather(first, second)

            assert events[0] == "first:enter"
            assert events[1] == "first:exit"
            assert events[2] == "second:enter"
            assert events[3] == "second:exit"
        finally:
            await redis_client_module.close_redis_client()
            dl._PROVIDER = None

    asyncio.run(_run())
