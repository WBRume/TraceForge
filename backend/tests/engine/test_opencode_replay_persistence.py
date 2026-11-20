"""Replay persists one visible reply/form even after the engine is recreated."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.agents.adapters.opencode.event_mapper import map_opencode_event
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.models.task_event_outbox import TaskEventOutbox
from app.engine.session.engine import TaskAgentEngine
from app.engine.session.frontend import FrontendFeed


@pytest.fixture
def engine_factory(db, monkeypatch):
    sessions = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr("app.engine.session.frontend.SessionLocal", sessions)
    monkeypatch.setattr("app.engine.session.persistence.SessionLocal", sessions)
    db.add(
        SddTask(
            id="replay-task",
            workspace_id="workspace",
            creator_id="user",
            name="Replay",
            session_generation=1,
            agent_backend="opencode",
            status=TaskStatus.RUNNING,
            status_run_id="replay-job",
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
            session_generation=1,
            session_revision=0,
        )
    )
    db.commit()

    def create():
        with patch.object(TaskAgentEngine, "_create_engine_backend", return_value=Mock()):
            engine = TaskAgentEngine("replay-task", "workspace", "user", job_id="replay-job")
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
async def test_reply_stream_uses_one_message_id_per_segment(db, engine_factory):
    engine = engine_factory()
    engine.cli.capabilities.supports_streaming_text = True

    async def send(kind, text_id, field, text):
        raw = {
            "type": f"session.text.{kind}",
            "data": {
                "assistantMessageID": "reply",
                "textID": text_id,
                field: text,
            },
        }
        await engine.handle_agent_event(map_opencode_event(raw)[0])

    await send("delta", "text-0", "delta", "first ")
    await send("delta", "text-0", "delta", "part")
    await send("delta", "text-1", "delta", "second ")
    drafts = [call.args[1] for call in engine.frontend.push.await_args_list]
    assert [draft["content"] for draft in drafts] == ["first ", "second "]
    assert len({draft["id"] for draft in drafts}) == 2
    assert db.query(ChatMessage).filter_by(task_id="replay-task").count() == 0

    await send("ended", "text-0", "text", "first part")
    await send("ended", "text-1", "text", "second part")
    await send("delta", "text-0", "delta", "late delta")
    await engine.text_stream.finish()
    messages = db.query(ChatMessage).filter_by(task_id="replay-task").order_by(ChatMessage.sort_seq).all()
    assert [(row.id, row.content) for row in messages] == [
        (drafts[0]["id"], "first part"),
        (drafts[1]["id"], "second part"),
    ]
    assert [call.args[0] for call in engine.frontend.push.await_args_list] == [
        "chat_message_stream",
        "chat_message_stream",
        "chat_message",
        "chat_message",
    ]


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
    assert (
        db.query(TaskEventOutbox).filter(TaskEventOutbox.payload_json["id"].as_string() == messages[0].id).count() == 1
    )
    assert await recovered.deliver_confirmation_response(original_id, '{"answer":"yes"}')
    recovered.cli.respond_to_ask_user.assert_awaited_once_with("frm_private", '{"answer":"yes"}')


@pytest.mark.asyncio
@pytest.mark.parametrize("second_opens_before_resolution", [True, False])
async def test_chained_questions_project_from_all_open_interactions(db, engine_factory, second_opens_before_resolution):
    from app.domains.task.services.task_confirmation_service import validate_reply_sync

    engine = engine_factory()
    await engine._on_ask_user({"ask_user_id": "first", "question": "First"})
    assert await engine.deliver_confirmation_response(engine._confirmation_id("first"), "yes")
    resolution = {"ask_user_id": "first", "status": "answered"}
    second = {"ask_user_id": "second", "question": "Second"}
    if second_opens_before_resolution:
        await engine._on_ask_user(second)
        await engine._on_ask_user_resolved(resolution)
    else:
        await engine._on_ask_user_resolved(resolution)
        await engine._on_ask_user(second)

    db.expire_all()
    question = db.query(ChatMessage).filter_by(task_id=engine.task_id, content="Second").one()
    assert db.get(SddTask, engine.task_id).status == TaskStatus.AWAITING_INPUT
    second_id = engine._confirmation_id("second")
    assert validate_reply_sync(db, engine.task_id, second_id, question.id)["job_id"] == engine.current_job_id
    db.rollback()
    await engine._on_ask_user_resolved({"ask_user_id": "second", "status": "cancelled"})
    await engine_factory()._on_ask_user(second)
    db.expire_all()
    assert db.get(SddTask, engine.task_id).status == TaskStatus.RUNNING


@pytest.mark.asyncio
async def test_confirmation_and_its_status_rollback_together(db, engine_factory, monkeypatch):
    from app.domains.task.services import task_confirmation_service as confirmations

    project = confirmations.sync_waiting_status

    def fail_after_transition(*args, **kwargs):
        project(*args, **kwargs)
        raise RuntimeError("simulate a failed confirmation transaction")

    monkeypatch.setattr(confirmations, "sync_waiting_status", fail_after_transition)
    engine = engine_factory()
    with pytest.raises(RuntimeError, match="failed confirmation transaction"):
        await engine._on_ask_user({"ask_user_id": "missing", "question": "Do not commit"})
    assert db.get(SddTask, engine.task_id).status == TaskStatus.RUNNING
    assert db.query(ChatMessage).filter_by(task_id=engine.task_id).count() == 0
    assert db.query(TaskEventOutbox).filter_by(task_id=engine.task_id).count() == 0


@pytest.mark.asyncio
async def test_turn_question_stays_in_snapshot_until_stopped(db, engine_factory):
    from app.domains.task.services import chat_submission_service, task_confirmation_service
    from app.domains.task.services import status_machine as sm

    engine = engine_factory()
    engine.cli.capabilities.hitl_modes = ["turn_based"]
    await engine._on_ask_user({"ask_user_id": "provider-tool-id", "question": "Choose"})
    question = db.query(ChatMessage).filter_by(task_id="replay-task").one()
    interaction = question.metadata_json["confirmation"]["interaction_id"]
    assert question.metadata_json["confirmation"]["delivery_mode"] == "turn"

    task = db.get(SddTask, "replay-task")
    job = db.get(SddAiJob, "replay-job")
    job.status = AiJobStatus.SUCCESS
    sm.execution_event(
        db,
        task,
        task_confirmation_service.round_finished_trigger(db, task, job),
        job_id=job.id,
        event_key="finish",
        generation=1,
        revision=0,
    )
    db.commit()
    state = chat_submission_service.build_session_state(db, task.id, actor_id="user")
    assert state["status"] == "AWAITING_INPUT"
    assert state["status_run_id"] == job.id
    assert [item["id"] for item in state["jobs"]] == [job.id]
    assert [item["id"] for item in state["messages"]] == [question.id]
    assert task_confirmation_service.validate_reply_sync(db, task.id, interaction, question.id)["job_id"] == job.id
    task.session_revision += 1
    db.flush()
    task_confirmation_service.validate_turn_reply(
        db, task.id, {"interaction_id": interaction, "reply_to_message_id": question.id}
    )

    sm.dispatch(db, task, sm.Trigger.INTERRUPT, event_key="stop", actor_id="user")
    with pytest.raises(task_confirmation_service.ConfirmationClosedError):
        task_confirmation_service.validate_reply_sync(db, task.id, interaction, question.id)


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
    pushed = (
        db.query(TaskEventOutbox)
        .filter(
            TaskEventOutbox.payload_json["metadata"]["confirmation_resolution"]["interaction_id"].as_string()
            == interaction
        )
        .one()
        .payload_json
    )
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
