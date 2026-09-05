import asyncio
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
    async def test_task_ws_buffer_replay_kept_until_live_delivery(self):
        manager = ConnectionManager()
        task_id = "task-buffer"

        await manager.send_message_to_room(
            task_id,
            WSMessage(type="status", payload={"step": 1}),
        )
        self.assertEqual(len(manager.pending_payloads[task_id]), 1)

        ws = _FakeTextSocket()
        await manager.connect(ws, task_id)
        self.assertTrue(ws.accepted)
        await _wait_all(manager, ws)
        self.assertEqual(len(ws.sent_texts), 1)
        self.assertEqual(len(manager.pending_payloads[task_id]), 1)

        await manager.send_message_to_room(
            task_id,
            WSMessage(type="status", payload={"step": 2}),
        )
        await _wait_all(manager, ws)
        self.assertEqual(len(ws.sent_texts), 2)
        self.assertEqual(len(manager.pending_payloads[task_id]), 0)

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
        await manager.connect(slow, task_id)
        await manager.connect(fast, task_id)

        await manager.send_message_to_room(task_id, WSMessage(type="status", payload={"step": 1}))
        await _wait_all(manager, fast)

        # 慢客户端阻塞自身 sender，但快连接已送达，广播未阻塞
        self.assertEqual(len(fast.sent_texts), 1)
        self.assertEqual(len(slow.sent_texts), 0)

        if slow._release is not None:
            slow._release.set_result(None)
        await _wait_all(manager, fast, slow)
        self.assertEqual(len(slow.sent_texts), 1)

    async def test_api_mock_broadcast_safe_when_connection_set_mutates(self):
        manager = ApiMockConnectionManager()
        project_id = "project-1"
        ws1 = _MutatingJsonSocket()
        ws2 = _MutatingJsonSocket(mutate=lambda: manager.disconnect(ws1, project_id))
        # 单测禁用 Redis 扇出：避免 .env REDIS_ENABLED=true 时启动真实订阅循环
        with mock.patch("app.domains.api_mock.ws.api_mock_manager.settings.REDIS_ENABLED", False):
            await manager.connect(ws1, project_id, "u1")
            await manager.connect(ws2, project_id, "u2")

            await manager.broadcast(project_id, {"type": "event"})
            await _wait_all(manager, ws1, ws2)
        self.assertGreaterEqual(len(ws2.sent_json), 1)

    async def test_asset_discussion_broadcast_safe_when_connection_set_mutates(self):
        manager = AssetDiscussionConnectionManager()
        asset_id = "asset-1"
        ws1 = _MutatingJsonSocket()
        ws2 = _MutatingJsonSocket(mutate=lambda: manager.disconnect(ws1, asset_id))
        await manager.connect(ws1, asset_id, "u1")
        await manager.connect(ws2, asset_id, "u2")

        await manager.broadcast(asset_id, {"type": "event"})
        await _wait_all(manager, ws1, ws2)
        self.assertGreaterEqual(len(ws2.sent_json), 1)


if __name__ == "__main__":
    unittest.main()
