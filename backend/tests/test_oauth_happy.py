"""
T03 OAuth 正向流程用例（happy path）。

覆盖任务书列出的正向能力：
- ``GET  /api/auth/oauth/providers``            返回已启用 provider（未配置的不出现）
- ``GET  /api/auth/oauth/{provider}/authorize`` 返回授权 URL + state
- ``GET  /api/auth/oauth/{provider}/callback``  302 只带 ticket，不带 JWT
- ``GET  /api/auth/oauth/identities``           列出已绑定身份 + 可用 provider
- ``DELETE /api/auth/oauth/identities/{id}``    解绑后可重新绑定
- ``GET  /api/auth/me``                         返回 ``bound_providers``

注意端点前缀为 ``/api/auth/oauth/...``（router prefix ``/auth/oauth`` + main.py 的 ``/api``）。
"""

import urllib.parse

from fastapi.testclient import TestClient

from app.config import settings
from app.domains.auth.models.oauth import OAuthIdentity
from app.domains.auth.services import auth_service

from tests.conftest import (
    auth_headers,
    github_profile,
    make_identity,
    make_user,
    run_login_flow,
)


# ══════════════════ 1. providers 列表 ══════════════════

def test_providers_returns_enabled_github(client: TestClient, github_mock):
    """已配置 client_id/secret 的 provider 出现在列表中，并带前端所需的展示字段。"""
    resp = client.get("/api/auth/oauth/providers")
    assert resp.status_code == 200, resp.text
    providers = resp.json()["providers"]
    names = [p["name"] for p in providers]
    assert "github" in names

    github = next(p for p in providers if p["name"] == "github")
    assert github["display_name"]
    assert github["authorize_path"] == "/api/auth/oauth/github/authorize"
    assert github["icon_key"] == "github"


def test_providers_hides_unconfigured_provider(client: TestClient, monkeypatch):
    """未配置 client_id/secret 的 provider 不得出现（NFR-M2：登录页隐藏三方入口）。"""
    monkeypatch.setattr(settings, "OAUTH_GITHUB_CLIENT_ID", "")
    monkeypatch.setattr(settings, "OAUTH_GITHUB_CLIENT_SECRET", "")
    resp = client.get("/api/auth/oauth/providers")
    assert resp.status_code == 200, resp.text
    assert [p["name"] for p in resp.json()["providers"]] == []


# ══════════════════ 2. authorize / callback ══════════════════

def test_authorize_returns_url_with_state(client: TestClient, github_mock):
    """authorize 返回三方授权 URL，且 URL 中的 state 与响应体一致。"""
    resp = client.get("/api/auth/oauth/github/authorize", params={"intent": "login"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"]
    assert body["expires_in"] == int(settings.OAUTH_STATE_TTL_SECONDS)

    query = dict(
        urllib.parse.parse_qsl(urllib.parse.urlparse(body["authorize_url"]).query)
    )
    assert query["state"] == body["state"]
    assert query["client_id"] == "test-client-id"
    assert query["redirect_uri"] == "http://frontend.test/oauth/callback/github"


def test_callback_redirect_carries_ticket_but_never_a_jwt(
    db, github_mock, client: TestClient
):
    """回调 302 的 Location 中只有 ticket / status / client_type，绝不含 JWT。"""
    user = make_user(db, email="bound@example.com", password="Bound-Pass-1")
    make_identity(db, user, provider="github", provider_uid="9001")
    github_mock.user_response = (200, github_profile(uid=9001))

    authz = client.get(
        "/api/auth/oauth/github/authorize", params={"intent": "login"}
    ).json()
    resp = client.get(
        "/api/auth/oauth/github/callback",
        params={"code": "good-code", "state": authz["state"]},
    )
    assert resp.status_code == 302
    location = resp.headers["location"]
    params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(location).query))

    assert params["status"] == "LOGIN_OK"
    assert params["ticket"]
    assert params["client_type"] == "web"
    assert set(params) == {"ticket", "status", "client_type"}
    # 🔴 URL 中严禁出现 token
    assert "access_token" not in location
    assert "refresh_token" not in location


# ══════════════════ 3. identities 列表 ══════════════════

