import os
import sys
import unittest
from unittest import mock


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.ai.services import chat_message_idempotency_service as service  # noqa: E402


class _FakeRedis:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)
        return 1


class ChatMessageIdempotencyServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_claim_then_done_returns_duplicate_done(self):
        redis = _FakeRedis()
        with mock.patch(
            "app.domains.ai.services.chat_message_idempotency_service.get_redis_client",
            new=mock.AsyncMock(return_value=redis),
        ):
            claim = await service.claim_message(
                task_id="task-1",
                user_id="user-1",
                client_message_id="client-1",
                content="hello",
            )
            self.assertTrue(claim.claimed)

            await service.mark_message_done(
                claim,
                chat_message_id="msg-1",
                ai_job_id="job-1",
            )

            duplicate = await service.claim_message(
                task_id="task-1",
                user_id="user-1",
                client_message_id="client-1",
                content="hello",
            )
            self.assertFalse(duplicate.claimed)
            self.assertEqual(duplicate.status, "done")
            self.assertEqual(duplicate.existing["chat_message_id"], "msg-1")
            self.assertEqual(duplicate.existing["ai_job_id"], "job-1")

    async def test_claim_conflict_when_client_id_reused_for_different_content(self):
        redis = _FakeRedis()
        with mock.patch(
            "app.domains.ai.services.chat_message_idempotency_service.get_redis_client",
            new=mock.AsyncMock(return_value=redis),
        ):
            await service.claim_message(
                task_id="task-1",
                user_id="user-1",
                client_message_id="client-1",
                content="hello",
            )

            duplicate = await service.claim_message(
                task_id="task-1",
                user_id="user-1",
                client_message_id="client-1",
                content="changed",
            )
            self.assertEqual(duplicate.status, "conflict")

    async def test_failed_claim_is_deleted_so_retry_can_claim(self):
        redis = _FakeRedis()
        with mock.patch(
            "app.domains.ai.services.chat_message_idempotency_service.get_redis_client",
            new=mock.AsyncMock(return_value=redis),
        ):
            claim = await service.claim_message(
                task_id="task-1",
                user_id="user-1",
                client_message_id="client-1",
                content="hello",
            )
            await service.mark_message_failed(claim)

            retry = await service.claim_message(
                task_id="task-1",
                user_id="user-1",
                client_message_id="client-1",
                content="hello",
            )
            self.assertTrue(retry.claimed)

    async def test_redis_error_raises_unavailable(self):
        with mock.patch(
            "app.domains.ai.services.chat_message_idempotency_service.get_redis_client",
            new=mock.AsyncMock(side_effect=RuntimeError("redis down")),
        ):
            with self.assertRaises(service.ChatMessageIdempotencyUnavailable):
                await service.claim_message(
                    task_id="task-1",
                    user_id="user-1",
                    client_message_id="client-1",
                    content="hello",
                )


if __name__ == "__main__":
    unittest.main()
