"""Enforce the desktop-only local task creation policy before provisioning."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_current_user, get_db
from app.domains.task.routers.task import crud
from app.domains.workflow.models.provision_job import ProvisionJobType
from tests.workflow.test_provision_jobs_api import _fake_job


@pytest.fixture
def creation(monkeypatch):
    app = FastAPI()
    app.include_router(crud.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-1")
    app.dependency_overrides[get_db] = lambda: Mock()
    monkeypatch.setattr(crud, "verify_workspace_permission", Mock())
    record = Mock(return_value=SimpleNamespace(id="task-1", name="Test task"))
    job = Mock(return_value=_fake_job(job_type=ProvisionJobType.CREATE_TASK, task_id="task-1", workspace_id="ws-1"))
    monkeypatch.setattr(crud.task_provisioning_creation, "create_task_record_for_provision", record)
    monkeypatch.setattr(crud.provision_job_service, "create_job", job)
    monkeypatch.setattr(crud.provision_job_service, "run_create_task_job", AsyncMock())
    return TestClient(app), record, job


@pytest.mark.parametrize("client_type", [None, "web", "unknown"])
@pytest.mark.parametrize("task_type", ["DEVELOPMENT", "DIAGNOSIS"])
def test_browser_cannot_create_local_task(creation, client_type, task_type):
    client, record, job = creation
    headers = {"X-TraceForge-Client": client_type} if client_type else {}
    response = client.post(
        "/api/workspaces/ws-1/tasks",
        headers=headers,
        json={
            "name": "Test",
            "task_type": task_type,
            "phenomenon": "Failure",
            "execution": {"location": "LOCAL", "resource_id": "resource", "profile_revision": 1},
        },
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "LOCAL_TASK_DESKTOP_REQUIRED"
    record.assert_not_called()
    job.assert_not_called()


@pytest.mark.parametrize("task_type", ["DEVELOPMENT", "DIAGNOSIS"])
def test_desktop_can_create_local_task(creation, task_type):
    client, record, job = creation
    response = client.post(
        "/api/workspaces/ws-1/tasks",
        headers={"X-TraceForge-Client": "desktop"},
        json={
            "name": "Test",
            "task_type": task_type,
            "phenomenon": "Failure",
            "execution": {"location": "LOCAL", "resource_id": "resource", "profile_revision": 1},
        },
    )
    assert response.status_code == 202, response.text
    assert record.call_args.kwargs["execution"].location == "LOCAL"
    job.assert_called_once()


@pytest.mark.parametrize("client_type", [None, "web", "desktop"])
def test_server_tasks_remain_available_on_every_client(creation, client_type):
    client, record, job = creation
    response = client.post(
        "/api/workspaces/ws-1/tasks",
        headers={"X-TraceForge-Client": client_type} if client_type else {},
        json={"name": "Test"},
    )
    assert response.status_code == 202, response.text
    assert record.call_args.kwargs["execution"].location == "SERVER"
    job.assert_called_once()