def test_identities_lists_bound_providers(db, github_mock, client: TestClient):
    """已登录用户可以看到自己已绑定的身份，以及当前可用的 provider。"""
    user = make_user(db, email="me@example.com", password="Me-Pass-1")
    identity = make_identity(db, user, provider="github", provider_uid="9001")

    resp = client.get("/api/auth/oauth/identities", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [i["id"] for i in body["identities"]] == [identity.id]
    assert [i["provider"] for i in body["identities"]] == ["github"]
    assert body["available_providers"] == ["github"]


def test_identities_only_shows_own_bindings(db, github_mock, client: TestClient):
    """身份列表严格按当前用户过滤，不泄漏他人绑定。"""
    me = make_user(db, email="me@example.com", password="Me-Pass-1")
    other = make_user(db, email="other@example.com", password="Other-Pass-1")
    make_identity(db, me, provider="github", provider_uid="1111")
    make_identity(db, other, provider="github", provider_uid="2222")

    resp = client.get("/api/auth/oauth/identities", headers=auth_headers(me))
    assert resp.status_code == 200, resp.text
    identities = resp.json()["identities"]
    assert len(identities) == 1
    assert identities[0]["id"] == db.query(OAuthIdentity).filter(
        OAuthIdentity.user_id == me.id
    ).one().id


def test_identities_requires_authentication(client: TestClient):
    """未带 token 访问身份列表 → 401。"""
    assert client.get("/api/auth/oauth/identities").status_code == 401


# ══════════════════ 4. unbind → 可重新绑定 ══════════════════

def test_unbind_removes_identity_and_rebind_works(db, github_mock, client: TestClient):
    """解绑删除绑定关系，且之后可以用同一三方身份重新绑定回来。"""
    user = make_user(db, email="rebind@example.com", password="Rebind-Pass-1")
    identity = make_identity(db, user, provider="github", provider_uid="9100")
    identity_id = identity.id

    # 解绑
    resp = client.delete(
        f"/api/auth/oauth/identities/{identity_id}", headers=auth_headers(user)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "UNBOUND"
    assert db.query(OAuthIdentity).count() == 0

    # 列表随之变空
    listed = client.get("/api/auth/oauth/identities", headers=auth_headers(user))
    assert listed.json()["identities"] == []

    # 解绑后密码登录仍然可用（密码是恒存在的兜底凭据）
    assert auth_service.authenticate_user(db, "rebind@example.com", "Rebind-Pass-1")

    # 重新绑定：走 intent=bind 回调再调 /bind
    params = run_login_flow(
        db,
        github_mock,
        profile=github_profile(uid=9100, email="octo@example.com"),
        intent="bind",
        user=user,
    )
    assert params["status"] == "LOGIN_OK"
    rebind = client.post("/api/auth/oauth/bind", json={"ticket": params["ticket"]})
    assert rebind.status_code == 200, rebind.text
    assert rebind.json()["status"] == "BOUND"

    rows = db.query(OAuthIdentity).all()
    assert len(rows) == 1
    assert rows[0].user_id == user.id
    assert rows[0].provider_uid == "9100"
    assert rows[0].id != identity_id, "重新绑定应是一条新记录"


def test_unbind_unknown_identity_returns_404(db, github_mock, client: TestClient):
    """解绑不存在的身份 → 404（不泄漏资源存在性）。"""
    user = make_user(db, email="me@example.com", password="Me-Pass-1")
    resp = client.delete(
        "/api/auth/oauth/identities/does-not-exist", headers=auth_headers(user)
    )
    assert resp.status_code == 404


# ══════════════════ 5. /me 的 bound_providers ══════════════════

def test_me_returns_bound_providers(db, github_mock, full_client: TestClient):
    """``/api/auth/me`` 返回已绑定的 provider 名列表（前端设置页据此渲染）。"""
    user = make_user(db, email="me@example.com", password="Me-Pass-1")

    # 未绑定时为空列表
    resp = full_client.get("/api/auth/me", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    assert resp.json()["bound_providers"] == []

    # 绑定后出现 provider 名，且去重
    make_identity(db, user, provider="github", provider_uid="9001")
    make_identity(db, user, provider="github", provider_uid="9002")
    resp = full_client.get("/api/auth/me", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["bound_providers"] == ["github"], "同 provider 的多身份应去重"
    assert body["email"] == "me@example.com"


def test_me_bound_providers_updates_after_unbind(db, github_mock, full_client: TestClient):
    """解绑后 ``/me`` 的 bound_providers 同步变空。"""
    user = make_user(db, email="me@example.com", password="Me-Pass-1")
    identity = make_identity(db, user, provider="github", provider_uid="9001")

    assert full_client.get("/api/auth/me", headers=auth_headers(user)).json()[
        "bound_providers"
    ] == ["github"]

    unbind = full_client.delete(
        f"/api/auth/oauth/identities/{identity.id}", headers=auth_headers(user)
    )
    assert unbind.status_code == 200, unbind.text

    assert full_client.get("/api/auth/me", headers=auth_headers(user)).json()[
        "bound_providers"
    ] == []


# ══════════════════ 6. 端到端：路径 C 注册后即可用 JWT 访问受保护端点 ══════════════════

def test_end_to_end_register_then_use_token_on_me(db, github_mock, full_client: TestClient):
    """路径 C 建号签发的 token 能直接访问 ``/api/auth/me``，且立即体现绑定关系。"""
    params = run_login_flow(
        db, github_mock, profile=github_profile(uid=7300, email="e2e@example.com")
    )
    assert params["status"] == "REGISTER_REQUIRED"

    registered = full_client.post(
        "/api/auth/oauth/register",
        json={
            "ticket": params["ticket"],
            "email": "e2e@example.com",
            "password": "E2E-Pass-1",
            "display_name": "E2E User",
        },
    )
    assert registered.status_code == 200, registered.text
    token = registered.json()["access_token"]

    me = full_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["email"] == "e2e@example.com"
    assert body["display_name"] == "E2E User"
    assert body["bound_providers"] == ["github"]
