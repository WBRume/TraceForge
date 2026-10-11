import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_current_user, get_db
from app.domains.local_resource.models import TaskExecutionBinding
from app.domains.task.models.task_repository import SddTaskRepository, TaskRepositoryState
from app.domains.task.routers.task import crud
from app.domains.task.services import git_worktree_service
from app.domains.task.services import task_repository_details as details
from app.domains.task.services.task_workspace import repositories
from tests.task.test_task_session_sharing import _seed


def git(path, *args):
    return subprocess.run(
        ["git", *args], cwd=path, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout.strip()


def seed_repo(db, task, **overrides):
    values = {
        "id": "binding-1",
        "task_id": task.id,
        "repo_name": "Repository at creation",
        "repo_url": "https://example.test/original.git",
        "repo_slug": "source",
        "branch_name": "release/original",
        "rel_path": "source",
        "state": TaskRepositoryState.PENDING,
    }
    repo = SddTaskRepository(**{**values, **overrides})
    db.add(repo)
    db.commit()
    return repo


def test_real_worktree_captures_initial_commit_and_survives_head_changes_and_removal(db, tmp_path, monkeypatch):
    _, ws, task = _seed(db)
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-b", "main")
    git(source, "config", "user.name", "Original Author")
    git(source, "config", "user.email", "original@example.test")
    git(source, "commit", "--allow-empty", "-m", "初始提交\n\n完整提交说明")
    initial_sha = git(source, "rev-parse", "HEAD")
    remote = tmp_path / "remote.git"
    git(tmp_path, "clone", "--bare", str(source), str(remote))
    git(source, "remote", "add", "origin", str(remote))
    repo = seed_repo(db, task, branch_name="main")
    task.project_path = str(tmp_path / "task")
    task.task_meta_json = {"existing_key": "preserve"}
    binding = git_worktree_service.RepoWorktreeBinding(
        repo_url=str(remote),
        repo_name="source",
        repo_slug="source",
        branch_name="main",
        base_dir=str(source),
    )
    monkeypatch.setattr(repositories, "build_task_worktree_bindings", lambda *args: [binding])
    repositories.prepare_task_repositories(db, ws, task, [repo])
    db.commit()
    worktree = tmp_path / "task" / "source"
    assert git(worktree, "rev-parse", "HEAD") == initial_sha
    assert task.task_meta_json["existing_key"] == "preserve"
    assert task.task_meta_json[details.COMMIT_SNAPSHOTS_KEY][repo.id]["sha"] == initial_sha
    git(worktree, "commit", "--allow-empty", "-m", "Later task commit")
    git(source, "commit", "--allow-empty", "-m", "Later source commit")
    git(source, "push", "origin", "main")
    ws.git_repo_url = "https://example.test/changed.git"
    db.commit()
    result = details.inspect_task_repositories(db, task)["repositories"][0]
    assert result.repo_url == "https://example.test/original.git"
    assert result.branch_name == "main"
    assert result.base_commit_sha == initial_sha
    assert result.base_commit.message == "初始提交\n\n完整提交说明"
    assert result.base_commit.author_name == "Original Author"
    assert result.base_commit.committed_at
    git(source, "worktree", "remove", str(worktree))
    assert details.inspect_task_repositories(db, task)["repositories"][0].base_commit == result.base_commit
    legacy_checkout = {}
    git_worktree_service.create_task_worktree(
        repo_path=str(source),
        task_id="legacy",
        task_project_path=str(tmp_path / "legacy"),
        checkout_details=legacy_checkout,
    )
    assert legacy_checkout["branch_name"] == "main"
    assert legacy_checkout["base_commit_sha"] == git(source, "rev-parse", "HEAD")
    assert legacy_checkout["base_commit"]["message"] == "Later source commit"


def test_old_record_looks_up_only_saved_sha_and_missing_repo_is_explicit(db, tmp_path):
    _, _, task = _seed(db)
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-b", "main")
    git(source, "config", "user.name", "Test")
    git(source, "config", "user.email", "test@example.test")
    git(source, "commit", "--allow-empty", "-m", "Initial")
    initial_sha = git(source, "rev-parse", "HEAD")
    git(source, "commit", "--allow-empty", "-m", "Current")
    task.project_path = str(tmp_path)
    repo = seed_repo(db, task, base_commit_sha=initial_sha, state=TaskRepositoryState.READY)
    assert details.inspect_task_repositories(db, task)["repositories"][0].base_commit.message == "Initial"
    repo.rel_path = "removed"
    result = details.inspect_task_repositories(db, task)["repositories"][0]
    assert result.base_commit_sha == initial_sha
    assert result.base_commit is None
    assert details.read_commit_info(str(source), "HEAD") is None
    assert details.read_commit_info(str(source), "--all") is None


def test_local_receipt_works_offline_and_keeps_host_path_flavor(db, monkeypatch):
    _, _, task = _seed(db)
    task.execution_location = "LOCAL"
    repo = seed_repo(db, task, base_commit_sha="a" * 40, state=TaskRepositoryState.READY)
    commit = {
        "sha": repo.base_commit_sha,
        "author_name": "Local author",
        "author_email": "a@test",
        "authored_at": "2026-10-11T10:00:00+08:00",
        "committer_name": "Local author",
        "committer_email": "a@test",
        "committed_at": "2026-10-11T10:00:00+08:00",
        "message": "Offline snapshot",
    }
    db.add(
        TaskExecutionBinding(
            task_id=task.id,
            resource_id="offline",
            profile_json={},
            receipt_json={
                "task_root": "/home/user/tasks/task-1",
                "repositories": [
                    {
                        "repository_id": repo.repository_id,
                        "base_commit": commit,
                        "task_branch": "traceforge/task/task-1/repo",
                    }
                ],
            },
        )
    )
    db.commit()
    monkeypatch.setattr(details, "read_commit_info", lambda *args: (_ for _ in ()).throw(AssertionError("local path")))
    monkeypatch.setattr(
        details, "_local_commit_details", lambda *args: (_ for _ in ()).throw(AssertionError("network"))
    )
    result = details.inspect_task_repositories(db, task)["repositories"][0]
    assert result.worktree_path == "/home/user/tasks/task-1/source"
    assert result.base_commit.message == "Offline snapshot"
    assert result.task_branch == "traceforge/task/task-1/repo"


def test_pending_and_legacy_tasks_never_invent_initial_head(db):
    _, _, task = _seed(db)
    task.git_repo_url = "https://example.test/legacy.git"
    legacy = details.inspect_task_repositories(db, task)["repositories"][0]
    assert legacy.base_commit_sha is None
    assert legacy.branch_name is None
    assert legacy.state == "UNKNOWN"
    seed_repo(db, task)
    pending = details.inspect_task_repositories(db, task)["repositories"][0]
    assert pending.base_commit_sha is None
    assert pending.state == "PENDING"


@pytest.mark.parametrize("offline", [False, True])
def test_old_local_tasks_read_exact_commit_from_host_or_keep_saved_sha_offline(db, monkeypatch, offline):
    from app.domains.local_resource import client, service

    _, _, task = _seed(db)
    task.execution_location = "LOCAL"
    repo = seed_repo(db, task, base_commit_sha="b" * 40, state=TaskRepositoryState.READY)
    db.add(
        TaskExecutionBinding(
            task_id=task.id,
            resource_id="r",
            profile_json={},
            receipt_json={
                "task_root": "C:\\tasks\\task-1",
                "repositories": [{"repository_id": repo.repository_id}],
            },
        )
    )
    db.commit()
    monkeypatch.setattr(service, "runtime_profile", lambda *args: {})

    class ReadOnlyClient:
        def __init__(self, profile, *, timeout):
            assert timeout == 4

        def operation(self, task_id, kind, payload):
            assert (task_id, kind, payload) == (task.id, "repository_details", {})
            if offline:
                raise client.ResourceError("offline")
            return {
                "repositories": [
                    {
                        "repository_id": repo.repository_id,
                        "base_commit": {
                            "sha": repo.base_commit_sha,
                            "author_name": "Original",
                            "author_email": "original@test",
                            "authored_at": "2026-10-11T10:00:00+08:00",
                            "committer_name": "Original",
                            "committer_email": "original@test",
                            "committed_at": "2026-10-11T10:00:00+08:00",
                            "message": "Old local commit",
                        },
                    }
                ]
            }

    monkeypatch.setattr(client, "ResourceClient", ReadOnlyClient)
    monkeypatch.setattr(details, "read_commit_info", lambda *args: pytest.fail("Must not read host paths on server"))
    result = details.inspect_task_repositories(db, task)["repositories"][0]
    assert result.base_commit_sha == "b" * 40
    assert result.worktree_path == "C:\\tasks\\task-1\\source"
    if offline:
        assert result.base_commit is None
    else:
        assert result.base_commit.message == "Old local commit"


def test_details_api_preserves_workspace_access_and_task_scope(db):
    owner, _, task = _seed(db)
    seed_repo(db, task)
    app = FastAPI()
    app.include_router(crud.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: owner
    client = TestClient(app)
    response = client.get("/api/workspaces/ws-1/tasks/task-1/details")
    assert response.status_code == 200, response.text
    assert response.json()["repositories"][0]["branch_name"] == "release/original"
    assert client.get("/api/workspaces/ws-1/tasks/missing/details").status_code == 404
    assert client.get("/api/workspaces/other/tasks/task-1/details").status_code == 403
