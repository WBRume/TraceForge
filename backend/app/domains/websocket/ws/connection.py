"""Shared per-connection sender and room-registry facade.

The sender owns all writes to a WebSocket. Replay state is deliberately not
stored here: recovery is room-scoped and is implemented by ``RoomHubRegistry``
in :mod:`room_hub`, so two tabs for one user can never consume one another's
server-side buffer.
"""

from __future__ import annotations

import asyncio
import json
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from fastapi import WebSocket

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__, category="task_execution")

_QueueItem = Tuple[str, object, int]


def _ws_send_timeout() -> float:
    return max(0.5, float(getattr(settings, "WS_SEND_TIMEOUT_SECONDS", 5.0) or 5.0))


def _queue_size() -> int:
    return max(1, int(getattr(settings, "WS_OUTBOUND_QUEUE_SIZE", 256) or 256))


def _max_bytes() -> int:
    return max(1, int(getattr(settings, "WS_OUTBOUND_MAX_BYTES", 1024 * 1024) or 1024 * 1024))


def _replay_timeout() -> float:
    return max(0.1, float(getattr(settings, "WS_REPLAY_TIMEOUT_SECONDS", 30.0) or 30.0))


def _shutdown_timeout() -> float:
    return max(0.1, float(getattr(settings, "WS_SHUTDOWN_TIMEOUT_SECONDS", 5.0) or 5.0))


