import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.agents.adapters.claude_code.claude_code_adapter import ClaudeCodeAdapter
from app.agents.adapters.claude_code.models import model_catalog
from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter
from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
from app.agents.contract import AgentRunRequest
from app.agents.model_selection import apply_task_selection, validate_selection


def test_model_preference_keeps_task_backend_and_other_metadata():
    task = SimpleNamespace(agent_backend="dsh", workspace_id="w", task_meta_json={"phenomenon": "slow"})
    apply_task_selection(None, task, {"backend": "dsh", "model": "private/model/with/slash"})
    assert task.task_meta_json["phenomenon"] == "slow"
    assert task.task_meta_json["agent_model"]["model"] == "private/model/with/slash"
    with pytest.raises(ValueError, match="引擎已改变"):
        apply_task_selection(None, task, {"backend": "opencode", "model": "private/a"})


@pytest.mark.parametrize("model", ["", "  ", "x\ny", "missing-provider", "/model", "provider/"])
def test_invalid_model_is_rejected(model):
    with pytest.raises(ValueError):
        validate_selection({"backend": "dsh", "model": model}, "dsh")


def test_claude_reads_current_and_project_models(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    (project / ".claude").mkdir(parents=True)
    (home / "settings.json").write_text(json.dumps({"model": "sonnet"}))
    (project / ".claude/settings.local.json").write_text(
        json.dumps(
            {
                "model": "custom-model",
                "availableModels": ["custom-model", "opus"],
            }
        )
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "managed"))
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    result = model_catalog(str(project))
    assert result["default_model"] == "custom-model"
    assert [x["value"] for x in result["options"]] == ["custom-model", "opus"]
    monkeypatch.setenv("ANTHROPIC_MODEL", "env-model")
    assert model_catalog(str(project))["default_model"] == "env-model"


@pytest.mark.asyncio
async def test_claude_passes_model_on_resume():
    adapter = ClaudeCodeAdapter()
    adapter._bridge = SimpleNamespace(
        start_session=AsyncMock(), wait=AsyncMock(), last_termination=None, session_id="existing", process=None
    )
    await adapter.run(
        AgentRunRequest(run_id="r", prompt="continue", project_path=".", session_id="existing", model="custom-model"),
        AsyncMock(),
    )
    args = adapter._bridge.start_session.call_args.kwargs
    assert args["model"] == "custom-model" and args["session_id"] == "existing"


@pytest.mark.asyncio
async def test_opencode_catalog_and_switch_use_full_provider_identity():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/api/model":
            assert request.url.params["location[directory]"] == "/work/project"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"providerID": "one", "id": "shared", "name": "Shared", "enabled": True},
                        {"providerID": "two", "id": "shared", "enabled": True},
                        {"providerID": "three", "id": "hidden", "enabled": False},
                    ]
                },
            )
        if request.url.path == "/api/session/existing" and request.method == "GET":
            return httpx.Response(200, json={"data": {"model": {"providerID": "two", "id": "shared"}}})
        return httpx.Response(200, json={"data": {"id": "message"}})

    adapter = OpenCodeAdapter("http://agent")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await adapter.model_catalog(project_path="/work/project", session_id="existing")
        assert result["default_model"] == "two/shared"
        assert [x["value"] for x in result["options"]] == ["one/shared", "two/shared"]
        await adapter._send_prompt(
            "existing", AgentRunRequest(run_id="r", prompt="hello", project_path=".", model="two/shared")
        )
        switch, prompt = seen[-2:]
        assert switch.url.path.endswith("/model") and prompt.url.path.endswith("/prompt")
        assert json.loads(switch.content) == {"model": {"providerID": "two", "id": "shared"}}
    finally:
        await adapter._client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("session_id", [None, "existing"])
