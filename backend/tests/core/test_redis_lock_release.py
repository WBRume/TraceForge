"""Release recovery using redis-py's real Lock and an isolated command transport."""

import asyncio
from unittest import mock

import pytest
from redis.asyncio import Redis
from redis.exceptions import (
    AuthenticationError,
    LockNotOwnedError,
)
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
)
from redis.exceptions import (
    TimeoutError as RedisTimeoutError,
)

from app.core import distributed_lock as dl


class RedisLockTransport:
    """Keep the official token lifecycle; inject failures at command boundaries."""

    def __init__(self, failures=(), *, successor=None, clear_token_on_failure=False):
        self.client = Redis()
        self.values = {}
        self.failures = list(failures)
        self.successor = successor
        self.clear_token_on_failure = clear_token_on_failure
        self.release_tokens = []
        self.locks = []

    def lock(self, **kwargs):
        lock = self.client.lock(**kwargs)
        self.locks.append(lock)

        async def acquire(token):
            if lock.name in self.values:
                return False
            self.values[lock.name] = token
            return True

        async def release(token):
            self.release_tokens.append(token)
            failure = self.failures.pop(0) if self.failures else None
            if self.clear_token_on_failure:
                # Older redis-py releases clear local state before sending Lua.
                lock.local.token = None
            if isinstance(failure, BaseException):
                raise failure
            if failure == "hang":
                await asyncio.Event().wait()
            if self.values.get(lock.name) != token:
                raise LockNotOwnedError("another owner or already released")
            del self.values[lock.name]
            if failure == "response_lost":
                if self.successor is not None:
                    self.values[lock.name] = self.successor
                raise RedisConnectionError("release response lost")

        lock.do_acquire = acquire
        lock.do_release = release
        return lock


@pytest.fixture
def transport_factory(monkeypatch):
    def create(*args, **kwargs):
        transport = RedisLockTransport(*args, **kwargs)
        monkeypatch.setattr(dl, "get_redis_client", mock.AsyncMock(return_value=transport))
        return transport

    return create


@pytest.mark.parametrize("clear_local", [False, True])
@pytest.mark.parametrize("failure", [RedisConnectionError("Connection lost"), RedisTimeoutError("read timed out")])
def test_release_failure_does_not_block_next_task_operation(transport_factory, clear_local, failure):
    transport = transport_factory([failure], clear_token_on_failure=clear_local)

    async def run():
        provider = dl.RedisLockProvider()
        for _ in range(2):
            async with provider.lock(resource_type="task", resource_id="initialize-then-stop", blocking_timeout=0.05):
                pass

    asyncio.run(run())
    assert transport.values == {}
    assert len(transport.release_tokens) == 3
    assert transport.release_tokens[0] == transport.release_tokens[1]
    assert transport.release_tokens[2] != transport.release_tokens[0]


@pytest.mark.parametrize("successor", [None, b"different-owner"])
def test_lost_release_response_preserves_a_successor_lock(transport_factory, successor):
    transport = transport_factory(["response_lost"], successor=successor)

    async def run():
        async with dl.RedisLockProvider().lock(resource_type="task", resource_id="response-lost") as context:
            return context.lock_key

    key = asyncio.run(run())
    assert transport.values == ({} if successor is None else {key: successor})
    assert len(transport.release_tokens) == 2
    assert transport.release_tokens[0] == transport.release_tokens[1]
    assert transport.locks[0].local.token is None


def test_persistent_release_failure_is_bounded_and_preserves_business_error(transport_factory):
    transport = transport_factory([RedisConnectionError("offline")] * 3)

    async def run():
        with pytest.raises(ValueError, match="business failure"):
            async with asyncio.timeout(1.0):
                async with dl.RedisLockProvider().lock(resource_type="task", resource_id="offline"):
                    raise ValueError("business failure")

    asyncio.run(run())
    assert len(transport.release_tokens) == 3
    assert len(set(transport.release_tokens)) == 1


def test_authentication_failure_on_release_is_not_retried(transport_factory):
    transport = transport_factory([AuthenticationError("credentials rejected")])

    async def run():
        async with dl.RedisLockProvider().lock(resource_type="task", resource_id="release-auth"):
            pass

    asyncio.run(run())
    assert len(transport.release_tokens) == 1


def test_hanging_release_has_an_overall_deadline(transport_factory):
    transport = transport_factory(["hang"])

    async def run():
        context = dl._build_context(
            resource_type="task", resource_id="hang-release", ttl=120, blocking_timeout=1, sleep=0.01
        )
        lock = transport.lock(name=context.lock_key, timeout=context.ttl, thread_local=False)
        assert await lock.acquire(token=b"owned-token")
        with pytest.raises(asyncio.TimeoutError):
            async with asyncio.timeout(0.5):
                await dl.RedisLockProvider()._release(lock, context, timeout=0.03)

    asyncio.run(run())
    assert transport.release_tokens == [b"owned-token"]


def test_external_cancellation_still_releases_after_a_disconnect(transport_factory):
    transport = transport_factory([RedisConnectionError("Connection lost")])

    async def run():
        with pytest.raises(asyncio.CancelledError):
            async with dl.RedisLockProvider().lock(resource_type="task", resource_id="cancel-release"):
                raise asyncio.CancelledError

    asyncio.run(run())
    assert transport.values == {}
    assert len(transport.release_tokens) == 2


def test_uncertain_acquire_cleanup_retries_with_original_token(transport_factory):
    transport = transport_factory([RedisConnectionError("Connection lost")])

    async def run():
        context = dl._build_context(
            resource_type="task", resource_id="uncertain-set", ttl=120, blocking_timeout=0.03, sleep=0.01
        )
        lock = transport.lock(name=context.lock_key, timeout=context.ttl, thread_local=False)

        async def acquire_with_lost_response(token):
            transport.values[context.lock_key] = token
            await asyncio.Event().wait()

        lock.do_acquire = acquire_with_lost_response
        with pytest.raises(asyncio.TimeoutError):
            await dl.RedisLockProvider()._acquire(lock, context)

    asyncio.run(run())
    assert transport.values == {}
    assert len(transport.release_tokens) == 2
    assert transport.release_tokens[0] == transport.release_tokens[1]
