import os
import sys
from datetime import datetime
from types import SimpleNamespace
from typing import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.workflow.models.provision_job import ProvisionJobType  # noqa: E402
from app.domains.workflow.routers import provision as provision_router
from app.domains.skill.routers import skill as skill_router
from app.domains.workspace.routers import workspace as workspace_router


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


def _fake_job(**overrides):
    now = datetime.utcnow()
    payload = {
        "id": "job-1",
        "job_type": ProvisionJobType.CREATE_WORKSPACE,
        "status": "PENDING",
        "progress": 0,
        "stage": "QUEUED",
        "message": "queued",
        "error_message": None,
        "result_json": {},
        "context_json": {},
        "workspace_id": None,
        "task_id": None,
        "creator_id": "user-1",
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "finished_at": None,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_create_workspace_returns_accepted_payload(monkeypatch):
    app = FastAPI()
    app.include_router(workspace_router.router, prefix="/api")
    app.dependency_overrides[workspace_router.get_db] = _override_db
    app.dependency_overrides[workspace_router.get_current_user] = _override_user

    async def _noop(_job_id: str):
        return None

    monkeypatch.setattr(workspace_router.provision_job_service, "create_job", lambda *args, **kwargs: _fake_job())
    monkeypatch.setattr(workspace_router.provision_job_service, "run_create_workspace_job", _noop)

    client = TestClient(app)
    resp = client.post(
        "/api/workspaces",
        json={
            "name": "Async Workspace",
            "description": "test",
            "project_path": "G:/tmp/ws-async",
            "git_repo_url": "https://github.com/example/repo",
        },
    )
    assert resp.status_code == 202
    payload = resp.json()
    assert payload["job_id"] == "job-1"
    assert payload["job_type"] == "CREATE_WORKSPACE"
    assert payload["status"] == "PENDING"
    assert payload["stage"] == "QUEUED"


def test_import_skill_from_github_returns_accepted_payload(monkeypatch):
    app = FastAPI()
    app.include_router(skill_router.router, prefix="/api")
    app.dependency_overrides[skill_router.get_db] = _override_db
    app.dependency_overrides[skill_router.get_current_user] = _override_user

    captured = {}

    def _create_job(*args, **kwargs):
        captured.update(kwargs)
        return _fake_job(
            job_type=ProvisionJobType.IMPORT_SKILL,
            message="Skill import queued",
        )

    async def _noop(_job_id: str):
        return None

    monkeypatch.setattr(skill_router.provision_job_service, "create_job", _create_job)
    monkeypatch.setattr(skill_router.provision_job_service, "run_import_skill_job", _noop)

    client = TestClient(app)
    resp = client.post(
        "/api/skills/import/github",
        json={
            "dimension": "GLOBAL",
            "repo_url": "https://github.com/openai/sample-skills",
            "skill_name": "demo-skill",
            "description": "demo",
            "follow_official_source": True,
        },
    )
    assert resp.status_code == 202
    payload = resp.json()
    assert payload["job_id"] == "job-1"
    assert payload["job_type"] == "IMPORT_SKILL"
    assert payload["message"] == "Skill import queued"
    assert captured["job_type"] == ProvisionJobType.IMPORT_SKILL
    assert captured["workspace_id"] is None
    assert captured["context_json"]["repo_url"] == "https://github.com/openai/sample-skills"
    assert captured["context_json"]["skill_name"] == "demo-skill"
    assert captured["context_json"]["dimension"] == "GLOBAL"


def test_get_provision_job_requires_creator_or_workspace_member(monkeypatch):
    app = FastAPI()
    app.include_router(provision_router.router, prefix="/api")
    app.dependency_overrides[provision_router.get_db] = _override_db
    app.dependency_overrides[provision_router.get_current_user] = _override_user

    monkeypatch.setattr(
        provision_router.provision_job_service,
        "get_job",
        lambda db, job_id: _fake_job(creator_id="another-user", workspace_id="ws-1"),
    )
    monkeypatch.setattr(
        provision_router.workspace_service,
        "get_workspace_member",
        lambda db, ws_id, user_id: None,
    )

    client = TestClient(app)
    resp = client.get("/api/provision-jobs/job-1")
    assert resp.status_code == 403


def test_get_provision_job_allows_creator(monkeypatch):
    app = FastAPI()
    app.include_router(provision_router.router, prefix="/api")
    app.dependency_overrides[provision_router.get_db] = _override_db
    app.dependency_overrides[provision_router.get_current_user] = _override_user

    monkeypatch.setattr(
        provision_router.provision_job_service,
        "get_job",
        lambda db, job_id: _fake_job(creator_id="user-1", workspace_id=None),
    )

    client = TestClient(app)
    resp = client.get("/api/provision-jobs/job-1")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["job_id"] == "job-1"
    assert payload["job_type"] == "CREATE_WORKSPACE"
