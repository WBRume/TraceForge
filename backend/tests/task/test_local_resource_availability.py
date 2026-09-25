from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.domains.local_resource import service
from app.domains.local_resource.client import ResourceError


@pytest.mark.parametrize("actor,expert", [("creator", False), ("expert", True)])
def test_offline_blocks_even_creator_and_expert(monkeypatch, actor, expert):
    monkeypatch.setattr(service, "require_member", lambda *args: SimpleNamespace(is_expert=expert))
    monkeypatch.setattr(service, "binding", lambda *args: None)
    monkeypatch.setattr(service, "runtime_profile", lambda *args: {})
    monkeypatch.setattr(service, "ResourceClient", Mock(side_effect=ResourceError("offline")))
    task = SimpleNamespace(id="task", workspace_id="ws", creator_id="creator", execution_location="LOCAL")
    with pytest.raises(ResourceError) as error:
        service.require_operation(None, task, actor)
    assert error.value.code == "LOCAL_RESOURCE_OFFLINE"
    assert error.value.status_code == 409


@pytest.mark.parametrize("agent_online", [True, False])
def test_both_host_and_agent_must_be_online(monkeypatch, agent_online):
    client = Mock()
    monkeypatch.setattr(service, "ResourceClient", client)
    probe = AsyncMock(side_effect=None if agent_online else RuntimeError("agent offline"))
    monkeypatch.setattr(service, "probe_provider", probe)
    if agent_online:
        service.require_online({})
    else:
        with pytest.raises(ResourceError, match="本地资源离线"):
            service.require_online({})
    client.assert_called_once_with({}, timeout=3)
    client.return_value.identity.assert_called_once()
    probe.assert_awaited_once()


def test_server_task_does_not_probe(monkeypatch):
    check = Mock()
    monkeypatch.setattr(service, "require_online", check)
    service.require_operation(None, SimpleNamespace(execution_location="SERVER"), "creator")
    check.assert_not_called()


@pytest.mark.asyncio
async def test_each_observer_receives_initial_state_offline_and_recovery(monkeypatch):
    import asyncio
    from app.domains.websocket.ws import task_handler
    from app.domains.websocket.ws.task_handler import TaskWebSocketHandler, TaskWebSocketUser

    async def run_sync(fn):
        return fn()

    sleep_calls = 0

    async def next_check(_delay):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls % 4 == 0:
            raise asyncio.CancelledError()

    monkeypatch.setattr(task_handler, "run_db", run_sync)
    monkeypatch.setattr(task_handler.asyncio, "sleep", next_check)
    for user_id in ("creator", "observer"):
        handler = TaskWebSocketHandler(Mock(), "task", TaskWebSocketUser(user_id, user_id, False), session_factory=Mock())
        handler._outbound = Mock(dropped=False)
        states = iter(["online", "online", "offline", "online"])
        monkeypatch.setattr(handler, "_local_resource_status_sync", lambda: {"task_id": "task", "status": next(states)})
        with pytest.raises(asyncio.CancelledError):
            await handler._monitor_local_resource()
        frames = [call.args[0] for call in handler._outbound.submit_json.call_args_list]
        assert [frame["payload"]["status"] for frame in frames] == ["online", "offline", "online"]
        assert all(frame["type"] == "local_resource_status" for frame in frames)
