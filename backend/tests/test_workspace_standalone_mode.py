"""
独立工作区模式 + 系统配置项测试（配置默认关闭项目管理/产品管理选择）：
- system_configs 默认值与读写；
- 配置关闭时：新建工作区不走项目/产品选择，直接填写项目/产品名称并手动选择仓库分支；
- 会话创建时按仓库选填分支覆盖。
"""

import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.dependencies import get_current_user, get_db, require_admin  # noqa: E402
from app.domains.auth.models.user import User, Workspace, WorkspaceMember, WorkspaceRole  # noqa: E402
from app.domains.management.models.management import SddManagementRepository  # noqa: E402
from app.domains.system_config.models.system_config import SystemConfig  # noqa: E402
from app.domains.system_config.services import system_config_service  # noqa: E402
from app.domains.task.services import git_worktree_service, task_service  # noqa: E402
from app.domains.workspace.routers import workspace as workspace_router  # noqa: E402
from app.domains.workspace.services import workspace_service  # noqa: E402


def _seed_user(db) -> User:
    user = User(id="user-1", email="user@example.com", hashed_password="x", display_name="User")
    db.add(user)
    db.commit()
    return user


def _seed_repos(db, count: int = 2):
    rows = []
    for index in range(count):
        row = SddManagementRepository(
            id=f"repo-{index + 1}",
            name=f"repo-{index + 1}",
            git_url=f"https://example.com/repo-{index + 1}.git",
            repo_type="OOTB" if index == 0 else "CUSTOM",
            default_branch="main",
        )
        db.add(row)
        rows.append(row)
    db.commit()
    return rows


def _disable_mgmt_selection(db) -> None:
    db.add(
        SystemConfig(
            key=system_config_service.CONFIG_PROJECT_PRODUCT_MANAGEMENT_ENABLED,
            value="false",
        )
    )
    db.commit()


# ──────────────────────── system config service ────────────────────────


def test_system_config_defaults_to_disabled(db):
    assert system_config_service.get_config_bool(
        db, system_config_service.CONFIG_PROJECT_PRODUCT_MANAGEMENT_ENABLED
    ) is False
    public = system_config_service.list_public_configs(db)
    assert public[system_config_service.CONFIG_PROJECT_PRODUCT_MANAGEMENT_ENABLED] is False


def test_system_config_set_and_read_roundtrip(db):
    system_config_service.set_config_value(
        db, system_config_service.CONFIG_PROJECT_PRODUCT_MANAGEMENT_ENABLED, "false", "admin-1"
    )
    assert (
        system_config_service.get_config_bool(
            db, system_config_service.CONFIG_PROJECT_PRODUCT_MANAGEMENT_ENABLED
        )
        is False
    )
    with pytest.raises(system_config_service.SystemConfigError):
        system_config_service.set_config_value(db, "unknown_key", "true")


# ──────────────────────── standalone workspace service ────────────────────────


def test_create_workspace_standalone_builds_custom_names_and_repos(db):
    user = _seed_user(db)
    _seed_repos(db)

    workspace = workspace_service.create_workspace(
        db,
        user,
        "Standalone WS",
        project_path="C:/ws/standalone",
        repositories=[
            {"repository_id": "repo-1", "branch_name": "release/8.0"},
            {"repository_id": "repo-2", "branch_name": ""},
        ],
        project_name="客户A Billing",
        product_name="Billing V8",
    )

    assert workspace.project_id is None
    assert workspace.custom_project_name == "客户A Billing"
    assert workspace.custom_product_name == "Billing V8"
    repos = {row.repo_slug: row for row in workspace.repositories}
    assert repos["repo-1"].branch_name == "release/8.0"
    # 未填分支时回退仓库默认分支
    assert repos["repo-2"].branch_name == "main"
    assert all(row.ref_type == "BRANCH" for row in workspace.repositories)


def test_create_workspace_standalone_requires_names_and_path(db):
    user = _seed_user(db)
    _seed_repos(db)

    with pytest.raises(git_worktree_service.GitWorktreeError):
        workspace_service.create_workspace(
            db,
            user,
            "No names",
            project_path="C:/ws/x",
            repositories=[{"repository_id": "repo-1", "branch_name": "main"}],
        )
    with pytest.raises(git_worktree_service.GitWorktreeError):
        workspace_service.create_workspace(
            db,
            user,
            "No path",
            repositories=[{"repository_id": "repo-1", "branch_name": "main"}],
            project_name="P",
            product_name="PR",
        )


