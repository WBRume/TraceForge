import os
import sys
import unittest
from unittest.mock import patch

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
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
        connection = await manager.connect(socket, "project-1", "user-1")
        await connection.wait_flushed()
        initial = socket.sent_payloads[0]
        self.assertEqual(initial["type"], "resync_required")
        self.assertTrue(
            await manager.complete_resync(
                socket,
                "project-1",
                epoch=initial["epoch"],
                barrier_sequence=initial["barrier_sequence"],
            )
        )
        with patch("app.domains.api_mock.ws.api_mock_manager._authorized_job_recipients", return_value={"user-1"}):
            await manager.broadcast_job_state(
                "project-1",
                {
                    "type": "job_update",
                    "project_id": "project-1",
                    "job": {
                        "id": "job-1",
                        "project_id": "project-1",
                        "creator_id": "user-1",
                        "job_type": "SYNC_TASK_SOURCE",
                        "status": "RUNNING",
                        "progress": 30,
                        "created_at": "2026-11-10T09:00:00Z",
                    },
                },
            )
        await connection.wait_flushed()

        self.assertTrue(socket.accepted)
        self.assertEqual(len(socket.sent_payloads), 3)
        self.assertEqual(socket.sent_payloads[2]["type"], "event")
        self.assertEqual(socket.sent_payloads[2]["payload"]["type"], "job_update")

        await manager.shutdown()
