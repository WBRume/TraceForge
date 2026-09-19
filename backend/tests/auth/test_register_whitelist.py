"""
T03 注册邮箱域名白名单用例（B-23，拍板 #4）。

- 白名单留空 = 不限制（NFR-C1：现网行为完全不变）
- 配置后：域名后缀匹配（corp.com 匹配 a@corp.com 与 a@sub.corp.com），
  非白名单域名 → 403 REGISTER_EMAIL_NOT_ALLOWED
- 路径 C 补全注册同样校验；白名单失败不消费 ticket（E-1b 可换邮箱重试）
"""

import pytest

from app.config import settings
from app.domains.auth.errors import (
    ERR_REGISTER_EMAIL_NOT_ALLOWED,
    RegisterEmailNotAllowedError,
)
from app.domains.auth.models.oauth import OAuthIdentity, OAuthTicket
from app.domains.auth.models.user import User
from app.domains.auth.services import auth_service, oauth_service

from tests.conftest import github_profile, make_user, run_login_flow


def _whitelist(monkeypatch, value: str) -> None:
    monkeypatch.setattr(settings, "REGISTER_EMAIL_DOMAIN_WHITELIST", value)


# ══════════════════ 白名单留空 = 不限制 ══════════════════

def test_empty_whitelist_means_no_restriction(monkeypatch):
    _whitelist(monkeypatch, "")
    # 任意域名均可通过
    auth_service.assert_email_allowed("anyone@any-domain.example")
    auth_service.assert_email_allowed("someone@gmail.com")
    auth_service.assert_email_allowed("user@corp.com")


def test_whitespace_only_whitelist_means_no_restriction(monkeypatch):
    _whitelist(monkeypatch, "  ,  ")
    auth_service.assert_email_allowed("anyone@gmail.com")


# ══════════════════ 配置后的匹配与拦截 ══════════════════

def test_configured_whitelist_allows_exact_and_subdomains(monkeypatch):
    _whitelist(monkeypatch, "corp.com")
    auth_service.assert_email_allowed("alice@corp.com")
    auth_service.assert_email_allowed("bob@sub.corp.com")  # 后缀匹配


def test_configured_whitelist_supports_multiple_entries(monkeypatch):
    _whitelist(monkeypatch, "corp.com, partner.io")
    auth_service.assert_email_allowed("a@corp.com")
    auth_service.assert_email_allowed("b@partner.io")


def test_configured_whitelist_rejects_other_domains(monkeypatch):
    _whitelist(monkeypatch, "corp.com")
    with pytest.raises(RegisterEmailNotAllowedError) as exc_info:
        auth_service.assert_email_allowed("intruder@gmail.com")
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == ERR_REGISTER_EMAIL_NOT_ALLOWED


def test_whitelist_matching_is_case_insensitive(monkeypatch):
    _whitelist(monkeypatch, "CORP.com")
    auth_service.assert_email_allowed("User@Corp.COM")


def test_lookalike_domain_is_rejected(monkeypatch):
    """``evilcorp.com`` 不得命中 ``corp.com``（后缀必须以 ``.`` 分界）。"""
    _whitelist(monkeypatch, "corp.com")
    with pytest.raises(RegisterEmailNotAllowedError):
        auth_service.assert_email_allowed("a@evilcorp.com")


# ══════════════════ 经典注册入口同样校验 ══════════════════

def test_classic_register_respects_whitelist(db, monkeypatch):
    _whitelist(monkeypatch, "corp.com")
    with pytest.raises(RegisterEmailNotAllowedError):
        auth_service.register_user(db, "x@gmail.com", "Passw0rd-1", "X")
    assert db.query(User).count() == 0

    user = auth_service.register_user(db, "x@corp.com", "Passw0rd-1", "X")
    assert user.email == "x@corp.com"
    # 首个用户 → bootstrap 管理员规则不受影响
    assert user.is_admin is True


# ══════════════════ 路径 C 补全注册同样校验（E-1b：失败不消费 ticket） ══════════════════

def test_path_c_register_blocked_by_whitelist_ticket_not_consumed(
    db, github_mock, monkeypatch
):
    """白名单拦截 → 403；ticket 不被消费，可换邮箱重试成功。"""
    _whitelist(monkeypatch, "corp.com")
    make_user(db, email="seed@example.com", password="Seed-Pass-1")

    params = run_login_flow(
        db, github_mock, profile=github_profile(uid=9100, email="thirdparty@gmail.com")
    )
    assert params["status"] == "REGISTER_REQUIRED"
    ticket = params["ticket"]

    # 手填非白名单邮箱 → 403
    with pytest.raises(RegisterEmailNotAllowedError):
        oauth_service.complete_register(
            db, ticket, "intruder@gmail.com", "Newbie-Pass-1", "Intruder"
        )

    # 🔴 ticket 未被消费：resolve 仍可读，且可换邮箱重试
    result = oauth_service.resolve_ticket(db, ticket)
    assert result.status == "REGISTER_REQUIRED"
    row = db.query(OAuthTicket).filter(OAuthTicket.ticket == ticket).one()
    assert row.consumed_at is None
    assert db.query(User).filter(User.email == "intruder@gmail.com").count() == 0
    assert db.query(OAuthIdentity).count() == 0

    # 换白名单邮箱重试 → 成功
    tokens = oauth_service.complete_register(
        db, ticket, "employee@corp.com", "Newbie-Pass-1", "Employee"
    )
    assert tokens.access_token
    user = db.query(User).filter(User.email == "employee@corp.com").one()
    assert user.display_name == "Employee"
    assert (
        db.query(OAuthIdentity)
        .filter(OAuthIdentity.user_id == user.id, OAuthIdentity.provider_uid == "9100")
        .count()
        == 1
    )


def test_path_c_empty_whitelist_allows_any_domain(db, github_mock, monkeypatch):
    _whitelist(monkeypatch, "")
    make_user(db, email="seed@example.com", password="Seed-Pass-1")

    params = run_login_flow(
        db, github_mock, profile=github_profile(uid=9200, email=None)
    )
    tokens = oauth_service.complete_register(
        db, params["ticket"], "anyone@gmail.com", "Newbie-Pass-1", "Anyone"
    )
    assert tokens.access_token
    assert db.query(User).filter(User.email == "anyone@gmail.com").count() == 1
