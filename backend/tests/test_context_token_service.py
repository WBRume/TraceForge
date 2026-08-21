import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.database import Base  # noqa: E402
import app.domains.api_mock.models.api_mock  # noqa: F401,E402
import app.domains.asset.models.asset  # noqa: F401,E402
import app.domains.dashboard.models.metric  # noqa: F401,E402
import app.domains.task.models.test_result  # noqa: F401,E402
import app.domains.workflow.models.task_change  # noqa: F401,E402
import app.domains.workspace_asset.models.workspace_asset  # noqa: F401,E402
from app.engine.claude_event_adapter import extract_claude_compaction_event, extract_claude_usage  # noqa: E402
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.auth.models.user import User, Workspace
from app.domains.skill.models.skill import (
    SddSkillRuntimeEvent,
    SkillRuntimeEventStatus,
    SkillRuntimeEventType,
    SkillRuntimeEvidenceLevel,
)
from app.domains.task.models.chat import ChatMessage, MessageRole, MessageType
from app.domains.task.models.context_token import (
    ContextTokenCategory,
    SddContextTokenSegment,
    SddContextTokenSnapshot,
)
from app.domains.task.models.log import LogType, SddExecutionLog
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.services import context_compaction_service, context_token_service  # noqa: E402


class ContextTokenServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        SessionLocal = sessionmaker(bind=self.engine)
        self.db = SessionLocal()
        user = User(id="user-1", email="u@example.com", hashed_password="x", display_name="User")
        workspace = Workspace(id="ws-1", name="Workspace", owner_id=user.id, project_path=self.tmpdir.name)
        task = SddTask(
            id="task-1",
            workspace_id=workspace.id,
            creator_id=user.id,
            name="Task",
            description="Build the thing",
            project_path=self.tmpdir.name,
            status=TaskStatus.CODING,
        )
        job = SddAiJob(
            id="job-1",
            workspace_id=workspace.id,
            task_id=task.id,
            channel=AiJobChannel.TASK_CHAT,
            queue_key="TASK_CHAT:task-1",
            status=AiJobStatus.RUNNING,
            progress=1,
            prompt_text="current prompt",
            creator_id=user.id,
        )
        self.db.add_all([user, workspace, task, job])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def test_claude_usage_parser_captures_assistant_and_result_usage(self):
        assistant_usage = extract_claude_usage(
            {
                "type": "assistant",
                "message": {
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "cache_read_input_tokens": 3,
                        "cache_creation_input_tokens": 2,
                        "output_tokens_details": {"thinking_tokens": 1},
                    }
                },
            }
        )
        self.assertEqual(assistant_usage["input_tokens"], 10)
        self.assertEqual(assistant_usage["output_tokens"], 5)
        self.assertEqual(assistant_usage["cache_read_tokens"], 3)
        self.assertEqual(assistant_usage["cache_creation_tokens"], 2)
        self.assertEqual(assistant_usage["thinking_tokens"], 1)
        self.assertEqual(assistant_usage["total_tokens"], 21)

        result_usage = extract_claude_usage(
            {
                "type": "result",
                "usage": {
                    "input_tokens": 7,
                    "output_tokens": 4,
                    "cache_read_tokens": 2,
                    "cache_creation_tokens": 1,
                    "tool_input_tokens": 6,
                    "tool_output_tokens": 8,
                },
            }
        )
        self.assertEqual(result_usage["tool_io_tokens"], 14)
        self.assertEqual(result_usage["total_tokens"], 28)

    def test_claude_compaction_parser_captures_unknown_stream_event(self):
        event = extract_claude_compaction_event(
            {
                "type": "context_compaction",
                "session_id": "session-1",
                "tokens_before": 120000,
                "tokens_after": 32000,
            }
        )

        self.assertIsNotNone(event)
        self.assertEqual(event["token_before"], 120000)
        self.assertEqual(event["token_after"], 32000)

    def test_claude_compaction_parser_ignores_regular_messages_about_feature(self):
        event = extract_claude_compaction_event(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": "请新增 Compaction / 上下文压缩可视化功能。压缩前4token压缩后4token。",
                },
            }
        )

        self.assertIsNone(event)

    def test_session_file_scan_requires_explicit_compaction_event_signal(self):
        session_file = Path(self.tmpdir.name) / "session.jsonl"
        session_file.write_text(
            json.dumps(
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": "讨论上下文压缩可视化，不是实际压缩事件。from 4 to 4",
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        events = context_compaction_service._scan_text_file_for_compaction(
            session_file,
            source="claude_session_file",
            source_label="~/.claude session file",
            source_ref_prefix=str(session_file),
        )

        self.assertEqual(events, [])

    def test_text_compaction_parser_filters_non_reducing_token_pairs(self):
        session_file = Path(self.tmpdir.name) / "compact.log"
        session_file.write_text(
            "[compaction] context compaction detected; tokens 4 -> 4",
            encoding="utf-8",
        )

        events = context_compaction_service._scan_text_file_for_compaction(
            session_file,
            source="session_trace",
            source_label="Claude session trace",
            source_ref_prefix=str(session_file),
        )

        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0].token_before)
        self.assertIsNone(events[0].token_after)

    def test_no_usage_keeps_provider_tokens_unavailable(self):
        self.assertIsNone(extract_claude_usage({"type": "assistant", "message": {"content": []}}))

        snapshot = context_token_service.ensure_snapshot(
            self.db,
            workspace_id="ws-1",
            task_id="task-1",
            ai_job_id="job-1",
        )
        context_token_service.update_snapshot_usage(
            self.db,
            snapshot=snapshot,
            duration_ms=123,
            total_cost_usd=0.01,
            usage=None,
        )

        payload = context_token_service.get_context_window(self.db, workspace_id="ws-1", task_id="task-1", ai_job_id="job-1")
        self.assertFalse(payload["provider_tokens"]["available"])
        self.assertIsNone(payload["provider_tokens"]["input_tokens"])
        self.assertEqual(payload["snapshot"]["duration_ms"], 123)
        self.assertEqual(payload["compaction"]["status"], "not_detected")
        self.assertEqual(payload["compaction"]["phases"][0]["phase_index"], 1)

    def test_context_window_aggregates_segments_by_snapshot_id(self):
        snapshot = context_token_service.ensure_snapshot(self.db, workspace_id="ws-1", task_id="task-1", ai_job_id="job-1")
        context_token_service.record_segment(
            self.db,
            snapshot=snapshot,
            category=ContextTokenCategory.TOOL_RESULT,
            source_kind="tool_result",
            source_ref_id="tool-1",
            tool_use_id="tool-1",
            content="abcd",
        )
        context_token_service.record_segment(
            self.db,
            snapshot=snapshot,
            category=ContextTokenCategory.THINKING,
            source_kind="assistant_thinking",
            content="xy",
        )

        payload = context_token_service.get_context_window(
            self.db,
            workspace_id="ws-1",
            task_id="task-1",
            ai_job_id="job-1",
            category="TOOL_RESULT",
        )

        categories = {item["category"]: item for item in payload["categories"]}
        self.assertEqual(categories["TOOL_RESULT"]["attribution_units"], 4)
        self.assertEqual(categories["THINKING"]["attribution_units"], 2)
        self.assertEqual(round(categories["TOOL_RESULT"]["percentage"], 1), 66.7)
        self.assertEqual(payload["segments_total"], 1)
        self.assertEqual(payload["segments"][0]["category"], "TOOL_RESULT")

    def test_context_window_falls_back_to_last_usable_snapshot(self):
        # 旧快照有真实用量
        usable = context_token_service.ensure_snapshot(
            self.db,
            workspace_id="ws-1",
            task_id="task-1",
            ai_job_id="job-old",
            status="SUCCESS",
        )
        context_token_service.update_snapshot_usage(
            self.db,
            snapshot=usable,
            usage={"input_tokens": 100, "output_tokens": 10},
        )

        # 新快照来自中断/未产生 usage 的回合，只有 0
        interrupted = context_token_service.ensure_snapshot(
            self.db,
            workspace_id="ws-1",
            task_id="task-1",
            ai_job_id="job-new",
            status="RUNNING",
        )
        context_token_service.update_snapshot_usage(
            self.db,
            snapshot=interrupted,
            usage={"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_creation_tokens": 0},
        )

        self.assertFalse(context_token_service._snapshot_has_usable_provider_tokens(interrupted))
        payload = context_token_service.get_context_window(
            self.db,
            workspace_id="ws-1",
            task_id="task-1",
            ai_job_id="job-new",
        )
        self.assertEqual(payload["snapshot"]["id"], usable.id)
        self.assertTrue(payload["provider_tokens"]["available"])
        self.assertEqual(payload["provider_tokens"]["input_tokens"], 100)

    def test_context_window_detects_compaction_from_execution_log(self):
        snapshot = context_token_service.ensure_snapshot(self.db, workspace_id="ws-1", task_id="task-1", ai_job_id="job-1")
        context_token_service.update_snapshot_usage(
            self.db,
            snapshot=snapshot,
            usage={"input_tokens": 30000, "output_tokens": 2000},
        )
        context_token_service.record_segment(
            self.db,
            snapshot=snapshot,
            category=ContextTokenCategory.HISTORY,
            source_kind="chat_message",
            source_ref_id="msg-old",
            content="older conversation",
        )
        context_token_service.record_segment(
            self.db,
            snapshot=snapshot,
            category=ContextTokenCategory.SPEC_DOCS,
            source_kind="asset",
            source_ref_id="asset-1",
            content="important spec",
        )
        context_token_service.record_segment(
            self.db,
            snapshot=snapshot,
            category=ContextTokenCategory.TOOL_RESULT,
            source_kind="tool_result",
            source_ref_id="tool-1",
            tool_use_id="tool-1",
            content="subagent worker output",
        )
        self.db.add(
            SddExecutionLog(
                id="log-compact-1",
                workspace_id="ws-1",
                task_id="task-1",
                creator_id="user-1",
                log_type=LogType.STDOUT,
                content="[compaction] context compaction detected; tokens 120000 -> 32000",
            )
        )
        self.db.commit()

        payload = context_token_service.get_context_window(self.db, workspace_id="ws-1", task_id="task-1", ai_job_id="job-1")

        compaction = payload["compaction"]
        self.assertEqual(compaction["status"], "detected")
        self.assertEqual(len(compaction["events"]), 1)
        event = compaction["events"][0]
        self.assertEqual(event["token_before_estimate"], 120000)
        self.assertEqual(event["token_after_estimate"], 32000)
        self.assertEqual(event["token_reduction_estimate"], 88000)
        self.assertEqual(event["trigger"]["log_id"], "log-compact-1")
        self.assertEqual(len(compaction["phases"]), 2)
        risk_counts = {risk["kind"]: risk["affected_segments"] for risk in event["risks"]}
        self.assertEqual(risk_counts["history"], 1)
        self.assertEqual(risk_counts["spec"], 1)
        self.assertEqual(risk_counts["tool_result"], 1)
        self.assertEqual(risk_counts["subagent"], 1)

    def test_tool_result_promotes_to_runtime_skills_when_runtime_file_evidence_exists(self):
        snapshot = context_token_service.ensure_snapshot(self.db, workspace_id="ws-1", task_id="task-1", ai_job_id="job-1")
        context_token_service.record_tool_result(
            self.db,
            workspace_id="ws-1",
            task_id="task-1",
            ai_job_id="job-1",
            session_id=None,
            tool_use_id="tool-1",
            output="runtime skill file content",
        )
        runtime_event = SddSkillRuntimeEvent(
            id="event-1",
            workspace_id="ws-1",
            task_id="task-1",
            ai_job_id="job-1",
            tool_use_id="tool-1",
            event_type=SkillRuntimeEventType.FILE_READ,
            evidence_level=SkillRuntimeEvidenceLevel.EXACT_PATH,
            materialized_dir="skill-dir",
            relative_path="SKILL.md",
            status=SkillRuntimeEventStatus.PENDING,
        )
        self.db.add(runtime_event)
        self.db.commit()

        context_token_service.promote_tool_result_to_runtime_skill(
            self.db,
            workspace_id="ws-1",
            task_id="task-1",
            ai_job_id="job-1",
            tool_use_id="tool-1",
            runtime_event_ids=["event-1"],
        )

        row = self.db.query(SddContextTokenSegment).filter(SddContextTokenSegment.snapshot_id == snapshot.id).one()
        self.assertEqual(row.category, ContextTokenCategory.RUNTIME_SKILLS)
        self.assertEqual(row.skill_runtime_event_id, "event-1")

    def test_segments_store_hash_counts_and_short_preview_not_raw_text(self):
        snapshot = context_token_service.ensure_snapshot(self.db, workspace_id="ws-1", task_id="task-1", ai_job_id="job-1")
        raw_text = "x" * 2000
        row = context_token_service.record_segment(
            self.db,
            snapshot=snapshot,
            category=ContextTokenCategory.TASK_PROMPT,
            source_kind="task_prompt",
            source_ref_id="job-1",
            content=raw_text,
        )

        self.assertEqual(row.char_count, 2000)
        self.assertEqual(row.byte_count, 2000)
        self.assertTrue(row.content_hash)
        self.assertIsNotNone(row.preview)
        self.assertLessEqual(len(row.preview), 503)
        self.assertNotIn(raw_text, row.preview)


if __name__ == "__main__":
    unittest.main()
