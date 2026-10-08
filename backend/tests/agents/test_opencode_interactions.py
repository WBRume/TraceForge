"""Native interaction completion, durable replay, and late reply races."""

import copy

import httpx
import pytest

from app.agents.adapters.opencode.execution import ExecutionMonitor
from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
from app.agents.contract import AgentRunRequest
from app.agents.errors import AgentError, AgentInteractionClosedError


def form():
    return {"id": "frm_test", "sessionID": "ses_test", "title": "Choose", "fields": [{"key": "q0", "type": "string"}]}


def create_monitor(handler, checkpoint=None):
    adapter = OpenCodeAdapter("http://agent")
    adapter._session_id = "ses_test"
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    events, checkpoints = [], []

    async def collect(event):
        if event.type == "ask_user":
            adapter._pending_asks.add(event.payload["ask_user_id"])
        events.append(event)

    async def save(value):
        checkpoints.append(copy.deepcopy(value))

    request = AgentRunRequest(prompt="test", execution_checkpoint=checkpoint or {}, on_execution_checkpoint=save)
    monitor = ExecutionMonitor(adapter, "ses_test", request, collect)
    monitor.checkpoint["phase"] = "submitted"
    adapter._execution_monitor = monitor
    return adapter, monitor, events, checkpoints


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,data,status",
    [
        ("form.replied", {"id": "frm_test", "answer": {"q0": "A"}}, "answered"),
        ("form.cancelled", {"id": "frm_test"}, "cancelled"),
        ("permission.replied", {"requestID": "per_test", "reply": "always"}, "approved"),
        ("permission.replied", {"requestID": "per_test", "reply": "reject"}, "rejected"),
    ],
)
async def test_terminal_events_clear_wait_and_publish_once(kind, data, status):
    adapter, monitor, events, checkpoints = create_monitor(lambda r: httpx.Response(200, json={"data": []}))
    rid = data.get("id") or data["requestID"]
    adapter._pending_asks.add(rid)
    event = {"type": kind, "data": {"sessionID": "ses_test", **data}}
    try:
        await monitor.handle_event(event)
        await monitor.handle_event(event)
        assert not adapter._pending_asks
        assert len(events) == 1
        assert events[0].type == "ask_user_resolved"
        assert events[0].payload["status"] == status
        assert checkpoints[-1]["interactions"][rid]["resolution"]["status"] == status
    finally:
        await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [{"status": "answered", "answer": {"q0": "A"}}, {"status": "cancelled"}, None])
async def test_worker_restart_recovers_answer_or_closes_expired_form(state):
    def handler(request):
        if request.url.path.endswith("/frm_test"):
            return (
                httpx.Response(404) if state is None else httpx.Response(200, json={"data": {**form(), "state": state}})
            )
        return httpx.Response(200, json={"data": []})

    first, monitor, _, checkpoints = create_monitor(handler)
    await monitor.handle_event({"type": "form.created", "data": {"form": form()}})
    await first.close()
    adapter, recovered, events, _ = create_monitor(handler, checkpoints[-1])
    try:
        await recovered.restore_asks()
        assert [event.type for event in events] == ["ask_user", "ask_user_resolved"]
        resolution = events[-1].payload
        assert resolution["status"] == (state["status"] if state else "closed")
        assert resolution["answer"] == (state.get("answer") if state else None)
        assert not adapter._pending_asks
        await recovered.restore_asks()
        assert len(events) == 2
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_transport_failure_does_not_invent_a_resolution():
    adapter, monitor, events, _ = create_monitor(lambda r: httpx.Response(503))
    try:
        await monitor.handle_event({"type": "form.created", "data": {"form": form()}})
        with pytest.raises(httpx.HTTPStatusError):
            await monitor.restore_asks()
        assert [event.type for event in events] == ["ask_user"]
        assert adapter._pending_asks == {"frm_test"}
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_settled_checkpoint_replays_without_querying_expired_result():
    adapter, monitor, events, checkpoints = create_monitor(lambda r: httpx.Response(200, json={"data": []}))
    await monitor.handle_event(
        {"type": "form.replied", "data": {"sessionID": "ses_test", "id": "frm_test", "answer": {"q0": "A"}}}
    )
    await adapter.close()
    adapter, recovered, events, _ = create_monitor(lambda r: httpx.Response(200, json={"data": []}), checkpoints[-1])
    try:
        await recovered.restore_asks()
        assert events[-1].payload["answer"] == {"q0": "A"}
    finally:
        await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("race", [False, True])
async def test_late_answer_is_rejected_and_authoritative_answer_is_published(race):
    posts = []

    def handler(request):
        if request.method == "POST":
            posts.append(request)
            return httpx.Response(409)
        state = {"status": "pending"} if race and not posts else {"status": "answered", "answer": {"q0": "external"}}
        return httpx.Response(200, json={"data": {**form(), "state": state}})

    adapter, monitor, events, _ = create_monitor(handler)
    try:
        await monitor.handle_event({"type": "form.created", "data": {"form": form()}})
        with pytest.raises(AgentInteractionClosedError):
            await adapter.respond_to_ask_user("frm_test", '{"q0":"late"}')
        assert len(posts) == int(race)
        assert events[-1].payload["answer"] == {"q0": "external"}
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_uncertain_reply_delivery_is_reported_without_fabricating_an_answer():
    def handler(request):
        if request.method == "POST":
            raise httpx.ReadTimeout("reply response lost")
        return httpx.Response(200, json={"data": form()})

    adapter, monitor, events, _ = create_monitor(handler)
    try:
        await monitor.handle_event({"type": "form.created", "data": {"form": form()}})
        with pytest.raises(AgentError, match="could not be confirmed"):
            await adapter.respond_to_ask_user("frm_test", '{"q0":"A"}')
        assert [event.type for event in events] == ["ask_user"]
        assert adapter._pending_asks == {"frm_test"}
    finally:
        await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "active,inbox,owned,completed,interrupted",
    [
        (False, False, True, True, True),
        (True, False, True, True, False),
        (False, True, True, True, False),
        (False, False, False, True, False),
        (False, False, True, False, False),
    ],
)
async def test_cancelled_tool_without_idle_requires_owned_completed_turn_and_quiescent_session(
    active, inbox, owned, completed, interrupted
):
    def handler(request):
        path = request.url.path
        if path.endswith("/message"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "msg_owned" if owned else "msg_other", "type": "user"},
                        {
                            "id": "msg_answer",
                            "type": "assistant",
                            "finish": "error",
                            "time": {"completed": 123 if completed else None},
                            "content": [
                                {
                                    "id": "tool",
                                    "type": "tool",
                                    "state": {
                                        "status": "error",
                                        "error": {"type": "aborted", "message": "The user dismissed this question"},
                                    },
                                },
                            ],
                        },
                    ],
                    "cursor": {},
                },
            )
        if path.endswith("/active"):
            return httpx.Response(200, json={"data": {"ses_test": {}} if active else {}})
        if path.endswith("/inbox"):
            return httpx.Response(200, json={"data": [{"id": "msg_owned"}] if inbox else []})
        return httpx.Response(200, json={"data": []})

    adapter, monitor, _, _ = create_monitor(handler)
    monitor.checkpoint["prompt_id"] = "msg_owned"
    try:
        result = await monitor.reconcile()
        assert result == ({"success": False, "finish_reason": "interrupted"} if interrupted else None)
    finally:
        await adapter.close()
