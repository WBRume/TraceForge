"""Single-worker room journal and replay/live hand-off implementation."""

from __future__ import annotations

import asyncio
import copy
import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from fastapi import WebSocket

from app.config import settings
from app.core.logging import get_logger
from app.domains.websocket.ws.connection import ConnectionState, OutboundConnection
from app.domains.websocket.ws.protocol import (
    CONTROL_FRAME_TYPES,
    NON_SEQUENCED_EVENT_TYPES,
    EventEnvelope,
    SERVER_EPOCH,
    control_frame,
    json_size,
)

logger = get_logger(__name__, category="task_execution")


def _int_setting(name: str, default: int, minimum: int = 1) -> int:
    return max(minimum, int(getattr(settings, name, default) or default))


def _float_setting(name: str, default: float, minimum: float = 0.1) -> float:
    return max(minimum, float(getattr(settings, name, default) or default))


@dataclass
class RoomJournal:
    room_key: str
    epoch: str = SERVER_EPOCH
    next_sequence: int = 1
    events: deque[EventEnvelope] = field(default_factory=deque)
    total_bytes: int = 0
    last_activity_at: float = field(default_factory=time.monotonic)

    @property
    def high_watermark(self) -> int:
        return self.next_sequence - 1

    @property
    def first_sequence(self) -> int:
        return self.events[0].sequence if self.events else self.next_sequence

    def append(
        self,
        *,
        event_type: str,
        payload: Any,
        aggregate_id: Optional[str] = None,
        aggregate_version: Optional[int] = None,
    ) -> EventEnvelope:
        envelope = EventEnvelope(
            room=self.room_key,
            epoch=self.epoch,
            sequence=self.next_sequence,
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            payload=copy.deepcopy(payload),
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
        )
        self.next_sequence += 1
        self.events.append(envelope)
        self.total_bytes += json_size(envelope.to_dict())
        self.last_activity_at = time.monotonic()
        max_events = _int_setting("WS_REPLAY_MAX_EVENTS", 1000)
        max_bytes = _int_setting("WS_REPLAY_MAX_BYTES", 4 * 1024 * 1024)
        while self.events and (len(self.events) > max_events or self.total_bytes > max_bytes):
            removed = self.events.popleft()
            self.total_bytes = max(0, self.total_bytes - json_size(removed.to_dict()))
        return envelope

    def can_replay(self, *, epoch: Optional[str], last_sequence: int) -> Tuple[bool, str]:
        if epoch != self.epoch:
            return False, "epoch_changed"
        if last_sequence < 0:
            return False, "cursor_ahead"
        if last_sequence > self.high_watermark:
            return False, "cursor_ahead"
        if self.events and last_sequence < self.first_sequence - 1:
            return False, "cursor_expired"
        return True, ""

    def snapshot_after(self, last_sequence: int, cutover_sequence: int) -> list[EventEnvelope]:
        return [
            event
            for event in self.events
            if last_sequence < event.sequence <= cutover_sequence
        ]


