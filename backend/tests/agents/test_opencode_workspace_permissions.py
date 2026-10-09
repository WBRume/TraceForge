"""OpenCode task path policy and session lifecycle regression coverage."""

import json
import re
from unittest.mock import AsyncMock

import httpx
import pytest

from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
from app.agents.adapters.opencode.workspace_permissions import (
    normalize_directory,
    same_directory,
    workspace_permissions,
)
from app.agents.contract import AgentRunRequest
from app.agents.errors import AgentError, SessionForkError


def decision(rules, action, resource, *, windows=False):
    """Evaluate the ordered whole-value wildcard protocol on emitted rules."""
    result = "ask"
    for rule in rules:
        flags = re.IGNORECASE if windows else 0
        if all(
            re.fullmatch(re.escape(rule[key]).replace(r"\*", ".*").replace(r"\?", "."), value, flags)
            for key, value in (("action", action), ("resource", resource.replace("\\", "/")))
        ):
            result = rule["effect"]
    return result


@pytest.mark.parametrize(
    "directory,root",
    [
        ("/srv/workspaces/任务甲/", "/srv/workspaces/任务甲"),
        (r"G:\工作区\任务甲\repo\..", "G:/工作区/任务甲"),
        (r"\\server\share\任务甲", "//server/share/任务甲"),
        (r"\\?\G:\工作区\任务甲", "G:/工作区/任务甲"),
        (r"\\?\UNC\server\share\任务甲", "//server/share/任务甲"),
    ],
)
def test_directory_policy_allows_only_task_external_boundary(directory, root):
    rules = [{"action": "*", "resource": "*", "effect": "allow"}, *workspace_permissions(directory)]
    assert normalize_directory(directory) == root
    assert decision(rules, "external_directory", root + "/*") == "allow"
    assert decision(rules, "external_directory", root + "/repo/src/*") == "allow"
    for outside in (root + "-other/*", root.rsplit("/", 1)[0] + "/*", "/etc/*", "C:/other/*"):
        assert decision(rules, "external_directory", outside) == "deny"
    for action in ("read", "edit"):
        for outside in ("..", "../task-b/file.py", "../../another-workspace/file.py"):
            assert decision(rules, action, outside) == "deny"
        assert decision(rules, action, "repo/src/main.py") == "allow"
    assert decision(rules, "shell", "python main.py") == "allow"
    assert decision(rules, "grep", "example") == "allow"


def test_directory_policy_does_not_relax_existing_read_or_edit_restrictions():
    rules = [
        {"action": "*", "resource": "*", "effect": "allow"},
        {"action": "read", "resource": "*.env", "effect": "ask"},
        {"action": "edit", "resource": "*", "effect": "deny"},
        *workspace_permissions("/tasks/task-a"),
    ]
    assert decision(rules, "read", ".env") == "ask"
    assert decision(rules, "edit", "src/main.py") == "deny"


@pytest.mark.parametrize("directory", ["", ".", "tasks/a", "/", "C:/", "C:/a/..", "C:task", "/tasks/*", "/tasks/a?"])
def test_ambiguous_or_unbounded_whitelist_paths_are_rejected(directory):
    with pytest.raises(AgentError):
        workspace_permissions(directory)


def test_remote_path_comparison_respects_windows_and_posix_semantics():
    assert same_directory(r"G:\Tasks\Task A", "g:/tasks/task a/")
    assert same_directory("//SERVER/Share/task", r"\\server\share\task")
    assert same_directory("/tasks/a/repo/..", "/tasks/a")
    assert not same_directory("/tasks/A", "/tasks/a")
    assert not same_directory("/tasks/a", "/tasks/a-other")
    rules = workspace_permissions(r"G:\Tasks\Task A")
    assert decision(rules, "external_directory", "g:/tasks/task a/*", windows=True) == "allow"


