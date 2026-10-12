"""Real clones, readiness visibility, partial failures and retry recovery."""

import asyncio
import subprocess
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from app.domains.auth.models.user import User, Workspace
from app.domains.management.models.management import SddManagementRepository
from app.domains.task.services import git_worktree_service as git
from app.domains.workflow.models.provision_job import ProvisionJobStatus, ProvisionJobType
from app.domains.workflow.services import provision_job_service as provision
from app.domains.workspace.models.workspace_repository import WorkspaceRepositoryState
from app.domains.workspace.services import workspace_service


def _git(path: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def workspace_job(db, tmp_path, monkeypatch):
    user = User(id="creator", email="creator@example.com", hashed_password="x", display_name="Creator")
    db.add(user)
    for index in range(2):
        source = tmp_path / f"source-{index}"
        source.mkdir()
        _git(source, "init", "-b", "main")
        _git(source, "config", "user.email", "git@example.com")
        _git(source, "config", "user.name", "Git test")
        (source / "code.txt").write_text("main", encoding="utf-8")
        _git(source, "add", ".")
        _git(source, "commit", "-m", "main")
        _git(source, "checkout", "-b", "feature/selected")
        (source / "code.txt").write_text("selected", encoding="utf-8")
        _git(source, "commit", "-am", "selected")
        _git(source, "tag", "v1")
        _git(source, "checkout", "main")
        db.add(
            SddManagementRepository(
                id=f"repo-{index}",
                name=f"repo-{index}",
                git_url=str(source),
                repo_type="CUSTOM",
                default_branch="main",
            )
        )
    db.commit()
    monkeypatch.setattr(provision, "SessionLocal", sessionmaker(bind=db.get_bind()))
    job = provision.create_job(
        db,
        job_type=ProvisionJobType.CREATE_WORKSPACE,
        creator_id=user.id,
        context_json={
            "name": "Two repos",
            "project_path": str(tmp_path / "workspace"),
            "project_name": "Project",
            "product_name": "Product",
            "repositories": [
                {"repository_id": f"repo-{index}", "branch_name": "feature/selected"} for index in range(2)
            ],
        },
    )
    return user, job


@pytest.mark.parametrize("failed_repos", [{"repo-1"}, {"repo-0", "repo-1"}, set()])
def test_workspace_published_only_after_all_clones_succeed(db, workspace_job, monkeypatch, failed_repos):
    user, job = workspace_job
    prepare = git.prepare_workspace_repository
    progress = []
    real_progress = provision.mark_progress

    def observe_progress(job_id, **kwargs):
        progress.append(kwargs)
        real_progress(job_id, **kwargs)

    def prepare_or_fail(repo_url, base_dir, branch_name, **kwargs):
        # Polling during either clone must never publish this workspace.
        assert workspace_service.list_user_workspaces(db, user) == []
        assert workspace_service.list_user_workspace_summaries(db, user) == []
        if Path(base_dir).name in failed_repos:
            raise git.GitWorktreeError("Git command timed out after 180s")
        return prepare(repo_url, base_dir, branch_name, **kwargs)

    monkeypatch.setattr(git, "prepare_workspace_repository", prepare_or_fail)
    monkeypatch.setattr(provision, "mark_progress", observe_progress)
    asyncio.run(provision.run_create_workspace_job(job.id))
    db.refresh(job)
    workspace_id = job.workspace_id
    assert workspace_id
    assert any("1/2: repo-0" in item["message"] for item in progress)
    assert any("2/2: repo-1" in item["message"] and item["progress"] > 40 for item in progress)

    if failed_repos:
        assert job.status == ProvisionJobStatus.FAILED
        assert "timed out after 180s" in job.error_message
        assert workspace_service.list_user_workspaces(db, user) == []
        assert workspace_service.list_user_workspace_summaries(db, user) == []
        outcomes = job.result_json["repository_materialization"]["repositories"]
        assert {r["repo_name"] for r in outcomes if r["state"] == "FAILED"} == failed_repos
        # Retry reuses the original workspace and safely keeps successful clones.
        job = provision.retry_job(db, source_job=job, creator_id=user.id)
        monkeypatch.setattr(git, "prepare_workspace_repository", prepare)
        asyncio.run(provision.run_create_workspace_job(job.id))
        db.refresh(job)

    assert job.status == ProvisionJobStatus.SUCCESS
    assert job.workspace_id == workspace_id
    assert db.query(Workspace).count() == 1
    assert [w.id for w in workspace_service.list_user_workspaces(db, user)] == [workspace_id]
    assert [w["id"] for w in workspace_service.list_user_workspace_summaries(db, user)] == [workspace_id]
    for row in job.result_json["repositories"]:
        assert row["state"] == "READY"
        assert row["base_commit_sha"] == _git(Path(row["base_dir"]), "rev-parse", "HEAD")
        assert (Path(row["base_dir"]) / "code.txt").read_text() == "selected"


def test_old_false_success_is_hidden_by_repository_state(db, workspace_job):
    user, job = workspace_job
    result = provision._create_workspace_sync(job_id=job.id, creator_id=user.id, context=job.context_json)
    workspace = db.get(Workspace, result["workspace_id"])
    for row in workspace.repositories:
        row.state = WorkspaceRepositoryState.FAILED
    job.status = ProvisionJobStatus.SUCCESS
    db.commit()
    assert workspace_service.list_user_workspaces(db, user) == []
    assert workspace_service.list_user_workspace_summaries(db, user) == []


def test_legacy_workspace_without_job_remains_visible(db, workspace_job):
    user, _ = workspace_job
    workspace = workspace_service.create_workspace(db, user, "Legacy workspace")
    assert [w.id for w in workspace_service.list_user_workspaces(db, user)] == [workspace.id]


@pytest.mark.parametrize("ref,ref_type", [("missing", "BRANCH"), ("v1", "TAG")])
def test_selected_ref_is_verified(workspace_job, tmp_path, ref, ref_type):
    source, destination = tmp_path / "source-0", tmp_path / "checkout"
    if ref == "missing":
        with pytest.raises(git.GitWorktreeError, match="does not exist on origin"):
            git.prepare_workspace_repository(str(source), str(destination), ref, ref_type=ref_type)
    else:
        sha = git.prepare_workspace_repository(str(source), str(destination), ref, ref_type=ref_type)
        assert sha == _git(source, "rev-parse", "v1")
        assert (destination / "code.txt").read_text() == "selected"


def test_failed_clone_cleanup_does_not_block_retry(workspace_job, tmp_path, monkeypatch):
    source, destination = tmp_path / "source-0", tmp_path / "retry-clone"
    real_run = git._run_git_checked

    def timed_out_clone(args, **kwargs):
        assert args[0] == "clone"
        (Path(args[-1]) / ".git").mkdir(parents=True)
        raise git.GitWorktreeError("clone timed out")

    monkeypatch.setattr(git, "_run_git_checked", timed_out_clone)
    monkeypatch.setattr(git.shutil, "rmtree", lambda *args, **kwargs: None)
    with pytest.raises(git.GitWorktreeError, match="timed out"):
        git.ensure_base_repository(str(source), str(destination))
    assert not destination.exists()
    assert list(tmp_path.glob("retry-clone.clone-*"))

    monkeypatch.setattr(git, "_run_git_checked", real_run)
    sha = git.prepare_workspace_repository(str(source), str(destination), "main")
    assert sha == _git(source, "rev-parse", "main")
    assert (destination / "code.txt").read_text() == "main"


@pytest.mark.parametrize("args,expected_timeout", [(["clone", "remote", "path"], 720), (["status"], None)])
def test_clone_timeout_is_configurable_and_isolated(monkeypatch, args, expected_timeout):
    from app.config import settings
    from app.core import subprocess_runner

    monkeypatch.setattr(settings, "GIT_CLONE_TIMEOUT_SECONDS", 720)
    calls = []

    def run_git(command, **kwargs):
        calls.append(kwargs["timeout_seconds"])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess_runner, "run_git", run_git)
    git._run_git_raw(args)
    assert calls == [expected_timeout]
