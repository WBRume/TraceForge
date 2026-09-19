"""
T03 三路判定正例 + 加绑/解绑 + ticket 生命周期用例（B-21）。

覆盖：
- 路径 A（身份已存在 → LOGIN_OK + token）、路径 B 正例、路径 C 正例
- 加绑：普通用户 / 管理员 CONFIRM_REQUIRED / ALREADY_BOUND 幂等 / BIND_CONFLICT
- 解绑：解绑后邮箱密码登录正常、E-6b 无密码防御、404 防存在性泄漏
- ticket 过期（E-17 → 410）/ 冷却（E-18 → 423，红线 7 已覆盖）/ resolve 幂等读
"""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domains.auth.errors import (
    ERR_OAUTH_PASSWORD_INVALID,
    ERR_OAUTH_PASSWORD_REQUIRED,
    OAuthAPIError,
    OAuthPasswordInvalidError,
    OAuthPasswordRequiredError,
    OAuthTicketExpiredError,
)
from app.domains.auth.models.oauth import OAuthIdentity, OAuthTicket
from app.domains.auth.models.user import User
from app.domains.auth.services import auth_service, oauth_service

from tests.conftest import (
    github_profile,
    make_identity,
    make_user,
    run_login_flow,
)


# ══════════════════ 路径 A：身份已存在 ══════════════════

def test_path_a_existing_identity_login_ok_issues_tokens(db, github_mock, client: TestClient):
    user = make_user(db, email="octo@example.com", password="Octo-Pass-1")
    make_identity(db, user, provider="github", provider_uid="9001")

    params = run_login_flow(db, github_mock, profile=github_profile(uid=9001))
    assert params["status"] == "LOGIN_OK"

    # resolve 用 ticket 兑换 token（登录路径唯一发 token 的入口）
    resp = client.post("/api/auth/oauth/resolve", json={"ticket": params["ticket"]})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "LOGIN_OK"
    assert payload["access_token"] and payload["refresh_token"]
    # token 属于绑定身份的用户
    claims = auth_service.decode_token(payload["access_token"], expected_type="access")
    assert claims["sub"] == user.id


def test_path_a_updates_last_login_and_snapshot(db, github_mock):
    user = make_user(db, email="octo@example.com", password="Octo-Pass-1")
    identity = make_identity(db, user, provider="github", provider_uid="9001")
    assert identity.last_login_at is None

    run_login_flow(
        db, github_mock, profile=github_profile(uid=9001, name="Octo Renamed")
    )
    db.refresh(identity)
    assert identity.last_login_at is not None
    # 资料快照随登录更新
    assert identity.provider_display_name == "Octo Renamed"


# ══════════════════ 路径 B 正例 ══════════════════

def test_path_b_correct_password_binds_and_logs_in(db, github_mock, client: TestClient):
    user = make_user(db, email="legacy@example.com", password="Legacy-Pass-1")
    params = run_login_flow(
        db, github_mock, profile=github_profile(uid=7001, email="legacy@example.com")
    )
    assert params["status"] == "BIND_REQUIRED"

    # resolve 只回脱敏邮箱
    resp = client.post("/api/auth/oauth/resolve", json={"ticket": params["ticket"]})
    payload = resp.json()
    assert payload["email_masked"] == "l***@example.com"

    # 正确密码 → 绑定 + 登录
    confirm = client.post(
        "/api/auth/oauth/bind/confirm",
        json={"ticket": params["ticket"], "password": "Legacy-Pass-1"},
    )
    assert confirm.status_code == 200
    body = confirm.json()
    assert body["status"] == "BOUND"
    claims = auth_service.decode_token(body["access_token"], expected_type="access")
    assert claims["sub"] == user.id

    identities = (
        db.query(OAuthIdentity).filter(OAuthIdentity.user_id == user.id).all()
    )
    assert len(identities) == 1
    assert identities[0].provider_uid == "7001"


def test_path_b_email_login_still_works_after_bind(db, github_mock):
    """绑定不改变本地凭证：邮箱+密码登录照常可用。"""
    user = make_user(db, email="legacy@example.com", password="Legacy-Pass-1")
    params = run_login_flow(
        db, github_mock, profile=github_profile(uid=7002, email="legacy@example.com")
    )
    tokens = oauth_service.confirm_bind(db, params["ticket"], "Legacy-Pass-1")
    assert tokens.access_token

    logged = auth_service.authenticate_user(db, "legacy@example.com", "Legacy-Pass-1")
    assert logged is not None and logged.id == user.id


# ══════════════════ 路径 C 正例 ══════════════════

