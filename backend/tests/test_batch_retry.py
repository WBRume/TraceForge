"""segment/log 批量落库失败回填与有界重试。"""

import asyncio
import os
import sys
import unittest
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.engine.session import TaskAgentEngine  # noqa: E402


def _engine():
    from unittest.mock import AsyncMock

    with patch.object(TaskAgentEngine, "_create_engine_backend", return_value=MagicMock()):
        engine = TaskAgentEngine("task-1", "ws-1", "user-1")
    engine.frontend.push = AsyncMock()
    return engine


class ExecutionLogRetryTest(unittest.IsolatedAsyncioTestCase):
    async def test_flush_failure_requeues_batch(self):
        engine = _engine()
        engine.logs.queue("first")
        with patch(
            "app.engine.session.persistence.run_db",
            mock.AsyncMock(side_effect=RuntimeError("db down")),
        ):
            await engine.logs.flush()

        # 失败回填：批次恢复进缓冲，等待下轮重试
        self.assertEqual([entry[0] for entry in engine.logs._buffer], ["first"])
        self.assertEqual(engine.logs._consecutive_failures, 1)

    async def test_consecutive_failures_drop_oldest_batch(self):
        engine = _engine()
        engine.logs.queue("first")
        with patch(
            "app.engine.session.persistence.run_db",
            mock.AsyncMock(side_effect=RuntimeError("db down")),
        ):
            await engine.logs.flush()
            await engine.logs.flush()
            await engine.logs.flush()

        # 连续 3 次失败：最旧批次被丢弃（有界重试上限），缓冲清空
        self.assertEqual(engine.logs._buffer, [])
        self.assertEqual(engine.logs._consecutive_failures, 0)

    async def test_success_resets_failure_counter(self):
        engine = _engine()
        engine.logs.queue("ok")
        with patch("app.engine.session.persistence.run_db", mock.AsyncMock(return_value=None)):
            await engine.logs.flush()
        self.assertEqual(engine.logs._consecutive_failures, 0)
        self.assertEqual(engine.logs._buffer, [])

    async def test_drain_bounded_retry_does_not_spin(self):
        engine = _engine()
        engine.logs.queue("first")
        with patch(
            "app.engine.session.persistence.run_db",
            mock.AsyncMock(side_effect=RuntimeError("db down")),
        ):
            await engine.logs.drain()
        # drain 有限轮数后退出（不无限自旋），失败批次被上限策略处理
        self.assertEqual(engine.logs._buffer, [])


class SegmentRetryTest(unittest.IsolatedAsyncioTestCase):
    async def test_segment_flush_failure_requeues_entries_and_snapshot(self):
        engine = _engine()
        engine.segments.record(
            "tool_input",
            workspace_id="ws-1", task_id="task-1", ai_job_id="job-1",
            session_id="s-1", tool_name="read_file", tool_input={}, tool_use_id="c1",
        )
        engine.segments.update_snapshot(status="RUNNING")
        with patch(
            "app.engine.session.persistence.run_db",
            mock.AsyncMock(side_effect=RuntimeError("db down")),
        ):
            await engine.segments.flush()

        recorders = [recorder for recorder, _kwargs in engine.segments._buffer]
        self.assertIn("tool_input", recorders)
        # snapshot 待写值恢复为 pending
        self.assertTrue(engine.segments._pending_snapshot)
        self.assertEqual(engine.segments._consecutive_failures, 1)

    async def test_segment_consecutive_failures_drop_oldest_batch(self):
        engine = _engine()
        engine.segments.record(
            "tool_result",
            workspace_id="ws-1", task_id="task-1", ai_job_id="job-1",
            session_id="s-1", tool_use_id="c1", output="x", is_error=False,
        )
        with patch(
            "app.engine.session.persistence.run_db",
            mock.AsyncMock(side_effect=RuntimeError("db down")),
        ):
            await engine.segments.flush()
            await engine.segments.flush()
            await engine.segments.flush()

        self.assertEqual(engine.segments._buffer, [])


if __name__ == "__main__":
    unittest.main()
