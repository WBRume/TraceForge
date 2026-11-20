"""Recovery and delivery invariants for a live confirmation answer."""

from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.agents.errors import AgentInteractionClosedError, AgentInteractionDeliveryUncertain
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.ai.services import ai_job_convergence_service
from app.domains.ai.services.jobs.executors import task_chat
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.confirmation_reply import TaskConfirmationReply
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.models.task_event_outbox import TaskEventOutbox
from app.domains.task.services import live_confirmation_service as replies
from app.domains.task.services import task_confirmation_service, task_session_turn_service
from tests.task.test_task_session_interrupt_resume import _seed_task


@pytest.fixture
def question(db, monkeypatch):
    task, job = _seed_task(db, task_status=TaskStatus.AWAITING_INPUT)
    db.add(
        ChatMessage(
            id="question",
            task_id=task.id,
            workspace_id=task.workspace_id,
            creator_id=task.creator_id,
            content="Choose a value",
            role="assistant",
            session_generation=task.session_generation,
            metadata_json={
                "confirmation": {
                    "job_id": job.id,
                    "interaction_id": "interaction",
                    "kind": "form",
                    "delivery_mode": "live",
                    "fields": [{"key": "answer", "type": "string"}],
                }
            },
        )
    )
    request = replies.ReplyRequest(task.id, task.creator_id, "reply-1", "interaction", "question", "yes", "yes")
    db.commit()
    sessions = sessionmaker(bind=db.get_bind(), autoflush=False)

    async def txn(body):
        with sessions.begin() as session:
            return body(session)

    monkeypatch.setattr(replies, "run_db_txn", txn)
    monkeypatch.setattr(replies, "_delivery_outcomes", {})
    return request


@pytest.mark.asyncio
@pytest.mark.parametrize("fault_point", ["outcome", "message"])
async def test_post_acceptance_rollback_recovers_without_redelivering(db, monkeypatch, question, fault_point):
    def assert_durable_intent(**kwargs):
        intent = db.query(TaskConfirmationReply).one()
        assert intent.status == "SENDING" and intent.content == kwargs["response"] == question.content
        assert kwargs["job_id"] == "job-1"
        db.rollback()
        return True

    provider = AsyncMock(side_effect=assert_durable_intent)
    monkeypatch.setattr(task_chat, "deliver_confirmation_response", provider)
    owner, method = (
        (replies, "_record_outcome")
        if fault_point == "outcome"
        else (task_session_turn_service, "persist_confirmation_reply")
    )
    original = getattr(owner, method)

    def reject_commit(*args, **kwargs):
        original(*args, **kwargs)
        raise OperationalError(None, None, RuntimeError("injected database write failure"))

    with monkeypatch.context() as fault:
        fault.setattr(owner, method, reject_commit)
        assert (await replies.submit(question)).status == "processing"
        db.expire_all()
        assert db.query(TaskConfirmationReply).one().status == ("SENDING" if fault_point == "outcome" else "ACCEPTED")
        assert db.query(ChatMessage).filter_by(role="user").count() == 0
        assert db.get(SddTask, question.task_id).status == TaskStatus.AWAITING_INPUT
        db.rollback()

    await replies.recover()
    duplicate = await replies.submit(question)
    assert duplicate.status == "duplicate"
    provider.assert_awaited_once()
    db.expire_all()
    assert db.query(TaskConfirmationReply).one().status == "DELIVERED"
    message = db.query(ChatMessage).filter_by(role="user").one()
    assert duplicate.message["id"] == message.id
    assert message.metadata_json["client_message_id"] == question.client_id
    assert db.get(SddTask, question.task_id).status == TaskStatus.RUNNING
    assert db.query(TaskEventOutbox).filter(TaskEventOutbox.payload_json["id"].as_string() == message.id).count() == 1
    with pytest.raises(task_confirmation_service.ConfirmationClosedError, match="different answer"):
        await replies.submit(replace(question, value="altered"))


@pytest.mark.asyncio
async def test_definitive_provider_rejection_leaves_question_open_for_another_try(db, monkeypatch, question):
    provider = AsyncMock(side_effect=[AgentInteractionClosedError("Rejected"), True])
    monkeypatch.setattr(task_chat, "deliver_confirmation_response", provider)
    assert (await replies.submit(question)).status == "failed"
    assert (await replies.submit(question)).status == "failed"
    assert db.query(ChatMessage).filter_by(role="user").count() == 0
    assert db.get(SddTask, question.task_id).status == TaskStatus.AWAITING_INPUT
    db.rollback()
    assert (await replies.submit(replace(question, client_id="reply-2"))).status == "accepted"
    assert provider.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("native_answer", ["yes", "other"])
async def test_lost_provider_ack_requires_matching_evidence(db, monkeypatch, question, native_answer):
    provider = AsyncMock(side_effect=AgentInteractionDeliveryUncertain("Network dropped the response"))
    monkeypatch.setattr(task_chat, "deliver_confirmation_response", provider)
    assert (await replies.submit(question)).status == "processing"
    assert (await replies.submit(question)).status == "processing"
    with pytest.raises(task_confirmation_service.ConfirmationClosedError, match="already being confirmed"):
        await replies.submit(replace(question, client_id="other-client"))
    provider.assert_awaited_once()
    intent = db.query(TaskConfirmationReply).one()
    job = db.get(SddAiJob, intent.job_id)
    replies.observe_resolution(
        db, job, {"interaction_id": question.interaction_id, "status": "answered", "answer": {"answer": native_answer}}
    )
    if native_answer != "yes":
        intent.updated_at = datetime.utcnow() - timedelta(minutes=3)
        job.status = AiJobStatus.SUCCESS
        ai_job_convergence_service._converge_task_status_in_txn(db, job, job.status)
    db.commit()

    await replies.recover()
    db.expire_all()
    assert intent.status == ("DELIVERED" if native_answer == "yes" else "FAILED")
    assert db.query(ChatMessage).filter_by(role="user").count() == int(native_answer == "yes")
    if native_answer != "yes":
        assert db.get(SddTask, question.task_id).status == TaskStatus.ROUND_COMPLETED


@pytest.mark.asyncio
async def test_reply_persisted_after_run_finishes_does_not_restart_task(db, monkeypatch, question):
    async def finish_before_ack(**kwargs):
        job = db.get(SddAiJob, kwargs["job_id"])
        job.status = AiJobStatus.SUCCESS
        ai_job_convergence_service._converge_task_status_in_txn(db, job, job.status)
        db.commit()
        return True

    monkeypatch.setattr(task_chat, "deliver_confirmation_response", finish_before_ack)
    result = await replies.submit(question)
    assert result.status == "accepted"
    assert db.get(SddTask, question.task_id).status == TaskStatus.ROUND_COMPLETED
    assert db.query(ChatMessage).filter_by(role="user").one().id == result.message["id"]