def test_path_c_complete_register_creates_user_and_identity(db, github_mock):
    make_user(db, email="existing@example.com", password="Whatever-1")  # 保证非首号用户
    # 三方未返回 email → 路径 C
    params = run_login_flow(db, github_mock, profile=github_profile(uid=7100, email=None))
    assert params["status"] == "REGISTER_REQUIRED"

    tokens = oauth_service.complete_register(
        db, params["ticket"], "newbie@example.com", "Newbie-Pass-1", "Newbie"
    )
    assert tokens.access_token

    user = (
        db.query(User)
        .filter(User.email == "newbie@example.com")
        .one()
    )
    assert user.display_name == "Newbie"
    assert not user.is_admin
    # 建号与绑定同一事务：绑定已存在
    assert (
        db.query(OAuthIdentity)
        .filter(
            OAuthIdentity.user_id == user.id,
            OAuthIdentity.provider_uid == "7100",
        )
        .count()
        == 1
    )
    # 🔴 手填优先：三方 email 仅快照
    identity = db.query(OAuthIdentity).filter(OAuthIdentity.user_id == user.id).one()
    assert identity.provider_email is None


def test_path_c_with_provider_email_prefills_suggestion(db, github_mock, client: TestClient):
    """三方有 email 但未注册 → REGISTER_REQUIRED，resolve 预填 suggested_*。"""
    make_user(db, email="seed@example.com", password="Seed-Pass-1")
    params = run_login_flow(
        db, github_mock, profile=github_profile(uid=7200, email="fresh@example.com")
    )
    assert params["status"] == "REGISTER_REQUIRED"

    resp = client.post("/api/auth/oauth/resolve", json={"ticket": params["ticket"]})
    payload = resp.json()
    assert payload["suggested_email"] == "fresh@example.com"
    assert payload["suggested_display_name"] == "Octo Cat"


# ══════════════════ 加绑 ══════════════════

def test_bind_intent_normal_user_no_password_needed(db, github_mock):
    user = make_user(db, email="me@example.com", password="Me-Pass-1")
    params = run_login_flow(
        db, github_mock, profile=github_profile(uid=7300, email="me@example.com"),
        intent="bind", user=user,
    )
    assert params["status"] == "LOGIN_OK"  # 以 LOGIN_OK 标记可绑定

    result = oauth_service.bind_identity(db, params["ticket"], None)
    assert result.identity.user_id == user.id


def test_bind_intent_admin_requires_password_confirmation(db, github_mock):
    """管理员加绑：CONFIRM_REQUIRED → 无密码 400 / 错密码 401 / 正密码成功。

    T02 实现语义：``bind_identity`` 先原子消费 ticket 再做密码校验，
    校验失败**不释放** ticket（fail-closed，需重新发起授权）——
    与路径 B（confirm_bind 释放重试）不同，此处按分支独立建 ticket 验证。
    """
    admin = make_user(db, email="admin@example.com", password="Admin-Pass-1", is_admin=True)
    profile = github_profile(uid=7400, email="admin@example.com")

    def _new_admin_ticket() -> str:
        params = run_login_flow(db, github_mock, profile=profile, intent="bind", user=admin)
        assert params["status"] == "CONFIRM_REQUIRED"
        return params["ticket"]

    # resolve 返回 admin_bind 语义
    result = oauth_service.resolve_ticket(db, _new_admin_ticket())
    assert result.status == "CONFIRM_REQUIRED"
    assert result.reason == "admin_bind"

    # 分支 1：无密码 → 400 OAUTH_PASSWORD_REQUIRED
    with pytest.raises(OAuthPasswordRequiredError) as no_pwd:
        oauth_service.bind_identity(db, _new_admin_ticket(), None)
    assert no_pwd.value.code == ERR_OAUTH_PASSWORD_REQUIRED

    # 分支 2：错密码 → 401 OAUTH_PASSWORD_INVALID
    with pytest.raises(OAuthPasswordInvalidError) as bad_pwd:
        oauth_service.bind_identity(db, _new_admin_ticket(), "Wrong-Pass")
    assert bad_pwd.value.code == ERR_OAUTH_PASSWORD_INVALID

    # 分支 3：正密码 → 绑定成功（各失败分支均未产生绑定）
    assert db.query(OAuthIdentity).count() == 0
    bound = oauth_service.bind_identity(db, _new_admin_ticket(), "Admin-Pass-1")
    assert bound.identity.user_id == admin.id
    assert db.query(OAuthIdentity).count() == 1


def test_bind_intent_already_bound_idempotent(db, github_mock):
    user = make_user(db, email="me@example.com", password="Me-Pass-1")
    make_identity(db, user, provider="github", provider_uid="7500")

    params = run_login_flow(
        db, github_mock, profile=github_profile(uid=7500),
        intent="bind", user=user,
    )
    assert params["status"] == "ALREADY_BOUND"

    result = oauth_service.bind_identity(db, params["ticket"], None)
    assert result.identity.user_id == user.id
    # 不产生重复绑定
    assert (
        db.query(OAuthIdentity)
        .filter(OAuthIdentity.user_id == user.id, OAuthIdentity.provider_uid == "7500")
        .count()
        == 1
    )


