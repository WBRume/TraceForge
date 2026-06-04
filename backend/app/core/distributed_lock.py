"""
Unified distributed lock provider abstraction.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import re
import time
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from typing import AsyncIterator, Dict, Optional

from app.config import settings
from app.core.logging import get_logger
from app.core.redis_client import get_redis_client, ping_redis_client

logger = get_logger(__name__)


_RESOURCE_PART_PATTERN = re.compile(r"[^a-zA-Z0-9:_-]+")


class LockAcquireTimeout(RuntimeError):
    def __init__(
        self,
        *,
        lock_key: str,
        resource_type: str,
        resource_id: str,
        backend: str,
        message: Optional[str] = None,
    ) -> None:
        super().__init__(
            message
            or (
                f"Failed to acquire lock for {resource_type}:{resource_id} "
                f"(backend={backend}, key={lock_key})"
            )
        )
        self.lock_key = lock_key
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.backend = backend
        self.status_code = 409


class ResourceBusyError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        resource_type: str,
        resource_id: str,
        lock_key: Optional[str] = None,
        backend: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = 409
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.lock_key = lock_key
        self.backend = backend


@dataclass(frozen=True)
class LockContext:
    lock_key: str
    resource_type: str
    resource_id: str
    ttl: int
    blocking_timeout: float
    sleep: float


def _normalize_component(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "unknown"
    collapsed = _RESOURCE_PART_PATTERN.sub("-", raw)
    collapsed = collapsed.strip("-")
    return collapsed or "unknown"


def _sanitize_lock_key(
    *,
    resource_type: str,
    resource_id: str,
) -> str:
    prefix = _normalize_component(str(settings.DISTRIBUTED_LOCK_KEY_PREFIX or "sdd-native"))
    normalized_type = _normalize_component(resource_type).lower()
    normalized_id = _normalize_component(resource_id).lower()
    return f"{prefix}:{normalized_type}:{normalized_id}"


def _resolve_ttl(ttl: Optional[int]) -> int:
    value = int(ttl or settings.DISTRIBUTED_LOCK_DEFAULT_TTL_SECONDS or 60)
    return max(1, value)


def _resolve_blocking_timeout(blocking_timeout: Optional[float]) -> float:
    raw = settings.DISTRIBUTED_LOCK_BLOCKING_TIMEOUT_SECONDS
    value = float(raw if blocking_timeout is None else blocking_timeout)
    return max(0.01, value)


def _resolve_sleep(sleep: Optional[float]) -> float:
    raw = settings.DISTRIBUTED_LOCK_SLEEP_SECONDS
    value = float(raw if sleep is None else sleep)
    return max(0.01, value)


def _build_context(
    *,
    resource_type: str,
    resource_id: str,
    ttl: Optional[int],
    blocking_timeout: Optional[float],
    sleep: Optional[float],
) -> LockContext:
    lock_key = _sanitize_lock_key(resource_type=resource_type, resource_id=resource_id)
    return LockContext(
        lock_key=lock_key,
        resource_type=str(resource_type or "").strip() or "resource",
        resource_id=str(resource_id or "").strip() or "unknown",
        ttl=_resolve_ttl(ttl),
        blocking_timeout=_resolve_blocking_timeout(blocking_timeout),
        sleep=_resolve_sleep(sleep),
    )


def _creation_lock_id(project_path: str, git_repo_url: str) -> str:
    raw = f"{str(project_path or '').strip()}|{str(git_repo_url or '').strip()}"
    digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"create:{digest}"


def _task_create_queue_key(workspace_id: str) -> str:
    return _sanitize_lock_key(
        resource_type="queue",
        resource_id=f"workspace:{str(workspace_id or '').strip()}:create_task",
    )


def _background_queue_key(queue_name: str) -> str:
    normalized = _normalize_component(str(queue_name or "").strip().lower() or "default")
    return _sanitize_lock_key(
        resource_type="queue",
        resource_id=f"background:{normalized}",
    )


class DistributedLockProvider(ABC):
    backend_name = "unknown"

    @abstractmethod
    @contextlib.asynccontextmanager
    async def lock(
        self,
        *,
        resource_type: str,
        resource_id: str,
        ttl: Optional[int] = None,
        blocking_timeout: Optional[float] = None,
        sleep: Optional[float] = None,
    ) -> AsyncIterator[LockContext]:
        raise NotImplementedError


class LocalLockProvider(DistributedLockProvider):
    """
    Local lock backend.
    This only protects critical sections in single-worker deployments.
    """

    backend_name = "local"

    def __init__(self) -> None:
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    @contextlib.asynccontextmanager
    async def lock(
        self,
        *,
        resource_type: str,
        resource_id: str,
        ttl: Optional[int] = None,
        blocking_timeout: Optional[float] = None,
        sleep: Optional[float] = None,
    ) -> AsyncIterator[LockContext]:
        context = _build_context(
            resource_type=resource_type,
            resource_id=resource_id,
            ttl=ttl,
            blocking_timeout=blocking_timeout,
            sleep=sleep,
        )
        local_lock = self._locks[context.lock_key]
        acquired = False
        try:
            await asyncio.wait_for(local_lock.acquire(), timeout=context.blocking_timeout)
            acquired = True
        except asyncio.TimeoutError as exc:
            logger.warning(
                "local lock acquire timeout: resource_type={}, resource_id={}, lock_key={}",
                context.resource_type,
                context.resource_id,
                context.lock_key,
            )
            raise LockAcquireTimeout(
                lock_key=context.lock_key,
                resource_type=context.resource_type,
                resource_id=context.resource_id,
                backend=self.backend_name,
            ) from exc

        try:
            yield context
        finally:
            if acquired and local_lock.locked():
                local_lock.release()


class RedisLockProvider(DistributedLockProvider):
    backend_name = "redis"

    @contextlib.asynccontextmanager
    async def lock(
        self,
        *,
        resource_type: str,
        resource_id: str,
        ttl: Optional[int] = None,
        blocking_timeout: Optional[float] = None,
        sleep: Optional[float] = None,
    ) -> AsyncIterator[LockContext]:
        context = _build_context(
            resource_type=resource_type,
            resource_id=resource_id,
            ttl=ttl,
            blocking_timeout=blocking_timeout,
            sleep=sleep,
        )
        client = await get_redis_client()
        lock = client.lock(
            name=context.lock_key,
            timeout=context.ttl,
            sleep=context.sleep,
            thread_local=False,
        )
        try:
            acquired = await lock.acquire(
                blocking=True,
                blocking_timeout=context.blocking_timeout,
            )
        except Exception as exc:
            logger.warning(
                "redis lock acquire failed: resource_type={}, resource_id={}, lock_key={}, error={}",
                context.resource_type,
                context.resource_id,
                context.lock_key,
                str(exc),
            )
            raise LockAcquireTimeout(
                lock_key=context.lock_key,
                resource_type=context.resource_type,
                resource_id=context.resource_id,
                backend=self.backend_name,
            ) from exc
        if not acquired:
            logger.warning(
                "redis lock acquire timeout: resource_type={}, resource_id={}, lock_key={}",
                context.resource_type,
                context.resource_id,
                context.lock_key,
            )
            raise LockAcquireTimeout(
                lock_key=context.lock_key,
                resource_type=context.resource_type,
                resource_id=context.resource_id,
                backend=self.backend_name,
            )

        try:
            yield context
        finally:
            try:
                await lock.release()
            except Exception as exc:
                logger.warning(
                    "redis lock release failed: resource_type={}, resource_id={}, lock_key={}, error={}",
                    context.resource_type,
                    context.resource_id,
                    context.lock_key,
                    str(exc),
                )


_PROVIDER: Optional[DistributedLockProvider] = None
_PROVIDER_LOCK = asyncio.Lock()
_LOCAL_QUEUE_SLOTS: Dict[str, tuple[asyncio.Semaphore, int]] = {}
_LOCAL_QUEUE_SLOTS_LOCK = asyncio.Lock()


async def _build_provider() -> DistributedLockProvider:
    backend = str(settings.DISTRIBUTED_LOCK_BACKEND or "local").strip().lower()
    allow_local_fallback = bool(settings.DISTRIBUTED_LOCK_ALLOW_LOCAL_FALLBACK)
    redis_enabled = bool(settings.REDIS_ENABLED)

    if backend == "local":
        return LocalLockProvider()

    if backend == "redis":
        if not redis_enabled:
            message = "Redis lock backend requested but REDIS_ENABLED is false"
            if allow_local_fallback:
                logger.warning(message + ", falling back to local lock provider")
                return LocalLockProvider()
            raise RuntimeError(message)

        try:
            await ping_redis_client()
            return RedisLockProvider()
        except Exception as exc:
            if allow_local_fallback:
                logger.warning(
                    "Redis lock backend unavailable, falling back to local provider: {}",
                    str(exc),
                )
                return LocalLockProvider()
            raise RuntimeError(
                "Redis lock backend unavailable and local fallback is disabled"
            ) from exc

    message = f"Unsupported lock backend '{backend}'"
    if allow_local_fallback:
        logger.warning(message + ", falling back to local lock provider")
        return LocalLockProvider()
    raise RuntimeError(message)


async def get_lock_provider() -> DistributedLockProvider:
    global _PROVIDER
    if _PROVIDER is not None:
        return _PROVIDER
    async with _PROVIDER_LOCK:
        if _PROVIDER is None:
            _PROVIDER = await _build_provider()
    return _PROVIDER


async def _get_local_queue_semaphore(queue_key: str, max_concurrent: int) -> asyncio.Semaphore:
    async with _LOCAL_QUEUE_SLOTS_LOCK:
        current = _LOCAL_QUEUE_SLOTS.get(queue_key)
        if current and int(current[1]) == int(max_concurrent):
            return current[0]
        semaphore = asyncio.Semaphore(max(1, int(max_concurrent)))
        _LOCAL_QUEUE_SLOTS[queue_key] = (semaphore, int(max_concurrent))
        return semaphore


@contextlib.asynccontextmanager
async def _lock_resource(
    *,
    resource_type: str,
    resource_id: str,
    ttl: Optional[int],
    blocking_timeout: Optional[float],
    sleep: Optional[float],
) -> AsyncIterator[LockContext]:
    provider = await get_lock_provider()
    async with provider.lock(
        resource_type=resource_type,
        resource_id=resource_id,
        ttl=ttl,
        blocking_timeout=blocking_timeout,
        sleep=sleep,
    ) as context:
        yield context


@contextlib.asynccontextmanager
async def lock_task(
    task_id: str,
    *,
    ttl: Optional[int] = None,
    blocking_timeout: Optional[float] = None,
    sleep: Optional[float] = None,
) -> AsyncIterator[LockContext]:
    async with _lock_resource(
        resource_type="task",
        resource_id=str(task_id or ""),
        ttl=ttl or settings.TASK_LOCK_TTL_SECONDS,
        blocking_timeout=blocking_timeout,
        sleep=sleep,
    ) as context:
        yield context


@contextlib.asynccontextmanager
async def lock_skill(
    skill_id: str,
    *,
    ttl: Optional[int] = None,
    blocking_timeout: Optional[float] = None,
    sleep: Optional[float] = None,
) -> AsyncIterator[LockContext]:
    async with _lock_resource(
        resource_type="skill",
        resource_id=str(skill_id or ""),
        ttl=ttl or settings.SKILL_LOCK_TTL_SECONDS,
        blocking_timeout=blocking_timeout,
        sleep=sleep,
    ) as context:
        yield context


@contextlib.asynccontextmanager
async def lock_workspace_repo(
    workspace_id: str,
    *,
    ttl: Optional[int] = None,
    blocking_timeout: Optional[float] = None,
    sleep: Optional[float] = None,
) -> AsyncIterator[LockContext]:
    async with _lock_resource(
        resource_type="workspace",
        resource_id=f"{str(workspace_id or '').strip()}:repo",
        ttl=ttl or settings.WORKSPACE_LOCK_TTL_SECONDS,
        blocking_timeout=blocking_timeout,
        sleep=sleep,
    ) as context:
        yield context


@contextlib.asynccontextmanager
async def lock_workspace_repo_creation(
    *,
    project_path: str,
    git_repo_url: str,
    ttl: Optional[int] = None,
    blocking_timeout: Optional[float] = None,
    sleep: Optional[float] = None,
) -> AsyncIterator[LockContext]:
    async with _lock_resource(
        resource_type="workspace",
        resource_id=f"{_creation_lock_id(project_path, git_repo_url)}:repo",
        ttl=ttl or settings.WORKSPACE_LOCK_TTL_SECONDS,
        blocking_timeout=blocking_timeout,
        sleep=sleep,
    ) as context:
        yield context


@contextlib.asynccontextmanager
async def lock_ai_queue(
    queue_key: str,
    *,
    ttl: Optional[int] = None,
    blocking_timeout: Optional[float] = None,
    sleep: Optional[float] = None,
) -> AsyncIterator[LockContext]:
    async with _lock_resource(
        resource_type="ai_queue",
        resource_id=str(queue_key or ""),
        ttl=ttl or settings.AI_JOB_LOCK_TTL_SECONDS,
        blocking_timeout=blocking_timeout,
        sleep=sleep,
    ) as context:
        yield context


@contextlib.asynccontextmanager
async def lock_api_mock_project(
    project_id: str,
    *,
    ttl: Optional[int] = None,
    blocking_timeout: Optional[float] = None,
    sleep: Optional[float] = None,
) -> AsyncIterator[LockContext]:
    async with _lock_resource(
        resource_type="api_mock_project",
        resource_id=str(project_id or ""),
        ttl=ttl or settings.AI_JOB_LOCK_TTL_SECONDS,
        blocking_timeout=blocking_timeout,
        sleep=sleep,
    ) as context:
        yield context


@contextlib.asynccontextmanager
async def lock_task_bootstrap(
    task_id: str,
    *,
    ttl: Optional[int] = None,
    blocking_timeout: Optional[float] = None,
    sleep: Optional[float] = None,
) -> AsyncIterator[LockContext]:
    async with _lock_resource(
        resource_type="task",
        resource_id=f"{str(task_id or '').strip()}:bootstrap",
        ttl=ttl or settings.BOOTSTRAP_LOCK_TTL_SECONDS,
        blocking_timeout=blocking_timeout,
        sleep=sleep,
    ) as context:
        yield context


@contextlib.asynccontextmanager
async def lock_thread_workspace(
    thread_id: str,
    *,
    ttl: Optional[int] = None,
    blocking_timeout: Optional[float] = None,
    sleep: Optional[float] = None,
) -> AsyncIterator[LockContext]:
    async with _lock_resource(
        resource_type="thread",
        resource_id=f"{str(thread_id or '').strip()}:workspace",
        ttl=ttl or settings.BOOTSTRAP_LOCK_TTL_SECONDS,
        blocking_timeout=blocking_timeout,
        sleep=sleep,
    ) as context:
        yield context


def make_resource_busy_error(
    exc: LockAcquireTimeout,
    message: str,
) -> ResourceBusyError:
    return ResourceBusyError(
        message,
        resource_type=exc.resource_type,
        resource_id=exc.resource_id,
        lock_key=exc.lock_key,
        backend=exc.backend,
    )


@contextlib.asynccontextmanager
async def queue_workspace_task_creation(
    workspace_id: str,
    *,
    wait_timeout: Optional[float] = None,
    poll_interval: Optional[float] = None,
) -> AsyncIterator[None]:
    timeout_sec = max(
        0.5,
        float(
            settings.TASK_CREATE_QUEUE_WAIT_TIMEOUT_SECONDS
            if wait_timeout is None
            else wait_timeout
        ),
    )
    sleep_sec = max(
        0.01,
        float(
            settings.TASK_CREATE_QUEUE_POLL_INTERVAL_SECONDS
            if poll_interval is None
            else poll_interval
        ),
    )
    queue_name = f"workspace:{str(workspace_id or '').strip()}:create_task"
    async with queue_background_job(
        queue_name=queue_name,
        max_concurrent=1,
        wait_timeout=timeout_sec,
        poll_interval=sleep_sec,
        resource_type="workspace_task_create_queue",
        resource_id=str(workspace_id or "").strip() or "unknown",
    ):
        yield


@contextlib.asynccontextmanager
async def queue_background_job(
    *,
    queue_name: str,
    max_concurrent: Optional[int] = None,
    wait_timeout: Optional[float] = None,
    poll_interval: Optional[float] = None,
    resource_type: str = "background_queue",
    resource_id: Optional[str] = None,
) -> AsyncIterator[None]:
    provider = await get_lock_provider()
    limit = max(
        1,
        int(
            settings.BACKGROUND_QUEUE_DEFAULT_MAX_CONCURRENT
            if max_concurrent is None
            else max_concurrent
        ),
    )
    timeout_sec = max(
        0.5,
        float(
            settings.BACKGROUND_QUEUE_WAIT_TIMEOUT_SECONDS
            if wait_timeout is None
            else wait_timeout
        ),
    )
    sleep_sec = max(
        0.01,
        float(
            settings.BACKGROUND_QUEUE_POLL_INTERVAL_SECONDS
            if poll_interval is None
            else poll_interval
        ),
    )
    rid = str(resource_id or queue_name or "unknown").strip() or "unknown"
    queue_key = _background_queue_key(queue_name)

    if provider.backend_name != "redis":
        semaphore = await _get_local_queue_semaphore(queue_key, limit)
        acquired = False
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=timeout_sec)
            acquired = True
            yield
        except asyncio.TimeoutError as exc:
            raise LockAcquireTimeout(
                lock_key=queue_key,
                resource_type=resource_type,
                resource_id=rid,
                backend="local",
                message=f"Timed out waiting in queue '{queue_name}'",
            ) from exc
        finally:
            if acquired:
                semaphore.release()
        return

    token = uuid.uuid4().hex.encode("ascii")
    deadline = time.monotonic() + timeout_sec
    client = await get_redis_client()
    await client.rpush(queue_key, token)
    try:
        while True:
            head_tokens = await client.lrange(queue_key, 0, max(0, limit - 1))
            if isinstance(head_tokens, list) and token in head_tokens:
                break
            if time.monotonic() >= deadline:
                raise LockAcquireTimeout(
                    lock_key=queue_key,
                    resource_type=resource_type,
                    resource_id=rid,
                    backend="redis",
                    message=f"Timed out waiting in queue '{queue_name}'",
                )
            await asyncio.sleep(sleep_sec)
        yield
    finally:
        try:
            await client.lrem(queue_key, 1, token)
            if int(await client.llen(queue_key) or 0) == 0:
                await client.delete(queue_key)
        except Exception as exc:
            logger.warning(
                "background queue cleanup failed: queue_name={}, queue_key={}, error={}",
                queue_name,
                queue_key,
                str(exc),
            )


@contextlib.asynccontextmanager
async def queue_provision_jobs(
    *,
    queue_tag: str,
    max_concurrent: Optional[int] = None,
    wait_timeout: Optional[float] = None,
    poll_interval: Optional[float] = None,
) -> AsyncIterator[None]:
    normalized_tag = _normalize_component(str(queue_tag or "default").strip().lower())
    async with queue_background_job(
        queue_name=f"provision:{normalized_tag}",
        max_concurrent=max_concurrent or settings.PROVISION_QUEUE_MAX_CONCURRENT,
        wait_timeout=wait_timeout,
        poll_interval=poll_interval,
        resource_type="provision_queue",
        resource_id=normalized_tag,
    ):
        yield


@contextlib.asynccontextmanager
async def queue_api_mock_jobs(
    *,
    queue_tag: str,
    max_concurrent: Optional[int] = None,
    wait_timeout: Optional[float] = None,
    poll_interval: Optional[float] = None,
) -> AsyncIterator[None]:
    normalized_tag = _normalize_component(str(queue_tag or "default").strip().lower())
    async with queue_background_job(
        queue_name=f"api_mock:{normalized_tag}",
        max_concurrent=max_concurrent or settings.API_MOCK_QUEUE_MAX_CONCURRENT,
        wait_timeout=wait_timeout,
        poll_interval=poll_interval,
        resource_type="api_mock_queue",
        resource_id=normalized_tag,
    ):
        yield


@contextlib.asynccontextmanager
async def queue_change_proposal_jobs(
    *,
    workspace_id: str,
    max_concurrent: int = 1,
    wait_timeout: Optional[float] = None,
    poll_interval: Optional[float] = None,
) -> AsyncIterator[None]:
    normalized_workspace = _normalize_component(str(workspace_id or "unknown").strip().lower())
    async with queue_background_job(
        queue_name=f"change_proposal:{normalized_workspace}",
        max_concurrent=max_concurrent,
        wait_timeout=(
            settings.TASK_CHANGE_PROPOSAL_QUEUE_WAIT_TIMEOUT_SECONDS
            if wait_timeout is None
            else wait_timeout
        ),
        poll_interval=(
            settings.TASK_CHANGE_PROPOSAL_QUEUE_POLL_INTERVAL_SECONDS
            if poll_interval is None
            else poll_interval
        ),
        resource_type="change_proposal_queue",
        resource_id=normalized_workspace,
    ):
        yield


@contextlib.asynccontextmanager
async def queue_workspace_compare_jobs(
    *,
    workspace_id: str,
    max_concurrent: int = 1,
    wait_timeout: Optional[float] = None,
    poll_interval: Optional[float] = None,
) -> AsyncIterator[None]:
    """Serialize compare (git fetch + diff) operations per workspace."""
    normalized_workspace = _normalize_component(str(workspace_id or "unknown").strip().lower())
    async with queue_background_job(
        queue_name=f"workspace:{normalized_workspace}:compare",
        max_concurrent=max_concurrent,
        wait_timeout=(
            settings.TASK_CHANGE_PROPOSAL_QUEUE_WAIT_TIMEOUT_SECONDS
            if wait_timeout is None
            else wait_timeout
        ),
        poll_interval=(
            settings.TASK_CHANGE_PROPOSAL_QUEUE_POLL_INTERVAL_SECONDS
            if poll_interval is None
            else poll_interval
        ),
        resource_type="workspace_compare_queue",
        resource_id=normalized_workspace,
    ):
        yield


@contextlib.asynccontextmanager
async def queue_bootstrap_jobs(
    *,
    queue_tag: str = "task_cli_bootstrap",
    max_concurrent: Optional[int] = None,
    wait_timeout: Optional[float] = None,
    poll_interval: Optional[float] = None,
) -> AsyncIterator[None]:
    normalized_tag = _normalize_component(str(queue_tag or "task_cli_bootstrap").strip().lower())
    async with queue_background_job(
        queue_name=f"bootstrap:{normalized_tag}",
        max_concurrent=max_concurrent or settings.BOOTSTRAP_QUEUE_MAX_CONCURRENT,
        wait_timeout=wait_timeout,
        poll_interval=poll_interval,
        resource_type="bootstrap_queue",
        resource_id=normalized_tag,
    ):
        yield