@pytest.mark.asyncio
async def test_create_session_includes_location_and_task_permissions_in_one_request():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": {"id": "ses_task"}})

    adapter = OpenCodeAdapter("http://agent")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        sid = await adapter._create_session(AgentRunRequest(project_path="/tasks/task-a", model="provider/model"))
        assert sid == "ses_task"
        assert len(calls) == 1
        assert calls[0].method == "POST" and calls[0].url.path == "/api/session"
        body = json.loads(calls[0].content)
        assert body["location"] == {"directory": "/tasks/task-a"}
        assert body["model"] == {"providerID": "provider", "id": "model"}
        assert decision(body["permissions"], "external_directory", "/tasks/task-a/*") == "allow"
        assert decision(body["permissions"], "external_directory", "/tasks/task-b/*") == "deny"
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_resume_updates_legacy_permissions_once_before_execution():
    original = [
        {"action": "external_directory", "resource": "*", "effect": "allow"},
        {"action": "edit", "resource": "*", "effect": "deny"},
    ]
    session = {"location": {"directory": "/tasks/task-a"}, "permissions": original.copy()}
    calls = []

    def handler(request):
        calls.append(request.method)
        assert request.url.path == "/api/session/ses_task"
        if request.method == "GET":
            return httpx.Response(200, json={"data": session})
        session["permissions"] = json.loads(request.content)["permissions"]
        return httpx.Response(204)

    adapter = OpenCodeAdapter("http://agent")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._consume_sse = AsyncMock(return_value=({}, set()))
    adapter._emit_run_result = AsyncMock()
    try:
        for _ in range(2):
            await adapter.run(AgentRunRequest(project_path="/tasks/task-a", session_id="ses_task"), AsyncMock())
        assert calls == ["GET", "PATCH", "GET"]
        assert session["permissions"][:2] == original
        assert decision(session["permissions"], "external_directory", "/tasks/task-b/*") == "deny"
        assert decision(session["permissions"], "edit", "src/main.py") == "deny"
        assert adapter._consume_sse.await_count == 2
    finally:
        await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["wrong_directory", "missing_directory", "update_rejected"])
async def test_invalid_binding_or_permission_update_stops_before_prompt(failure):
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "GET":
            location = {"directory": "/tasks/task-b" if failure == "wrong_directory" else "/tasks/task-a"}
            return httpx.Response(200, json={"data": {} if failure == "missing_directory" else {"location": location}})
        return httpx.Response(403, json={"message": "denied"})

    adapter = OpenCodeAdapter("http://agent")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._consume_sse = AsyncMock()
    try:
        with pytest.raises(AgentError):
            await adapter.run(AgentRunRequest(project_path="/tasks/task-a", session_id="ses_task"), AsyncMock())
        adapter._consume_sse.assert_not_awaited()
        assert calls == (["GET", "PATCH"] if failure == "update_rejected" else ["GET"])
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_fork_refreshes_inherited_whitelist_for_target_task():
    session = {"location": {"directory": "/tasks/task-b"}, "permissions": workspace_permissions("/tasks/task-a")}

    def handler(request):
        if request.url.path.endswith("/fork"):
            return httpx.Response(200, json={"data": {"id": "ses_fork"}})
        if request.url.path.endswith("/move"):
            return httpx.Response(204)
        if request.method == "GET":
            return httpx.Response(200, json={"data": session})
        assert request.method == "PATCH"
        session["permissions"] = json.loads(request.content)["permissions"]
        return httpx.Response(204)

    adapter = OpenCodeAdapter("http://agent")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert await adapter.fork_session("base", source_dir="/tasks/task-a", target_dir="/tasks/task-b") == "ses_fork"
        assert decision(session["permissions"], "external_directory", "/tasks/task-a/*") == "deny"
        assert decision(session["permissions"], "external_directory", "/tasks/task-b/*") == "allow"
    finally:
        await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 500])
async def test_fork_permission_failure_cleans_up_unrestricted_session(status):
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/fork"):
            return httpx.Response(200, json={"data": {"id": "ses_fork"}})
        if request.method == "GET":
            return httpx.Response(200, json={"data": {"location": {"directory": "/tasks/task-a"}}})
        return httpx.Response(status if request.method == "PATCH" else 204)

    adapter = OpenCodeAdapter("http://agent")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(SessionForkError):
            await adapter.fork_session("base", source_dir="/tasks/task-a", target_dir="/tasks/task-a")
        assert calls[-1] == ("DELETE", "/api/session/ses_fork")
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_recovery_applies_directory_permissions_without_submitting_another_prompt(monkeypatch):
    from app.agents.adapters.opencode.execution import ExecutionMonitor

    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json={"data": {"location": {"directory": "/tasks/task-a"}}})
        return httpx.Response(204)

    reconciled = {"success": True}
    monkeypatch.setattr(ExecutionMonitor, "reconcile", AsyncMock(return_value=reconciled))
    adapter = OpenCodeAdapter("http://agent")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._consume_sse = AsyncMock()
    adapter._send_prompt = AsyncMock()
    adapter._emit_run_result = AsyncMock()
    try:
        await adapter.run(
            AgentRunRequest(
                project_path="/tasks/task-a",
                session_id="ses_task",
                execution_checkpoint={"phase": "submitted", "deadline": 9999999999, "prompt_id": "msg_original"},
            ),
            AsyncMock(),
        )
        assert calls == ["GET", "PATCH"]
        adapter._consume_sse.assert_not_awaited()
        adapter._send_prompt.assert_not_awaited()
        assert adapter._emit_run_result.call_args.args[0] is reconciled
    finally:
        await adapter.close()
