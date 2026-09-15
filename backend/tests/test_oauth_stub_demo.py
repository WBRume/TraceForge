"""
Stub 本地 Demo（OAUTH_STUB_ENABLED=true）端到端验证（B-DEMO）。

验证目标：在「零 GitHub 申请、零外部回调」前提下，走【真实后端 OAuth 链路】：
    providers → authorize（建一次性 state）→ 模拟授权页 302 → callback（state 校验 /
    换 token / 建 ticket）→ resolve 三路判定 → register（签发自家 JWT）→ /auth/me
    真实验证 → 二次登录直接 LOGIN_OK。

另含生产安全用例：默认（未开启）时 stub 不出现在 /providers，authorize 与
模拟授权页均 404 —— stub 不校验真实身份，生产必须保持关闭。
"""

import pytest

from app.config import settings
from app.domains.auth.errors import ERR_OAUTH_PROVIDER_DISABLED
from app.domains.auth.providers import get_provider, list_enabled_providers

from tests.conftest import parse_redirect

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "Demo-Pass-1"
DEMO_DISPLAY_NAME = "Stub Demo"


@pytest.fixture()
def stub_enabled(monkeypatch):
    """Demo 用：打开 OAUTH_STUB_ENABLED（用例结束自动还原）。"""
    monkeypatch.setattr(settings, "OAUTH_STUB_ENABLED", True)


def _authorize_to_ticket(client) -> str:
    """完整走一遍「授权 → 模拟授权页 → 真实回调」，返回前端拿到的 ticket。"""
    resp = client.get(
        "/api/auth/oauth/stub/authorize",
        params={"intent": "login", "client_type": "web"},
    )
    assert resp.status_code == 200, resp.text
    authorize_url = resp.json()["authorize_url"]
    assert "stub/authorize-redirect" in authorize_url

    # 模拟三方授权页：302 回本项目的回调路由（携带 code + state）
    resp = client.get(authorize_url)
    assert resp.status_code == 302, resp.text
    callback_url = resp.headers["location"]
    assert callback_url.startswith(settings.OAUTH_STUB_REDIRECT_URI_WEB)
    cb_params = parse_redirect(callback_url)
    assert cb_params["code"] == "stub-code"
    assert cb_params["state"]

    # 真实 callback 路由：state 校验 → 换 token → ticket
    resp = client.get(callback_url)
    assert resp.status_code == 302, resp.text
    landed = parse_redirect(resp.headers["location"])
    assert "ticket" in landed
    return landed["ticket"]


def test_stub_registered_and_visible_only_when_enabled(stub_enabled):
    provider = get_provider("stub")
    assert provider.name == "stub"
    assert provider.display_name == "Stub (Demo)"
    names = [p.name for p in list_enabled_providers()]
    assert "stub" in names


def test_stub_full_chain_register_then_login(full_client, db, stub_enabled):
    """首次登录（未注册 → 路径 C 补全注册 → JWT），二次登录（路径 A 直接 LOGIN_OK）。"""
    # ── ① 首次：demo@stub.local 不存在 → REGISTER_REQUIRED ──
    ticket = _authorize_to_ticket(full_client)
    resp = full_client.post("/api/auth/oauth/resolve", json={"ticket": ticket})
    assert resp.status_code == 200, resp.text
    resolved = resp.json()
    assert resolved["status"] == "REGISTER_REQUIRED"
    assert resolved["provider"] == "stub"
    assert resolved["suggested_email"] == DEMO_EMAIL

    # ── ② 补全注册：建号 + 绑定 + 签发自家 JWT ──
    resp = full_client.post(
        "/api/auth/oauth/register",
        json={
            "ticket": ticket,
            "email": DEMO_EMAIL,
            "password": DEMO_PASSWORD,
            "display_name": DEMO_DISPLAY_NAME,
        },
    )
    assert resp.status_code == 200, resp.text
    registered = resp.json()
    assert registered["status"] == "REGISTERED"
    assert registered["access_token"]

    # ── ③ /auth/me：用自家 JWT 真实验证登录态 + 绑定身份 ──
    resp = full_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {registered['access_token']}"},
    )
    assert resp.status_code == 200, resp.text
    me = resp.json()
    assert me["email"] == DEMO_EMAIL
    assert "stub" in me["bound_providers"]

    # ── ④ 二次登录：直接 LOGIN_OK（路径 A）──
    ticket = _authorize_to_ticket(full_client)
    resp = full_client.post("/api/auth/oauth/resolve", json={"ticket": ticket})
    assert resp.status_code == 200, resp.text
    resolved = resp.json()
    assert resolved["status"] == "LOGIN_OK"
    assert resolved["access_token"]

    resp = full_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {resolved['access_token']}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == DEMO_EMAIL


def test_stub_hidden_and_rejected_when_disabled(full_client, monkeypatch):
    """生产安全：默认（或显式 false）时 stub 不可见、不可用（404）。"""
    monkeypatch.setattr(settings, "OAUTH_STUB_ENABLED", False)

    names = [p.name for p in list_enabled_providers()]
    assert "stub" not in names

    resp = full_client.get(
        "/api/auth/oauth/stub/authorize",
        params={"intent": "login", "client_type": "web"},
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == ERR_OAUTH_PROVIDER_DISABLED

    resp = full_client.get(
        "/api/auth/oauth/stub/authorize-redirect",
        params={"state": "stub-state", "redirect_uri": settings.OAUTH_STUB_REDIRECT_URI_WEB},
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == ERR_OAUTH_PROVIDER_DISABLED