"""旧版 Claude dict 事件归一（claude_stream_to_agent_events）与回合结果分类。"""

import os
import sys
import unittest

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.engine.claude_event_adapter import claude_stream_to_agent_events  # noqa: E402
from app.engine.session.engine import classify_turn_outcome  # noqa: E402


class ClaudeStreamNormalizationTest(unittest.TestCase):
    def test_system_init_maps_to_session_started(self):
        events = claude_stream_to_agent_events({
            "type": "system", "subtype": "init",
            "session_id": "sid-1", "model": "mock-model",
        })
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, "session_started")
        self.assertEqual(events[0].payload["provider_session_id"], "sid-1")
        self.assertEqual(events[0].payload["model"], "mock-model")

    def test_assistant_blocks_map_to_agent_events(self):
        events = claude_stream_to_agent_events({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "ponder"},
                    {"type": "text", "text": "answer"},
                    {"type": "tool_use", "name": "Read", "input": {"path": "a"}, "id": "c1"},
                    {"type": "unrelated", "foo": "bar"},
                ],
            },
        })
        self.assertEqual([e.type for e in events], ["thinking", "text", "tool_use"])
        self.assertEqual(events[0].payload, {"text": "ponder"})
        self.assertEqual(events[1].payload, {"text": "answer"})
        self.assertEqual(events[2].payload["tool_name"], "Read")
        self.assertEqual(events[2].payload["tool_input"], {"path": "a"})
        self.assertEqual(events[2].payload["tool_use_id"], "c1")

    def test_tool_result_list_output_is_flattened(self):
        events = claude_stream_to_agent_events({
            "type": "assistant",
            "message": {"content": [{
                "type": "tool_result",
                "tool_use_id": "c1",
                "output": [{"text": "line1"}, {"text": "line2"}, "junk"],
                "is_error": False,
            }]},
        })
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, "tool_result")
        self.assertEqual(events[0].payload["output"], "line1\nline2")
        self.assertFalse(events[0].payload["is_error"])

    def test_result_event_maps_fields(self):
        events = claude_stream_to_agent_events({
            "type": "result", "subtype": "success", "is_error": False,
            "result": "done", "duration_ms": 2500, "total_cost_usd": 0.5,
        })
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, "result")
        self.assertEqual(events[0].payload["result"], "done")
        self.assertEqual(events[0].payload["duration_ms"], 2500)
        self.assertEqual(events[0].payload["cost_usd"], 0.5)
        self.assertEqual(events[0].payload["finish_reason"], "completed")

    def test_error_result_folds_subtype_into_finish_reason(self):
        events = claude_stream_to_agent_events({
            "type": "result", "subtype": "error", "is_error": True, "result": "boom",
        })
        self.assertEqual(events[0].payload["finish_reason"], "error")

    def test_compaction_signal_in_unknown_event(self):
        events = claude_stream_to_agent_events({
            "type": "weird_event", "name": "context compacted",
        })
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, "context_compacted")
        self.assertTrue(events[0].payload["summary"])

    def test_unknown_event_without_signal_yields_nothing(self):
        self.assertEqual(claude_stream_to_agent_events({"type": "whatever"}), [])


class TurnOutcomeClassificationTest(unittest.TestCase):
    def test_timeout_markers_only_classify_failed_results(self):
        self.assertEqual(classify_turn_outcome("Request timed out", is_error=True, finish_reason="error"), "timeout")
        self.assertEqual(classify_turn_outcome("连接超时", is_error=True, finish_reason="completed"), "timeout")
        self.assertEqual(classify_turn_outcome("anything", is_error=False, finish_reason="timeout"), "timeout")

    def test_successful_diagnosis_of_business_timeouts_is_not_agent_timeout(self):
        for text in ("MySQL 1205 Lock wait timeout exceeded", "连接超时", "Request timed out",
                     "请检查 innodb_lock_wait_timeout 和 ETIMEDOUT 日志"):
            self.assertEqual(classify_turn_outcome(text, is_error=False, finish_reason="completed"), "success")

    def test_error_reasons(self):
        self.assertEqual(classify_turn_outcome("boom", is_error=True, finish_reason="completed"), "failed")
        self.assertEqual(classify_turn_outcome("boom", is_error=False, finish_reason="error"), "failed")
        self.assertEqual(classify_turn_outcome("boom", is_error=False, finish_reason="aborted"), "failed")

    def test_success(self):
        self.assertEqual(classify_turn_outcome("ok", is_error=False, finish_reason="completed"), "success")


if __name__ == "__main__":
    unittest.main()
