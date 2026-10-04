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
    db.add(SddTask(id="replay-task", workspace_id="workspace", creator_id="user", name="Replay"))
    db.add(SddAiJob(id="replay-job", task_id="replay-task", workspace_id="workspace", creator_id="user",
                    channel=AiJobChannel.TASK_CHAT, status=AiJobStatus.RUNNING, queue_key="TASK_CHAT:replay-task"))
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
        engine.cli = SimpleNamespace(capabilities=SimpleNamespace(hitl_modes=["long_connection"]),
                                     respond_to_ask_user=AsyncMock())
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
    event = {"ask_user_id": "frm_private", "question": "Choose", "kind": "form",
             "fields": [{"key": "answer", "type": "string"}]}
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
