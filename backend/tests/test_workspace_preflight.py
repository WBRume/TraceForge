"""
工作区创建冲突预检（POST /workspaces/preflight）测试：
- 服务层：同名工作区检测；目标目录与已有工作区目录重叠（相同/互为父子）检测；
- API 层：预检接口返回冲突明细，且不阻断创建（仅供参考）。
"""

import os
import sys
from types import SimpleNamespace

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_current_user, get_db  # noqa: E402
from app.domains.auth.models.user import User, Workspace, WorkspaceMember, WorkspaceRole  # noqa: E402
from app.domains.workspace.routers import workspace as workspace_router  # noqa: E402
from app.domains.workspace.services import workspace_service  # noqa: E402


def _seed_workspace(db, ws_id: str, name: str, project_path: str | None, owner: User) -> Workspace:
    workspace = Workspace(
        id=ws_id,
        name=name,
        owner_id=owner.id,
        project_path=project_path,
    )
    member = WorkspaceMember(
        workspace_id=ws_id,
        user_id=owner.id,
        role=WorkspaceRole.OWNER,
        permissions_json="[]",
        is_expert=True,
    )
    db.add_all([workspace, member])
    db.commit()
    return workspace


def test_preflight_detects_name_conflict(db):
    owner = User(id="user-1", email="u@example.com", hashed_password="x", display_name="User")
    db.add(owner)
    _seed_workspace(db, "ws-1", "Script Workspace", None, owner)

    result = workspace_service.preflight_workspace_conflicts(db, name="Script Workspace")

    assert result["name_conflict"] is True
    assert result["name_conflict_workspaces"][0]["name"] == "Script Workspace"
    assert result["name_conflict_workspaces"][0]["owner_name"] == "User"
    assert result["path_conflict"] is False


def test_preflight_detects_path_overlap_both_directions(db, tmp_path):
    owner = User(id="user-1", email="u@example.com", hashed_password="x", display_name="User")
    db.add(owner)
    existing = str(tmp_path / "workspace" / "ws-a")
    _seed_workspace(db, "ws-1", "WS A", existing, owner)

    # 相同路径
    same = workspace_service.preflight_workspace_conflicts(
        db, name="New WS", project_path=existing
    )
    assert same["path_conflict"] is True
    assert same["path_conflict_workspaces"][0]["name"] == "WS A"

    # 新路径位于已有工作区目录之下
    nested = os.path.join(existing, "sub")
    nested_result = workspace_service.preflight_workspace_conflicts(
        db, name="New WS", project_path=nested
    )
    assert nested_result["path_conflict"] is True

    # 新路径包含已有工作区目录
    parent = str(tmp_path / "workspace")
    parent_result = workspace_service.preflight_workspace_conflicts(
        db, name="New WS", project_path=parent
    )
    assert parent_result["path_conflict"] is True

    # 无重叠不报冲突
    unrelated = str(tmp_path / "elsewhere")
    unrelated_result = workspace_service.preflight_workspace_conflicts(
        db, name="New WS", project_path=unrelated
    )
    assert unrelated_result["path_conflict"] is False


def test_preflight_no_conflicts_when_empty(db):
    result = workspace_service.preflight_workspace_conflicts(
        db, name="Brand New WS", project_path=None
    )
    assert result["name_conflict"] is False
    assert result["path_conflict"] is False
    assert result["name_conflict_workspaces"] == []
    assert result["path_conflict_workspaces"] == []


def test_preflight_checks_all_users_workspaces_not_only_current(db, tmp_path):
    """预检必须覆盖全部用户的已有工作区（全局校验），而非仅当前用户的。

    用户 A 创建了同名工作区与同目录工作区；随后（以用户 B 的视角调用预检）
    必须依然命中 A 的工作区冲突，避免用户 B 与用户 A 创建出同名/同目录工作区。
    """
    user_a = User(id="user-a", email="a@example.com", hashed_password="x", display_name="User A")
    user_b = User(id="user-b", email="b@example.com", hashed_password="x", display_name="User B")
    db.add_all([user_a, user_b])
    db.commit()

    ws_path = str(tmp_path / "workspace" / "shared-ws")
    _seed_workspace(db, "ws-a1", "Shared Name", ws_path, user_a)

    # 预检本身不感知任何“当前用户”：传入的 name/path 与 user_b 无任何关联，
    # 命中的是 user_a 的工作区
    result = workspace_service.preflight_workspace_conflicts(
        db, name="Shared Name", project_path=ws_path
    )
    assert result["name_conflict"] is True
    assert [row["name"] for row in result["name_conflict_workspaces"]] == ["Shared Name"]
    assert result["name_conflict_workspaces"][0]["owner_name"] == "User A"
    assert result["path_conflict"] is True
    assert result["path_conflict_workspaces"][0]["owner_name"] == "User A"

    # user_b 视角调用（换一个无权限的 db 会话对象不影响结果，此处仅传参语义）
    result_b_view = workspace_service.preflight_workspace_conflicts(
        db, name="Shared Name", project_path=str(tmp_path / "workspace")
    )
    assert result_b_view["name_conflict"] is True
    assert result_b_view["path_conflict"] is True


def test_preflight_name_conflict_is_case_insensitive(db):
    """同名判断大小写不敏感：'script ws' 与 'Script WS' 视为同名冲突。"""
    owner = User(id="user-1", email="u@example.com", hashed_password="x", display_name="User")
    db.add(owner)
    _seed_workspace(db, "ws-1", "Script WS", None, owner)

    result = workspace_service.preflight_workspace_conflicts(db, name="script ws")
    assert result["name_conflict"] is True
    assert result["name_conflict_workspaces"][0]["name"] == "Script WS"


def test_preflight_api_returns_conflicts(db, tmp_path):
    owner = User(id="user-1", email="u@example.com", hashed_password="x", display_name="User")
    db.add(owner)
    _seed_workspace(db, "ws-1", "WS A", str(tmp_path / "workspace" / "ws-a"), owner)

    app = FastAPI()
    app.include_router(workspace_router.router, prefix="/api")

    def _override_db():
        yield db

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="user-1", display_name="tester"
    )
    app.dependency_overrides[get_db] = _override_db

    client = TestClient(app)
    resp = client.post(
        "/api/workspaces/preflight",
        json={"name": "WS A", "project_path": str(tmp_path / "workspace")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["name_conflict"] is True
    assert data["name_conflict_workspaces"][0]["name"] == "WS A"
    assert data["path_conflict"] is True
    assert data["path_conflict_workspaces"][0]["project_path"].endswith("ws-a")
