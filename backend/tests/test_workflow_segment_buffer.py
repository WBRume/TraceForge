"""WorkflowEngine segment/snapshot 批量窗口与思考合并行为。"""

import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.engine.workflow_engine import SessionGate, WorkflowEngine  # noqa: E402


def _engine() -> WorkflowEngine:
    with patch.object(WorkflowEngine, "_create_engine_backend", return_value=MagicMock()):
        engine = WorkflowEngine("task-1", "ws-1", "user-1")
    engine.current_job_id = "job-1"
    engine.session_id = "session-1"
    engine.session_turn_id = "turn-1"
    engine._ws_push = AsyncMock()
    return engine


class WorkflowSegmentBufferTest(unittest.IsolatedAsyncioTestCase):
    async def test_tool_segments_batched_and_thinking_merged(self):
        engine = _engine()
        run_db_mock = AsyncMock()
        with patch("app.engine.workflow_engine.run_db", run_db_mock):
            engine._thinking_buffer = "merged thinking"
            await engine._push_thinking("merged thinking")
            await engine._push_thinking("merged thinking")

            engine._record_context_segment(
                "tool_input",
                workspace_id="ws-1",
                task_id="task-1",
                ai_job_id="job-1",
                session_id="session-1",
                tool_name="read_file",
                tool_input={"path": "README.md"},
                tool_use_id="call-1",
            )

            await engine._flush_segments()

        run_db_mock.assert_awaited_once()
        persist_fn, entries, snapshot_update = run_db_mock.await_args.args
        self.assertIs(persist_fn.__func__, WorkflowEngine._persist_segments_sync)
        self.assertIsNone(snapshot_update)

        recorders = [recorder for recorder, _kwargs in entries]
        # thinking 只合并为一条
        self.assertEqual(recorders.count("thinking"), 1)
        self.assertIn("tool_input", recorders)
        thinking_entry = next(kwargs for recorder, kwargs in entries if recorder == "thinking")
        self.assertEqual(thinking_entry["content"], "merged thinking")
        self.assertEqual(thinking_entry["ai_job_id"], "job-1")

        # drain 后缓冲清空，无 pending task
        await engine._drain_buffers()
        self.assertEqual(engine._segment_buffer, [])
        self.assertFalse(engine._thinking_dirty)
        self.assertIsNone(engine._segment_flush_task)

    async def test_snapshot_update_coalesces_latest_values(self):
        engine = _engine()
        run_db_mock = AsyncMock()
        with patch("app.engine.workflow_engine.run_db", run_db_mock):
            engine._update_context_snapshot(
                usage={"input_tokens": 5, "output_tokens": 2},
                status="RUNNING",
            )
            engine._update_context_snapshot(
                usage={"input_tokens": 9},
                total_cost_usd=0.5,
            )
            await engine._flush_segments()

        run_db_mock.assert_awaited_once()
        _fn, entries, snapshot_update = run_db_mock.await_args.args
        self.assertEqual(entries, [])
        self.assertIsNotNone(snapshot_update)
        self.assertEqual(snapshot_update["usage"]["input_tokens"], 9)
        self.assertEqual(snapshot_update["usage"]["output_tokens"], 2)
        self.assertEqual(snapshot_update["status"], "RUNNING")
        self.assertEqual(snapshot_update["total_cost_usd"], 0.5)
        self.assertEqual(snapshot_update["workspace_id"], "ws-1")
        self.assertEqual(snapshot_update["task_id"], "task-1")
        self.assertEqual(snapshot_update["ai_job_id"], "job-1")

        await engine._drain_buffers()

    async def test_push_hitl_forces_flush_before_broadcast(self):
        engine = _engine()
        events = []

        async def _capture_flush():
            events.append("flush")

        with (
            patch("app.engine.workflow_engine.run_db", AsyncMock()),
            patch.object(engine, "_flush_segments", _capture_flush),
        ):
            await engine._push_hitl(prompt="需要确认", hitl_type="text")

        # 强制 flush 发生在 WS 广播之前
        self.assertEqual(events, ["flush"])
        engine._ws_push.assert_awaited_once()
        self.assertEqual(engine._ws_push.await_args.args[0], "hitl_request")

        with patch("app.engine.workflow_engine.run_db", AsyncMock()):
            await engine._drain_buffers()

    async def test_interrupt_invalidates_gate_and_blocks_events(self):
        engine = _engine()
        self.assertTrue(engine._event_is_current())

        engine._gate = SessionGate(
            task_id="task-1", job_id="job-1", session_revision=2, ttl_seconds=60.0
        )
        engine.cli = MagicMock()
        engine.cli.interrupt = AsyncMock()
        await engine.interrupt()
        self.assertFalse(engine._event_is_current())

        with patch("app.engine.workflow_engine.run_db", AsyncMock()):
            await engine._drain_buffers()


if __name__ == "__main__":
    unittest.main()
