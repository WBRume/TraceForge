"""Replay persists one visible reply/form even after the engine is recreated."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.orm import sessionmaker

from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.task import SddTask
from app.engine.session.engine import TaskAgentEngine
from app.engine.session.frontend import FrontendFeed


@pytest.fixture
def engine_factory(db, monkeypatch):
    monkeypatch.setattr("app.engine.session.frontend.SessionLocal", sessionmaker(bind=db.get_bind()))
    db.add(
        SddTask(
            id="replay-task",
            workspace_id="workspace",
            creator_id="user",
            name="Replay",
            session_generation=1,
            agent_backend="opencode",
        )
    )
    db.add(
        SddAiJob(
            id="replay-job",
            task_id="replay-task",
            workspace_id="workspace",
            creator_id="user",
            channel=AiJobChannel.TASK_CHAT,
            status=AiJobStatus.RUNNING,
            queue_key="TASK_CHAT:replay-task",
        )
    )
    db.commit()

    def create():
        engine = object.__new__(TaskAgentEngine)
        engine.is_current = lambda: True
        engine.task_id, engine.ws_id, engine.user_id = "replay-task", "workspace", "user"
        engine.current_job_id, engine.session_id = "replay-job", "ses_test"
        engine.session_turn_id, engine._session_generation, engine._gate = None, 1, None
        engine._pending_confirmations = {}
        engine.segments = SimpleNamespace(record=Mock(), flush=AsyncMock())
        engine.frontend = FrontendFeed(engine)
        engine.frontend.push = AsyncMock()
        engine.on_hitl, engine._emit_hook = None, AsyncMock()
        engine.running = True
        engine.cli = SimpleNamespace(
            capabilities=SimpleNamespace(hitl_modes=["long_connection"]), respond_to_ask_user=AsyncMock()
        )
        return engine

    return create


def test_reply_replay_from_new_engine_is_deduplicated_in_database(db, engine_factory):
    first, recovered = engine_factory(), engine_factory()
    metadata = {"provider_event_key": "stable-provider-message"}
    assert first.frontend._persist_chat_message_sync("assistant", "finished", metadata)
    assert recovered.frontend._persist_chat_message_sync("assistant", "finished", metadata) is None
    assert db.query(ChatMessage).filter_by(task_id="replay-task").count() == 1


@pytest.mark.asyncio
async def test_pending_form_recovers_same_public_id_and_private_reply_route(db, engine_factory):
    event = {
        "ask_user_id": "frm_private",
        "question": "Choose",
        "kind": "form",
        "fields": [{"key": "answer", "type": "string"}],
    }
    first = engine_factory()
    await first._on_ask_user(event)
    original_id = next(iter(first._pending_confirmations))
    recovered = engine_factory()
    await recovered._on_ask_user(event)
    assert recovered._pending_confirmations == {original_id: "frm_private"}
    recovered.frontend.push.assert_not_awaited()
    messages = db.query(ChatMessage).filter_by(task_id="replay-task").all()
    assert len(messages) == 1
    assert messages[0].metadata_json["confirmation"]["interaction_id"] == original_id
    assert await recovered.deliver_confirmation_response(original_id, '{"answer":"yes"}')
    recovered.cli.respond_to_ask_user.assert_awaited_once_with("frm_private", '{"answer":"yes"}')


@pytest.mark.asyncio
@pytest.mark.parametrize("status,answer", [("answered", {"answer": "external"}), ("cancelled", None), ("closed", None)])
async def test_provider_resolution_is_durable_deduplicated_and_not_attributed_as_user(
    db, engine_factory, status, answer
):
    from app.domains.task.services.task_confirmation_service import (
        ConfirmationClosedError,
        snapshot_messages,
        validate_reply_sync,
    )

    first = engine_factory()
    await first._on_ask_user(
        {
            "ask_user_id": "frm_private",
            "question": "Choose",
            "kind": "form",
            "fields": [{"key": "answer", "type": "string"}],
        }
    )
    interaction = next(iter(first._pending_confirmations))
    prompt = db.query(ChatMessage).filter_by(task_id="replay-task").one()
    assert validate_reply_sync(db, "replay-task", interaction, prompt.id)["delivery_mode"] == "live"
    event = {"ask_user_id": "frm_private", "status": status, "answer": answer}
    await first._on_ask_user_resolved(event)
    await engine_factory()._on_ask_user_resolved(event)
    assert not first.can_deliver_confirmation(interaction)
    db.expire_all()
    rows = snapshot_messages(db, "replay-task", 1, ["replay-job"])
    assert len(rows) == 2
    resolution = next(row for row in rows if "confirmation_resolution" in row.metadata_json)
    assert resolution.role == "assistant"
    assert resolution.metadata_json["confirmation_resolution"]["answer"] == answer
    assert "frm_private" not in str(resolution.metadata_json)
    with pytest.raises(ConfirmationClosedError):
        validate_reply_sync(db, "replay-task", interaction, prompt.id)


@pytest.mark.asyncio
async def test_answer_page_and_provider_event_include_full_question_context(db, engine_factory):
    from app.domains.task.services.conversation.history import serialize_history_messages

    engine = engine_factory()
    fields = [{"key": "q0", "type": "string", "title": "项目类型", "description": "你想创建哪种项目？"}]
    await engine._on_ask_user({"ask_user_id": "frm_private", "question": "Questions", "kind": "form", "fields": fields})
    interaction = next(iter(engine._pending_confirmations))
    parent = db.query(ChatMessage).filter_by(task_id="replay-task").one()
    reply = ChatMessage(
        id="user-answer",
        task_id="replay-task",
        workspace_id="workspace",
        creator_id="user",
        role="user",
        content='{"q0":"AI"}',
        session_generation=1,
        metadata_json={"interaction_id": interaction, "reply_to_message_id": parent.id},
    )
    db.add(reply)
    db.commit()
    await engine._on_ask_user_resolved({"ask_user_id": "frm_private", "status": "answered", "answer": {"q0": "AI"}})
    pushed = engine.frontend.push.await_args.args[1]
    assert pushed["metadata"]["confirmation_context"]["fields"] == fields
    assert pushed["metadata"]["confirmation_context"]["answer_message_id"] == reply.id
    task = db.get(SddTask, "replay-task")
    page = serialize_history_messages(db, task, [reply], "workspace", "replay-task")
    assert page[0]["metadata"]["confirmation_context"]["fields"] == fields
    assert "confirmation_context" not in reply.metadata_json
    reply.session_generation = 2
    db.flush()
    page = serialize_history_messages(db, task, [reply], "workspace", "replay-task")
    assert "confirmation_context" not in page[0]["metadata"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stale", ["generation", "job", "task", "parent"])
async def test_stale_native_question_is_rejected_even_without_a_resolution(db, engine_factory, stale):
    from app.domains.task.services.task_confirmation_service import ConfirmationClosedError, validate_reply_sync

    engine = engine_factory()
    await engine._on_ask_user({"ask_user_id": "frm_private", "question": "Choose", "kind": "text"})
    interaction = next(iter(engine._pending_confirmations))
    prompt = db.query(ChatMessage).filter_by(task_id="replay-task").one()
    if stale == "generation":
        db.get(SddTask, "replay-task").session_generation += 1
    elif stale == "job":
        db.get(SddAiJob, "replay-job").status = AiJobStatus.SUCCESS
    elif stale == "task":
        db.get(SddTask, "replay-task").status = "INTERRUPTED"
    else:
        prompt.role = "user"
    db.commit()
    with pytest.raises(ConfirmationClosedError):
        validate_reply_sync(db, "replay-task", interaction, prompt.id)