class ConnectionState(str, Enum):
    CONNECTING = "CONNECTING"
    SYNCING = "SYNCING"
    REPLAYING = "REPLAYING"
    LIVE = "LIVE"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class OutboundConnection:
    """One WebSocket's bounded outbound queue and sender task."""

    def __init__(
        self,
        websocket: WebSocket,
        *,
        queue_size: Optional[int] = None,
        max_bytes: Optional[int] = None,
        client_id: Optional[str] = None,
        message_kind: str = "text",
        on_evicted=None,
        generation: int = 0,
    ) -> None:
        self.websocket = websocket
        self.client_id = str(client_id or "") or None
        self.generation = int(generation or 0)
        self.message_kind = message_kind if message_kind in {"text", "json"} else "text"
        self._queue: asyncio.Queue[Optional[_QueueItem]] = asyncio.Queue(
            maxsize=max(1, int(queue_size if queue_size is not None else _queue_size()))
        )
        self._max_bytes = max(1, int(max_bytes if max_bytes is not None else _max_bytes()))
        self._pending_bytes = 0
        self._sender_task: Optional[asyncio.Task] = None
        self._close_task: Optional[asyncio.Task] = None
        self._queue_low_water = asyncio.Event()
        self._queue_low_water.set()
        self._closed = False
        self.dropped = False
        self.state = ConnectionState.CONNECTING
        self.barrier_sequence: Optional[int] = None
        self.cutover_sequence: Optional[int] = None
        self.replay_task: Optional[asyncio.Task] = None
        self._deferred_live: list[Tuple[str, object, int, Optional[int]]] = []
        self._deferred_bytes = 0
        self._max_deferred_events = max(
            1, int(getattr(settings, "WS_DEFERRED_LIVE_MAX_EVENTS", 256) or 256)
        )
        self._max_deferred_bytes = max(
            1, int(getattr(settings, "WS_DEFERRED_LIVE_MAX_BYTES", 1024 * 1024) or 1024 * 1024)
        )
        self._on_evicted = on_evicted
        self.eviction_reason: Optional[str] = None

    @property
    def sender_task(self) -> Optional[asyncio.Task]:
        return self._sender_task

    @property
    def close_task(self) -> Optional[asyncio.Task]:
        return self._close_task

    @property
    def pending_bytes(self) -> int:
        return self._pending_bytes

    @property
    def deferred_bytes(self) -> int:
        return self._deferred_bytes

    @property
    def deferred_count(self) -> int:
        return len(self._deferred_live)

    async def start(self) -> None:
        if self._sender_task is None or self._sender_task.done():
            self._sender_task = asyncio.create_task(self._sender_loop())

    def mark_state(self, state: ConnectionState) -> None:
        if self.state in {ConnectionState.CLOSING, ConnectionState.CLOSED}:
            return
        self.state = state

    def submit_text(self, text: str) -> bool:
        return self._submit("text", text, len(str(text).encode("utf-8", errors="ignore")))

    def submit_json(self, payload: dict) -> bool:
        text = json.dumps(payload, ensure_ascii=False, default=str)
        return self._submit("json", payload, len(text.encode("utf-8", errors="ignore")))

    def submit_frame(self, value: object, *, kind: Optional[str] = None) -> bool:
        selected_kind = kind or self.message_kind
        if selected_kind == "json" and isinstance(value, dict):
            return self.submit_json(value)
        if selected_kind == "json":
            return self.submit_text(json.dumps(value, ensure_ascii=False, default=str))
        return self.submit_text(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str))

    def defer_frame(self, value: object, *, kind: Optional[str] = None, sequence: Optional[int] = None) -> bool:
        """Hold a frame until replay/resync hands over to live delivery."""
        if self._closed or self.dropped:
            return False
        selected_kind = kind or self.message_kind
        if selected_kind == "json" and isinstance(value, dict):
            size = len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8", errors="ignore"))
            stored_value = value
        else:
            stored_value = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
            size = len(str(stored_value).encode("utf-8", errors="ignore"))
        if size > self._max_deferred_bytes or (
            len(self._deferred_live) >= self._max_deferred_events
            or self._deferred_bytes + size > self._max_deferred_bytes
        ):
            self.evict("deferred_live_overflow")
            return False
        self._deferred_live.append((selected_kind, stored_value, size, sequence))
        self._deferred_bytes += size
        return True

    def drain_deferred(self) -> list[Tuple[str, object, int, Optional[int]]]:
        items = list(self._deferred_live)
        self._deferred_live.clear()
        self._deferred_bytes = 0
        return items

    async def wait_for_low_water(self) -> None:
        """Wait for this connection only; never hold a room lock here."""
        if self._closed or self.dropped:
            return
        if self._queue.qsize() < max(1, self._queue.maxsize // 2) and self._pending_bytes < self._max_bytes // 2:
            return
        try:
            await asyncio.wait_for(self._queue_low_water.wait(), timeout=_replay_timeout())
        except asyncio.TimeoutError:
            self.evict("replay_timeout")

    def _submit(self, kind: str, value: object, size: int) -> bool:
        if self._closed or self.dropped:
            return False
        if size > self._max_bytes:
            logger.warning(
                f"WS outbound message exceeds byte limit ({size} > {self._max_bytes}), evicting connection"
            )
            self.evict("message_over_byte_limit")
            return False
        try:
            self._queue.put_nowait((kind, value, size))
        except asyncio.QueueFull:
            logger.warning("WS outbound queue full, evicting slow client")
            self.evict("queue_full")
            return False
        self._pending_bytes += size
        if self._queue.qsize() >= max(1, self._queue.maxsize // 2) or self._pending_bytes >= self._max_bytes // 2:
            self._queue_low_water.clear()
        if self._pending_bytes > self._max_bytes:
            logger.warning(
                f"WS outbound pending bytes {self._pending_bytes} exceed {self._max_bytes}, evicting slow client"
            )
            self.evict("pending_bytes_over_limit")
            return False
        return True

    async def wait_flushed(self) -> None:
        if self._closed or self.dropped:
            return
        await self._queue.join()

    def drop(self) -> None:
        self.evict("dropped")

    def evict(self, reason: str) -> None:
        already = self.dropped
        if self.eviction_reason is None:
            self.eviction_reason = str(reason)
        self.dropped = True
        self._closed = True
        self.state = ConnectionState.CLOSED
        if self._sender_task is not None and not self._sender_task.done():
            if self._sender_task is not asyncio.current_task():
                self._sender_task.cancel()
        if self.replay_task is not None and not self.replay_task.done():
            if self.replay_task is not asyncio.current_task():
                self.replay_task.cancel()
        if already:
            return
        self._close_socket(code=1001)
        callback = self._on_evicted
        if callback is not None:
            try:
                callback(self)
            except Exception:
                logger.exception("WS evict callback failed")
        logger.info(
            f"WebSocket connection evicted: reason={reason} client_id={self.client_id or ''}"
        )

    def _close_socket(self, code: int) -> None:
        close = getattr(self.websocket, "close", None)
        if not callable(close):
            return
        state = getattr(self.websocket, "client_state", None)
        if state is not None and getattr(state, "name", "") == "DISCONNECTED":
            return

        async def _close_guarded() -> None:
            try:
                await close(code=code)
            except Exception:
                pass

        try:
            self._close_task = asyncio.get_running_loop().create_task(_close_guarded())
        except RuntimeError:
            pass

    async def close(self) -> None:
        self._closed = True
        self.state = ConnectionState.CLOSING
        if self.replay_task is not None and not self.replay_task.done():
            if self.replay_task is not asyncio.current_task():
                self.replay_task.cancel()
                await asyncio.gather(self.replay_task, return_exceptions=True)
        task = self._sender_task
        if task is None or task.done():
            self.state = ConnectionState.CLOSED
            return
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self.state = ConnectionState.CLOSED
        if self._close_task is not None:
            try:
                await asyncio.wait_for(self._close_task, timeout=_shutdown_timeout())
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._close_task.cancel()
                await asyncio.gather(self._close_task, return_exceptions=True)

    async def _send(self, kind: str, value: object) -> None:
        if kind == "json":
            send_json = getattr(self.websocket, "send_json", None)
            if callable(send_json):
                await send_json(value)
                return
            await self.websocket.send_text(json.dumps(value, ensure_ascii=False, default=str))
            return
        await self.websocket.send_text(str(value))

    async def _sender_loop(self) -> None:
        timeout = _ws_send_timeout()
        try:
            while True:
                item = await self._queue.get()
                kind, value, size = item if item is not None else ("", None, 0)
                try:
                    if item is None:
                        return
                    try:
                        await asyncio.wait_for(self._send(kind, value), timeout=timeout)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.warning(f"WS send failed/timeout ({exc}), evicting connection")
                        self.evict("send_failed")
                        return
                finally:
                    self._pending_bytes = max(0, self._pending_bytes - size)
                    self._queue.task_done()
                    if self._queue.qsize() < max(1, self._queue.maxsize // 2) and self._pending_bytes < self._max_bytes // 2:
                        self._queue_low_water.set()
        except asyncio.CancelledError:
            raise
        finally:
            if not self.dropped:
                self.state = ConnectionState.CLOSED


class ConnectionRegistry:
    """Compatibility facade over the shared :class:`RoomHubRegistry`."""

    def __init__(self, **kwargs: Any) -> None:
        from app.domains.websocket.ws.room_hub import RoomHubRegistry

        self._hub_registry = RoomHubRegistry(**kwargs)

    @property
    def rooms(self) -> Dict[str, Dict[WebSocket, OutboundConnection]]:
        return self._hub_registry.rooms

    @property
    def presence(self) -> Dict[str, Dict[WebSocket, str]]:
        return self._hub_registry.presence

    async def connect(
        self,
        room_key: str,
        websocket: WebSocket,
        *,
        user_id: Optional[str] = None,
        client_id: Optional[str] = None,
        epoch: Optional[str] = None,
        last_sequence: Optional[int] = None,
        message_kind: str = "text",
    ) -> OutboundConnection:
        return await self._hub_registry.connect(
            room_key,
            websocket,
            user_id=user_id,
            client_id=client_id,
            epoch=epoch,
            last_sequence=last_sequence,
            message_kind=message_kind,
        )

    def disconnect(self, room_key: str, websocket: WebSocket) -> Optional[OutboundConnection]:
        return self._hub_registry.disconnect(room_key, websocket)

    async def complete_resync(
        self,
        room_key: str,
        websocket: WebSocket,
        *,
        epoch: str,
        barrier_sequence: int,
    ) -> bool:
        return await self._hub_registry.complete_resync(
            room_key,
            websocket,
            epoch=epoch,
            barrier_sequence=barrier_sequence,
        )

    def broadcast_text(self, room_key: str, text: str, *, sequenced: Optional[bool] = None) -> int:
        return self._hub_registry.publish_text(room_key, text, sequenced=sequenced)

    def broadcast_json(self, room_key: str, payload: dict, *, sequenced: Optional[bool] = None) -> int:
        return self._hub_registry.publish_json(room_key, payload, sequenced=sequenced)

    def has_subscribers(self, room_key: str) -> bool:
        return self._hub_registry.has_subscribers(room_key)

    def online_users(self, room_key: str) -> List[str]:
        return self._hub_registry.online_users(room_key)

    async def sweep(self) -> int:
        return await self._hub_registry.sweep()

    async def shutdown(self) -> None:
        await self._hub_registry.shutdown()

    def reset(self) -> None:
        self._hub_registry.reset()

    def stats(self) -> dict[str, int]:
        return self._hub_registry.stats()