def test_create_workspace_standalone_unknown_repo_raises(db):
    user = _seed_user(db)
    _seed_repos(db, count=1)

    with pytest.raises(ValueError):
        workspace_service.create_workspace(
            db,
            user,
            "Bad repo",
            project_path="C:/ws/y",
            repositories=[{"repository_id": "repo-missing", "branch_name": "main"}],
            project_name="P",
            product_name="PR",
        )


# ──────────────────────── provision job materialization ────────────────────────


def test_run_create_workspace_job_standalone_materializes_repos(monkeypatch):
    """独立模式（无 project_id、仅 repositories）也必须执行仓库物化（clone）阶段，
    否则初始化完成后仓库停留在 PENDING，本地目录不会下载任何代码。"""
    import asyncio
    import contextlib

    from app.domains.workflow.services import provision_job_service

    context = {
        "name": "Standalone WS",
        "project_path": "C:/ws/standalone-job",
        "project_name": "P",
        "product_name": "PR",
        "repositories": [
            {"repository_id": "repo-1", "branch_name": "main"},
            {"repository_id": "repo-2", "branch_name": "develop"},
        ],
    }
    calls: dict = {}

    monkeypatch.setattr(
        provision_job_service,
        "_get_job_payload",
        lambda job_id: {"creator_id": "user-1", "context_json": context},
    )
    monkeypatch.setattr(provision_job_service, "mark_running", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        provision_job_service,
        "mark_progress",
        lambda *args, **kwargs: calls.setdefault("stages", []).append(kwargs.get("stage")),
    )
    monkeypatch.setattr(
        provision_job_service,
        "mark_success",
        lambda *args, **kwargs: calls.__setitem__("result_json", kwargs.get("result_json")),
    )
    monkeypatch.setattr(
        provision_job_service,
        "mark_failed",
        lambda *args, **kwargs: calls.__setitem__("failed", True),
    )
    monkeypatch.setattr(provision_job_service, "audit_log", lambda *args, **kwargs: None)

    def _fake_create_sync(*, job_id, creator_id, context):
        calls["created_repositories"] = list(context.get("repositories") or [])
        return {"workspace_id": "ws-9", "repositories": []}

    def _fake_materialize(*, workspace_id):
        calls["materialized_workspace_id"] = workspace_id
        return {"repositories": []}

    monkeypatch.setattr(provision_job_service, "_create_workspace_sync", _fake_create_sync)
    monkeypatch.setattr(provision_job_service, "_materialize_workspace_repos_sync", _fake_materialize)

    @contextlib.asynccontextmanager
    async def _passthrough(*args, **kwargs):
        yield

    monkeypatch.setattr(provision_job_service, "queue_provision_jobs", _passthrough)
    monkeypatch.setattr(provision_job_service, "lock_workspace_repo_creation", _passthrough)

    asyncio.run(provision_job_service.run_create_workspace_job("job-standalone-1"))

    assert calls["created_repositories"] == context["repositories"]
    assert calls["materialized_workspace_id"] == "ws-9"
    assert "MATERIALIZE_REPOS" in calls["stages"]
    assert "failed" not in calls


