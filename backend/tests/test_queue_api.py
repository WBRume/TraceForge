import os
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.ai.routers import queue as queue_router
from app.domains.workflow.models.provision_job import ProvisionJobStatus, ProvisionJobType  # noqa: E402
from app.domains.ai.services import queue_service  # noqa: E402


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
        "target_path": "/ws/ws-1/chat/task-1",
        "actions": {"can_stop": False, "can_retry": True, "can_open": False},
    }
    payload.update(overrides)
    return payload


class _FakeQueueDb:
    def __init__(self):
        self.committed = False
        self.refreshed = False

    def commit(self):
        self.committed = True

    def refresh(self, _job):
        self.refreshed = True


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


def test_stale_import_skill_provision_job_is_marked_failed(monkeypatch):
    monkeypatch.setattr(queue_service.settings, "SKILL_GITHUB_IMPORT_GIT_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(queue_service.settings, "SKILL_GITHUB_IMPORT_STALE_GRACE_SECONDS", 0)
    job = SimpleNamespace(
        job_type=ProvisionJobType.IMPORT_SKILL,
        status=ProvisionJobStatus.RUNNING,
        progress=20,
        stage="CLONING_REPOSITORY",
        message="Importing skill from GitHub",
        error_message=None,
        updated_at=datetime.utcnow() - timedelta(seconds=5),
        started_at=datetime.utcnow() - timedelta(seconds=5),
        created_at=datetime.utcnow() - timedelta(seconds=5),
        finished_at=None,
    )
    db = _FakeQueueDb()

    queue_service._mark_stale_import_skill_job_failed(db, job)

    assert job.status == ProvisionJobStatus.FAILED
    assert job.stage == "FAILED"
    assert "timed out" in job.error_message
    assert db.committed is True
    assert db.refreshed is True


def test_stale_import_skill_job_uses_started_at_before_local_updated_at(monkeypatch):
    monkeypatch.setattr(queue_service.settings, "SKILL_GITHUB_IMPORT_GIT_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(queue_service.settings, "SKILL_GITHUB_IMPORT_STALE_GRACE_SECONDS", 0)
    job = SimpleNamespace(
        job_type=ProvisionJobType.IMPORT_SKILL,
        status=ProvisionJobStatus.RUNNING,
        progress=20,
        stage="CLONING_REPOSITORY",
        message="Importing skill from GitHub",
        error_message=None,
        updated_at=datetime.utcnow() + timedelta(hours=8),
        started_at=datetime.utcnow() - timedelta(seconds=5),
        created_at=datetime.utcnow() + timedelta(hours=8),
        finished_at=None,
    )
    db = _FakeQueueDb()

    queue_service._mark_stale_import_skill_job_failed(db, job)

    assert job.status == ProvisionJobStatus.FAILED
    assert job.stage == "FAILED"
    assert db.committed is True


def test_retry_queue_job_returns_new_job_id(monkeypatch):
    app = FastAPI()
    app.include_router(queue_router.router, prefix="/api")
    app.dependency_overrides[queue_router.get_db] = _override_db
    app.dependency_overrides[queue_router.get_current_user] = _override_user

    monkeypatch.setattr(
        queue_router.queue_service,
        "retry_queue_job",
        lambda *args, **kwargs: {
            "source": "provision",
            "job_id": "job-1",
            "new_job_id": "job-2",
            "message": "retry queued",
        },
    )

    client = TestClient(app)
    resp = client.post("/api/queue/jobs/provision/job-1/retry")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["action"] == "retry"
    assert payload["new_job_id"] == "job-2"


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
