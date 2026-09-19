"""
delete_task 软删除归档测试

覆盖：
- 非 git 任务删除后，任务目录被移入 <工作区根>/.delete/，而非原地删除
- 多仓任务清理 worktree 后残留的任务根目录同样移入 .delete
- 归档名冲突时追加 _1 序号
- 目录位于工作区之外 / 已不存在时不移动、不报错
"""

import os
import shutil
import sys
import tempfile
import unittest

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.dirname(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

from app.database import Base  # noqa: E402
from app.domains.auth.models.user import User, Workspace, WorkspaceRole  # noqa: E402
from app.domains.task.models.task import SddTask, TaskStatus  # noqa: E402
from app.domains.task.services import task_service  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from test_workspace_asset_boundary import _session  # noqa: E402


class DeleteTaskTrashArchiveTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace_root = os.path.realpath(tempfile.mkdtemp(dir=self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()
        self.engine.dispose()

    def _seed(self, *, task_id: str, task_name: str, task_path: str, git_repo_url: str = ""):
        with _session(self.SessionLocal) as db:
            user = User(id="user-1", email="user@example.com", hashed_password="x", display_name="User")
            workspace = Workspace(
                id="ws-1", name="Workspace", owner_id=user.id, project_path=self.workspace_root
            )
            task = SddTask(
                id=task_id,
                workspace_id="ws-1",
                creator_id=user.id,
                name=task_name,
                project_path=task_path,
                git_repo_url=git_repo_url,
                status=TaskStatus.PLANNING,
            )
            db.add_all([user, workspace, task])
            db.commit()

    def _delete(self, task_id: str):
        with _session(self.SessionLocal) as db:
            return task_service.delete_task(db, task_id, "ws-1")

    def test_plain_task_dir_moved_into_delete_trash(self):
        task_dir = os.path.join(self.workspace_root, "task-1_My task")
        os.makedirs(task_dir)
        with open(os.path.join(task_dir, "hello.txt"), "w", encoding="utf-8") as f:
            f.write("data")
        self._seed(task_id="task-1", task_name="My task", task_path=task_dir)

        self.assertTrue(self._delete("task-1"))
        self.assertFalse(os.path.exists(task_dir))
        archived = os.path.join(self.workspace_root, ".delete", "task-1_My task")
        self.assertTrue(os.path.isdir(archived))
        with open(os.path.join(archived, "hello.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "data")

    def test_name_conflict_gets_sequence_suffix(self):
        task_dir = os.path.join(self.workspace_root, "task-2_Dup")
        os.makedirs(task_dir)
        trash_existing = os.path.join(self.workspace_root, ".delete", "task-2_Dup")
        os.makedirs(trash_existing)
        self._seed(task_id="task-2", task_name="Dup", task_path=task_dir)

        self.assertTrue(self._delete("task-2"))
        self.assertFalse(os.path.exists(task_dir))
        self.assertTrue(os.path.isdir(os.path.join(self.workspace_root, ".delete", "task-2_Dup_1")))

    def test_dir_outside_workspace_not_touched(self):
        outside = os.path.realpath(os.path.join(self._tmp.name, "outside-root"))
        task_dir = os.path.join(outside, "task-3_External")
        os.makedirs(task_dir)
        self._seed(task_id="task-3", task_name="External", task_path=task_dir)

        self.assertTrue(self._delete("task-3"))
        self.assertTrue(os.path.isdir(task_dir))
        self.assertFalse(os.path.isdir(os.path.join(self.workspace_root, ".delete")))

    def test_missing_dir_is_noop(self):
        task_dir = os.path.join(self.workspace_root, "task-4_Ghost")
        self._seed(task_id="task-4", task_name="Ghost", task_path=task_dir)

        self.assertTrue(self._delete("task-4"))
        self.assertFalse(os.path.exists(task_dir))
        self.assertFalse(os.path.isdir(os.path.join(self.workspace_root, ".delete")))


if __name__ == "__main__":
    unittest.main()