def test_standalone_multi_repo_job_clones_repos_end_to_end(db, tmp_path, monkeypatch):
    """端到端：独立模式（配置关闭）多仓创建，初始化阶段必须把每个仓库
    clone 到 project_path 下的子目录，并将仓库状态置为 READY。"""
    import asyncio
    import contextlib
    import subprocess
    from pathlib import Path

    from sqlalchemy.orm import sessionmaker

    from app.domains.workflow.models.provision_job import ProvisionJobStatus
    from app.domains.workflow.services import provision_job_service
    from app.domains.workspace.models.workspace_repository import WorkspaceRepositoryState

    def _init_source_repo(path: Path, filename: str) -> str:
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=str(path), check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "t@example.com"], check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "tester"], check=True)
        (path / filename).write_text("hello", encoding="utf-8")
        subprocess.run(["git", "-C", str(path), "add", "."], check=True)
        subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True)
        subprocess.run(["git", "-C", str(path), "branch", "-M", "main"], check=True)
        return str(path)

    source_a = _init_source_repo(tmp_path / "src-repo-a", "a.txt")
    source_b = _init_source_repo(tmp_path / "src-repo-b", "b.txt")

    user = _seed_user(db)
    db.add_all(
        [
            SddManagementRepository(
                id="repo-a", name="repo-a", git_url=source_a, repo_type="OOTB", default_branch="main"
            ),
            SddManagementRepository(
                id="repo-b", name="repo-b", git_url=source_b, repo_type="CUSTOM", default_branch="main"
            ),
        ]
    )
    db.commit()

    # job 执行器使用独立 Session：绑定到测试内存库
    monkeypatch.setattr(
        provision_job_service,
        "SessionLocal",
        sessionmaker(autocommit=False, autoflush=False, bind=db.get_bind()),
    )

    @contextlib.asynccontextmanager
    async def _passthrough(*args, **kwargs):
        yield

    # 队列/分布式锁依赖 Redis，测试环境直接透传
    monkeypatch.setattr(provision_job_service, "queue_provision_jobs", _passthrough)
    monkeypatch.setattr(provision_job_service, "lock_workspace_repo_creation", _passthrough)

    ws_root = tmp_path / "ws-root"
    job = provision_job_service.create_job(
        db,
        job_type=provision_job_service.ProvisionJobType.CREATE_WORKSPACE,
        creator_id=user.id,
        context_json={
            "name": "Standalone WS",
            "project_path": str(ws_root),
            "project_name": "客户A",
            "product_name": "Billing V8",
            "repositories": [
                {"repository_id": "repo-a", "branch_name": "main"},
                {"repository_id": "repo-b", "branch_name": "main"},
            ],
        },
    )

    asyncio.run(provision_job_service.run_create_workspace_job(job.id))

    # job 执行器在独立 Session 中更新了状态，丢弃 fixture 会话的旧快照
    db.rollback()
    db.expire_all()

    finished = provision_job_service.get_job(db, job.id)
    assert finished.status == ProvisionJobStatus.SUCCESS, finished.error_message

    workspace = db.query(Workspace).filter(Workspace.id == finished.workspace_id).first()
    assert workspace is not None
    assert workspace.custom_project_name == "客户A"
    repos = {row.repo_slug: row for row in workspace.repositories}
    assert set(repos) == {"repo-a", "repo-b"}
    expected_files = {"repo-a": "a.txt", "repo-b": "b.txt"}
    for slug, row in repos.items():
        state = getattr(row.state, "value", row.state)
        assert state == "READY", row.error_message
        assert Path(row.base_dir).is_dir()
        assert (Path(row.base_dir) / ".git").exists()
        assert (Path(row.base_dir) / expected_files[slug]).exists()
        assert row.base_commit_sha


# ──────────────────────── task branch overrides ────────────────────────


def _seed_workspace_with_repos(db):
    user = _seed_user(db)
    workspace = Workspace(
        id="ws-1",
        name="WS",
        owner_id=user.id,
        project_path="C:/ws/repo",
        custom_project_name="P",
        custom_product_name="PR",
    )
    member = WorkspaceMember(
        id="member-1",
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.OWNER,
        permissions_json="[]",
        is_expert=True,
    )
    from app.domains.workspace.models.workspace_repository import (
        SddWorkspaceRepository,
        WorkspaceRepositoryState,
    )

    ws_repos = [
        SddWorkspaceRepository(
            workspace_id="ws-1",
            repository_id="repo-1",
            repo_url="https://example.com/repo-1.git",
            repo_name="repo-1",
            repo_slug="repo-1",
            branch_name="main",
            ref_type="BRANCH",
            base_dir="C:/ws/repo/repo-1",
            state=WorkspaceRepositoryState.READY,
        ),
        SddWorkspaceRepository(
            workspace_id="ws-1",
            repository_id="repo-2",
            repo_url="https://example.com/repo-2.git",
            repo_name="repo-2",
            repo_slug="repo-2",
            branch_name="develop",
            ref_type="BRANCH",
            base_dir="C:/ws/repo/repo-2",
            state=WorkspaceRepositoryState.READY,
        ),
    ]
    db.add_all([user, workspace, member] + ws_repos)
    db.commit()
    return user, workspace


