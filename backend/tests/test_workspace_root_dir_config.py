"""
工作区根目录配置项（workspace_root_dir）测试：
- 配置读写：字符串解析、允许留空（清空）、非法值（相对路径/文件系统根）拒绝；
- 配置为空时：create_workspace 保持原有逻辑，路径由调用方传入；
- 配置非空时：project_path 默认回退为 根目录/workspace/工作区名称，
  传入路径仅允许位于 根目录/workspace 之内，否则拒绝；
- API 层：字符串型配置可由管理员更新。
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
from app.domains.auth.models.user import User  # noqa: E402
from app.domains.system_config.routers import system_config as system_config_router  # noqa: E402
from app.domains.system_config.services import system_config_service  # noqa: E402
from app.domains.task.services import git_worktree_service  # noqa: E402
from app.domains.workspace.routers import workspace as workspace_router  # noqa: E402
from app.domains.workspace.services import workspace_service  # noqa: E402


def _seed_user(db) -> User:
    user = User(id="user-1", email="user@example.com", hashed_password="x", display_name="User")
    db.add(user)
    db.commit()
    return user


def _set_root_dir(db, value: str) -> None:
    system_config_service.set_config_value(db, system_config_service.CONFIG_WORKSPACE_ROOT_DIR, value)


# ──────────────────────── system config service ────────────────────────


def test_workspace_root_dir_defaults_to_empty(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "WORKSPACE_ROOT_DIR", "")
    assert system_config_service.get_config_str(
        db, system_config_service.CONFIG_WORKSPACE_ROOT_DIR
    ) == ""
    public = system_config_service.list_public_configs(db)
    assert public[system_config_service.CONFIG_WORKSPACE_ROOT_DIR] == ""


def test_workspace_root_dir_env_default_fallback(db, tmp_path, monkeypatch):
    """优先级：系统配置表（界面保存）> env 默认值 > 空。

    - 未在界面配置时，GET 返回 env（WORKSPACE_ROOT_DIR）默认值；
    - 界面保存非空值后覆盖 env；
    - 界面清空保存后回退 env 默认值。
    """
    from app.config import settings

    env_value = str(tmp_path / "env-default-root")
    monkeypatch.setattr(settings, "WORKSPACE_ROOT_DIR", env_value)

    # 未配置：回退 env 默认值
    assert (
        system_config_service.get_config_str(db, system_config_service.CONFIG_WORKSPACE_ROOT_DIR)
        == env_value
    )
    public = system_config_service.list_public_configs(db)
    assert public[system_config_service.CONFIG_WORKSPACE_ROOT_DIR] == env_value

    # 界面保存非空值：覆盖 env
    ui_override = str(tmp_path / "ui-override")
    _set_root_dir(db, ui_override)
    assert (
        system_config_service.get_config_str(db, system_config_service.CONFIG_WORKSPACE_ROOT_DIR)
        == ui_override
    )

    # 界面清空：回退 env 默认值
    _set_root_dir(db, "")
    assert (
        system_config_service.get_config_str(db, system_config_service.CONFIG_WORKSPACE_ROOT_DIR)
        == env_value
    )


def test_workspace_root_dir_roundtrip_and_clear(db, tmp_path):
    override = str(tmp_path / "sdd-root")
    _set_root_dir(db, override)
    assert (
        system_config_service.get_config_str(db, system_config_service.CONFIG_WORKSPACE_ROOT_DIR)
        == override
    )
    # 留空表示清空配置（回退 env 默认值），允许写入
    _set_root_dir(db, "")
    assert (
        system_config_service.get_config_str(db, system_config_service.CONFIG_WORKSPACE_ROOT_DIR)
        == ""
    )


@pytest.mark.parametrize("value", ["relative/path", "D:\\", "/", "C:\\"])
def test_workspace_root_dir_rejects_invalid_values(db, value):
    with pytest.raises(system_config_service.SystemConfigError):
        _set_root_dir(db, value)


# ──────────────────────── workspace create policy ────────────────────────


def test_create_workspace_default_path_when_root_dir_set(db, tmp_path, monkeypatch):
    """配置根目录后，未传 project_path 时默认使用 根目录/workspace/工作区名称。"""
    user = _seed_user(db)
    init_paths = []
    monkeypatch.setattr(
        git_worktree_service,
        "init_git_repository",
        lambda path: init_paths.append(path),
    )
    _set_root_dir(db, str(tmp_path / "root"))

    workspace = workspace_service.create_workspace(db, user, "客户A Billing")

    expected_base = os.path.join(str(tmp_path / "root"), "workspace")
    expected_path = os.path.join(expected_base, "客户A Billing")
    assert workspace.project_path == expected_path
    assert init_paths == [expected_path]


def test_create_workspace_outside_base_rejected_when_root_dir_set(db, tmp_path, monkeypatch):
    user = _seed_user(db)
    monkeypatch.setattr(git_worktree_service, "init_git_repository", lambda path: None)
    _set_root_dir(db, str(tmp_path / "root"))

    with pytest.raises(git_worktree_service.GitWorktreeError):
        workspace_service.create_workspace(
            db, user, "WS", project_path=str(tmp_path / "outside" / "ws")
        )
    # 位于 base 内（含嵌套子目录）允许
    inside = os.path.join(str(tmp_path / "root"), "workspace", "team-a", "ws")
    workspace = workspace_service.create_workspace(db, user, "WS", project_path=inside)
    assert workspace.project_path == inside


def test_create_workspace_no_restriction_when_root_dir_empty(db, tmp_path, monkeypatch):
    """配置为空时保持原有逻辑：任意路径均可。"""
    user = _seed_user(db)
    monkeypatch.setattr(git_worktree_service, "init_git_repository", lambda path: None)

    outside = str(tmp_path / "free" / "ws")
    workspace = workspace_service.create_workspace(db, user, "WS", project_path=outside)
    assert workspace.project_path == outside


def test_create_workspace_case_insensitive_within_base(db, tmp_path, monkeypatch):
    """Windows 风格路径大小写不敏感：盘符/目录大小写不同仍在 base 内。"""
    if os.name != "nt":
        pytest.skip("case-insensitive comparison is Windows-specific")
    user = _seed_user(db)
    monkeypatch.setattr(git_worktree_service, "init_git_repository", lambda path: None)
    root = str(tmp_path / "root")
    _set_root_dir(db, root)

    base = os.path.join(root, "workspace")
    upper_case = os.path.join(base.upper(), "ws")
    workspace = workspace_service.create_workspace(db, user, "WS", project_path=upper_case)
    assert workspace.project_path == upper_case
    assert workspace_service._is_path_within(upper_case, base)


# ──────────────────────── API level ────────────────────────


def _build_config_app(db):
    app = FastAPI()
    app.include_router(system_config_router.router, prefix="/api")

    def _override_db():
        yield db

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1", display_name="tester"
    )
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(
        id="admin-1", display_name="admin", is_admin=True
    )
    app.dependency_overrides[get_db] = _override_db
    return app


def test_system_config_api_update_workspace_root_dir(db, monkeypatch, tmp_path):
    from app.config import settings

    monkeypatch.setattr(settings, "WORKSPACE_ROOT_DIR", "")
    app = _build_config_app(db)
    client = TestClient(app)

    override = str(tmp_path / "sdd")
    resp = client.put(
        f"/api/system-configs/{system_config_service.CONFIG_WORKSPACE_ROOT_DIR}",
        json={"value": override},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()[system_config_service.CONFIG_WORKSPACE_ROOT_DIR] == override

    # bool 型配置提交字符串 / 字符串型配置提交 bool 均被拒绝
    resp = client.put(
        f"/api/system-configs/{system_config_service.CONFIG_WORKSPACE_ROOT_DIR}",
        json={"value": True},
    )
    assert resp.status_code == 400, resp.text
    resp = client.put(
        f"/api/system-configs/{system_config_service.CONFIG_PROJECT_PRODUCT_MANAGEMENT_ENABLED}",
        json={"value": "true"},
    )
    assert resp.status_code == 400, resp.text

    # 相对路径被拒绝
    resp = client.put(
        f"/api/system-configs/{system_config_service.CONFIG_WORKSPACE_ROOT_DIR}",
        json={"value": "relative/path"},
    )
    assert resp.status_code == 400, resp.text


def _build_workspace_app(db):
    app = FastAPI()
    app.include_router(workspace_router.router, prefix="/api")

    def _override_db():
        yield db

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1", display_name="tester"
    )
    app.dependency_overrides[get_db] = _override_db
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


def test_create_workspace_api_rejects_path_outside_base(db, monkeypatch, tmp_path):
    from app.config import settings

    monkeypatch.setattr(settings, "WORKSPACE_ROOT_DIR", "")
    _seed_user(db)
    _set_root_dir(db, str(tmp_path / "sdd-root"))
    app = _build_workspace_app(db)
    monkeypatch.setattr(
        workspace_router.provision_job_service, "create_job", lambda *a, **k: _fake_job()
    )

    client = TestClient(app)
    resp = client.post(
        "/api/workspaces",
        json={
            "name": "WS",
            "project_path": str(tmp_path / "elsewhere" / "ws"),
            "project_name": "P",
            "product_name": "PR",
        },
    )
    assert resp.status_code == 400, resp.text
    assert "workspace base directory" in resp.json()["detail"]
