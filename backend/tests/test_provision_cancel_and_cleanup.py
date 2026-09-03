"""
任务创建取消/失败回滚测试

覆盖：
- git 阶段失败（认证/网络）→ 清理资源并删除任务记录（不再残留 FAILED 任务）
- 准备中取消（排队/worktree 创建后）→ 终止工作流并回滚
- 成功路径回归（PROVISIONING → PENDING）
- 任务列表不展示 PROVISIONING；initialize 拦截 PREPARE_FAILED
- provision job 取消接口（仅创建人可取消）与 active 列表（仅创建人可见）
"""

import asyncio
import os
import shutil
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.dirname(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

import app.domains.task.models.task_repository  # noqa: F401,E402
import app.domains.workflow.models.provision_job  # noqa: F401,E402
from app.database import Base  # noqa: E402
from app.domains.auth.models.user import User, Workspace, WorkspaceMember, WorkspaceRole  # noqa: E402
from app.domains.task.models.task import SddTask, TaskStatus  # noqa: E402
from app.domains.task.routers import task as task_router  # noqa: E402
from app.domains.task.services import git_worktree_service  # noqa: E402
from app.domains.task.services.task_service import (  # noqa: E402
    create_task_record_for_provision,
    list_tasks,
)
from app.domains.workflow.models.provision_job import ProvisionJobType, SddProvisionJob  # noqa: E402
from app.domains.workflow.routers import provision as provision_router  # noqa: E402
from app.domains.workflow.services import provision_job_service  # noqa: E402
from test_workspace_asset_boundary import _build_db, _session  # noqa: E402


def _seed_workspace(
    db,
    *,
    workspace_id: str,
    task_id: str,
    user_id: str = "user-1",
    project_path: str = "",
    git_repo_url: str = "",
    task_status=TaskStatus.PROVISIONING,
):
    user = User(id=user_id, email=f"{user_id}@example.com", hashed_password="x", display_name="User")
    workspace = Workspace(
        id=workspace_id,
        name="Workspace",
        owner_id=user.id,
        project_path=project_path,
        git_repo_url=git_repo_url,
    )
    member = WorkspaceMember(
        id=f"member-{workspace_id}",
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.OWNER,
        permissions_json="[]",
        is_expert=True,
    )
    task = SddTask(
        id=task_id,
        workspace_id=workspace.id,
        creator_id=user.id,
        name="Task",
        project_path=project_path,
        git_repo_url=git_repo_url,
        status=task_status,
        current_phase="PREPARING",
    )
    db.add_all([user, workspace, member, task])
    db.commit()
    return user, workspace, task


def _seed_provision_job(db, *, user, workspace, task):
    job = provision_job_service.create_job(
        db,
        job_type=ProvisionJobType.CREATE_TASK,
        creator_id=user.id,
        workspace_id=workspace.id,
        task_id=task.id,
        context_json={"workspace_id": workspace.id, "task_id": task.id, "task_name": task.name},
    )
    return job


def _fake_worktree_creator(job_id=None, session_factory=None):
    """模拟 git worktree 创建：真实创建任务目录，可选在创建后立刻置取消标记。"""

    def _create(*, repo_path, task_id, task_project_path, expected_git_repo_url):
        os.makedirs(task_project_path, exist_ok=True)
        if session_factory is not None and job_id:
            with _session(session_factory) as s:
                row = s.query(SddProvisionJob).filter(SddProvisionJob.id == job_id).first()
                row.cancel_requested = True
                s.commit()

    return _create


def test_git_failure_deletes_task_and_keeps_no_failed_record(tmp_path, monkeypatch):
    """git 阶段认证失败：job FAILED 带原因，任务记录删除，不残留 FAILED 任务。"""
    engine, SessionLocal = _build_db()
    try:
        monkeypatch.setattr(provision_job_service, "SessionLocal", SessionLocal)
        with _session(SessionLocal) as db:
            user, workspace, _ = _seed_workspace(
                db,
                workspace_id="ws-git-fail",
                task_id="task-git-fail",
                project_path=str(tmp_path / "repo"),
                git_repo_url="https://git.example.com/repo.git",
            )
            task = create_task_record_for_provision(db, user, workspace.id, name="git-fail-task")
            job = _seed_provision_job(db, user=user, workspace=workspace, task=task)
            task_id, project_path = task.id, task.project_path

        def _raise_auth_error(*, repo_path, task_id, task_project_path, expected_git_repo_url):
            raise git_worktree_service.GitWorktreeError("Authentication failed for 'https://git.example.com/repo.git'")

        monkeypatch.setattr(git_worktree_service, "create_task_worktree", _raise_auth_error)

        asyncio.run(provision_job_service.run_create_task_job(job.id))

        with _session(SessionLocal) as db:
            job_row = provision_job_service.get_job(db, job.id)
            assert str(job_row.status.value) == "FAILED"
            assert "Authentication failed" in str(job_row.error_message or "")
            assert db.query(SddTask).filter(SddTask.id == task_id).first() is None
            assert not os.path.exists(project_path)
    finally:
        engine.dispose()


def test_cancel_before_prepare_deletes_task(tmp_path, monkeypatch):
    """排队阶段取消：任务记录删除、不创建目录、job 标记 CANCELLED。"""
    engine, SessionLocal = _build_db()
    try:
        monkeypatch.setattr(provision_job_service, "SessionLocal", SessionLocal)
        with _session(SessionLocal) as db:
            user, workspace, _ = _seed_workspace(
                db,
                workspace_id="ws-cancel-queued",
                task_id="task-cancel-queued",
                project_path=str(tmp_path / "plain"),
            )
            task = create_task_record_for_provision(db, user, workspace.id, name="cancel-queued-task")
            job = _seed_provision_job(db, user=user, workspace=workspace, task=task)
            # 任务尚未开始准备即请求取消
            job_row = db.query(SddProvisionJob).filter(SddProvisionJob.id == job.id).first()
            job_row.cancel_requested = True
            db.commit()
            task_id, project_path = task.id, task.project_path

        def _fail_if_called(**kwargs):
            raise AssertionError("prepare must not run after cancellation")

        monkeypatch.setattr(git_worktree_service, "create_task_worktree", _fail_if_called)

        asyncio.run(provision_job_service.run_create_task_job(job.id))

        with _session(SessionLocal) as db:
            job_row = provision_job_service.get_job(db, job.id)
            assert str(job_row.status.value) == "FAILED"
            assert str(job_row.stage) == "CANCELLED"
            assert db.query(SddTask).filter(SddTask.id == task_id).first() is None
            assert not os.path.exists(project_path)
    finally:
        engine.dispose()


def test_cancel_after_worktree_creation_cleans_worktree_and_task(tmp_path, monkeypatch):
    """worktree 创建后取消：回滚移除 worktree 目录并删除任务记录。"""
    engine, SessionLocal = _build_db()
    try:
        monkeypatch.setattr(provision_job_service, "SessionLocal", SessionLocal)
        with _session(SessionLocal) as db:
            user, workspace, _ = _seed_workspace(
                db,
                workspace_id="ws-cancel-wt",
                task_id="task-cancel-wt",
                project_path=str(tmp_path / "repo"),
                git_repo_url="https://git.example.com/repo.git",
            )
            task = create_task_record_for_provision(db, user, workspace.id, name="cancel-wt-task")
            job = _seed_provision_job(db, user=user, workspace=workspace, task=task)
            task_id = task.id

        monkeypatch.setattr(
            git_worktree_service,
            "create_task_worktree",
            _fake_worktree_creator(job_id=job.id, session_factory=SessionLocal),
        )
        removed_paths = []

        def _fake_remove(*, repo_path, task_id, task_project_path, expected_git_repo_url=None, missing_ok=True, **kwargs):
            removed_paths.append(str(task_project_path))
            shutil.rmtree(task_project_path, ignore_errors=True)

        monkeypatch.setattr(git_worktree_service, "remove_task_worktree", _fake_remove)

        task_project_path = None
        with _session(SessionLocal) as db:
            task_row = db.query(SddTask).filter(SddTask.id == task_id).first()
            task_project_path = task_row.project_path

        asyncio.run(provision_job_service.run_create_task_job(job.id))

        with _session(SessionLocal) as db:
            job_row = provision_job_service.get_job(db, job.id)
            assert str(job_row.stage) == "CANCELLED"
            assert db.query(SddTask).filter(SddTask.id == task_id).first() is None
            assert task_project_path in removed_paths
            assert not os.path.exists(task_project_path)
    finally:
        engine.dispose()


def test_success_path_still_moves_task_to_pending(tmp_path, monkeypatch):
    """成功路径回归：worktree 创建 → 任务 PENDING、job SUCCESS。"""
    engine, SessionLocal = _build_db()
    try:
        monkeypatch.setattr(provision_job_service, "SessionLocal", SessionLocal)
        with _session(SessionLocal) as db:
            user, workspace, _ = _seed_workspace(
                db,
                workspace_id="ws-ok",
                task_id="task-ok",
                project_path=str(tmp_path / "repo"),
                git_repo_url="https://git.example.com/repo.git",
            )
            task = create_task_record_for_provision(db, user, workspace.id, name="ok-task")
            job = _seed_provision_job(db, user=user, workspace=workspace, task=task)
            task_id = task.id

        monkeypatch.setattr(git_worktree_service, "create_task_worktree", _fake_worktree_creator())

        asyncio.run(provision_job_service.run_create_task_job(job.id))

        with _session(SessionLocal) as db:
            task_row = db.query(SddTask).filter(SddTask.id == task_id).first()
            assert task_row is not None
            assert task_row.status == TaskStatus.PENDING.value
            assert os.path.exists(task_row.project_path)
            job_row = provision_job_service.get_job(db, job.id)
            assert str(job_row.status.value) == "SUCCESS"
            assert str(job_row.stage) == "COMPLETED"
    finally:
        engine.dispose()


def test_non_git_failure_removes_directory_and_task(tmp_path, monkeypatch):
    """非 git 工作区准备失败：任务目录删除、任务记录删除。"""
    engine, SessionLocal = _build_db()
    try:
        monkeypatch.setattr(provision_job_service, "SessionLocal", SessionLocal)
        with _session(SessionLocal) as db:
            user, workspace, _ = _seed_workspace(
                db,
                workspace_id="ws-plain-fail",
                task_id="task-plain-fail",
                project_path=str(tmp_path / "plain"),
            )
            task = create_task_record_for_provision(db, user, workspace.id, name="plain-fail-task")
            job = _seed_provision_job(db, user=user, workspace=workspace, task=task)
            task_id = task.id
            # 预创建任务目录，使 prepare 抛出 "already exists"
            os.makedirs(task.project_path, exist_ok=True)

        asyncio.run(provision_job_service.run_create_task_job(job.id))

        with _session(SessionLocal) as db:
            assert db.query(SddTask).filter(SddTask.id == task_id).first() is None
            job_row = provision_job_service.get_job(db, job.id)
            assert str(job_row.status.value) == "FAILED"
    finally:
        engine.dispose()


def test_list_tasks_hides_provisioning(tmp_path):
    """任务列表不展示准备中的任务。"""
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, _ = _seed_workspace(
                db,
                workspace_id="ws-list",
                task_id="task-list-prov",
                project_path=str(tmp_path),
            )
            ready = SddTask(
                id="task-list-ready",
                workspace_id=workspace.id,
                creator_id=user.id,
                name="Ready task",
                project_path=str(tmp_path),
                status=TaskStatus.PENDING,
            )
            db.add(ready)
            db.commit()

            items, total = list_tasks(db, workspace.id)
            ids = {task.id for task in items}
            assert "task-list-prov" not in ids
            assert "task-list-ready" in ids
            assert total == 1
    finally:
        engine.dispose()


def _build_task_app(SessionLocal, user):
    def _override_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(task_router.router, prefix="/api")
    app.include_router(provision_router.router, prefix="/api")
    app.dependency_overrides[task_router.get_db] = _override_db
    app.dependency_overrides[task_router.get_current_user] = lambda: user
    app.dependency_overrides[provision_router.get_db] = _override_db
    app.dependency_overrides[provision_router.get_current_user] = lambda: user
    return app


def test_initialize_rejects_prepare_failed_task(tmp_path):
    """准备失败（PREPARE_FAILED）的任务不允许初始化进入对话。"""
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(
                db,
                workspace_id="ws-init-guard",
                task_id="task-init-guard",
                project_path=str(tmp_path),
            )
            task.status = TaskStatus.FAILED
            task.current_phase = "PREPARE_FAILED"
            task.error_message = "git auth failed"
            db.commit()
            ws_id, task_id = workspace.id, task.id
        client = TestClient(_build_task_app(SessionLocal, user))

        resp = client.post(f"/api/workspaces/{ws_id}/tasks/{task_id}/initialize", json={})
        assert resp.status_code == 409, resp.text
    finally:
        engine.dispose()


def test_provision_cancel_api_is_creator_only(tmp_path):
    """取消接口仅创建人可调用；active 列表仅返回创建人自己的 job。"""
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user1, workspace, task = _seed_workspace(
                db,
                workspace_id="ws-cancel-api",
                task_id="task-cancel-api",
                user_id="creator-1",
                project_path=str(tmp_path),
            )
            job = _seed_provision_job(db, user=user1, workspace=workspace, task=task)
            other = User(id="other-1", email="other@example.com", hashed_password="x", display_name="Other")
            db.add(other)
            db.commit()
            ws_id = workspace.id

        creator_client = TestClient(_build_task_app(SessionLocal, user1))
        other_client = TestClient(_build_task_app(SessionLocal, other))

        # active 列表：仅创建人可见
        resp = creator_client.get("/api/provision-jobs/active")
        assert resp.status_code == 200, resp.text
        assert [item["job_id"] for item in resp.json()] == [job.id]

        resp = other_client.get("/api/provision-jobs/active")
        assert resp.status_code == 200
        assert resp.json() == []

        # 非创建人取消 → 403
        resp = other_client.post(f"/api/provision-jobs/{job.id}/cancel")
        assert resp.status_code == 403, resp.text

        # 创建人取消 → 200 且标记生效
        resp = creator_client.post(f"/api/provision-jobs/{job.id}/cancel")
        assert resp.status_code == 200, resp.text
        assert resp.json()["cancel_requested"] is True

        with _session(SessionLocal) as db:
            job_row = provision_job_service.get_job(db, job.id)
            assert job_row.cancel_requested is True
            assert str(job_row.stage) == "CANCELLING"
    finally:
        engine.dispose()
