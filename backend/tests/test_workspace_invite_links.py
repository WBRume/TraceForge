"""
工作区链接邀请（workspace invite links）测试：

- 服务层：创建/序列化/撤销/状态推导；接受邀请（新成员/已是成员/失效链接）；
- API 层：管理员创建/列出/撤销链接；公共预览；已登录用户接受邀请；
  无 manage_members 权限的用户被拒绝。
"""

import os
import sys
from datetime import timedelta

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.dependencies import get_current_user, get_db  # noqa: E402
from app.domains.auth.models.user import (  # noqa: E402
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)
from app.domains.workspace.routers import invite_join as invite_join_router  # noqa: E402
from app.domains.workspace.routers import workspace as workspace_router  # noqa: E402
from app.domains.workspace.services import workspace_service  # noqa: E402


def _seed_workspace(db, ws_id: str, name: str, owner: User) -> Workspace:
    workspace = Workspace(id=ws_id, name=name, owner_id=owner.id)
    member = WorkspaceMember(
        workspace_id=ws_id,
        user_id=owner.id,
        role=WorkspaceRole.OWNER,
        permissions_json="[]",
    )
    db.add_all([workspace, member])
    db.commit()
    return workspace


def _seed_user(db, user_id: str, email: str, name: str) -> User:
    user = User(id=user_id, email=email, hashed_password="x", display_name=name)
    db.add(user)
    db.commit()
    return user


# ────────────────────────── 服务层 ──────────────────────────

def test_create_invite_link_defaults_and_expiry(db):
    owner = _seed_user(db, "user-1", "owner@example.com", "Owner")
    _seed_workspace(db, "ws-1", "WS", owner)

    link = workspace_service.create_invite_link(
        db, "ws-1", creator_user_id=owner.id, role="DEVELOPER", valid_days=7, max_uses=5
    )

    assert link.token and len(link.token) == 48
    assert link.role == WorkspaceRole.DEVELOPER
    assert link.is_expert is False
    assert link.max_uses == 5
    assert link.used_count == 0
    assert link.expires_at is not None
    assert workspace_service.invite_link_status(link) == "ACTIVE"

    payload = workspace_service.serialize_invite_link(link)
    assert payload["remaining_uses"] == 5
    assert payload["status"] == "ACTIVE"
    # DEVELOPER 默认权限集
    assert payload["permissions"]["create_task"] is True
    assert payload["permissions"]["manage_members"] is False


def test_create_invite_link_rejects_owner_role(db):
    owner = _seed_user(db, "user-1", "owner@example.com", "Owner")
    _seed_workspace(db, "ws-1", "WS", owner)

    try:
        workspace_service.create_invite_link(db, "ws-1", creator_user_id=owner.id, role="OWNER")
    except ValueError as exc:
        assert "owner" in str(exc).lower()
    else:
        raise AssertionError("owner role should be rejected")


def test_accept_invite_link_creates_member_with_preset(db):
    owner = _seed_user(db, "user-1", "owner@example.com", "Owner")
    _seed_workspace(db, "ws-1", "WS", owner)
    invitee = _seed_user(db, "user-2", "invitee@example.com", "Invitee")

    link = workspace_service.create_invite_link(
        db,
        "ws-1",
        creator_user_id=owner.id,
        role="VIEWER",
        is_expert=True,
        permissions_flags={"view_dashboard": True, "view_assets": True, "view_api_mock": True, "export_task": True},
        max_uses=2,
    )

    member, refreshed_link, already_member = workspace_service.accept_invite_link(db, link.token, invitee)

    assert already_member is False
    assert member.workspace_id == "ws-1"
    assert member.role == WorkspaceRole.VIEWER
    assert member.is_expert is True
    permissions = workspace_service.permissions_to_flags(
        workspace_service._permission_set_from_json(member.permissions_json, member.role)
    )
    assert permissions["export_task"] is True
    assert permissions["manage_members"] is False
    assert refreshed_link.used_count == 1

    # 二次接受（同一用户）→ 幂等，不消耗次数
    member_again, link_again, already = workspace_service.accept_invite_link(db, link.token, invitee)
    assert already is True
    assert member_again.id == member.id
    assert link_again.used_count == 1


