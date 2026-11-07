import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents.contract import AgentRunRequest
from app.agents.domain_tools.claude import provider_environment
from app.agents.domain_tools.invocation import active_domain_binding, bound_request
from app.agents.domain_tools.opencode import scoped_request
from app.agents.errors import AgentConfigurationError


def backend_stub():
    response = SimpleNamespace(
        json=lambda: {"data": [{"name": "traceforge_domain", "status": {"status": "connected"}}]}
    )
    original = SimpleNamespace(
        json=lambda: {"data": {"permissions": [{"action": "read", "effect": "allow", "resource": "*"}]}}
    )

    async def get(url, **_kwargs):
        return response if url.endswith("/api/mcp") else original

    client = SimpleNamespace(
        put=AsyncMock(return_value=response),
        get=AsyncMock(side_effect=get),
        patch=AsyncMock(return_value=response),
        delete=AsyncMock(return_value=response),
    )
    backend = SimpleNamespace(
        name="opencode",
        server_url="http://127.0.0.1:4097",
        _ensure_client=AsyncMock(return_value=client),
        _check_response=lambda *_: None,
        fork_session=AsyncMock(return_value="forked"),
        _session_url=lambda session_id: "http://127.0.0.1:4097/api/session/" + session_id,
        _fork_move=AsyncMock(),
        _ensure_workspace_permissions=AsyncMock(),
    )
    return backend, client


@pytest.mark.asyncio
async def test_opencode_scope_forks_preserves_history_and_cleans_after_failure(tmp_path):
    backend, client = backend_stub()
    request = AgentRunRequest(project_path=str(tmp_path), session_id="original")
    binding = {"url": "http://127.0.0.1:1234/mcp", "headers": {"Authorization": "Bearer scoped"}}
    with pytest.raises(RuntimeError, match="turn failed"):
        async with scoped_request(backend, request, binding) as scoped:
            directory = scoped.project_path
            assert Path(directory).is_dir()
            assert directory != request.project_path
            assert scoped.session_id == "forked"
            assert scoped.provider_options["domain_mcp"] == binding
            backend.fork_session.assert_awaited_once_with("original", source_dir=str(tmp_path), target_dir=directory)
            assert request.session_id == "original" and not request.provider_options
            raise RuntimeError("turn failed")
    assert not Path(directory).exists()
    client.delete.assert_awaited_once()
    assert client.put.await_args.kwargs["params"] == client.delete.await_args.kwargs["params"]
    backend._fork_move.assert_not_awaited()


@pytest.mark.asyncio
async def test_successful_child_restores_directory_and_permissions_for_followup(tmp_path):
    backend, client = backend_stub()
    async with scoped_request(
        backend, AgentRunRequest(project_path=str(tmp_path), session_id="original"), {"url": "local", "headers": {}}
    ) as scoped:
        directory = scoped.project_path
    backend._fork_move.assert_awaited_once_with(client, "forked", str(tmp_path))
    backend._ensure_workspace_permissions.assert_awaited_once_with("forked", str(tmp_path))
    assert client.patch.await_args.kwargs["json"]["permissions"] == [
        {"action": "read", "effect": "allow", "resource": "*"}
    ]
    assert not Path(directory).exists()


@pytest.mark.asyncio
async def test_concurrent_opencode_turns_have_different_configuration_scopes(tmp_path):
    backend, client = backend_stub()
    scopes = []
    both_entered = asyncio.Event()

    async def run():
        async with scoped_request(
            backend, AgentRunRequest(project_path=str(tmp_path)), {"url": "local", "headers": {}}
        ) as scoped:
            scopes.append(scoped.project_path)
            if len(scopes) == 2:
                both_entered.set()
            await asyncio.wait_for(both_entered.wait(), 2)
            assert Path(scoped.project_path).is_dir()

    await asyncio.gather(run(), run())
    assert len(set(scopes)) == 2
    assert client.delete.await_count == 2
    assert all(not Path(path).exists() for path in scopes)


@pytest.mark.asyncio
async def test_unsupported_backend_fails_without_running_or_mutating_request():
    token = active_domain_binding.set({"url": "local", "headers": {}})
    try:
        with pytest.raises(AgentConfigurationError, match="DOMAIN_TOOLS_UNSUPPORTED"):
            async with bound_request(SimpleNamespace(name="dsh"), AgentRunRequest()):
                pytest.fail("An unsupported backend must not run a text fallback")
    finally:
        active_domain_binding.reset(token)


@pytest.mark.asyncio
async def test_remote_opencode_rejected_before_tool_credential_transfer():
    backend, client = backend_stub()
    backend.server_url = "https://remote.example.test"
    with pytest.raises(AgentConfigurationError, match="COLOCATED"):
        async with scoped_request(backend, AgentRunRequest(), {"url": "local", "headers": {}}):
            pytest.fail("Remote host cannot use this invocation's loopback listener")
    client.put.assert_not_called()


def test_claude_provider_settings_do_not_import_hooks_or_shell_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        json.dumps(
            {
                "model": "model-a",
                "env": {
                    "ANTHROPIC_AUTH_TOKEN": "test-only",
                    "ANTHROPIC_BASE_URL": "https://provider.test",
                    "NODE_OPTIONS": "bad",
                    "BASH_ENV": "bad",
                    "UNKNOWN_SETTING": "bad",
                },
                "hooks": {"SessionStart": "bad"},
            }
        ),
        encoding="utf-8",
    )
    assert provider_environment() == {
        "ANTHROPIC_AUTH_TOKEN": "test-only",
        "ANTHROPIC_BASE_URL": "https://provider.test",
        "ANTHROPIC_MODEL": "model-a",
    }
