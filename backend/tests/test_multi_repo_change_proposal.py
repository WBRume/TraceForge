"""
Multi-repository change proposal / patch snapshot tests.
"""

import os
import sys
import unittest
from unittest import mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.database import Base  # noqa: E402
from app.domains.auth.models.user import User, Workspace  # noqa: E402
from app.domains.task.models.task import SddTask  # noqa: E402
from app.domains.task.models.task_repository import (  # noqa: E402
    SddTaskRepository,
    TaskRepositoryState,
)
from app.domains.task.services import git_patch_service  # noqa: E402

import app.models.asset  # noqa: E402,F401
import app.models.chat  # noqa: E402,F401
import app.models.log  # noqa: E402,F401
import app.models.test_result  # noqa: E402,F401
import app.models.metric  # noqa: E402,F401
import app.models.skill  # noqa: E402,F401
import app.models.api_mock  # noqa: E402,F401
import app.models.ai_job  # noqa: E402,F401
import app.models.workspace_asset  # noqa: E402,F401
import app.models.task_change  # noqa: E402,F401
import app.models.task_cli_bootstrap  # noqa: E402,F401
import app.models.provision_job  # noqa: E402,F401
import app.models.management  # noqa: E402,F401
import app.models.workspace_repository  # noqa: E402,F401


def _snapshot(repo_name="billing-core", changed=True):
    if not changed:
        raise git_patch_service.GitPatchError("No changes in task worktree", status_code=409)
    return git_patch_service.TaskPatchSnapshot(
        base_repo_url="https://git.example.com/" + repo_name + ".git",
        base_branch="release/v8r21",
        base_commit_sha="base-sha",
        cloud_task_branch="task/task-1",
        cloud_head_sha="head-sha",
        patch_text="diff --git a/a b/a",
        changed_files_count=1,
        insertions=3,
        deletions=1,
        files=[
            git_patch_service.PatchFileChange(
                file_path="a",
                change_type="modified",
                insertions=3,
                deletions=1,
            )
        ],
    )


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)
    db = session()
    try:
        yield db
    finally:
        db.close()


def _seed_task(db):
    user = User(id="user-1", email="u@example.com", hashed_password="x", display_name="U")
    workspace = Workspace(id="ws-1", name="W", owner_id="user-1", project_path="C:/ws")
    db.add(user)
    db.add(workspace)
    db.commit()
    task = SddTask(
        id="task-1",
        workspace_id="ws-1",
        creator_id="user-1",
        name="T",
        project_path="C:/ws/task-1",
        status="PENDING",
    )
    db.add(task)
    db.commit()
    return task


class MultiRepoPatchSnapshotTest(unittest.TestCase):
    def test_aggregates_per_repo_snapshots_and_skips_unchanged(self):
        task = mock.Mock()
        task.id = "task-1"
        task.project_path = "C:/ws/task-1"
        task.git_repo_url = None
        db = mock.Mock()

        binding_ready = mock.Mock()
        binding_ready.repository_id = "repo-1"
        binding_ready.repo_url = "https://git.example.com/one.git"
        binding_ready.repo_name = "one"
        binding_ready.repo_slug = "one"
        binding_ready.branch_name = "main"
        binding_ready.rel_path = "one"
        binding_ready.state = TaskRepositoryState.READY

        binding_unchanged = mock.Mock()
        binding_unchanged.repository_id = "repo-2"
        binding_unchanged.repo_url = "https://git.example.com/two.git"
        binding_unchanged.repo_name = "two"
        binding_unchanged.repo_slug = "two"
        binding_unchanged.branch_name = "main"
        binding_unchanged.rel_path = "two"
        binding_unchanged.state = TaskRepositoryState.READY

        with mock.patch(
            "app.domains.task.services.task_service.get_task_repositories",
            return_value=[binding_ready, binding_unchanged],
        ), mock.patch(
            "app.domains.task.services.git_patch_service.os.path.isdir",
            return_value=True,
        ), mock.patch.object(
            git_patch_service,
            "_generate_patch_snapshot_for_repo",
            side_effect=[
                _snapshot("one"),
                git_patch_service.GitPatchError("No changes in task worktree", status_code=409),
            ],
        ):
            snapshots = git_patch_service.generate_task_repo_patch_snapshots(task, None, db=db)
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0].repo_name, "one")
            self.assertEqual(snapshots[0].repository_id, "repo-1")

    def test_all_unchanged_raises(self):
        task = mock.Mock()
        task.id = "task-1"
        task.project_path = "C:/ws/task-1"
        task.git_repo_url = None
        db = mock.Mock()
        binding = mock.Mock()
        binding.repository_id = "repo-1"
        binding.repo_url = "https://git.example.com/one.git"
        binding.repo_name = "one"
        binding.repo_slug = "one"
        binding.branch_name = "main"
        binding.rel_path = "one"
        binding.state = TaskRepositoryState.READY

        with mock.patch(
            "app.domains.task.services.task_service.get_task_repositories",
            return_value=[binding],
        ), mock.patch(
            "app.domains.task.services.git_patch_service.os.path.isdir",
            return_value=True,
        ), mock.patch.object(
            git_patch_service,
            "_generate_patch_snapshot_for_repo",
            side_effect=git_patch_service.GitPatchError("No changes in task worktree", status_code=409),
        ):
            with self.assertRaises(git_patch_service.GitPatchError) as ctx:
                git_patch_service.generate_task_repo_patch_snapshots(task, None, db=db)
            self.assertIn("No changes in any task repository", str(ctx.exception))
            self.assertEqual(ctx.exception.status_code, 409)

    def test_falls_back_to_legacy_single_repo_without_bindings(self):
        task = mock.Mock()
        task.id = "task-1"
        task.project_path = "C:/ws/task-1"
        task.git_repo_url = "https://git.example.com/one.git"
        db = mock.Mock()

        with mock.patch(
            "app.domains.task.services.task_service.get_task_repositories",
            return_value=[],
        ), mock.patch.object(
            git_patch_service,
            "generate_task_patch_snapshot",
            return_value=_snapshot("legacy"),
        ):
            snapshots = git_patch_service.generate_task_repo_patch_snapshots(task, None, db=db)
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0].repo_slug, "repo")
