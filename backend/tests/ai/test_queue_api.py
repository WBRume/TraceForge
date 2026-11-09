from collections.abc import Iterator
from datetime import datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domains.ai.routers import queue as queue_router
from app.domains.ai.services import queue_service


class _FakeDb:
    def close(self) -> None:
        return None


def _override_db() -> Iterator[_FakeDb]:
    db = _FakeDb()
    try:
        yield db
    finally:
        db.close()


def _override_user():
    return SimpleNamespace(id="user-1", display_name="tester")


def _queue_item(**overrides):
    payload = {
        "source": "provision",
        "job_id": "job-1",
        "job_type": "CREATE_TASK",
        "status": "FAILED",
        "progress": 100,
        "stage": "FAILED",
        "message": "failed",
        "error_message": "x",
        "workspace_id": "ws-1",
        "task_id": "task-1",
        "creator_id": "user-1",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "target_path": "/workspaces/ws-1/chat/task-1",
        "actions": {"can_stop": False, "can_retry": True, "can_open": False},
    }
    payload.update(overrides)
    return payload


def test_list_queue_jobs_returns_items(monkeypatch):
    app = FastAPI()
    app.include_router(queue_router.router, prefix="/api")
    app.dependency_overrides[queue_router.get_db] = _override_db
    app.dependency_overrides[queue_router.get_current_user] = _override_user

    monkeypatch.setattr(
        queue_router.queue_service,
        "list_queue_jobs",
        lambda *args, **kwargs: ([_queue_item()], 1),
    )

    client = TestClient(app)
    resp = client.get("/api/queue/jobs")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["source"] == "provision"


def test_retry_queue_job_returns_new_job_id(monkeypatch):
    import asyncio
    import threading

    caller_threads = {}

    def start_job(job_id, job_type):
        assert asyncio.get_running_loop().is_running()
        caller_threads["dispatch"] = threading.get_ident()
        assert (job_id, job_type) == ("job-2", "CREATE_WORKSPACE")

    monkeypatch.setattr(queue_service, "start_provision_job", start_job)

    def retry_in_worker(*args, **kwargs):
        caller_threads["database"] = threading.get_ident()
        return {
            "source": "provision",
            "job_id": "job-1",
            "new_job_id": "job-2",
            "provision_job_type": "CREATE_WORKSPACE",
            "message": "retry queued",
        }

    app = FastAPI()
    app.include_router(queue_router.router, prefix="/api")
    app.dependency_overrides[queue_router.get_db] = _override_db
    app.dependency_overrides[queue_router.get_current_user] = _override_user

    monkeypatch.setattr(
        queue_router.queue_service,
        "retry_queue_job",
        retry_in_worker,
    )

    client = TestClient(app)
    resp = client.post("/api/queue/jobs/provision/job-1/retry")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["action"] == "retry"
    assert payload["new_job_id"] == "job-2"
    assert caller_threads["database"] != caller_threads["dispatch"]


def test_get_queue_job_detail_returns_item(monkeypatch):
    app = FastAPI()
    app.include_router(queue_router.router, prefix="/api")
    app.dependency_overrides[queue_router.get_db] = _override_db
    app.dependency_overrides[queue_router.get_current_user] = _override_user

    monkeypatch.setattr(
        queue_router.queue_service,
        "get_queue_job",
        lambda *args, **kwargs: _queue_item(source="api_mock", job_id="job-9"),
    )

    client = TestClient(app)
    resp = client.get("/api/queue/jobs/api_mock/job-9")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["source"] == "api_mock"
    assert payload["job_id"] == "job-9"


def test_get_queue_job_detail_forbidden_returns_403(monkeypatch):
    app = FastAPI()
    app.include_router(queue_router.router, prefix="/api")
    app.dependency_overrides[queue_router.get_db] = _override_db
    app.dependency_overrides[queue_router.get_current_user] = _override_user

    monkeypatch.setattr(
        queue_router.queue_service,
        "get_queue_job",
        lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("forbidden")),
    )

    client = TestClient(app)
    resp = client.get("/api/queue/jobs/provision/job-1")
    assert resp.status_code == 403
    assert "forbidden" in resp.json().get("detail", "")


def test_get_queue_job_detail_not_found_returns_404(monkeypatch):
    app = FastAPI()
    app.include_router(queue_router.router, prefix="/api")
    app.dependency_overrides[queue_router.get_db] = _override_db
    app.dependency_overrides[queue_router.get_current_user] = _override_user

    monkeypatch.setattr(
        queue_router.queue_service,
        "get_queue_job",
        lambda *args, **kwargs: (_ for _ in ()).throw(LookupError("missing")),
    )

    client = TestClient(app)
    resp = client.get("/api/queue/jobs/bootstrap/job-x")
    assert resp.status_code == 404
    assert "missing" in resp.json().get("detail", "")


def test_stop_queue_job_unsupported_returns_409(monkeypatch):
    app = FastAPI()
    app.include_router(queue_router.router, prefix="/api")
    app.dependency_overrides[queue_router.get_db] = _override_db
    app.dependency_overrides[queue_router.get_current_user] = _override_user

    monkeypatch.setattr(
        queue_router.queue_service,
        "stop_queue_job",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("Stop is not supported")),
    )

    client = TestClient(app)
    resp = client.post("/api/queue/jobs/provision/job-1/stop")
    assert resp.status_code == 409
    assert "Stop is not supported" in resp.json().get("detail", "")