def test_accept_invite_link_rejects_invalid_states(db):
    owner = _seed_user(db, "user-1", "owner@example.com", "Owner")
    _seed_workspace(db, "ws-1", "WS", owner)
    invitee = _seed_user(db, "user-2", "invitee@example.com", "Invitee")

    # 未知名 token
    try:
        workspace_service.accept_invite_link(db, "no-such-token", invitee)
    except ValueError as exc:
        assert "not found" in str(exc).lower()
    else:
        raise AssertionError("unknown token should fail")

    # 已撤销
    link = workspace_service.create_invite_link(db, "ws-1", creator_user_id=owner.id, role="DEVELOPER")
    workspace_service.revoke_invite_link(db, "ws-1", link.id)
    try:
        workspace_service.accept_invite_link(db, link.token, invitee)
    except ValueError as exc:
        assert "revoked" in str(exc).lower()
    else:
        raise AssertionError("revoked link should fail")

    # 已过期
    expired = workspace_service.create_invite_link(
        db, "ws-1", creator_user_id=owner.id, role="DEVELOPER", valid_days=1
    )
    expired = workspace_service.get_invite_link(db, "ws-1", expired.id)
    expired.expires_at = expired.created_at - timedelta(days=1)
    db.commit()
    try:
        workspace_service.accept_invite_link(db, expired.token, invitee)
    except ValueError as exc:
        assert "expired" in str(exc).lower()
    else:
        raise AssertionError("expired link should fail")

    # 次数耗尽
    limited = workspace_service.create_invite_link(
        db, "ws-1", creator_user_id=owner.id, role="DEVELOPER", max_uses=1
    )
    workspace_service.accept_invite_link(db, limited.token, invitee)
    another = _seed_user(db, "user-3", "another@example.com", "Another")
    try:
        workspace_service.accept_invite_link(db, limited.token, another)
    except ValueError as exc:
        assert "exhausted" in str(exc).lower()
    else:
        raise AssertionError("exhausted link should fail")


# ────────────────────────── API 层 ──────────────────────────

def _build_client(db, current_user: User):
    app = FastAPI()
    app.include_router(workspace_router.router, prefix="/api")
    app.include_router(invite_join_router.router, prefix="/api")

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current_user
    return TestClient(app)


def test_invite_link_api_full_flow(db):
    owner = _seed_user(db, "user-1", "owner@example.com", "Owner")
    _seed_workspace(db, "ws-1", "WS One", owner)
    invitee = _seed_user(db, "user-2", "invitee@example.com", "Invitee")

    client = _build_client(db, owner)
    resp = client.post(
        "/api/workspaces/ws-1/invite-links",
        json={"role": "DEVELOPER", "valid_days": 30, "max_uses": 10, "is_expert": False},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "ACTIVE"
    assert body["remaining_uses"] == 10

    token = body["token"]

    # 公开预览（无需登录态断言：预览路由不依赖 current_user）
    preview = client.get(f"/api/invites/{token}")
    assert preview.status_code == 200
    assert preview.json()["workspace_name"] == "WS One"
    assert preview.json()["role"] == "DEVELOPER"

    # 接受邀请
    accept_client = _build_client(db, invitee)
    accepted = accept_client.post(f"/api/invites/{token}/accept")
    assert accepted.status_code == 200
    assert accepted.json()["already_member"] is False
    assert accepted.json()["role"] == "DEVELOPER"

    # 列表显示已使用次数
    listed = client.get("/api/workspaces/ws-1/invite-links")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["used_count"] == 1

    # 撤销后再接受 → 400
    revoked = client.delete(f"/api/workspaces/ws-1/invite-links/{body['id']}")
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "REVOKED"

    accepted_again = accept_client.post(f"/api/invites/{token}/accept")
    assert accepted_again.status_code == 200  # 已是成员幂等放行
    assert accepted_again.json()["already_member"] is True


def test_invite_link_api_requires_manage_members(db):
    owner = _seed_user(db, "user-1", "owner@example.com", "Owner")
    _seed_workspace(db, "ws-1", "WS One", owner)
    plain = _seed_user(db, "user-2", "dev@example.com", "Dev")
    db.add(
        WorkspaceMember(
            workspace_id="ws-1",
            user_id=plain.id,
            role=WorkspaceRole.DEVELOPER,
            permissions_json="[]",
        )
    )
    db.commit()

    client = _build_client(db, plain)
    resp = client.post(
        "/api/workspaces/ws-1/invite-links",
        json={"role": "DEVELOPER"},
    )
    assert resp.status_code == 403

    listed = client.get("/api/workspaces/ws-1/invite-links")
    assert listed.status_code == 403


def test_invite_preview_unknown_token_404(db):
    client = _build_client(db, None)
    resp = client.get("/api/invites/unknown-token")
    assert resp.status_code == 404
