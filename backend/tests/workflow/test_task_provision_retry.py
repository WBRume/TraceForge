"""Creation receipts survive cleanup and retry prepares fresh, real dual worktrees."""

import asyncio
from pathlib import Path

import pytest
from fastapi import BackgroundTasks
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request
from workspace import test_workspace_provision_readiness as workspace_fixtures

from app.config import settings
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.models.task_repository import SddTaskRepository
from app.domains.task.routers.task.crud import create_task
from app.domains.task.schemas.task import TaskCreate
from app.domains.task.services.provisioning import resources
from app.domains.workflow.models.provision_job import ProvisionJobStatus, ProvisionJobType, SddProvisionJob
from app.domains.workflow.services import provision_job_service as provision
from app.domains.workspace.models.workspace_repository import SddWorkspaceRepository

workspace_job = workspace_fixtures.workspace_job
_git = workspace_fixtures._git


def test_failed_dual_task_retry_recreates_bindings_and_prepares_both_repos(db, workspace_job, tmp_path, monkeypatch):
    user, workspace_receipt = workspace_job
    # Match production sessions; polling uses a second session on SQLite's
    # shared connection and must not roll back implicitly flushed bindings.
    monkeypatch.setattr(provision, "SessionLocal", sessionmaker(bind=db.get_bind(), autoflush=False))
    monkeypatch.setattr(settings, "TASK_SESSION_SNAPSHOT_ROOT", str(tmp_path / "snapshots"))
    asyncio.run(provision.run_create_workspace_job(workspace_receipt.id))
    db.refresh(workspace_receipt)
    assert workspace_receipt.status == ProvisionJobStatus.SUCCESS
    data = TaskCreate(
        name="Dual retry",
        description=" original description ",
        requirement_duration_hours=3.5,
        repository_ids=["repo-0", "repo-1"],
        repository_branches=[{"repository_id": "repo-0", "branch_name": "main"}],
    )
    accepted = create_task(
        workspace_receipt.workspace_id, data, BackgroundTasks(), Request({"type": "http", "headers": []}), user, db
    )
    job = db.get(SddProvisionJob, accepted["job_id"])
    old_id = job.task_id
    old_path = db.get(SddTask, old_id).project_path
    saved_request = job.context_json["task_create_request"]
    assert saved_request["repository_ids"] == ["repo-0", "repo-1"]
    assert saved_request["repository_branches"] == [
        {"repository_id": "repo-0", "branch_name": "main"},
        {"repository_id": "repo-1", "branch_name": "feature/selected"},
    ]
    original_checkpoint = resources._prepare_initial_workspace_checkpoint

    def fail_after_both_worktrees(*args):
        assert (Path(old_path) / "repo-0/code.txt").read_text() == "main"
        assert (Path(old_path) / "repo-1/code.txt").read_text() == "selected"
        raise OSError("Controlled checkpoint failure")

    monkeypatch.setattr(resources, "_prepare_initial_workspace_checkpoint", fail_after_both_worktrees)
    asyncio.run(provision.run_create_task_job(job.id))
    db.expire_all()
    assert job.status == ProvisionJobStatus.FAILED
    assert db.get(SddTask, old_id) is None
    assert not Path(old_path).exists()
    db.query(SddWorkspaceRepository).filter_by(
        workspace_id=workspace_receipt.workspace_id, repository_id="repo-1"
    ).one().branch_name = "main"
    db.commit()
    retry = provision.retry_job(db, source_job=job, creator_id=user.id)
    assert retry.task_id != old_id and retry.task_id
    task = db.get(SddTask, retry.task_id)
    assert task.description == "original description" and task.requirement_duration_hours == 3.5
    assert retry.context_json["task_id"] == task.id
    assert retry.context_json["task_create_request"] == saved_request
    with pytest.raises(ValueError, match="已发起重试"):
        provision.retry_job(db, source_job=job, creator_id=user.id)
    db.rollback()
    monkeypatch.setattr(resources, "_prepare_initial_workspace_checkpoint", original_checkpoint)
    asyncio.run(provision.run_create_task_job(retry.id))
    db.expire_all()
    assert retry.status == ProvisionJobStatus.SUCCESS
    assert task.status == TaskStatus.PENDING
    assert task.task_meta_json["initial_workspace_checkpoint"]
    bindings = db.query(SddTaskRepository).filter_by(task_id=task.id).all()
    assert {r.repository_id for r in bindings} == {"repo-0", "repo-1"}
    for row in bindings:
        directory = Path(task.project_path) / row.rel_path
        assert _git(directory, "rev-parse", "HEAD") == row.base_commit_sha
        assert (directory / "code.txt").read_text() == ("main" if row.repository_id == "repo-0" else "selected")


def test_legacy_deleted_task_rejects_retry_without_creating_a_broken_job(db, workspace_job):
    user, _workspace_receipt = workspace_job
    job = provision.create_job(
        db,
        job_type=ProvisionJobType.CREATE_TASK,
        creator_id=user.id,
        context_json={"task_id": "deleted", "task_name": "Legacy"},
    )
    job.status = ProvisionJobStatus.FAILED
    db.commit()
    count = db.query(SddProvisionJob).count()
    with pytest.raises(ValueError, match="未保存创建参数"):
        provision.retry_job(db, source_job=job, creator_id=user.id)
    assert db.query(SddProvisionJob).count() == count
    assert db.query(SddTask).count() == 0
