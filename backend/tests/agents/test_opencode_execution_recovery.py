"""Fault injection for durable OpenCode observation; no model calls."""

import asyncio
import json
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from app.agents.activity_watchdog import AgentActivityWatchdog
from app.agents.adapters.opencode.execution import ExecutionMonitor, turn_messages
from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
from app.agents.contract import AgentRunRequest, AgentStopResult
from app.agents.errors import AgentExecutionDetached, AgentTimeoutError
from app.config import Settings, settings


class Provider:
    def __init__(self, *, finish_after=0.05, active=True, disconnects=0, lost_response=False):
        self.finish_after = finish_after
        self.active = active
        self.disconnects = disconnects
        self.lost_response = lost_response
        self.posts = 0
        self.streams = 0
        self.closed = 0
        self.probes = 0
        self.prompt_id = None
        self.started = time.monotonic()
        self.outcome = "succeeded"
        self.forms = []
        self.unavailable = False

    @property
    def done(self):
        return self.prompt_id and time.monotonic() - self.started >= self.finish_after

    def messages(self):
        rows = [{"id": "msg_old_idle", "type": "idle", "outcome": "succeeded"}]
        if self.prompt_id:
            rows.append({"type": "user", "id": self.prompt_id})
        if self.done:
            rows.extend(
                [
                    {
                        "id": "msg_answer",
                        "type": "assistant",
                        "time": {"completed": 123},
                        "content": [{"type": "text", "text": "finished"}],
                        "finish": "stop",
                    },
                    {"id": "msg_idle", "type": "idle", "outcome": self.outcome},
                ]
            )
        return rows

    def handle(self, request):
        if self.unavailable:
            raise httpx.ConnectError("connection lost", request=request)
        path = request.url.path
        if path == "/api/event":
            self.streams += 1
            provider, stream_number = self, self.streams

            class Stream(httpx.AsyncByteStream):
                async def __aiter__(self):
                    yield b'data: {"type":"server.connected","data":{}}\n\n'
                    if stream_number <= provider.disconnects:
                        return
                    # No terminal SSE: recovery must consult durable messages.
                    while True:
                        await asyncio.sleep(0.005)
                        yield b'data: {"type":"server.heartbeat","data":{}}\n\n'

                async def aclose(self):
                    provider.closed += 1

            return httpx.Response(200, stream=Stream())
        if path.endswith("/prompt"):
            self.posts += 1
            self.prompt_id = json.loads(request.content)["id"]
            if self.lost_response and self.posts == 1:
                raise httpx.ReadTimeout("accepted but response lost", request=request)
            return httpx.Response(200, json={"data": {"id": self.prompt_id}})
        if path.endswith("/message"):
            self.probes += 1
            return httpx.Response(200, json={"data": self.messages(), "cursor": {}})
        if path.endswith("/active"):
            active = {"ses_test": {"type": "running"}} if self.active and not self.done else {}
            return httpx.Response(200, json={"data": active})
        if path.endswith("/form"):
            return httpx.Response(200, json={"data": self.forms})
        if path.endswith(("/permission", "/inbox")):
            return httpx.Response(200, json={"data": []})
        raise AssertionError((request.method, path))


def checkpoint(provider, *, phase="submitted", remaining=100):
    provider.prompt_id = "msg_original"
    return {
        "version": 1,
        "session_id": "ses_test",
        "prompt_id": provider.prompt_id,
        "deadline": time.time() + remaining,
        "phase": phase,
    }


@pytest.fixture
def fast_reconcile(monkeypatch):
    monkeypatch.setattr(settings, "OPENCODE_RECONCILE_INTERVAL_SECONDS", 0.01)


async def execute(provider, **kwargs):
    adapter = OpenCodeAdapter("http://agent")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(provider.handle))
    adapter.interrupt = AsyncMock(return_value=AgentStopResult(execution_kind="REMOTE_SESSION", stop_acknowledged=True))
    events = []

    async def collect(event):
        events.append(event)

    request = AgentRunRequest(
        prompt="work", session_id="ses_test", idle_timeout_seconds=0.05, timeout_seconds=5, **kwargs
    )
    try:
        result = await asyncio.wait_for(adapter.run(request, collect), 4)
        return result, events, adapter
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_eof_reconnects_without_submitting_again(fast_reconcile):
    provider = Provider(disconnects=1, finish_after=1.4)
    result, events, _ = await execute(provider)
    assert result.success
    assert provider.streams >= 2
    assert provider.posts == 1
    assert provider.closed == provider.streams
    assert [e.payload["text"] for e in events if e.type == "text"] == ["finished"]


@pytest.mark.asyncio
async def test_lost_admission_response_reconciles_instead_of_resubmitting(fast_reconcile):
    provider = Provider(lost_response=True)
    result, _, _ = await execute(provider)
    assert result.success
    assert provider.posts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["succeeded", "failed", "interrupted"])
async def test_missing_terminal_sse_converges_from_this_input(outcome, fast_reconcile):
    provider = Provider()
    provider.outcome = outcome
    result, events, _ = await execute(provider)
    assert result.success is (outcome == "succeeded")
    assert result.finish_reason == {"succeeded": "completed", "failed": "error", "interrupted": "interrupted"}[outcome]
    assert len([e for e in events if e.type == "result"]) == 1


