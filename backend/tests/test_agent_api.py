import os
import subprocess
import sys
import tempfile
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.config import settings  # noqa: E402
from app.database import Base  # noqa: E402
from app.domains.auth.models.user import (
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)
from app.domains.task.models.task import SddTask
from app.domains.task.models.task import TaskStatus  # noqa: E402
from app.domains.ai.routers import agent as agent_router
from app.domains.workflow.services import change_proposal_service


def _run_git(args, cwd):
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr or result.stdout}")
    return result


def _seed_repo(repo_path: str):
    _run_git(["init"], cwd=repo_path)
    _run_git(["config", "user.email", "tester@example.com"], cwd=repo_path)
    _run_git(["config", "user.name", "tester"], cwd=repo_path)
    with open(os.path.join(repo_path, "README.md"), "w", encoding="utf-8") as handle:
        handle.write("hello\n")
    _run_git(["add", "README.md"], cwd=repo_path)
    _run_git(["commit", "-m", "seed"], cwd=repo_path)
    _run_git(["branch", "-M", "main"], cwd=repo_path)
    with open(os.path.join(repo_path, "README.md"), "a", encoding="utf-8") as handle:
        handle.write("world\n")


def _build_db(repo_path: str):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    db = SessionLocal()
    user = User(id="user-1", email="user@example.com", hashed_password="x", display_name="User")
    other = User(id="user-2", email="other@example.com", hashed_password="x", display_name="Other")
    workspace = Workspace(
        id="ws-1",
        name="Workspace",
        owner_id=user.id,
        project_path=repo_path,
        git_repo_url="https://example.com/repo.git",
    )
    member = WorkspaceMember(
        id="member-1",
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.OWNER,
        permissions_json="[]",
        is_expert=True,
    )
    task = SddTask(
        id="task-1",
        workspace_id=workspace.id,
        creator_id=user.id,
        name="Task",
        project_path=repo_path,
        git_repo_url=workspace.git_repo_url,
        status=TaskStatus.PENDING,
    )
    db.add_all([user, other, workspace, member, task])
    db.commit()
    proposal = change_proposal_service.create_change_proposal(
        db,
        task=task,
        workspace=workspace,
        creator_id=user.id,
    )
    proposal_id = proposal.id
    base_sha = proposal.base_commit_sha
    db.close()
    return engine, SessionLocal, user, other, proposal_id, base_sha


def _build_app(SessionLocal, current_user_state, monkeypatch):
    @asynccontextmanager
    async def _fake_lock_task(_task_id):
        yield

    monkeypatch.setattr(agent_router, "lock_task", _fake_lock_task)

    def _override_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(agent_router.router, prefix="/api")
    app.dependency_overrides[agent_router.get_db] = _override_db
    app.dependency_overrides[agent_router.get_current_user] = lambda: current_user_state["user"]
    return app


def test_agent_api_downloads_patch_and_hides_server_paths(monkeypatch):
    with tempfile.TemporaryDirectory() as repo_path:
        _seed_repo(repo_path)
        engine, SessionLocal, user, _other, proposal_id, base_sha = _build_db(repo_path)
        current_user = {"user": user}
        client = TestClient(_build_app(SessionLocal, current_user, monkeypatch))

        task_resp = client.get("/api/agent/tasks/task-1")
        assert task_resp.status_code == 200
        task_payload = task_resp.json()
        assert "project_path" not in task_payload
        assert task_payload["latest_change_proposal_id"] == proposal_id

        proposal_resp = client.get(f"/api/agent/change-proposals/{proposal_id}")
        assert proposal_resp.status_code == 200
        assert "patch_file_path" not in proposal_resp.json()

        files_resp = client.get(f"/api/agent/change-proposals/{proposal_id}/files")
        assert files_resp.status_code == 200
        assert files_resp.json()["total"] == 1

        patch_resp = client.get(f"/api/agent/change-proposals/{proposal_id}/patch")
        assert patch_resp.status_code == 200
        assert "README.md" in patch_resp.text

        bad_apply = client.post(
            "/api/agent/tasks/task-1/apply-results",
            json={"proposal_id": proposal_id, "status": "applied", "base_commit_sha": "bad"},
        )
        assert bad_apply.status_code == 409

        run_resp = client.post(
            "/api/agent/tasks/task-1/verification-runs",
            json={
                "proposal_id": proposal_id,
                "status": "success",
                "command": "pytest",
                "base_commit_sha": base_sha,
                "local_head_sha": "local",
            },
        )
        assert run_resp.status_code == 201
        assert run_resp.json()["status"] == "success"
        engine.dispose()


def test_agent_api_latest_change_proposal_empty_returns_null(monkeypatch):
    with tempfile.TemporaryDirectory() as repo_path:
        _seed_repo(repo_path)
        engine, SessionLocal, user, _other, _proposal_id, _base_sha = _build_db(repo_path)
        db = SessionLocal()
        try:
            from app.domains.workflow.models.task_change import SddTaskChangeProposal, SddTaskChangeProposalFile

            db.query(SddTaskChangeProposalFile).delete()
            db.query(SddTaskChangeProposal).delete()
            db.commit()
        finally:
            db.close()

        current_user = {"user": user}
        client = TestClient(_build_app(SessionLocal, current_user, monkeypatch))

        latest_resp = client.get("/api/agent/tasks/task-1/change-proposals/latest")
        assert latest_resp.status_code == 200
        assert latest_resp.json() is None
        engine.dispose()


def test_agent_api_forbids_non_workspace_member(monkeypatch):
    with tempfile.TemporaryDirectory() as repo_path:
        _seed_repo(repo_path)
        engine, SessionLocal, _user, other, proposal_id, _base_sha = _build_db(repo_path)
        current_user = {"user": other}
        client = TestClient(_build_app(SessionLocal, current_user, monkeypatch))

        task_resp = client.get("/api/agent/tasks/task-1")
        assert task_resp.status_code == 403
        patch_resp = client.get(f"/api/agent/change-proposals/{proposal_id}/patch")
        assert patch_resp.status_code == 403
        engine.dispose()


def test_agent_api_rejects_oversized_verification_log(monkeypatch):
    original_limit = settings.TASK_CHANGE_MAX_UPLOAD_BYTES
    settings.TASK_CHANGE_MAX_UPLOAD_BYTES = 5
    try:
        with tempfile.TemporaryDirectory() as repo_path:
            _seed_repo(repo_path)
            engine, SessionLocal, user, _other, proposal_id, base_sha = _build_db(repo_path)
            current_user = {"user": user}
            client = TestClient(_build_app(SessionLocal, current_user, monkeypatch))

            run_resp = client.post(
                "/api/agent/tasks/task-1/verification-runs",
                json={
                    "proposal_id": proposal_id,
                    "status": "running",
                    "base_commit_sha": base_sha,
                },
            )
            assert run_resp.status_code == 201
            run_id = run_resp.json()["id"]

            upload_resp = client.post(
                f"/api/agent/tasks/task-1/verification-runs/{run_id}/logs",
                files={"file": ("large.log", b"0123456789", "text/plain")},
            )
            assert upload_resp.status_code == 413
            engine.dispose()
    finally:
        settings.TASK_CHANGE_MAX_UPLOAD_BYTES = original_limit
