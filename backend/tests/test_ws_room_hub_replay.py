"""Room journal invariants for disconnect/replay/live hand-off."""

from __future__ import annotations

import asyncio
import json
from unittest import IsolatedAsyncioTestCase, mock

from app.config import settings
from app.domains.websocket.ws.connection import ConnectionRegistry, OutboundConnection


class _Socket:
    def __init__(self) -> None:
        self.sent_texts: list[str] = []
        self.closed_codes: list[int] = []

    async def send_text(self, payload: str) -> None:
        self.sent_texts.append(payload)

    async def close(self, code: int = 1000) -> None:
        self.closed_codes.append(code)


async def _complete_initial_sync(registry: ConnectionRegistry, room_key: str, socket: _Socket, connection: OutboundConnection) -> None:
    await connection.wait_flushed()
    control = json.loads(socket.sent_texts[0])
    assert control["type"] == "resync_required"
    assert await registry.complete_resync(
        room_key,
        socket,
        epoch=control["epoch"],
        barrier_sequence=control["barrier_sequence"],
    )
    await connection.wait_flushed()


class RoomJournalReplayTest(IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        # Each test owns its registry, but allow all sender/replay tasks to
        # finish before IsolatedAsyncioTestCase closes the loop.
        registry = getattr(self, "registry", None)
        if registry is not None:
            await registry.shutdown()

    async def test_offline_event_replays_once_without_client_buffer(self) -> None:
        self.registry = ConnectionRegistry()
        first = _Socket()
        connection = await self.registry.connect("task:test", first, client_id="tab-1")
        await _complete_initial_sync(self.registry, "task:test", first, connection)
        self.registry.broadcast_text("task:test", json.dumps({"type": "status", "payload": {"step": 1}}))
        await connection.wait_flushed()
        first_frame = next(json.loads(frame) for frame in first.sent_texts if json.loads(frame).get("type") == "event")

        self.registry.disconnect("task:test", first)
        self.registry.broadcast_text("task:test", json.dumps({"type": "status", "payload": {"step": 2}}))

        second = _Socket()
        replayed = await self.registry.connect(
            "task:test",
            second,
            client_id="tab-1",
            epoch=first_frame["epoch"],
            last_sequence=first_frame["sequence"],
        )
        await asyncio.wait_for(replayed.replay_task, timeout=2)
        await replayed.wait_flushed()

        event_frames = [json.loads(frame) for frame in second.sent_texts if json.loads(frame).get("type") == "event"]
        self.assertEqual([frame["sequence"] for frame in event_frames], [2])
        self.assertEqual(event_frames[0]["payload"]["step"], 2)
        self.assertFalse(hasattr(self.registry, "client_replay"))

    async def test_live_event_during_replay_is_delivered_after_replay(self) -> None:
        self.registry = ConnectionRegistry()
        first = _Socket()
        connection = await self.registry.connect("task:handoff", first, client_id="tab-1")
        await _complete_initial_sync(self.registry, "task:handoff", first, connection)
        self.registry.broadcast_text("task:handoff", json.dumps({"type": "status", "payload": {"step": 1}}))
        await connection.wait_flushed()
        first_frame = next(json.loads(frame) for frame in first.sent_texts if json.loads(frame).get("type") == "event")
        self.registry.disconnect("task:handoff", first)
        self.registry.broadcast_text("task:handoff", json.dumps({"type": "status", "payload": {"step": 2}}))

        gate = asyncio.Event()
        original_wait = OutboundConnection.wait_for_low_water

        async def delayed_wait(current: OutboundConnection) -> None:
            await gate.wait()
            await original_wait(current)

        second = _Socket()
        with mock.patch.object(OutboundConnection, "wait_for_low_water", new=delayed_wait):
            replayed = await self.registry.connect(
                "task:handoff",
                second,
                client_id="tab-1",
                epoch=first_frame["epoch"],
                last_sequence=first_frame["sequence"],
            )
            self.registry.broadcast_text("task:handoff", json.dumps({"type": "status", "payload": {"step": 3}}))
            gate.set()
            await asyncio.wait_for(replayed.replay_task, timeout=2)
        await replayed.wait_flushed()

        frames = [json.loads(frame) for frame in second.sent_texts]
        self.assertEqual(
            [frame["sequence"] for frame in frames if frame.get("type") == "event"],
            [2, 3],
        )
        self.assertEqual([frame["type"] for frame in frames], ["event", "event", "resume_ok"])

    async def test_expired_cursor_requires_resync_and_journal_survives_live_delivery(self) -> None:
        self.registry = ConnectionRegistry()
        with mock.patch.object(settings, "WS_REPLAY_MAX_EVENTS", 1):
            socket = _Socket()
            connection = await self.registry.connect("task:expired", socket, client_id="tab-1")
            await _complete_initial_sync(self.registry, "task:expired", socket, connection)
            self.registry.broadcast_text("task:expired", json.dumps({"type": "status", "payload": {"step": 1}}))
            self.registry.broadcast_text("task:expired", json.dumps({"type": "status", "payload": {"step": 2}}))
            await connection.wait_flushed()
            first_frame = next(json.loads(frame) for frame in socket.sent_texts if json.loads(frame).get("type") == "event")
            journal = self.registry._hub_registry._hubs["task:expired"].journal
            self.assertEqual([event.sequence for event in journal.events], [2])

            reconnect = _Socket()
            connection2 = await self.registry.connect(
                "task:expired",
                reconnect,
                client_id="tab-1",
                epoch=first_frame["epoch"],
                last_sequence=0,
            )
            await connection2.wait_flushed()

        self.assertEqual(json.loads(reconnect.sent_texts[0])["type"], "resync_required")
        self.assertEqual(json.loads(reconnect.sent_texts[0])["reason"], "cursor_expired")