@dataclass
class RoomHub:
    room_key: str
    journal: RoomJournal
    connections: Dict[WebSocket, OutboundConnection] = field(default_factory=dict)
    last_activity_at: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class RoomHubRegistry:
    """Own all room journals and coordinate replay/live hand-off."""

    def __init__(self) -> None:
        self.rooms: Dict[str, Dict[WebSocket, OutboundConnection]] = {}
        self.presence: Dict[str, Dict[WebSocket, str]] = {}
        self._hubs: Dict[str, RoomHub] = {}
        self._sweeper_task: Optional[asyncio.Task] = None
        self._replay_events_total = 0
        self._resync_required_total: Dict[str, int] = {}
        self._slow_client_evictions = 0

    def _ensure_sweeper(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._sweeper_task is None or self._sweeper_task.done():
            self._sweeper_task = loop.create_task(self._sweep_loop())

    def _hub(self, room_key: str) -> RoomHub:
        hub = self._hubs.get(room_key)
        if hub is None:
            hub = RoomHub(room_key=room_key, journal=RoomJournal(room_key=room_key))
            self._hubs[room_key] = hub
            self.rooms[room_key] = hub.connections
            self.presence[room_key] = {}
        else:
            # Keep the compatibility views self-healing if a test or legacy
            # caller clears the public mapping directly.
            self.rooms.setdefault(room_key, hub.connections)
            self.presence.setdefault(room_key, {})
        hub.last_activity_at = time.monotonic()
        hub.journal.last_activity_at = hub.last_activity_at
        self._ensure_sweeper()
        return hub

    def _remove_connection(
        self,
        room_key: str,
        websocket: WebSocket,
        connection: Optional[OutboundConnection] = None,
    ) -> None:
        hub = self._hubs.get(room_key)
        if hub is None:
            return
        current = hub.connections.get(websocket)
        if current is not None and (connection is None or current is connection):
            hub.connections.pop(websocket, None)
            self.presence.get(room_key, {}).pop(websocket, None)
        if not hub.connections:
            hub.last_activity_at = time.monotonic()
            hub.journal.last_activity_at = hub.last_activity_at

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
        hub = self._hub(room_key)
        parsed_last = self._parse_sequence(last_sequence)
        connection = OutboundConnection(
            websocket,
            client_id=client_id,
            message_kind=message_kind,
            on_evicted=lambda conn: self._remove_connection(room_key, websocket, conn),
        )
        hub.connections[websocket] = connection
        if user_id is not None:
            self.presence.setdefault(room_key, {})[websocket] = str(user_id)

        replay_snapshot: list[EventEnvelope] = []
        cutover_sequence = hub.journal.high_watermark
        # A connection without a cursor is a first load. The client loads the
        # authoritative REST state before opening the socket, so it can start
        # live immediately. Explicit cursors are always validated.
        if epoch is None and parsed_last is None:
            connection.mark_state(ConnectionState.LIVE)
        else:
            valid, reason = hub.journal.can_replay(
                epoch=epoch,
                last_sequence=parsed_last if parsed_last is not None else -1,
            )
            if valid:
                connection.mark_state(ConnectionState.REPLAYING)
                connection.cutover_sequence = cutover_sequence
                replay_snapshot = hub.journal.snapshot_after(parsed_last or 0, cutover_sequence)
            else:
                connection.mark_state(ConnectionState.SYNCING)
                connection.barrier_sequence = cutover_sequence
                self._resync_required_total[reason] = self._resync_required_total.get(reason, 0) + 1

        await connection.start()
        if connection.state == ConnectionState.REPLAYING:
            connection.replay_task = asyncio.create_task(
                self._replay_connection(
                    hub,
                    websocket,
                    connection,
                    replay_snapshot,
                    parsed_last or 0,
                    cutover_sequence,
                )
            )
        elif connection.state == ConnectionState.SYNCING:
            self._send_control(
                connection,
                control_frame(
                    "resync_required",
                    epoch=hub.journal.epoch,
                    barrier_sequence=connection.barrier_sequence or 0,
                    reason=reason,
                ),
            )
        return connection

    @staticmethod
    def _parse_sequence(value: Optional[int]) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    def disconnect(self, room_key: str, websocket: WebSocket) -> Optional[OutboundConnection]:
        hub = self._hubs.get(room_key)
        if hub is None:
            return None
        connection = hub.connections.get(websocket)
        if connection is None:
            return None
        self._remove_connection(room_key, websocket, connection)
        connection.drop()
        return connection

    def _send_control(self, connection: OutboundConnection, payload: dict[str, Any]) -> bool:
        if connection.message_kind == "json":
            return connection.submit_json(payload)
        return connection.submit_text(json.dumps(payload, ensure_ascii=False, default=str))

    def _submit_or_remove(
        self,
        hub: RoomHub,
        websocket: WebSocket,
        connection: OutboundConnection,
        value: object,
        *,
        kind: str,
        sequence: Optional[int] = None,
    ) -> bool:
        if connection.state == ConnectionState.LIVE:
            accepted = connection.submit_frame(value, kind=kind)
        elif connection.state in {ConnectionState.REPLAYING, ConnectionState.SYNCING}:
            accepted = connection.defer_frame(value, kind=kind, sequence=sequence)
        else:
            accepted = False
        if not accepted:
            self._remove_connection(hub.room_key, websocket, connection)
        return accepted

    @staticmethod
    def _decode_text(text: str) -> tuple[str, Any, bool, Optional[str], Optional[int]]:
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return "message", text, True, None, None
        if not isinstance(data, dict):
            return "message", data, True, None, None
        event_type = str(data.get("type") or "message")
        if event_type in CONTROL_FRAME_TYPES or event_type in NON_SEQUENCED_EVENT_TYPES:
            return event_type, data, False, None, None
        payload = data.get("payload") if "payload" in data else data
        aggregate_id = data.get("id") or data.get("job_id")
        aggregate_version = data.get("version")
        return event_type, payload, True, str(aggregate_id) if aggregate_id else None, aggregate_version

    @staticmethod
    def _decode_json(payload: dict) -> tuple[str, Any, bool, Optional[str], Optional[int]]:
        event_type = str(payload.get("type") or "event")
        if event_type in CONTROL_FRAME_TYPES or event_type in NON_SEQUENCED_EVENT_TYPES:
            return event_type, payload, False, None, None
        aggregate = payload.get("job") if isinstance(payload.get("job"), dict) else payload
        aggregate_id = aggregate.get("id") if isinstance(aggregate, dict) else None
        version = aggregate.get("version") if isinstance(aggregate, dict) else None
        return event_type, payload, True, str(aggregate_id) if aggregate_id else None, version

    def publish_text(self, room_key: str, text: str, *, sequenced: Optional[bool] = None) -> int:
        event_type, payload, inferred, aggregate_id, aggregate_version = self._decode_text(text)
        return self._publish(
            room_key,
            event_type,
            payload,
            kind="text",
            sequenced=inferred if sequenced is None else sequenced,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
        )

    def publish_json(self, room_key: str, payload: dict, *, sequenced: Optional[bool] = None) -> int:
        event_type, event_payload, inferred, aggregate_id, aggregate_version = self._decode_json(payload)
        return self._publish(
            room_key,
            event_type,
            event_payload,
            kind="json",
            sequenced=inferred if sequenced is None else sequenced,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
        )

    def _publish(
        self,
        room_key: str,
        event_type: str,
        payload: Any,
        *,
        kind: str,
        sequenced: bool,
        aggregate_id: Optional[str],
        aggregate_version: Optional[int],
    ) -> int:
        hub = self._hub(room_key)
        if sequenced:
            envelope = hub.journal.append(
                event_type=event_type,
                payload=payload,
                aggregate_id=aggregate_id,
                aggregate_version=aggregate_version,
            )
            value: object = envelope.to_dict()
            sequence = envelope.sequence
        else:
            value = copy.deepcopy(payload)
            sequence = None
        delivered = 0
        for websocket, connection in list(hub.connections.items()):
            if self._submit_or_remove(
                hub,
                websocket,
                connection,
                value,
                kind=kind,
                sequence=sequence,
            ):
                delivered += 1
        return delivered

    async def _replay_connection(
        self,
        hub: RoomHub,
        websocket: WebSocket,
        connection: OutboundConnection,
        replay_snapshot: list[EventEnvelope],
        last_sequence: int,
        cutover_sequence: int,
    ) -> None:
        try:
            for envelope in replay_snapshot:
                await connection.wait_for_low_water()
                if connection.dropped:
                    return
                if not connection.submit_frame(envelope.to_dict(), kind=connection.message_kind):
                    return
                self._replay_events_total += 1

            # The synchronous publish path cannot interleave while this
            # critical section is running. New events therefore either appear
            # in deferred_live before the hand-off or in the live queue after it.
            current = hub.connections.get(websocket)
            if current is not connection or connection.dropped:
                return
            deferred = connection.drain_deferred()
            for kind, value, _size, sequence in deferred:
                if sequence is not None and sequence <= cutover_sequence:
                    continue
                if not connection.submit_frame(value, kind=kind):
                    return
            if not self._send_control(
                connection,
                control_frame(
                    "resume_ok",
                    epoch=hub.journal.epoch,
                    from_sequence=last_sequence + 1,
                    to_sequence=cutover_sequence,
                ),
            ):
                return
            connection.mark_state(ConnectionState.LIVE)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                f"WebSocket replay failed: room={hub.room_key} client_id={connection.client_id or ''}"
            )
            connection.evict("replay_failed")

    async def complete_resync(
        self,
        room_key: str,
        websocket: WebSocket,
        *,
        epoch: str,
        barrier_sequence: int,
    ) -> bool:
        hub = self._hubs.get(room_key)
        connection = hub.connections.get(websocket) if hub else None
        if hub is None or connection is None or connection.state != ConnectionState.SYNCING:
            return False
        if epoch != hub.journal.epoch or connection.barrier_sequence != int(barrier_sequence):
            return False
        deferred = connection.drain_deferred()
        for kind, value, _size, sequence in deferred:
            if sequence is not None and sequence <= int(barrier_sequence):
                continue
            if not connection.submit_frame(value, kind=kind):
                return False
        if not self._send_control(
            connection,
            control_frame(
                "resync_ok",
                epoch=hub.journal.epoch,
                from_sequence=int(barrier_sequence) + 1,
                to_sequence=hub.journal.high_watermark,
            ),
        ):
            return False
        connection.mark_state(ConnectionState.LIVE)
        return True

    def has_subscribers(self, room_key: str) -> bool:
        return bool(self.rooms.get(room_key))

    def online_users(self, room_key: str) -> list[str]:
        users: list[str] = []
        for user_id in self.presence.get(room_key, {}).values():
            if user_id not in users:
                users.append(user_id)
        return users

    async def _sweep_loop(self) -> None:
        interval = _float_setting("WS_REPLAY_SWEEP_INTERVAL_SECONDS", 60.0)
        try:
            while True:
                await asyncio.sleep(interval)
                await self.sweep()
        except asyncio.CancelledError:
            return

    async def sweep(self) -> int:
        ttl = _float_setting("WS_REPLAY_ROOM_TTL_SECONDS", 900.0)
        now = time.monotonic()
        removed = 0
        for room_key, hub in list(self._hubs.items()):
            if hub.connections:
                continue
            if now - max(hub.last_activity_at, hub.journal.last_activity_at) < ttl:
                continue
            if self._hubs.get(room_key) is not hub:
                continue
            self._hubs.pop(room_key, None)
            self.rooms.pop(room_key, None)
            self.presence.pop(room_key, None)
            removed += 1
        return removed

    def stats(self) -> dict[str, int]:
        connections = sum(len(room) for room in self.rooms.values())
        journal_events = sum(len(hub.journal.events) for hub in self._hubs.values())
        journal_bytes = sum(hub.journal.total_bytes for hub in self._hubs.values())
        sender_tasks = sum(
            1
            for room in self.rooms.values()
            for connection in room.values()
            if connection.sender_task and not connection.sender_task.done()
        )
        replay_tasks = sum(
            1
            for room in self.rooms.values()
            for connection in room.values()
            if connection.replay_task and not connection.replay_task.done()
        )
        return {
            "ws_active_rooms": len(self._hubs),
            "ws_active_connections": connections,
            "ws_journal_events": journal_events,
            "ws_journal_bytes": journal_bytes,
            "ws_sender_tasks": sender_tasks,
            "ws_replay_tasks": replay_tasks,
            "ws_slow_client_evictions_total": self._slow_client_evictions,
            "ws_replay_events_total": self._replay_events_total,
            "ws_resync_required_total": sum(self._resync_required_total.values()),
        }

    async def shutdown(self) -> None:
        if self._sweeper_task is not None:
            self._sweeper_task.cancel()
            await asyncio.gather(self._sweeper_task, return_exceptions=True)
            self._sweeper_task = None
        connections = [connection for room in self.rooms.values() for connection in room.values()]
        replay_tasks = [
            connection.replay_task
            for connection in connections
            if connection.replay_task and not connection.replay_task.done()
        ]
        for connection in connections:
            if connection.replay_task and not connection.replay_task.done():
                connection.replay_task.cancel()
        if replay_tasks:
            await asyncio.gather(*replay_tasks, return_exceptions=True)
        sender_tasks = [
            connection.sender_task
            for connection in connections
            if connection.sender_task and not connection.sender_task.done()
        ]
        for connection in connections:
            connection.evict("shutdown")
            if connection.close_task is not None:
                await connection.close_task
        if sender_tasks:
            await asyncio.gather(*sender_tasks, return_exceptions=True)
        self._hubs.clear()
        self.rooms.clear()
        self.presence.clear()

    def reset(self) -> None:
        """Synchronous test/process reset; production uses ``shutdown``."""
        if self._sweeper_task is not None and not self._sweeper_task.done():
            self._sweeper_task.cancel()
        self._sweeper_task = None
        for room in list(self.rooms.values()):
            for connection in list(room.values()):
                connection.evict("reset")
        self._hubs.clear()
        self.rooms.clear()
        self.presence.clear()
