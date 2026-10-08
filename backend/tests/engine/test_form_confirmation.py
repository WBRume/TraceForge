import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.events import AgentEvent
from app.domains.task.models.context_token import SddContextTokenSegment, SddContextTokenSnapshot
from app.engine.session.engine import TaskAgentEngine
from app.engine.session.persistence import ContextSegmentBatcher


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["opencode", "claude-code", "dsh"])
@pytest.mark.parametrize(
    "status,label,answer",
    [
        ("answered", "提问已回答", {"build": "Maven"}),
        ("cancelled", "提问已取消", None),
        ("approved", "请求已批准", True),
        ("rejected", "请求已拒绝", False),
        ("closed", "交互已关闭，具体处理结果无法恢复", None),
        ("unknown", "交互已关闭，具体处理结果无法恢复", None),
    ],
)
async def test_interaction_resolution_uses_the_same_contract_for_every_provider(provider, status, label, answer):
    engine = object.__new__(TaskAgentEngine)
    engine.is_current = lambda: True
    engine.ws_id, engine.task_id, engine.user_id = "workspace", "task", "user"
    engine.session_id, engine.current_job_id = "session", "job"
    engine.frontend = SimpleNamespace(push_chat=AsyncMock())
    request_id = "provider-private-request"
    interaction_id = engine._confirmation_id(request_id)
    engine._pending_confirmations = {interaction_id: request_id, "other-interaction": "other-request"}

    await engine.handle_agent_event(
        AgentEvent(
            type="ask_user_resolved",
            provider=provider,
            payload={"ask_user_id": request_id, "status": status, "answer": answer},
        )
    )

    expected_content = label if answer is None else label + "：\n" + json.dumps(answer, ensure_ascii=False, indent=2)
    engine.frontend.push_chat.assert_awaited_once_with(
        "assistant",
        expected_content,
        metadata={
            "confirmation_resolution": {
                "interaction_id": interaction_id,
                "job_id": "job",
                "status": status,
                "answer": answer,
                "source": "provider",
            },
            "provider_event_key": f"confirmation-resolution:{interaction_id}",
        },
    )
    assert engine._pending_confirmations == {"other-interaction": "other-request"}


def test_questionnaire_is_persisted_as_chat_confirmation_without_provider_locator():
    async def run():
        engine = object.__new__(TaskAgentEngine)
        engine.is_current = lambda: True
        engine.ws_id = "workspace"
        engine.task_id = "task"
        engine.session_id = "session"
        engine.current_job_id = "job"
        engine._pending_confirmations = {}
        engine.segments = SimpleNamespace(record=MagicMock(), flush=AsyncMock())
        engine.frontend = SimpleNamespace(
            persist_chat_message=AsyncMock(return_value={"id": "message"}),
            push=AsyncMock(),
        )
        engine.on_hitl = None
        engine._emit_hook = AsyncMock()
        fields = [
            {"key": "build", "type": "string", "title": "构建工具", "options": [{"value": "maven", "label": "Maven"}]}
        ]
        await engine._on_ask_user(
            {"ask_user_id": "frm_private", "question": "构建工具", "kind": "form", "fields": fields}
        )
        call = engine.frontend.persist_chat_message.await_args
        confirmation = call.kwargs["metadata"]["confirmation"]
        assert confirmation["kind"] == "form"
        assert confirmation["fields"] == fields
        assert confirmation["job_id"] == "job"
        assert "frm_private" not in str(call)
        assert engine._pending_confirmations[confirmation["interaction_id"]] == "frm_private"
        engine.frontend.push.assert_awaited_once_with("chat_message", {"id": "message"})

    asyncio.run(run())


def test_questionnaire_flushes_real_segment_batch_without_dropping_entries(db, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    monkeypatch.setattr("app.engine.session.persistence.SessionLocal", sessionmaker(bind=db.get_bind()))

    async def run():
        engine = object.__new__(TaskAgentEngine)
        engine.is_current = lambda: True
        engine.ws_id = "workspace-form"
        engine.task_id = "task-form"
        engine.session_id = "session-form"
        engine.current_job_id = "job-form"
        engine._gate = None
        engine._pending_confirmations = {}
        engine.segments = ContextSegmentBatcher(engine)
        engine.frontend = SimpleNamespace(
            persist_chat_message=AsyncMock(return_value={"id": "message"}),
            push=AsyncMock(),
        )
        engine.on_hitl = None
        engine._emit_hook = AsyncMock()
        common = {
            "workspace_id": engine.ws_id,
            "task_id": engine.task_id,
            "ai_job_id": engine.current_job_id,
            "session_id": engine.session_id,
        }
        engine.segments.record("thinking", **common, content="正在收集需求")
        engine.segments.record(
            "tool_input",
            **common,
            tool_name="question",
            tool_input={"questions": ["构建工具"]},
            tool_use_id="call-form",
        )
        try:
            await engine._on_ask_user(
                {
                    "ask_user_id": "frm_private",
                    "question": "构建工具",
                    "kind": "form",
                    "fields": [{"key": "build", "type": "string"}],
                }
            )
            assert engine.segments._buffer == []
            assert engine.segments._consecutive_failures == 0
            confirmation = engine.frontend.persist_chat_message.await_args.kwargs["metadata"]["confirmation"]
            rows = db.query(SddContextTokenSegment).filter_by(task_id=engine.task_id).all()
            assert len(rows) == 3
            prompt = next(row for row in rows if row.source_kind == "confirmation_prompt")
            assert prompt.source_ref_id == confirmation["interaction_id"]
            assert db.query(SddContextTokenSnapshot).filter_by(task_id=engine.task_id).one().status == "RUNNING"
        finally:
            await engine.segments.drain()

    asyncio.run(run())