def test_create_task_applies_repository_branch_overrides(db):
    user, workspace = _seed_workspace_with_repos(db)

    task = task_service.create_task_record_for_provision(
        db,
        user,
        workspace.id,
        name="Session with branch",
        repository_branches=[{"repository_id": "repo-1", "branch_name": "hotfix/urgent"}],
    )

    bindings = {row.repository_id: row for row in task.repo_bindings}
    assert bindings["repo-1"].branch_name == "hotfix/urgent"
    # 未覆盖的仓库沿用工作区分支
    assert bindings["repo-2"].branch_name == "develop"


def test_create_task_rejects_branch_override_for_foreign_repo(db):
    user, workspace = _seed_workspace_with_repos(db)

    with pytest.raises(ValueError):
        task_service.create_task_record_for_provision(
            db,
            user,
            workspace.id,
            name="Bad branch repo",
            repository_branches=[{"repository_id": "repo-foreign", "branch_name": "main"}],
        )


# ──────────────────────── task repository subset selection ────────────────────────


def test_create_task_with_selected_repository_subset(db):
    user, workspace = _seed_workspace_with_repos(db)

    task = task_service.create_task_record_for_provision(
        db,
        user,
        workspace.id,
        name="Subset task",
        repository_ids=["repo-2"],
    )

    # 仅为所选仓库创建 worktree 绑定，分支沿用工作区绑定
    assert [row.repository_id for row in task.repo_bindings] == ["repo-2"]
    assert task.repo_bindings[0].branch_name == "develop"


def test_create_task_subset_with_branch_override(db):
    user, workspace = _seed_workspace_with_repos(db)

    task = task_service.create_task_record_for_provision(
        db,
        user,
        workspace.id,
        name="Subset with branch",
        repository_branches=[{"repository_id": "repo-2", "branch_name": "hotfix/x"}],
        repository_ids=["repo-1", "repo-2"],
    )

    bindings = {row.repository_id: row for row in task.repo_bindings}
    assert set(bindings) == {"repo-1", "repo-2"}
    assert bindings["repo-1"].branch_name == "main"
    assert bindings["repo-2"].branch_name == "hotfix/x"


def test_create_task_rejects_unknown_repository_selection(db):
    user, workspace = _seed_workspace_with_repos(db)

    with pytest.raises(ValueError):
        task_service.create_task_record_for_provision(
            db,
            user,
            workspace.id,
            name="Unknown subset",
            repository_ids=["repo-foreign"],
        )


def test_create_task_rejects_empty_repository_selection(db):
    user, workspace = _seed_workspace_with_repos(db)

    with pytest.raises(ValueError):
        task_service.create_task_record_for_provision(
            db,
            user,
            workspace.id,
            name="Empty subset",
            repository_ids=[],
        )


# ──────────────────────── API level ────────────────────────


def _build_test_app(db):
    app = FastAPI()
    app.include_router(workspace_router.router, prefix="/api")

    def _override_db():
        yield db

    def _override_user():
        return SimpleNamespace(id="user-1", display_name="tester")

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return app


def _fake_job():
    from datetime import datetime

    from app.domains.workflow.models.provision_job import ProvisionJobType

    now = datetime.utcnow()
    return SimpleNamespace(
        id="job-1",
        job_type=ProvisionJobType.CREATE_WORKSPACE,
        status="PENDING",
        progress=0,
        stage="QUEUED",
        message="queued",
        error_message=None,
        result_json={},
        context_json={},
        workspace_id=None,
        task_id=None,
        creator_id="user-1",
        created_at=now,
        updated_at=now,
        started_at=None,
        finished_at=None,
    )


def test_create_workspace_api_rejects_project_selection_when_disabled(db, monkeypatch):
    _disable_mgmt_selection(db)
    app = _build_test_app(db)
    monkeypatch.setattr(
        workspace_router.provision_job_service, "create_job", lambda *a, **k: _fake_job()
    )

    client = TestClient(app)
    resp = client.post(
        "/api/workspaces",
        json={
            "name": "WS",
            "project_path": "C:/ws/api",
            "project_id": "proj-1",
            "project_name": "P",
            "product_name": "PR",
            "repositories": [{"repository_id": "repo-1", "branch_name": "main"}],
        },
    )
    assert resp.status_code == 400, resp.text
    assert "disabled" in resp.json()["detail"]


