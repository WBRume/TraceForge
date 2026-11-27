import base64

import httpx
import pytest

from app.agents import selection
from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
from app.domains.ai.services.jobs.reaper import stop_remote_session


@pytest.mark.asyncio
@pytest.mark.parametrize("response_kind", ["ack", "rejected", "unreachable"])
async def test_reaper_stops_explicit_session_with_fresh_authenticated_adapter(monkeypatch, response_kind):
    requests = []
    clients = []
    real_client = httpx.AsyncClient

    def handler(request):
        requests.append(request)
        if response_kind == "unreachable":
            raise httpx.ConnectError("provider unavailable", request=request)
        if request.url.path == "/api/session/ses_persisted/interrupt":
            assert request.url.params["resume"] == "false"
            return httpx.Response(200, json={"interrupted": False}) if response_kind == "ack" else httpx.Response(503)
        assert request.url.path == "/api/session/active"
        return httpx.Response(200, json={"data": {}})

    def client_factory(**kwargs):
        client = real_client(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    adapter = OpenCodeAdapter("http://provider", username="acceptance", password="test-secret")
    adapter._session_id = "ses_unrelated"
    assert adapter._client is None
    monkeypatch.setattr(selection, "create_agent_backend_by_name", lambda *args, **kwargs: adapter)

    result = await stop_remote_session({"agent_backend": "opencode", "session_id": "ses_persisted", "task_id": "task"})

    assert result.stop_acknowledged is (response_kind == "ack")
    assert result.execution_kind == "REMOTE_SESSION"
    assert len(clients) == 1 and clients[0].is_closed
    assert adapter._client is None
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/api/session/ses_persisted/interrupt"
    assert requests[0].headers["authorization"] == "Basic " + base64.b64encode(b"acceptance:test-secret").decode()
    assert [r.method for r in requests] == (["POST", "GET"] if response_kind == "ack" else ["POST"])
    if response_kind != "ack":
        assert result.failure_code == (
            "OPENCODE_ABORT_REJECTED" if response_kind == "rejected" else "OPENCODE_ABORT_NETWORK_ERROR"
        )


@pytest.mark.asyncio
async def test_missing_persisted_identity_does_not_connect(monkeypatch):
    adapter = OpenCodeAdapter()

    def forbidden(**kwargs):
        pytest.fail("Missing identity must not create a connection")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    result = await adapter.cancel_persisted_session("  ")
    assert not result.stop_acknowledged
    assert result.failure_code == "REMOTE_STOP_LOCATOR_MISSING"


@pytest.mark.asyncio
async def test_ordinary_interrupt_after_close_does_not_reopen_transport(monkeypatch):
    adapter = OpenCodeAdapter()
    await adapter.close()

    def forbidden(**kwargs):
        pytest.fail("Only explicit durable cleanup may reconnect a closed adapter")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    result = await adapter.interrupt(session_id="ses_old")
    assert not result.stop_acknowledged


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("phase", "transcript", "queued", "expected_ack", "abort_session"),
    [
        ("submitted", ["previous"], True, True, False),
        ("submitting", ["previous"], True, True, False),
        ("submitting", ["previous"], False, False, False),
        ("submitted", ["previous", "owned"], False, True, True),
        ("submitted", ["owned", "idle", "next"], False, True, False),
        ("submitted", ["owned", "next"], False, False, False),
        ("prepared", ["previous"], False, True, False),
        ("rejected", ["previous"], False, True, False),
    ],
)
async def test_stop_proves_the_owned_prompt_before_interrupting_the_session(
    phase, transcript, queued, expected_ack, abort_session
):
    calls = []

    def native(request):
        calls.append((request.method, request.url.path))
        if request.method == "DELETE":
            assert request.url.path.endswith("/inbox/owned")
            return httpx.Response(204)
        if request.url.path.endswith("/inbox"):
            return httpx.Response(200, json={"data": [{"id": "owned"}] if queued else []})
        if request.url.path.endswith("/message"):
            rows = [
                {"id": item, "type": "idle", "outcome": "succeeded"} if item == "idle" else {"id": item, "type": "user"}
                for item in transcript
            ]
            return httpx.Response(200, json={"data": rows, "cursor": {}})
        if request.url.path.endswith("/interrupt"):
            return httpx.Response(200, json={"interrupted": True})
        assert request.url.path.endswith("/active")
        return httpx.Response(200, json={"data": {}})

    adapter = OpenCodeAdapter("http://provider")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(native))
    adapter._session_id = "ses_owned"
    adapter._execution_checkpoint = {"session_id": "ses_owned", "prompt_id": "owned", "phase": phase}
    try:
        result = await adapter.interrupt()
    finally:
        await adapter.close()

    assert result.stop_acknowledged is expected_ack
    assert (("POST", "/api/session/ses_owned/interrupt") in calls) is abort_session
    assert (("DELETE", "/api/session/ses_owned/inbox/owned") in calls) is (phase in {"submitted", "submitting"})
