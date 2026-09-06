"""WS evict 闭环：发送超时、背压淘汰关 socket、按 client 重放缓冲。"""

import asyncio
import json
import os
import sys
import unittest
from unittest import mock

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.config import settings  # noqa: E402
from app.domains.websocket.ws.connection import (  # noqa: E402
    ConnectionRegistry,
    OutboundConnection,
)
from starlette.websockets import WebSocketState  # noqa: E402


class _FakeSocket:
    def __init__(self, *, fail=False, block_event: asyncio.Event = None):
        self.sent_texts = []
        self.closed_codes = []
        self.fail = fail
        self._block_event = block_event

    async def send_text(self, payload: str):
        if self._block_event is not None:
            await self._block_event.wait()
        if self.fail:
            raise RuntimeError("gone")
        self.sent_texts.append(payload)

    async def close(self, code: int = 1000):
        self.closed_codes.append(code)


async def _flush_all(registry, room_key):
    room = registry.rooms.get(room_key, {})
    for connection in list(room.values()):
        await asyncio.wait_for(connection.wait_flushed(), timeout=2)


class _BrokenCloseSocket(_FakeSocket):
    """模拟 uvicorn 拒绝重复 close：close 抛 RuntimeError 且连接已不可用。"""

    def __init__(self):
        super().__init__(fail=True)
        self.close_attempts = []

    async def close(self, code: int = 1000):
        self.close_attempts.append(code)
        raise RuntimeError(
            "Unexpected ASGI message 'websocket.close', after sending "
            "'websocket.close' or response already completed."
        )


class EvictClosureTest(unittest.IsolatedAsyncioTestCase):
    async def test_send_timeout_evicts_closes_socket_and_removes_from_registry(self):
        registry = ConnectionRegistry()
        socket = _FakeSocket(block_event=asyncio.Event())  # send 永久挂起
        with mock.patch.object(settings, "WS_SEND_TIMEOUT_SECONDS", 0.2):
            await registry.connect("room-evict", socket, user_id="u-slow")
            # 未确认字节未超限，但 send 超时应触发 evict 闭环
            registry.broadcast_text("room-evict", "x" * 10)
            await asyncio.sleep(0.6)

        self.assertTrue(registry.rooms.get("room-evict", {}) == {})
        self.assertEqual(socket.closed_codes, [1001])

    async def test_queue_full_evicts_only_slow_connection(self):
        registry = ConnectionRegistry()
        fast, slow = _FakeSocket(), _FakeSocket(block_event=asyncio.Event())
        fast_conn = await registry.connect("room-2", fast, user_id="u-fast")
        slow_conn = await registry.connect("room-2", slow, user_id="u-slow")
        # 人为压缩慢连接队列容量
        slow_conn._queue._maxsize = 1  # type: ignore[attr-defined]

        delivered = 0
        for i in range(6):
            delivered += registry.broadcast_text("room-2", f"m{i}")
        await _flush_all(registry, "room-2")

        self.assertGreaterEqual(delivered, 1)
        self.assertTrue(slow_conn.dropped)
        self.assertEqual(slow.closed_codes, [1001])
        self.assertNotIn("u-slow", [u for u in registry.online_users("room-2")])
        self.assertFalse(fast_conn.dropped)
        if slow._block_event is not None:
            slow._block_event.set()

    async def test_send_failure_evicts_closes_socket(self):
        registry = ConnectionRegistry()
        socket = _FakeSocket(fail=True)
        connection = await registry.connect("room-3", socket, user_id="u-dead")
        registry.broadcast_text("room-3", "hello")
        await asyncio.wait_for(connection.sender_task, timeout=2)

        self.assertTrue(connection.dropped)
        self.assertEqual(socket.closed_codes, [1001])
        self.assertFalse(registry.has_subscribers("room-3"))

    async def test_evict_close_failure_is_swallowed(self):
        """close 被拒（重复 close/已断开）不得留下未取回的 Task 异常。"""
        registry = ConnectionRegistry()
        socket = _BrokenCloseSocket()
        connection = await registry.connect("room-4", socket, user_id="u-broken")
        registry.broadcast_text("room-4", "hello")
        await asyncio.wait_for(connection.sender_task, timeout=2)

        self.assertTrue(connection.dropped)
        self.assertFalse(registry.has_subscribers("room-4"))
        # fire-and-forget 关闭任务的异常必须被就地吞掉
        if connection._close_task is not None:
            await connection._close_task
            self.assertIsNone(connection._close_task.exception())
        self.assertEqual(socket.close_attempts, [1001])

    async def test_evict_skips_close_when_client_already_disconnected(self):
        registry = ConnectionRegistry()
        socket = _FakeSocket(fail=True)
        socket.client_state = WebSocketState.DISCONNECTED  # 端点已收到断开
        connection = await registry.connect("room-5", socket, user_id="u-gone")
        connection.evict("send_failed")

        self.assertTrue(connection.dropped)
        self.assertEqual(socket.closed_codes, [])  # 不再对已断开的连接发 close
        self.assertFalse(registry.has_subscribers("room-5"))

    async def test_double_evict_closes_socket_once(self):
        registry = ConnectionRegistry()
        socket = _FakeSocket()
        connection = await registry.connect("room-6", socket, user_id="u-dup")
        connection.evict("queue_full")
        connection.evict("dropped")
        if connection._close_task is not None:
            await connection._close_task

        self.assertEqual(socket.closed_codes, [1001])


class ClientReplayTest(unittest.IsolatedAsyncioTestCase):
    async def test_reconnect_replays_from_room_journal_without_client_buffer(self):
        registry = ConnectionRegistry()
        socket1 = _FakeSocket()
        conn1 = await registry.connect("room-rp", socket1, client_id="tab-1")
        registry.broadcast_text("room-rp", "event-1")
        await conn1.wait_flushed()
        first = json.loads(socket1.sent_texts[0])
        registry.disconnect("room-rp", socket1)
        registry.broadcast_text("room-rp", "event-2")

        socket2 = _FakeSocket()
        conn2 = await registry.connect(
            "room-rp",
            socket2,
            client_id="tab-1",
            epoch=first["epoch"],
            last_sequence=first["sequence"],
        )
        await asyncio.wait_for(conn2.replay_task, timeout=2)
        await asyncio.wait_for(conn2.wait_flushed(), timeout=2)

        frames = [json.loads(frame) for frame in socket2.sent_texts]
        self.assertEqual([frame["sequence"] for frame in frames if frame.get("type") == "event"], [2])
        self.assertFalse(hasattr(registry, "client_replay"))

    async def test_no_client_key_uses_no_replay(self):
        registry = ConnectionRegistry()
        socket = _FakeSocket()
        connection = await registry.connect("room-anon", socket)
        registry.broadcast_text("room-anon", "msg")
        await asyncio.wait_for(connection.wait_flushed(), timeout=2)
        self.assertEqual(len(socket.sent_texts), 1)
        self.assertEqual(json.loads(socket.sent_texts[0])["type"], "event")
        self.assertFalse(hasattr(registry, "client_replay"))


if __name__ == "__main__":
    unittest.main()