def test_create_workspace_api_standalone_requires_names_and_repos_when_disabled(db, monkeypatch):
    _disable_mgmt_selection(db)
    app = _build_test_app(db)
    monkeypatch.setattr(
        workspace_router.provision_job_service, "create_job", lambda *a, **k: _fake_job()
    )

    client = TestClient(app)
    resp = client.post(
        "/api/workspaces",
        json={"name": "WS", "project_path": "C:/ws/api"},
    )
    assert resp.status_code == 400, resp.text
    assert "project_name" in resp.json()["detail"]

    resp = client.post(
        "/api/workspaces",
        json={"name": "WS", "project_path": "C:/ws/api", "project_name": "P", "product_name": "PR"},
    )
    assert resp.status_code == 400, resp.text


def test_create_workspace_api_standalone_accepted_and_context_payload(db, monkeypatch):
    _disable_mgmt_selection(db)
    app = _build_test_app(db)
    captured = {}

    def _create_job(*args, **kwargs):
        captured.update(kwargs)
        return _fake_job()

    async def _noop(_job_id):
        return None

    monkeypatch.setattr(workspace_router.provision_job_service, "create_job", _create_job)
    monkeypatch.setattr(workspace_router.provision_job_service, "run_create_workspace_job", _noop)

    client = TestClient(app)
    resp = client.post(
        "/api/workspaces",
        json={
            "name": "Standalone WS",
            "project_path": "C:/ws/api2",
            "project_name": "客户A",
            "product_name": "Billing V8",
            "repositories": [
                {"repository_id": "repo-1", "branch_name": "release/8.0"},
                {"repository_id": "repo-2", "branch_name": "main"},
            ],
        },
    )
    assert resp.status_code == 202, resp.text
    context = captured["context_json"]
    assert context["project_name"] == "客户A"
    assert context["product_name"] == "Billing V8"
    assert context["repositories"][0] == {"repository_id": "repo-1", "branch_name": "release/8.0"}
    assert not context["project_id"]


def test_create_workspace_api_legacy_flow_when_enabled(db, monkeypatch):
    # 配置项默认关闭；显式开启后恢复原有（项目/产品选择）流程
    db.add(
        SystemConfig(
            key=system_config_service.CONFIG_PROJECT_PRODUCT_MANAGEMENT_ENABLED,
            value="true",
        )
    )
    db.commit()
    app = _build_test_app(db)

    async def _noop(_job_id):
        return None

    monkeypatch.setattr(
        workspace_router.provision_job_service, "create_job", lambda *a, **k: _fake_job()
    )
    monkeypatch.setattr(workspace_router.provision_job_service, "run_create_workspace_job", _noop)

    client = TestClient(app)
    resp = client.post(
        "/api/workspaces",
        json={
            "name": "Legacy WS",
            "project_path": "C:/ws/legacy",
            "git_repo_url": "https://github.com/example/repo",
        },
    )
    assert resp.status_code == 202, resp.text


def test_system_configs_api_get_and_update(db, monkeypatch):
    from app.domains.system_config.routers import system_config as system_config_router

    app = FastAPI()
    app.include_router(system_config_router.router, prefix="/api")

    def _override_db():
        yield db

    def _override_user():
        return SimpleNamespace(id="user-1", display_name="tester", is_admin=False)

    def _override_admin():
        return SimpleNamespace(id="admin-1", display_name="admin", is_admin=True)

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[require_admin] = _override_admin
    # get_db 需要按名称覆盖：system_config 路由内引用的是 get_db 符号
    app.dependency_overrides[get_db] = _override_db

    client = TestClient(app)
    resp = client.get("/api/system-configs")
    assert resp.status_code == 200, resp.text
    assert resp.json()[system_config_service.CONFIG_PROJECT_PRODUCT_MANAGEMENT_ENABLED] is False

    resp = client.put(
        f"/api/system-configs/{system_config_service.CONFIG_PROJECT_PRODUCT_MANAGEMENT_ENABLED}",
        json={"value": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()[system_config_service.CONFIG_PROJECT_PRODUCT_MANAGEMENT_ENABLED] is True
