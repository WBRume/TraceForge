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
from app.domains.task.services import task_session_service  # noqa: E402
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


class _EvictedWebSocket(_FakeWebSocket):
    """Sender evicts the connection between frames; Starlette then refuses reads."""

    def __init__(self, manager):
        super().__init__()
        self._manager = manager
        self.receive_calls = 0

    async def receive_json(self):
        self.receive_calls += 1
        self._manager.outbound.dropped = True
        raise RuntimeError('WebSocket is not connected. Need to call "accept" first.')


class _BrokenReadWebSocket(_FakeWebSocket):
    async def receive_json(self):
        raise RuntimeError("unexpected reader failure")


class _RecordingLogger:
    def __init__(self):
        self.errors = []

    def exception(self, *args, **kwargs):
        self.errors.append(args)

    def warning(self, *args, **kwargs):
        pass


class _FakeOutbound:
    """单连接发送器替身：记录 submit_json 的回执。"""

    def __init__(self):
        self.sent_json = []
        self.dropped = False

    def submit_json(self, payload) -> bool:
        if self.dropped:
            return False
        self.sent_json.append(payload)
        return True


class _FakeConnectionManager:
    def __init__(self):
        self.connect_calls = []
        self.disconnect_calls = []
        self.room_messages = []
        self.outbound = _FakeOutbound()

    async def connect(self, websocket, task_id, client_key=None):
        self.connect_calls.append((websocket, task_id))
        return self.outbound

    def disconnect(self, websocket, task_id):
        self.disconnect_calls.append((websocket, task_id))

    async def send_message_to_room(self, task_id, message):
        self.room_messages.append((task_id, message))


