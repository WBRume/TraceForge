"""Focused tests for the task WebSocket connection and chat protocol."""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import WebSocketDisconnect


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.task.models.task import TaskStatus  # noqa: E402
from app.domains.websocket.ws import task_handler  # noqa: E402
from app.domains.websocket.ws.task_handler import (  # noqa: E402
    TaskWebSocketHandler,
    TaskWebSocketUser,
)


class _FakeWebSocket:
    def __init__(self, incoming=None):
        self.incoming = list(incoming or [])
        self.sent_json = []

    async def receive_json(self):
        if self.incoming:
            return self.incoming.pop(0)
        raise WebSocketDisconnect()

    async def send_json(self, payload):
        self.sent_json.append(payload)


class _DisconnectedWebSocket(_FakeWebSocket):
    async def send_json(self, payload):
        raise WebSocketDisconnect()


class _FakeConnectionManager:
    def __init__(self):
        self.connect_calls = []
        self.disconnect_calls = []
        self.room_messages = []

    async def connect(self, websocket, task_id):
        self.connect_calls.append((websocket, task_id))

    def disconnect(self, websocket, task_id):
        self.disconnect_calls.append((websocket, task_id))

    async def send_message_to_room(self, task_id, message):
        self.room_messages.append((task_id, message))


def _handler(*, websocket=None, manager=None, session=None):
    websocket = websocket or _FakeWebSocket()
    manager = manager or _FakeConnectionManager()
    session = session or Mock()
    return TaskWebSocketHandler(
        websocket,
        "task-1",
        TaskWebSocketUser(
            id="user-1",
            display_name="User One",
            is_workspace_expert=True,
            avatar_url="avatar.png",
        ),
        session_factory=lambda: session,
        connection_manager=manager,
    )


@pytest.mark.asyncio
async def test_run_disconnects_once_when_client_disconnects():
    websocket = _FakeWebSocket(incoming=[{"type": "unknown"}])
    manager = _FakeConnectionManager()

    await _handler(websocket=websocket, manager=manager).run()

    assert manager.connect_calls == [(websocket, "task-1")]
    assert manager.disconnect_calls == [(websocket, "task-1")]


@pytest.mark.asyncio
async def test_chat_message_is_acked_broadcast_and_enqueued(monkeypatch):
    websocket = _FakeWebSocket()
    manager = _FakeConnectionManager()
    db = Mock()
    task = SimpleNamespace(id="task-1", status=TaskStatus.CODING)
    db.query.return_value.filter.return_value.first.return_value = task

    claim = SimpleNamespace(claimed=True)
    saved_message = SimpleNamespace(
        id="message-1",
        created_at=datetime(2026, 9, 2, 9, 30),
        session_turn_id="turn-1",
        session_generation=3,
    )
    job = SimpleNamespace(id="job-1")
    claim_message = AsyncMock(return_value=claim)
    mark_done = AsyncMock()
    create_turn = AsyncMock(return_value=(Mock(), saved_message, job, Mock()))
    enqueue = AsyncMock()

    @asynccontextmanager
    async def _unlocked(_task_id):
        yield

    monkeypatch.setattr(task_handler, "lock_task", _unlocked)
    monkeypatch.setattr(
        task_handler.chat_message_idempotency_service,
        "claim_message",
        claim_message,
    )
    monkeypatch.setattr(
        task_handler.chat_message_idempotency_service,
        "mark_message_done",
        mark_done,
    )
    monkeypatch.setattr(
        task_handler.task_session_service,
        "create_task_chat_turn",
        create_turn,
    )
    monkeypatch.setattr(
        task_handler.ai_job_service,
        "enqueue_task_chat_job",
        enqueue,
    )

    handler = _handler(websocket=websocket, manager=manager, session=db)
    await handler._dispatch(
        {
            "type": "chat_message",
            "payload": {"content": "hello", "client_message_id": "client-1"},
        }
    )

    ack = websocket.sent_json[0]
    assert ack["type"] == "chat_message_ack"
    assert ack["payload"]["status"] == "accepted"
    assert ack["payload"]["client_message_id"] == "client-1"
    assert ack["payload"]["chat_message_id"] == "message-1"
    assert ack["payload"]["ai_job_id"] == "job-1"

    assert len(manager.room_messages) == 1
    task_id, event = manager.room_messages[0]
    assert task_id == "task-1"
    assert event.type == "chat_message"
    assert event.payload["content"] == "hello"
    assert event.payload["creator_id"] == "user-1"
    assert event.payload["session_turn_id"] == "turn-1"
    enqueue.assert_awaited_once_with("job-1")
    db.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_duplicate_chat_message_returns_existing_identifiers(monkeypatch):
    websocket = _FakeWebSocket()
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(id="task-1")
    claim = SimpleNamespace(
        claimed=False,
        status="done",
        existing={
            "chat_message_id": "message-existing",
            "ai_job_id": "job-existing",
            "finished_at": "2026-09-02T09:30:00",
        },
    )
    monkeypatch.setattr(
        task_handler.chat_message_idempotency_service,
        "claim_message",
        AsyncMock(return_value=claim),
    )

    await _handler(websocket=websocket, session=db)._dispatch(
        {
            "type": "chat_message",
            "payload": {"content": "hello", "client_message_id": "client-1"},
        }
    )

    ack = websocket.sent_json[0]["payload"]
    assert ack["status"] == "duplicate"
    assert ack["chat_message_id"] == "message-existing"
    assert ack["ai_job_id"] == "job-existing"
    assert ack["created_at"] == "2026-09-02T09:30:00"
    db.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_hitl_response_resumes_waiting_job(monkeypatch):
    resume_job = AsyncMock(return_value=True)
    monkeypatch.setattr(
        task_handler.ai_job_service,
        "resume_waiting_hitl_job",
        resume_job,
    )

    await _handler()._dispatch(
        {
            "type": "hitl_response",
            "payload": {"response": "  approved  ", "job_id": 42},
        }
    )

    resume_job.assert_awaited_once_with(
        task_id="task-1",
        response="approved",
        job_id="42",
    )


@pytest.mark.asyncio
async def test_durable_chat_turn_is_enqueued_when_ack_connection_is_closed(monkeypatch):
    enqueue = AsyncMock()
    monkeypatch.setattr(
        task_handler.ai_job_service,
        "enqueue_task_chat_job",
        enqueue,
    )
    saved_message = SimpleNamespace(
        id="message-1",
        created_at=datetime(2026, 9, 2, 9, 30),
        session_turn_id="turn-1",
        session_generation=3,
    )
    request = task_handler._ChatMessageRequest(
        content="hello",
        client_message_id="client-1",
    )
    created = task_handler._CreatedChatTurn(message=saved_message, job_id="job-1")

    with pytest.raises(WebSocketDisconnect):
        await _handler(websocket=_DisconnectedWebSocket())._publish_chat_message(
            request,
            created,
        )

    enqueue.assert_awaited_once_with("job-1")
