"""
Redis client utilities for infrastructure modules.
"""

from __future__ import annotations

import asyncio
import weakref
from typing import Any, Optional

from app.config import settings


_REDIS_CLIENTS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Any]" = weakref.WeakKeyDictionary()
_REDIS_CLIENT_LOCK = asyncio.Lock()


def _load_redis_asyncio_module() -> Any:
    try:
        import redis.asyncio as redis_asyncio  # type: ignore
    except Exception as exc:  # pragma: no cover - import failure path
        raise RuntimeError("redis package is required for redis lock backend") from exc
    return redis_asyncio


async def get_redis_client() -> Any:
    loop = asyncio.get_running_loop()
    cached_client = _REDIS_CLIENTS.get(loop)
    if cached_client is not None:
        return cached_client

    async with _REDIS_CLIENT_LOCK:
        cached_client = _REDIS_CLIENTS.get(loop)
        if cached_client is not None:
            return cached_client

        redis_asyncio = _load_redis_asyncio_module()
        client = redis_asyncio.from_url(
            str(settings.REDIS_URL or "").strip(),
            socket_timeout=float(settings.REDIS_SOCKET_TIMEOUT_SECONDS or 3.0),
            socket_connect_timeout=float(settings.REDIS_CONNECT_TIMEOUT_SECONDS or 3.0),
            decode_responses=False,
            health_check_interval=30,
        )
        _REDIS_CLIENTS[loop] = client
        return client


async def ping_redis_client() -> bool:
    client = await get_redis_client()
    return bool(await client.ping())


async def close_redis_client() -> None:
    async with _REDIS_CLIENT_LOCK:
        clients = list(_REDIS_CLIENTS.values())
        _REDIS_CLIENTS.clear()

    for client in clients:
        if client is None:
            continue
        try:
            close = getattr(client, "aclose", None)
            if callable(close):
                await close()
                continue

            close = getattr(client, "close", None)
            if callable(close):
                result = close()
                if asyncio.iscoroutine(result):
                    await result
        except RuntimeError as exc:
            if "Event loop is closed" in str(exc):
                continue
            raise
