"""OutboundConnection / ConnectionRegistry：双重限长与慢客户端隔离。"""

import asyncio
import os
import sys
import unittest


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.websocket.ws.connection import (  # noqa: E402
    ConnectionRegistry,
    OutboundConnection,
)


class _FakeSocket:
    def __init__(self, *, fail=False, block_event: asyncio.Event = None):
        self.sent_texts = []
        self.fail = fail
        self._block_event = block_event

    async def send_text(self, payload: str):
        if self._block_event is not None:
            await self._block_event.wait()
        if self.fail:
            raise RuntimeError("connection gone")
        self.sent_texts.append(payload)


class OutboundConnectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_submit_delivers_in_order(self):
        socket = _FakeSocket()
        connection = OutboundConnection(socket, queue_size=8, max_bytes=65536)
        await connection.start()
        self.assertTrue(connection.submit_text("first"))
        self.assertTrue(connection.submit_text("second"))
        await asyncio.wait_for(connection.wait_flushed(), timeout=2)
        self.assertEqual(socket.sent_texts, ["first", "second"])

    async def test_event_count_overflow_disconnects_only_self(self):
        socket = _FakeSocket()
        connection = OutboundConnection(socket, queue_size=2, max_bytes=65536)
        await connection.start()
        self.assertTrue(connection.submit_text("1"))
        self.assertTrue(connection.submit_text("2"))
        # 第三条触发条数上限：断开该连接
        self.assertFalse(connection.submit_text("3"))
        self.assertTrue(connection.dropped)
        # 后续提交一律拒绝
        self.assertFalse(connection.submit_text("4"))

    async def test_single_message_over_byte_limit_disconnects(self):
        socket = _FakeSocket()
        connection = OutboundConnection(socket, queue_size=8, max_bytes=10)
        await connection.start()
        self.assertFalse(connection.submit_text("x" * 11))
        self.assertTrue(connection.dropped)

    async def test_pending_bytes_overflow_disconnects(self):
        socket = _FakeSocket()
        connection = OutboundConnection(socket, queue_size=8, max_bytes=100)
        await connection.start()
        block = asyncio.Event()
        socket._block_event = block  # 发送挂起，字节账保持累计
        self.assertTrue(connection.submit_text("y" * 40))
        self.assertTrue(connection.submit_text("y" * 40))
        # 未确认字节 80 < 100；再压 40 超限 → 断开
        self.assertFalse(connection.submit_text("y" * 40))
        self.assertTrue(connection.dropped)
        block.set()

    async def test_send_failure_marks_dropped(self):
        socket = _FakeSocket(fail=True)
        connection = OutboundConnection(socket, queue_size=8, max_bytes=65536)
        await connection.start()
        self.assertTrue(connection.submit_text("msg"))
        await asyncio.sleep(0.05)
        self.assertTrue(connection.dropped)

    async def test_json_payload_sent_via_send_json_when_available(self):
        sent = []

        class _JsonSocket:
            async def send_json(self, payload):
                sent.append(payload)

        connection = OutboundConnection(_JsonSocket(), queue_size=4, max_bytes=65536)
        await connection.start()
        self.assertTrue(connection.submit_json({"a": 1}))
        await asyncio.wait_for(connection.wait_flushed(), timeout=2)
        self.assertEqual(sent, [{"a": 1}])


class ConnectionRegistryTest(unittest.IsolatedAsyncioTestCase):
    async def test_presence_and_subscriber_queries(self):
        registry = ConnectionRegistry()
        ws1, ws2 = _FakeSocket(), _FakeSocket()
        await registry.connect("room-1", ws1, user_id="u1")
        await registry.connect("room-1", ws2, user_id="u1")
        await registry.connect("room-2", _FakeSocket(), user_id="u2")

        self.assertTrue(registry.has_subscribers("room-1"))
        self.assertFalse(registry.has_subscribers("room-x"))
        self.assertEqual(registry.online_users("room-1"), ["u1"])

        registry.disconnect("room-1", ws1)
        registry.disconnect("room-1", ws2)
        self.assertFalse(registry.has_subscribers("room-1"))
        self.assertEqual(registry.online_users("room-1"), [])

    async def test_broadcast_skips_dropped_and_cleans_registry(self):
        registry = ConnectionRegistry()
        good, bad = _FakeSocket(), _FakeSocket()
        await registry.connect("room-1", good)
        await registry.connect("room-1", bad)

        bad_conn = registry.rooms["room-1"][bad]
        bad_conn.dropped = True  # 模拟已被判定的慢客户端

        delivered = registry.broadcast_text("room-1", "hello")
        self.assertEqual(delivered, 1)
        self.assertNotIn(bad, registry.rooms["room-1"])
        await asyncio.wait_for(good_conn_wait(registry, good), timeout=2)
        self.assertEqual(good.sent_texts, ["hello"])


async def good_conn_wait(registry, socket):
    connection = registry.rooms.get("room-1", {}).get(socket)
    if connection is not None:
        await connection.wait_flushed()


if __name__ == "__main__":
    unittest.main()
