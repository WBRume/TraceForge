import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.agents import selection
from app.domains.api_mock.services.api_mock import cli_sync_service
from app.domains.api_mock.services.api_mock.job_service import JobCancelledError


@pytest.mark.parametrize("backend_name", ["opencode", "dsh"])
def test_agent_session_adapts_remote_events_and_closes(monkeypatch, backend_name):
    backend = SimpleNamespace(
        capabilities=SimpleNamespace(execution_kind="REMOTE_SESSION"),
        close=AsyncMock(),
    )
    factory = Mock(return_value=backend)
    monkeypatch.setattr(selection, "create_agent_backend_by_name", factory)
    captured = []

    async def run(_backend, request, on_event):
        captured.append(request)
        for kind, payload in [
            ("text", {"text": '[{"name":"ok"}]'}),
            ("result", {"success": True, "result": '[{"name":"ok"}]'}),
        ]:
            await on_event(SimpleNamespace(type=kind, payload=payload))
        return SimpleNamespace(session_id="remote-session")

    monkeypatch.setattr(selection, "run_agent_backend_with_logging", run)
    events, logs = [], []
    result = asyncio.run(cli_sync_service.run_agent_session(
        backend_name, "workspace", "generate cases", on_event=events.append, on_output=logs.append,
    ))
    factory.assert_called_once_with(backend_name)
    assert result == (['[{"name":"ok"}]'], ['[{"name":"ok"}]'])
    assert captured[0].project_path == "workspace"
    assert captured[0].prompt == "generate cases"
    assert captured[0].session_id is None
    assert events and logs
    backend.close.assert_awaited_once()


def test_agent_session_uses_unified_claude_configuration(monkeypatch):
    bridge = SimpleNamespace(start_session=AsyncMock(), wait=AsyncMock(), is_running=lambda: False)
    factory = Mock(return_value=bridge)
    monkeypatch.setattr(selection, "create_cli_bridge", factory)
    assert asyncio.run(cli_sync_service.run_agent_session("claude-code", "workspace", "prompt")) == ([], [])
    factory.assert_called_once_with()


def test_remote_cancellation_is_a_job_cancellation(monkeypatch):
    backend = SimpleNamespace(
        capabilities=SimpleNamespace(execution_kind="REMOTE_SESSION"),
        close=AsyncMock(), cancel=AsyncMock(),
    )
    monkeypatch.setattr(selection, "create_agent_backend_by_name", lambda _: backend)

    async def run(*_args):
        await asyncio.Future()

    monkeypatch.setattr(selection, "run_agent_backend_with_logging", run)
    with pytest.raises(JobCancelledError):
        asyncio.run(cli_sync_service.run_agent_session(
            "dsh", "workspace", "prompt", should_cancel=lambda: True,
        ))
    backend.cancel.assert_awaited_once()
    backend.close.assert_awaited_once()


def test_agent_failure_propagates_and_closes(monkeypatch):
    backend = SimpleNamespace(
        capabilities=SimpleNamespace(execution_kind="REMOTE_SESSION"),
        close=AsyncMock(),
    )
    monkeypatch.setattr(selection, "create_agent_backend_by_name", lambda _: backend)
    monkeypatch.setattr(
        selection, "run_agent_backend_with_logging", AsyncMock(side_effect=RuntimeError("backend unavailable")),
    )
    with pytest.raises(RuntimeError, match="backend unavailable"):
        asyncio.run(cli_sync_service.run_agent_session("dsh", "workspace", "prompt"))
    backend.close.assert_awaited_once()


@pytest.mark.parametrize("workspace_backend, expected", [("opencode", "opencode"), (None, "dsh")])
def test_workspace_selection_and_global_fallback(monkeypatch, workspace_backend, expected):
    monkeypatch.setattr(selection.settings, "AGENT_BACKEND", "dsh")
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(agent_backend=workspace_backend)
    assert selection.resolve_workspace_backend(db, "ws-1") == expected
    db.commit.assert_not_called()
