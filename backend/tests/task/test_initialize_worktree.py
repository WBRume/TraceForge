"""Actual Git worktrees, durable SQLite journal, incremental snapshots and fault replay."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app import database
from app.agents import selection
from app.config import settings
from app.domains.ai.models.ai_job import SddAiJob
from app.domains.ai.services.jobs import publishing
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.models.task_repository import SddTaskRepository, TaskRepositoryState
from app.domains.task.services import chat_submission_service
from app.domains.task.services import task_session_snapshot_service as snapshots
from app.domains.task.services.initialization import service, state, worktree
from app.domains.task.services.repository_updates.git import git
from app.domains.workspace_collaboration import service as collaboration
from tests.workspace_asset.test_workspace_asset_boundary import _build_db, _seed_workspace


@pytest.fixture
def environment(tmp_path, monkeypatch):
    engine, factory = _build_db()
    root = tmp_path / "task"
    root.mkdir()
    upstreams = []
    for name in ("a", "b"):
        upstream = tmp_path / ("upstream-" + name)
        upstream.mkdir()
        git(upstream, "init", "-b", "main")
        (upstream / "stable.txt").write_text("unchanged\n")
        (upstream / "edited.txt").write_text("initial\n")
        (upstream / ".gitignore").write_text("dist/\n")
        git(upstream, "add", ".")
        git(upstream, "commit", "-m", "base")
        git(tmp_path, "clone", str(upstream), str(root / name))
        upstreams.append(upstream)
    monkeypatch.setattr(settings, "TASK_SESSION_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))
    with factory() as db:
        user, ws, task = _seed_workspace(db)
        task.project_path = str(root)
        task.status = TaskStatus.CODING
        task.session_id = "old-provider-session"
        task.session_generation = 2
        for name, upstream in zip(("a", "b"), upstreams, strict=True):
            db.add(
                SddTaskRepository(
                    id=name,
                    task_id=task.id,
                    repo_url=str(upstream),
                    repo_name=name,
                    repo_slug=name,
                    branch_name="main",
                    base_commit_sha=git(root / name, "rev-parse", "HEAD"),
                    rel_path=name,
                    state=TaskRepositoryState.READY,
                )
            )
        checkpoint = snapshots._create_checkpoint_sync(
            str(root), ["a", "b"], "none", None, ws.id, ws.name, task.id, task.name
        )
        task.task_meta_json = {"initial_workspace_checkpoint": checkpoint["root"]}
        db.commit()
    monkeypatch.setattr(database, "SessionLocal", factory)
    monkeypatch.setattr(selection, "resolve_task_backend", lambda *args: "opencode")
    monkeypatch.setattr(service.control, "get_engine", lambda *args: None)
    monkeypatch.setattr(publishing, "enqueue_task_chat_job", AsyncMock())
    monkeypatch.setattr(publishing, "publish_job", AsyncMock())
    yield factory, root, upstreams, checkpoint["root"]
    engine.dispose()


async def initialize(factory, operation_id="reset-operation-1"):
    with factory() as db:
        return await service.initialize(
            db,
            ws_id="ws-1",
            task_id="task-1",
            actor_user_id="user-1",
            operation_id=operation_id,
            skill_ids=None,
            keep_deleted_runtime_skills=False,
            requested_prompt="Only inspect the clean code",
            reason="restart",
        )


def dirty(root):
    for name in ("a", "b"):
        repo = root / name
        (repo / "edited.txt").write_text("local merge resolution\n")
        (repo / "generated.txt").write_text("generated\n")
        git(repo, "add", ".")
        git(repo, "commit", "-m", "agent result")
        (repo / "untracked.txt").write_text("untracked\n")
        (repo / "dist").mkdir()
        (repo / "dist/result.txt").write_text("ignored output\n")
    (root / "RESULT.md").write_text("task root output\n")
    spec = root / ".sdd/spec/input.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("input specification\n")


def advance(upstreams):
    for upstream in upstreams:
        (upstream / "edited.txt").write_text("latest remote\n")
        git(upstream, "add", ".")
        git(upstream, "commit", "-m", "remote update")


@pytest.mark.asyncio
async def test_dual_reset_removes_all_output_and_reuses_git_and_snapshot_store(environment):
    factory, root, upstreams, initial = environment
    dirty(root)
    advance(upstreams)
    stamps = [(root / name / "stable.txt").stat().st_mtime_ns for name in ("a", "b")]
    result = await initialize(factory)
    for index, name in enumerate(("a", "b")):
        repo = root / name
        assert git(repo, "rev-parse", "HEAD") == git(upstreams[index], "rev-parse", "HEAD")
        assert (repo / "edited.txt").read_text() == "latest remote\n"
        assert (repo / "stable.txt").stat().st_mtime_ns == stamps[index]
        assert not any((repo / path).exists() for path in ("generated.txt", "untracked.txt", "dist"))
    assert not (root / "RESULT.md").exists()
    assert (root / ".sdd/spec/input.md").read_text() == "input specification\n"
    with factory() as db:
        task = db.get(SddTask, "task-1")
        operation = state.current(task)
        assert operation["state"] == "COMPLETED"
        assert task.session_generation == 3 and task.session_id is None
        assert db.get(SddAiJob, result["job"]["id"]).session_id is None
        checkpoint = task.task_meta_json["initial_workspace_checkpoint"]
        assert Path(checkpoint).parent == Path(initial).parent
        assert checkpoint != initial
        assert len(list(Path(initial).parent.glob("turn-*"))) == 2  # One clean boundary, no pre-reset backup.
        assert not list(Path(initial).parent.rglob("compensation*"))
    again = await initialize(factory)
    assert again["job"]["id"] == result["job"]["id"]
    with factory() as db:
        assert db.query(SddAiJob).count() == 1
        assert db.get(SddTask, "task-1").session_generation == 3


@pytest.mark.asyncio
async def test_interruption_keeps_heads_pinned_and_fences_writes_then_resumes(environment, monkeypatch):
    factory, root, upstreams, _ = environment
    dirty(root)
    advance(upstreams)
    targets = [git(upstream, "rev-parse", "HEAD") for upstream in upstreams]
    original = worktree.reset

    def fail_second(task_root, repo):
        if repo["id"] == "b":
            raise OSError("injected process boundary")
        return original(task_root, repo)

    monkeypatch.setattr(worktree, "reset", fail_second)
    with pytest.raises(state.InitializationError):
        await initialize(factory)
    with factory() as db:
        task = db.get(SddTask, "task-1")
        operation = state.current(task)
        assert operation["state"] == "RESETTING"
        assert operation["repositories"][0]["completed"] is True
        assert not operation["repositories"][1].get("completed")
        assert db.query(SddAiJob).count() == 0
        assert task.session_generation == 2
        with pytest.raises(chat_submission_service.SubmissionError):
            chat_submission_service.assert_no_preparing_submission(db, task.id)
        with pytest.raises(collaboration.CollaborationError):
            collaboration._assert_no_writer(db, task.id, read_only=True)
    # A later upstream push must not silently change an in-progress operation.
    for upstream in upstreams:
        (upstream / "later.txt").write_text("after operation began\n")
        git(upstream, "add", ".")
        git(upstream, "commit", "-m", "later")
    monkeypatch.setattr(worktree, "reset", original)
    await initialize(factory)
    assert [git(root / name, "rev-parse", "HEAD") for name in ("a", "b")] == targets
    assert not (root / "b/later.txt").exists()


@pytest.mark.asyncio
async def test_failed_baseline_retries_without_advancing_generation_twice(environment, monkeypatch):
    factory, root, _, _ = environment
    dirty(root)
    original = snapshots.create_checkpoint
    monkeypatch.setattr(snapshots, "create_checkpoint", AsyncMock(side_effect=OSError("snapshot interrupted")))
    with pytest.raises(state.InitializationError):
        await initialize(factory)
    with factory() as db:
        assert state.current(db.get(SddTask, "task-1"))["state"] == "STARTING"
        assert db.get(SddTask, "task-1").session_generation == 3
        assert db.query(SddAiJob).count() == 0
    monkeypatch.setattr(snapshots, "create_checkpoint", original)
    await initialize(factory)
    with factory() as db:
        assert db.get(SddTask, "task-1").session_generation == 3
        assert db.query(SddAiJob).count() == 1


@pytest.mark.asyncio
async def test_fetch_failure_never_modifies_either_worktree(environment, monkeypatch):
    factory, root, _, _ = environment
    dirty(root)
    original = worktree.fetch

    def fail_second(task_root, repo):
        if repo["id"] == "b":
            raise OSError("unreachable")
        return original(task_root, repo)

    monkeypatch.setattr(worktree, "fetch", fail_second)
    with pytest.raises(state.InitializationError):
        await initialize(factory)
    assert all((root / name / "generated.txt").exists() for name in ("a", "b"))
    assert (root / "RESULT.md").exists()