def _handler(*, websocket=None, manager=None, session=None):
    websocket = websocket or _FakeWebSocket()
    manager = manager or _FakeConnectionManager()
    session = session or Mock()
    handler = TaskWebSocketHandler(
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
    # 直调 _dispatch 的用例绕过 run()：预先绑定单连接发送器
    handler._outbound = manager.outbound
    return handler


@pytest.mark.asyncio
async def test_run_disconnects_once_when_client_disconnects():
    websocket = _FakeWebSocket(incoming=[{"type": "unknown"}])
    manager = _FakeConnectionManager()
    handler = _handler(websocket=websocket, manager=manager)

    await handler.run()

    assert manager.connect_calls == [(websocket, "task-1")]
    assert manager.disconnect_calls == [(websocket, "task-1")]
    # handler 持有单连接发送器（单写契约）
    assert handler._outbound is manager.outbound


@pytest.mark.asyncio
async def test_run_exits_quietly_when_connection_evicted_between_frames(monkeypatch):
    manager = _FakeConnectionManager()
    websocket = _EvictedWebSocket(manager)
    recorder = _RecordingLogger()
    monkeypatch.setattr(task_handler, "task_logger", recorder)
    handler = _handler(websocket=websocket, manager=manager)

    await handler.run()

    assert websocket.receive_calls == 1
    assert recorder.errors == []
    assert manager.disconnect_calls == [(websocket, "task-1")]


@pytest.mark.asyncio
async def test_run_stops_reading_once_sender_evicted():
    manager = _FakeConnectionManager()
    manager.outbound.dropped = True
    websocket = _EvictedWebSocket(manager)
    handler = _handler(websocket=websocket, manager=manager)

    await handler.run()

    assert websocket.receive_calls == 0
    assert manager.disconnect_calls == [(websocket, "task-1")]


@pytest.mark.asyncio
async def test_run_still_reports_unexpected_read_failure(monkeypatch):
    manager = _FakeConnectionManager()
    recorder = _RecordingLogger()
    monkeypatch.setattr(task_handler, "task_logger", recorder)
    handler = _handler(websocket=_BrokenReadWebSocket(), manager=manager)

    await handler.run()

    assert len(recorder.errors) == 1
    assert manager.disconnect_calls == [(handler._websocket, "task-1")]


@pytest.mark.asyncio
async def test_chat_message_returns_durable_preparation_receipt(monkeypatch):
    from app.domains.task.services import chat_submission_service
    manager = _FakeConnectionManager()
    receipt = {"id": "receipt-1", "task_id": "task-1", "client_message_id": "client-1", "status": "PREPARING"}
    accept = AsyncMock(return_value=receipt)
    monkeypatch.setattr(task_handler, "run_db", AsyncMock(return_value="CODING"))
    monkeypatch.setattr(chat_submission_service, "accept", accept)
    await _handler(manager=manager)._dispatch({"type": "chat_message", "payload": {
        "content": "hello", "client_message_id": "client-1"}})
    assert manager.outbound.sent_json == [{"type": "chat_submission_update", "payload": receipt}]
    assert manager.room_messages == []  # No invented formal chat message before checkpoint.
    accept.assert_awaited_once_with(task_id="task-1", actor_id="user-1",
        client_message_id="client-1", content="hello", metadata={})


@pytest.mark.asyncio
async def test_duplicate_chat_message_returns_existing_receipt(monkeypatch):
    from app.domains.task.services import chat_submission_service
    manager = _FakeConnectionManager()
    receipt = {"id": "receipt-existing", "chat_message_id": "message-existing", "ai_job_id": "job-existing", "status": "EXECUTING"}
    monkeypatch.setattr(task_handler, "run_db", AsyncMock(return_value="CODING"))
    monkeypatch.setattr(chat_submission_service, "accept", AsyncMock(return_value=receipt))
    await _handler(manager=manager)._dispatch({"type": "chat_message", "payload": {
        "content": "hello", "client_message_id": "client-1"}})
    assert manager.outbound.sent_json[0]["payload"] == receipt


@pytest.mark.asyncio
async def test_run_survives_message_handler_exception(monkeypatch):
    websocket = _FakeWebSocket(incoming=[{"type": "chat_message"}, {"type": "unknown"}])
    manager = _FakeConnectionManager()
    handler = _handler(websocket=websocket, manager=manager)
    received = []

    async def _flaky(message):
        received.append(message)
        if len(received) == 1:
            raise RuntimeError("boom")

    monkeypatch.setattr(handler, "_dispatch", _flaky)

    await handler.run()

    assert len(received) == 2
    assert manager.disconnect_calls == [(websocket, "task-1")]


@pytest.mark.asyncio
async def test_unexpected_chat_failure_acks_failed(monkeypatch):
    manager = _FakeConnectionManager()
    claim = SimpleNamespace(claimed=True)
    mark_failed = AsyncMock()

    @asynccontextmanager
    async def _unlocked(_task_id):
        yield

    monkeypatch.setattr(task_handler, "run_db", AsyncMock(return_value="CODING"))
    monkeypatch.setattr(task_handler, "lock_task", _unlocked)
    monkeypatch.setattr(
        task_handler.chat_message_idempotency_service,
        "claim_message",
        AsyncMock(return_value=claim),
    )
    monkeypatch.setattr(
        task_handler.chat_message_idempotency_service,
        "mark_message_failed",
        mark_failed,
    )
    monkeypatch.setattr(
        task_handler.task_session_service,
        "create_task_chat_turn",
        AsyncMock(side_effect=RuntimeError("checkpoint failed")),
    )

    handler = _handler(manager=manager)
    with pytest.raises(RuntimeError):
        await handler._persist_chat_message(
            SimpleNamespace(content="hello", client_message_id="client-1", metadata={}), claim,
        )

    mark_failed.assert_awaited_once_with(claim)
    ack = manager.outbound.sent_json[0]
    assert ack["type"] == "chat_message_ack"
    assert ack["payload"]["status"] == "failed"
    assert ack["payload"]["client_message_id"] == "client-1"


@pytest.mark.asyncio
async def test_deprecated_hitl_response_is_ignored(monkeypatch):
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

    resume_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_durable_chat_turn_is_enqueued_when_ack_connection_is_closed(monkeypatch):
    enqueue = AsyncMock()
    monkeypatch.setattr(
        task_handler.ai_job_service,
        "enqueue_task_chat_job",
        enqueue,
    )
    created = task_session_service.CreatedChatTurn(
        task_id="task-1",
        workspace_id="ws-1",
        message_id="message-1",
        created_at=datetime(2026, 9, 2, 9, 30),
        session_turn_id="turn-1",
        session_generation=3,
        job_id="job-1",
    )
    request = task_handler._ChatMessageRequest(
        content="hello",
        client_message_id="client-1",
    )

    # 回执连接已死（outbound dropped）：不再抛断连异常，turn 仍然入队
    manager = _FakeConnectionManager()
    manager.outbound.dropped = True
    handler = _handler(manager=manager)
    await handler._publish_chat_message(request, created)

    enqueue.assert_awaited_once_with("job-1")
    assert manager.outbound.sent_json == []