def test_bind_intent_conflict_when_identity_bound_to_other(db, github_mock):
    """身份已绑他人 → BIND_CONFLICT（E-2），不可用于加绑。"""
    me = make_user(db, email="me@example.com", password="Me-Pass-1")
    other = make_user(db, email="other@example.com", password="Other-Pass-1")
    make_identity(db, other, provider="github", provider_uid="7600")

    params = run_login_flow(
        db, github_mock, profile=github_profile(uid=7600),
        intent="bind", user=me,
    )
    assert params["status"] == "BIND_CONFLICT"

    with pytest.raises(OAuthAPIError) as exc_info:
        oauth_service.bind_identity(db, params["ticket"], None)
    assert exc_info.value.status_code == 400


# ══════════════════ 解绑 ══════════════════

def test_unbind_then_password_login_still_works(db, github_mock, client: TestClient):
    user = make_user(db, email="me@example.com", password="Me-Pass-1")
    identity = make_identity(db, user, provider="github", provider_uid="7700")

    app_client = client
    # 注入当前用户后走 DELETE 端点
    from app.dependencies import get_current_user

    app_client.app.dependency_overrides[get_current_user] = lambda: user  # type: ignore[attr-defined]
    resp = app_client.delete(f"/api/auth/oauth/identities/{identity.id}")
    assert resp.status_code == 200
    assert resp.json() == {"status": "UNBOUND"}

    assert db.query(OAuthIdentity).filter(OAuthIdentity.id == identity.id).count() == 0
    # 解绑后邮箱密码登录正常
    logged = auth_service.authenticate_user(db, "me@example.com", "Me-Pass-1")
    assert logged is not None and logged.id == user.id


def test_unbind_other_users_identity_returns_404(db, client: TestClient):
    """解绑他人身份 → 404（不返回 403，避免泄漏存在性）。"""
    me = make_user(db, email="me@example.com", password="Me-Pass-1")
    other = make_user(db, email="other@example.com", password="Other-Pass-1")
    identity = make_identity(db, other, provider="github", provider_uid="7800")

    from app.dependencies import get_current_user

    client.app.dependency_overrides[get_current_user] = lambda: me  # type: ignore[attr-defined]
    resp = client.delete(f"/api/auth/oauth/identities/{identity.id}")
    assert resp.status_code == 404
    # 对方绑定未被误删
    assert db.query(OAuthIdentity).filter(OAuthIdentity.id == identity.id).count() == 1


def test_unbind_blocked_when_account_has_no_password(db):
    """E-6b 防御：账号无密码（脏数据）→ 400 OAUTH_NO_PASSWORD。"""
    user = make_user(db, email="ghost@example.com", password="")
    identity = make_identity(db, user, provider="github", provider_uid="7900")

    with pytest.raises(OAuthAPIError) as exc_info:
        oauth_service.unbind_identity(db, user, identity.id)
    assert exc_info.value.status_code == 400
    # 绑定未被删除
    assert db.query(OAuthIdentity).filter(OAuthIdentity.id == identity.id).count() == 1


# ══════════════════ ticket 生命周期 ══════════════════

def test_expired_ticket_resolve_returns_410(db, github_mock):
    """E-17：过期 ticket → 410 OAUTH_TICKET_EXPIRED。"""
    user = make_user(db, email="octo@example.com", password="Octo-Pass-1")
    make_identity(db, user, provider="github", provider_uid="9001")
    params = run_login_flow(db, github_mock, profile=github_profile(uid=9001))

    row = db.query(OAuthTicket).filter(OAuthTicket.ticket == params["ticket"]).one()
    row.expires_at = oauth_service._utcnow()
    db.commit()

    with pytest.raises(OAuthTicketExpiredError) as exc_info:
        oauth_service.resolve_ticket(db, params["ticket"])
    assert exc_info.value.status_code == 410


def test_resolve_is_idempotent_and_does_not_consume(db, github_mock, client: TestClient):
    """resolve 幂等读：可重复调用、不消费；之后 confirm 仍可用。"""
    make_user(db, email="legacy@example.com", password="Legacy-Pass-1")
    params = run_login_flow(
        db, github_mock, profile=github_profile(uid=8001, email="legacy@example.com")
    )
    ticket = params["ticket"]

    for _ in range(3):
        resp = client.post("/api/auth/oauth/resolve", json={"ticket": ticket})
        assert resp.status_code == 200
        assert resp.json()["status"] == "BIND_REQUIRED"

    row = db.query(OAuthTicket).filter(OAuthTicket.ticket == ticket).one()
    assert row.consumed_at is None

    # 多次 resolve 之后 confirm 仍正常
    confirm = client.post(
        "/api/auth/oauth/bind/confirm", json={"ticket": ticket, "password": "Legacy-Pass-1"}
    )
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "BOUND"


def test_unknown_ticket_returns_404(db, client: TestClient):
    resp = client.post("/api/auth/oauth/resolve", json={"ticket": "no-such-ticket"})
    assert resp.status_code == 404


# 显式拒绝未覆盖的 HTTPException 泄漏（unbind 404 走标准 HTTPException，非 OAuth 域）
def test_http_exception_is_not_oauth_error():
    assert issubclass(OAuthAPIError, HTTPException)
