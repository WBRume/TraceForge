import asyncio
import os
import sys
import unittest


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.api_mock.ws.api_mock_manager import ApiMockConnectionManager  # noqa: E402


class _FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.sent_payloads = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload) -> None:
        self.sent_payloads.append(payload)


class ApiMockWsManagerTest(unittest.IsolatedAsyncioTestCase):
    async def test_broadcast_job_state_uses_the_room_journal_path(self):
        manager = ApiMockConnectionManager()
        socket = _FakeWebSocket()
        await manager.connect(socket, "project-1", "user-1")
        await manager.broadcast_job_state("project-1", {"type": "job_update"})
        await asyncio.sleep(0.01)

        self.assertTrue(socket.accepted)
        self.assertEqual(len(socket.sent_payloads), 1)
        self.assertEqual(socket.sent_payloads[0]["type"], "event")
        self.assertEqual(socket.sent_payloads[0]["payload"]["type"], "job_update")

        await manager.shutdown()
