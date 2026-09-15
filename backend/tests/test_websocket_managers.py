import asyncio
import json
import os
import sys
import unittest
from unittest import mock


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.ai.schemas.websocket import WSMessage  # noqa: E402
from app.domains.api_mock.ws.api_mock_manager import ApiMockConnectionManager  # noqa: E402
from app.domains.asset.ws.asset_discussion_manager import AssetDiscussionConnectionManager  # noqa: E402
from app.domains.websocket.ws.manager import ConnectionManager  # noqa: E402


class _FakeTextSocket:
    def __init__(self):
        self.accepted = False
        self.sent_texts = []

    async def accept(self):
        self.accepted = True

    async def send_text(self, payload: str):
        self.sent_texts.append(payload)


class _MutatingJsonSocket:
    def __init__(self, mutate=None):
        self.accepted = False
        self.sent_json = []
        self._mutate = mutate

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        if self._mutate:
            self._mutate()
        self.sent_json.append(payload)


async def _wait_all(manager, *sockets):
    for socket in sockets:
        for room in manager.registry.rooms.values():
            connection = room.get(socket)
            if connection is not None:
                await asyncio.wait_for(connection.wait_flushed(), timeout=2)
                break


class WebSocketManagerTest(unittest.IsolatedAsyncioTestCase):
    async def test_task_ws_journal_replay_is_not_cleared_by_live_delivery(self):
        manager = ConnectionManager()
        task_id = "task-buffer"

        first_ws = _FakeTextSocket()
        first_connection = await manager.connect(first_ws, task_id)
        await first_connection.wait_flushed()
        initial = json.loads(first_ws.sent_texts[0])
        self.assertEqual(initial["type"], "resync_required")
        self.assertTrue(
            await manager.complete_resync(
                first_ws,
                task_id,
                epoch=initial["epoch"],
                barrier_sequence=initial["barrier_sequence"],
            )
        )
        await manager.send_message_to_room(
            task_id,
            WSMessage(type="status", payload={"step": 1}),
        )
        self.assertTrue(first_ws.accepted)
        await _wait_all(manager, first_ws)
        self.assertEqual(len(first_ws.sent_texts), 3)
        first = next(json.loads(frame) for frame in first_ws.sent_texts if json.loads(frame).get("type") == "event")
        self.assertEqual(first["type"], "event")
        manager.disconnect(first_ws, task_id)

        # This event is offline; reconnect with the explicit cursor to ask for
        # the room journal rather than relying on a user-scoped buffer.
        await manager.send_message_to_room(
            task_id,
            WSMessage(type="status", payload={"step": 2}),
        )
        ws = _FakeTextSocket()
        await manager.connect(
            ws,
            task_id,
            epoch=first["epoch"],
            last_sequence=first["sequence"],
        )
        await _wait_all(manager, ws)
        await asyncio.sleep(0)
        await _wait_all(manager, ws)

        self.assertEqual(len(ws.sent_texts), 2)
        journal = manager.registry._hub_registry._hubs["task:task-buffer"].journal
        self.assertEqual([event.sequence for event in journal.events], [1, 2])
        self.assertFalse(hasattr(manager, "pending_payloads"))

    async def test_task_ws_slow_client_does_not_block_room_broadcast(self):
        manager = ConnectionManager()
        task_id = "task-slow"

        class _BlockingSocket:
            def __init__(self):
                self.accepted = False
                self.sent_texts = []
                self._release = None

            async def accept(self):
                self.accepted = True

            async def send_text(self, payload: str):
                if self._release is None:
                    loop = asyncio.get_running_loop()
                    self._release = loop.create_future()
                await self._release
                self.sent_texts.append(payload)

        slow = _BlockingSocket()
        fast = _FakeTextSocket()
        slow_connection = await manager.connect(slow, task_id)
        fast_connection = await manager.connect(fast, task_id)
        slow._release = asyncio.get_running_loop().create_future()
        slow._release.set_result(None)
        for socket, connection in ((slow, slow_connection), (fast, fast_connection)):
            await connection.wait_flushed()
            initial = json.loads(socket.sent_texts[0])
            self.assertTrue(
                await manager.complete_resync(
                    socket,
                    task_id,
                    epoch=initial["epoch"],
                    barrier_sequence=initial["barrier_sequence"],
                )
            )
            await connection.wait_flushed()
        slow._release = asyncio.get_running_loop().create_future()

        await manager.send_message_to_room(task_id, WSMessage(type="status", payload={"step": 1}))
        await _wait_all(manager, fast)

        # 慢客户端阻塞自身 sender，但快连接已送达，广播未阻塞
        self.assertEqual(json.loads(fast.sent_texts[-1])["type"], "event")
        self.assertEqual(len(slow.sent_texts), 2)

        if slow._release is not None:
            slow._release.set_result(None)
        await _wait_all(manager, fast, slow)
        self.assertEqual(len(slow.sent_texts), 3)

    async def test_api_mock_broadcast_safe_when_connection_set_mutates(self):
        manager = ApiMockConnectionManager()
        project_id = "project-1"
        ws1 = _MutatingJsonSocket()
        ws2 = _MutatingJsonSocket()
        conn1 = await manager.connect(ws1, project_id, "u1")
        conn2 = await manager.connect(ws2, project_id, "u2")
        for socket, connection in ((ws1, conn1), (ws2, conn2)):
            await connection.wait_flushed()
            control = socket.sent_json[0]
            self.assertTrue(
                await manager.complete_resync(
                    socket,
                    project_id,
                    epoch=control["epoch"],
                    barrier_sequence=control["barrier_sequence"],
                )
            )
        ws2._mutate = lambda: manager.disconnect(ws1, project_id)

        await manager.broadcast(project_id, {"type": "event"})
        await _wait_all(manager, ws1, ws2)
        self.assertGreaterEqual(len(ws2.sent_json), 1)

    async def test_asset_discussion_broadcast_safe_when_connection_set_mutates(self):
        manager = AssetDiscussionConnectionManager()
        asset_id = "asset-1"
        ws1 = _MutatingJsonSocket()
        ws2 = _MutatingJsonSocket()
        conn1 = await manager.connect(ws1, asset_id, "u1")
        conn2 = await manager.connect(ws2, asset_id, "u2")
        for socket, connection in ((ws1, conn1), (ws2, conn2)):
            await connection.wait_flushed()
            control = socket.sent_json[0]
            self.assertTrue(
                await manager.complete_resync(
                    socket,
                    asset_id,
                    epoch=control["epoch"],
                    barrier_sequence=control["barrier_sequence"],
                )
            )
        ws2._mutate = lambda: manager.disconnect(ws1, asset_id)

        await manager.broadcast(asset_id, {"type": "event"})
        await _wait_all(manager, ws1, ws2)
        self.assertGreaterEqual(len(ws2.sent_json), 1)


if __name__ == "__main__":
    unittest.main()
