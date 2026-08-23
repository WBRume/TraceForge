import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

import app.domains.api_mock.models.api_mock  # noqa: F401,E402
import app.domains.task.models.test_result  # noqa: F401,E402
import app.domains.workflow.models.task_change  # noqa: F401,E402
import app.domains.workspace_asset.models.workspace_asset  # noqa: F401,E402
from app.database import Base  # noqa: E402
from app.domains.auth.models.user import User, Workspace  # noqa: E402
from app.domains.task.models.task import SddTask  # noqa: E402
from app.domains.task.models.task_repository import (  # noqa: E402
    SddTaskRepository,
    TaskRepositoryState,
)
from app.domains.task.services import task_service  # noqa: E402


def _build_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed_multi_repo_task(db):
    user = User(id="user-1", email="user@example.com", hashed_password="x", display_name="User")
    workspace = Workspace(id="ws-1", name="Workspace", owner_id=user.id, project_path="G:/tmp")
    task = SddTask(
        id="task-1",
        workspace_id=workspace.id,
        creator_id=user.id,
        name="Task",
        project_path="G:/tmp/task-1",
        status="CODING",
    )
    db.add_all([user, workspace, task])
    db.flush()

    for index, (repo_id, slug) in enumerate(
        [("repo-1", "repo-a"), ("repo-2", "repo-b"), ("repo-3", "repo-c")]
    ):
        db.add(
            SddTaskRepository(
                id=f"binding-{index + 1}",
                task_id=task.id,
                repository_id=repo_id,
                repo_url=f"https://example.com/{slug}.git",
                repo_name=slug,
                repo_slug=slug,
                branch_name="main",
                base_commit_sha="abc123",
                rel_path=slug,
                state=TaskRepositoryState.READY,
            )
        )
    db.commit()
    return task


def _seed_single_repo_task(db):
    user = User(id="user-1", email="user@example.com", hashed_password="x", display_name="User")
    workspace = Workspace(id="ws-1", name="Workspace", owner_id=user.id)
    task = SddTask(
        id="task-2",
        workspace_id=workspace.id,
        creator_id=user.id,
        name="Task",
        project_path="G:/tmp/task-2",
        status="CODING",
    )
    db.add_all([user, workspace, task])
    db.commit()
    return task


def test_multi_repo_task_cli_dir_is_task_root_not_primary_repo(tmp_path, monkeypatch):
    # Use a real temp dir so the primary repo subdirectory actually exists and the
    # old implementation would have picked it.
    root = tmp_path / "task-root"
    root.mkdir(parents=True, exist_ok=True)
    (root / "repo-a").mkdir(parents=True, exist_ok=True)

    SessionLocal = _build_session()
    db = SessionLocal()
    task = _seed_multi_repo_task(db)
    task.project_path = str(root)
    db.commit()

    cli_dir = task_service.resolve_task_cli_dir(db, task)
    assert os.path.normcase(os.path.abspath(cli_dir)) == os.path.normcase(os.path.abspath(str(root)))
    # It must NOT point into the first repository worktree.
    assert cli_dir != os.path.join(str(root), "repo-a")


def test_single_repo_task_cli_dir_is_task_root(tmp_path):
    root = tmp_path / "task-root-single"
    root.mkdir(parents=True, exist_ok=True)

    SessionLocal = _build_session()
    db = SessionLocal()
    task = _seed_single_repo_task(db)
    task.project_path = str(root)
    db.commit()

    cli_dir = task_service.resolve_task_cli_dir(db, task)
    assert os.path.normcase(os.path.abspath(cli_dir)) == os.path.normcase(os.path.abspath(str(root)))


def test_resolve_task_cli_dir_falls_back_to_dot_when_project_path_empty():
    SessionLocal = _build_session()
    db = SessionLocal()
    user = User(id="user-1", email="user@example.com", hashed_password="x", display_name="User")
    workspace = Workspace(id="ws-1", name="Workspace", owner_id=user.id)
    task = SddTask(
        id="task-3",
        workspace_id=workspace.id,
        creator_id=user.id,
        name="Task",
        project_path="",
        status="CODING",
    )
    db.add_all([user, workspace, task])
    db.commit()

    assert task_service.resolve_task_cli_dir(db, task) == "."
