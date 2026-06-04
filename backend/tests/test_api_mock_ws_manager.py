import asyncio
import json
import os
import sys
import unittest
from unittest import mock


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


class _FakePubSub:
    def __init__(self, messages):
        self._messages = list(messages)
        self.patterns = []
        self.closed = False

    async def psubscribe(self, pattern: str) -> None:
        self.patterns.append(pattern)

    async def get_message(self, **_kwargs):
        await asyncio.sleep(0)
        if self._messages:
            return self._messages.pop(0)
        await asyncio.sleep(0.01)
        return None

    async def aclose(self) -> None:
        self.closed = True


class _FakeRedis:
    def __init__(self, pubsub):
        self._pubsub = pubsub
        self.published = []

    def pubsub(self):
        return self._pubsub

    async def publish(self, channel, data):
        self.published.append((channel, data))
        return 1


class ApiMockWsManagerTest(unittest.IsolatedAsyncioTestCase):
    async def test_broadcast_job_state_publishes_to_redis_when_enabled(self):
        manager = ApiMockConnectionManager()
        fake_pubsub = _FakePubSub([])
        fake_redis = _FakeRedis(fake_pubsub)

        with mock.patch("app.domains.api_mock.ws.api_mock_manager.settings.REDIS_ENABLED", True), mock.patch(
            "app.domains.api_mock.ws.api_mock_manager.get_redis_client",
            new=mock.AsyncMock(return_value=fake_redis),
        ):
            await manager.broadcast_job_state("project-1", {"type": "job_update"})

        self.assertEqual(len(fake_redis.published), 1)
        channel, data = fake_redis.published[0]
        self.assertTrue(str(channel).endswith(":project-1"))
        envelope = json.loads(data)
        self.assertEqual(envelope["project_id"], "project-1")
        self.assertEqual(envelope["payload"]["type"], "job_update")

        await manager.shutdown()

    async def test_redis_subscription_forwards_remote_job_payload_to_local_socket(self):
        manager = ApiMockConnectionManager()
        socket = _FakeWebSocket()
        remote_payload = {"type": "job_done", "project_id": "project-1", "job": {"id": "job-1"}}
        channel = manager._job_channel("project-1")
        fake_pubsub = _FakePubSub(
            [
                {
                    "type": "pmessage",
                    "pattern": manager._job_channel_pattern().encode("utf-8"),
                    "channel": channel.encode("utf-8"),
                    "data": json.dumps(
                        {
                            "origin": "another-process",
                            "project_id": "project-1",
                            "payload": remote_payload,
                        }
                    ).encode("utf-8"),
                }
            ]
        )
        fake_redis = _FakeRedis(fake_pubsub)

        with mock.patch("app.domains.api_mock.ws.api_mock_manager.settings.REDIS_ENABLED", True), mock.patch(
            "app.domains.api_mock.ws.api_mock_manager.get_redis_client",
            new=mock.AsyncMock(return_value=fake_redis),
        ):
            await manager.connect(socket, "project-1", "user-1")
            await asyncio.sleep(0.08)

        self.assertTrue(socket.accepted)
        self.assertIn(remote_payload, socket.sent_payloads)

        await manager.shutdown()
