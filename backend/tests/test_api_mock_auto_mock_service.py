import json
import os
import sys
from types import SimpleNamespace
from unittest import mock


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.api_mock.services.api_mock import auto_mock_service  # noqa: E402


def test_auto_generate_mock_cases_persists_request_matchers_and_prompt_fields(monkeypatch):
    project = SimpleNamespace(
        id="project-1",
        workspace_id="ws-1",
        task_id="task-1",
        task=SimpleNamespace(project_path="G:/proj/SDD-native"),
    )
    endpoint = SimpleNamespace(id="endpoint-1", method="POST", path="/users")
    job = SimpleNamespace(id="job-1")

    created_calls = []
    captured = {"prompt": None, "success_result": None}

    async def _fake_run_claude_session(_cli_cmd, _cwd, prompt, **_kwargs):
        captured["prompt"] = prompt
        payload = [
            {
                "name": "Create user success",
                "description": "create admin user",
                "mode": "STATIC",
                "status_code": 201,
                "delay_ms": 0,
                "headers_json": {"Content-Type": "application/json"},
                "request_query_json": {"source": "ai"},
                "request_body_json": '{"name":"Alice","role":"admin"}',
                "static_body_json": {"id": "u-1", "name": "Alice"},
            },
            {
                "name": "Create user conflict",
                "description": "duplicated email",
                "mode": "STATIC",
                "status_code": 409,
                "delay_ms": 0,
                "headers_json": {"Content-Type": "application/json"},
                "request_query_json": {"source": "ai"},
                "request_body_json": '{"name":"Bob","role":"member"}',
                "static_body_json": {"message": "email already exists"},
            },
        ]
        return [json.dumps(payload)], []

    def _fake_create_mock_case(_db, _project, **kwargs):
        created_calls.append(kwargs)
        return SimpleNamespace(id=f"case-{len(created_calls)}")

    def _fake_set_job_success(_db, _project_id, _job, result, _message):
        captured["success_result"] = result

    monkeypatch.setattr(auto_mock_service, "get_job", lambda *_args, **_kwargs: job)
    monkeypatch.setattr(auto_mock_service, "get_endpoint", lambda *_args, **_kwargs: endpoint)
    monkeypatch.setattr(auto_mock_service, "_set_job_running", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(auto_mock_service, "_append_job_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(auto_mock_service, "_raise_if_cancel_requested", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(auto_mock_service, "_set_job_progress", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(auto_mock_service, "_set_job_success", _fake_set_job_success)
    monkeypatch.setattr(auto_mock_service, "_api_mock_cli_candidates", lambda: ["claude"])
    monkeypatch.setattr(auto_mock_service, "_temp_workspace_path", lambda *_args, **_kwargs: "G:/tmp/api-mock")
    monkeypatch.setattr(auto_mock_service, "_copy_task_workspace", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(auto_mock_service, "run_claude_session", _fake_run_claude_session)
    monkeypatch.setattr(auto_mock_service, "list_mock_cases_for_endpoint", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(auto_mock_service, "create_mock_case", _fake_create_mock_case)
    monkeypatch.setattr(
        "app.domains.api_mock.services.api_mock.mock_case_service.next_mock_case_sort_order",
        lambda *_args, **_kwargs: 0,
    )

    auto_mock_service.auto_generate_mock_cases_for_endpoint(
        mock.MagicMock(),
        project,
        job_id="job-1",
        endpoint_id="endpoint-1",
        creator_id="user-1",
        workspace_sync_needed=False,
    )

    assert len(created_calls) == 2
    created = created_calls[0]
    assert created["request_query_json"] == {"source": "ai"}
    assert created["request_body_json"] == {"name": "Alice", "role": "admin"}
    assert created["request_path_params_json"] is None

    assert captured["success_result"]["cases_created"] == 2
    assert captured["success_result"]["created_count"] == 2
    assert captured["success_result"]["updated_count"] == 0
    assert "request_body_json" in str(captured["prompt"])
