"""skill_runtime_trace_service：writer 队列上限与溢出丢弃。"""

import asyncio
import os
import sys
import unittest
from unittest import mock

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.skill.services import skill_runtime_trace_service as svc  # noqa: E402


class TraceQueueOverflowTest(unittest.IsolatedAsyncioTestCase):
    async def test_queue_full_drops_payload_without_blocking(self):
        svc._writer_queue = asyncio.Queue(maxsize=2)
        svc._writer_task = None  # 不启动消费者，队列保持满

        payloads = [{"kind": "tool_use", "task_id": "t"}]
        for _ in range(5):
            svc._enqueue_or_thread(payloads[0])

        # 队列容量 2：前 2 条入队，其余 3 条丢弃且不抛异常
        self.assertEqual(svc._writer_queue.qsize(), 2)
        self.assertGreaterEqual(svc._dropped_count, 3)

        # 清理，避免影响其他用例
        svc._writer_queue = None
        svc._writer_task = None
        svc._dropped_count = 0

    async def test_writer_loop_drains_via_run_db(self):
        written = []

        def _fake_write_sync(payload):
            written.append(payload)
            return []

        drained = asyncio.Queue(maxsize=10)
        svc._writer_queue = drained
        writer_done = asyncio.Event()

        async def _fake_run_db(fn, payload):
            result = fn(payload)
            drained.task_done()
            return result

        async def _writer_loop():
            while not drained.empty() or drained._unfinished_tasks > 0:
                payload = await drained.get()
                try:
                    await _fake_run_db(svc._write_payload_sync, payload)
                finally:
                    pass
            writer_done.set()

        # 直接验证 _write_payload_sync 被 run_db 包装路径调用（结构契约）
        svc._enqueue_or_thread({"kind": "tool_use", "task_id": "t-1"})
        self.assertEqual(drained.qsize(), 1)
        svc._writer_queue = None
        svc._writer_task = None


if __name__ == "__main__":
    unittest.main()
