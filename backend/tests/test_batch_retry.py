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

from app.engine.workflow_engine import WorkflowEngine  # noqa: E402


def _engine() -> WorkflowEngine:
    from unittest.mock import AsyncMock

    with patch.object(WorkflowEngine, "_create_engine_backend", return_value=MagicMock()):
        engine = WorkflowEngine("task-1", "ws-1", "user-1")
    engine._ws_push = AsyncMock()
    return engine


class ExecutionLogRetryTest(unittest.IsolatedAsyncioTestCase):
    async def test_flush_failure_requeues_batch(self):
        engine = _engine()
        engine._queue_execution_log("first")
        with patch(
            "app.engine.workflow_engine.run_db",
            mock.AsyncMock(side_effect=RuntimeError("db down")),
        ):
            await engine._flush_execution_logs()

        # 失败回填：批次恢复进缓冲，等待下轮重试
        self.assertEqual([entry[0] for entry in engine._execution_log_buffer], ["first"])
        self.assertEqual(engine._execution_log_failures, 1)

    async def test_consecutive_failures_drop_oldest_batch(self):
        engine = _engine()
        engine._queue_execution_log("first")
        with patch(
            "app.engine.workflow_engine.run_db",
            mock.AsyncMock(side_effect=RuntimeError("db down")),
        ):
            await engine._flush_execution_logs()
            await engine._flush_execution_logs()
            await engine._flush_execution_logs()

        # 连续 3 次失败：最旧批次被丢弃（有界重试上限），缓冲清空
        self.assertEqual(engine._execution_log_buffer, [])
        self.assertEqual(engine._execution_log_failures, 0)

    async def test_success_resets_failure_counter(self):
        engine = _engine()
        engine._queue_execution_log("ok")
        with patch("app.engine.workflow_engine.run_db", mock.AsyncMock(return_value=None)):
            await engine._flush_execution_logs()
        self.assertEqual(engine._execution_log_failures, 0)
        self.assertEqual(engine._execution_log_buffer, [])

    async def test_drain_bounded_retry_does_not_spin(self):
        engine = _engine()
        engine._queue_execution_log("first")
        with patch(
            "app.engine.workflow_engine.run_db",
            mock.AsyncMock(side_effect=RuntimeError("db down")),
        ):
            await engine._drain_execution_logs()
        # drain 有限轮数后退出（不无限自旋），失败批次被上限策略处理
        self.assertEqual(engine._execution_log_buffer, [])


class SegmentRetryTest(unittest.IsolatedAsyncioTestCase):
    async def test_segment_flush_failure_requeues_entries_and_snapshot(self):
        engine = _engine()
        engine._record_context_segment(
            "tool_input",
            workspace_id="ws-1", task_id="task-1", ai_job_id="job-1",
            session_id="s-1", tool_name="read_file", tool_input={}, tool_use_id="c1",
        )
        engine._update_context_snapshot(status="RUNNING")
        with patch(
            "app.engine.workflow_engine.run_db",
            mock.AsyncMock(side_effect=RuntimeError("db down")),
        ):
            await engine._flush_segments()

        recorders = [recorder for recorder, _kwargs in engine._segment_buffer]
        self.assertIn("tool_input", recorders)
        # snapshot 待写值恢复为 pending
        self.assertTrue(engine._pending_snapshot_update)
        self.assertEqual(engine._segment_failures, 1)

    async def test_segment_consecutive_failures_drop_oldest_batch(self):
        engine = _engine()
        engine._record_context_segment(
            "tool_result",
            workspace_id="ws-1", task_id="task-1", ai_job_id="job-1",
            session_id="s-1", tool_use_id="c1", output="x", is_error=False,
        )
        with patch(
            "app.engine.workflow_engine.run_db",
            mock.AsyncMock(side_effect=RuntimeError("db down")),
        ):
            await engine._flush_segments()
            await engine._flush_segments()
            await engine._flush_segments()

        self.assertEqual(engine._segment_buffer, [])


if __name__ == "__main__":
    unittest.main()