@pytest.mark.asyncio
async def test_long_silent_tool_survives_many_idle_windows(fast_reconcile):
    provider = Provider(finish_after=0.3)
    result, _, adapter = await execute(provider)
    assert result.success and provider.probes >= 5
    adapter.interrupt.assert_not_awaited()


@pytest.mark.asyncio
async def test_transport_heartbeat_does_not_prove_execution_alive(fast_reconcile):
    provider = Provider(finish_after=100, active=False)
    with pytest.raises(AgentTimeoutError) as error:
        await execute(provider)
    assert error.value.phase == "idle"
    assert provider.closed == provider.streams


@pytest.mark.asyncio
async def test_restart_keeps_original_input_and_deadline_after_nine_hours(fast_reconcile):
    provider = Provider()
    original = checkpoint(provider, remaining=15 * 3600)  # 24h limit, 9h already elapsed.
    saved = []

    async def save(value):
        saved.append(value)

    result, _, _ = await execute(provider, execution_checkpoint=original, on_execution_checkpoint=save)
    assert result.success and provider.posts == 0
    assert saved and all(row == original for row in saved)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["submitting", "submitted"])
async def test_completion_while_backend_down_wins_over_expired_deadline(fast_reconcile, phase):
    provider = Provider(finish_after=0)
    result, _, adapter = await execute(provider, execution_checkpoint=checkpoint(provider, remaining=-10, phase=phase))
    assert result.success and provider.posts == 0 and provider.streams == 0
    adapter.interrupt.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_recovery_does_not_grant_another_runtime_budget(fast_reconcile):
    provider = Provider(finish_after=100)
    with pytest.raises(AgentTimeoutError) as error:
        await execute(provider, execution_checkpoint=checkpoint(provider, remaining=-10))
    assert error.value.phase == "hard"
    assert provider.posts == 0


@pytest.mark.asyncio
async def test_expired_unsubmitted_recovery_never_enqueues_input(fast_reconcile):
    provider = Provider(finish_after=100)
    saved = checkpoint(provider, phase="submitting", remaining=-10)
    provider.prompt_id = None
    with pytest.raises(AgentTimeoutError):
        await execute(provider, execution_checkpoint=saved)
    assert provider.posts == 0


@pytest.mark.asyncio
async def test_lost_owner_cannot_submit_or_interrupt_remote_session(fast_reconcile):
    provider = Provider()

    async def reject(_):
        raise AgentExecutionDetached("replaced owner")

    with pytest.raises(AgentExecutionDetached):
        await execute(provider, execution_checkpoint=checkpoint(provider), on_execution_checkpoint=reject)
    assert provider.posts == provider.probes == provider.streams == 0


@pytest.mark.asyncio
async def test_cancellation_closes_sse_without_interrupting_provider(fast_reconcile):
    provider = Provider(finish_after=100)
    task = asyncio.create_task(execute(provider))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert provider.posts == 1 and provider.closed == provider.streams


@pytest.mark.asyncio
async def test_snapshot_does_not_duplicate_text_already_delivered_by_sse():
    provider = Provider(finish_after=0)
    adapter = OpenCodeAdapter("http://agent")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(provider.handle))
    events = []

    async def collect(event):
        events.append(event)

    monitor = ExecutionMonitor(adapter, "ses_test", AgentRunRequest(execution_checkpoint=checkpoint(provider)), collect)
    try:
        await monitor.handle_event(
            {
                "type": "session.text.ended",
                "data": {
                    "sessionID": "ses_test",
                    "assistantMessageID": "msg_answer",
                    "textID": "text-0",
                    "text": "finished",
                },
            }
        )
        assert (await monitor.reconcile())["success"]
        assert (await monitor.reconcile())["success"]
        assert len([e for e in events if e.type == "text"]) == 1
    finally:
        await adapter.close()


def test_previous_idle_and_next_user_do_not_complete_our_input():
    assert turn_messages([{"type": "idle", "outcome": "succeeded"}], "msg_new") == []
    rows = [
        {"id": "msg_new", "type": "user"},
        {"id": "msg_other", "type": "user"},
        {"type": "idle", "outcome": "succeeded"},
    ]
    assert turn_messages(rows, "msg_new") == []


def test_nine_hour_execution_is_alive_and_hard_limit_remains_bounded():
    watch = AgentActivityWatchdog(startup_timeout_seconds=60, idle_timeout_seconds=600, hard_timeout_seconds=86400)
    watch._started_at -= 9 * 3600
    watch.confirm_remote_liveness()
    assert watch._next_timeout()[2] > 0
    watch.pause_idle()
    assert 14 * 3600 < watch._next_timeout()[2] <= 15 * 3600
    watch._started_at -= 16 * 3600
    assert watch._next_timeout()[0] == "hard" and watch._next_timeout()[2] < 0


def test_human_readable_runtime_units_and_invalid_values():
    required = {"DB_PASSWORD": "test", "JWT_SECRET_KEY": "test-secret-for-validation"}
    config = Settings(_env_file=None, **required, AGENT_MAX_RUNTIME_HOURS=36, AGENT_IDLE_TIMEOUT_MINUTES=15)
    assert config.agent_max_runtime_seconds == 129600
    assert config.agent_idle_timeout_seconds == 900
    for value in (0, -1, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            Settings(_env_file=None, **required, AGENT_MAX_RUNTIME_HOURS=value)