async def test_dsh_catalog_default_and_switch_before_prompt(session_id):
    adapter = DshServerAdapter("http://agent")
    seen = []

    async def rpc(method, payload):
        seen.append((method, payload))
        if method == "session.modelCatalog":
            return {
                "default": {"provider": "private", "model": "m"},
                "groups": [{"id": "private", "name": "Private", "models": [{"id": "m", "name": "Model"}]}],
            }
        return {"sessionId": "new"}

    adapter._rpc = rpc
    adapter._ensure_client = AsyncMock()
    adapter._ensure_event_protocol = AsyncMock()
    adapter._consume_events = AsyncMock(return_value={"text": "ok", "finish_reason": "completed"})
    result = await adapter.model_catalog()
    assert result["default_model"] == "private/m"
    assert result["options"][0]["value"] == "private/m"
    await adapter.run(
        AgentRunRequest(
            run_id="r", prompt="hello", project_path=".", session_id=session_id, model="private/model/path"
        ),
        AsyncMock(),
    )
    select = next(i for i, item in enumerate(seen) if item[0] == "session.selectModel")
    prompt = next(i for i, item in enumerate(seen) if item[0] == "session.prompt")
    assert select < prompt
    assert seen[select][1] == {"sessionId": session_id or "new", "provider": "private", "model": "model/path"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "agent_model,config_model,expected",
    [
        ({"providerID": "p", "id": "agent"}, "p/config", "p/agent"),
        (None, "p/config", "p/config"),
        (None, {"providerID": "p", "model": "config"}, "p/config"),
        (None, None, "p/newest"),
    ],
)
async def test_opencode_new_task_default_precedence(agent_model, config_model, expected):
    def handler(request):
        if request.url.path == "/api/model":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"providerID": "p", "id": "config", "time": {"released": 1}},
                        {"providerID": "p", "id": "agent", "time": {"released": 2}},
                        {"providerID": "p", "id": "newest", "time": {"released": 3}},
                    ]
                },
            )
        if request.url.path == "/api/config":
            return httpx.Response(
                200, json=[{"type": "document", "info": {"model": config_model, "default_agent": "custom"}}]
            )
        return httpx.Response(200, json={"data": [{"id": "custom", "model": agent_model}]})

    adapter = OpenCodeAdapter("http://agent")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert (await adapter.model_catalog())["default_model"] == expected
    finally:
        await adapter._client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["cold", "subscription_race", "empty", "timeout", "cancel"])
async def test_opencode_first_catalog_waits_for_location_initialization(scenario, monkeypatch):
    location = {"directory": "/work/project"}
    ready = False
    reads = 0
    closed = False
    connected = asyncio.Event()
    real_timeout = asyncio.timeout
    if scenario == "timeout":
        monkeypatch.setattr(asyncio, "timeout", lambda _: real_timeout(0.02))

    class Events(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal ready
            if scenario == "subscription_race":
                ready = True
            yield b'data: {"type":"server.connected","data":{}}\n\n'
            connected.set()
            if scenario in ("timeout", "cancel"):
                await asyncio.Event().wait()
            # Another workspace's update must not settle this empty catalogue.
            yield b'data: {"type":"catalog.updated","location":{"directory":"/other"},"data":{}}\n\n'
            assert reads == 2
            ready = True
            yield (
                "data: " + json.dumps({"type": "catalog.updated", "location": location, "data": {}}) + "\n\n"
            ).encode()

        async def aclose(self):
            nonlocal closed
            closed = True

    def handler(request):
        nonlocal reads
        if request.url.path == "/api/event":
            return httpx.Response(200, stream=Events(), headers={"content-type": "text/event-stream"})
        assert request.url.params["location[directory]"] == location["directory"]
        if request.url.path == "/api/model":
            reads += 1
            models = [{"providerID": "private", "id": "current"}] if ready and scenario != "empty" else []
            return httpx.Response(200, json={"location": location, "data": models})
        if request.url.path == "/api/config":
            return httpx.Response(200, json=[{"info": {"model": "private/current"}}])
        assert request.url.path == "/api/agent"
        return httpx.Response(200, json={"data": []})

    adapter = OpenCodeAdapter("http://agent")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        request = asyncio.create_task(adapter.model_catalog(project_path=location["directory"]))
        if scenario == "cancel":
            await connected.wait()
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
        else:
            result = await request
            if scenario in ("empty", "timeout"):
                assert result == {"options": [], "default_model": None}
            else:
                assert result["default_model"] == "private/current"
                assert result["options"][0]["value"] == "private/current"
            assert reads == (2 if scenario == "subscription_race" else 3)
        assert closed
    finally:
        await adapter._client.aclose()
