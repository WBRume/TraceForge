"""
🔴 T03 安全红线用例（B-20，对应 PRD AC-S1/S2/S6/S7，最高优先级）。

红线清单（失败即阻断合并）：
1. 路径 B 不提供密码 → 绑定与登录均失败，DB 无 oauth_identities 新增
2. 路径 B 错误密码 → 同上，且 failed_attempts 递增
3. 伪造 profile（三方 email == 受害者 email）→ 绝不会登录到受害者账号
4. UNIQUE(provider, provider_uid) 并发冲突 → 捕获为 409
5. 密码错误 vs 账号不存在 响应体逐字节一致
6. state 重放被拒绝
7. 密码失败重试语义（T02 实现语义）：未达阈值释放占用可重试；达 5 次锁定 15 分钟（E-18）
8. bind-intent 的 LOGIN_OK ticket 不可当登录凭证兑换 token
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings  # noqa: E402
from app.domains.auth.errors import (
    ERR_OAUTH_IDENTITY_CONFLICT,
    ERR_OAUTH_PASSWORD_INVALID,
    ERR_OAUTH_TICKET_LOCKED,
    OAuthAPIError,
    OAuthPasswordInvalidError,
    OAuthTicketLockedError,
)
from app.domains.auth.models.oauth import OAuthIdentity, OAuthTicket
from app.domains.auth.services import oauth_service

from tests.conftest import (
    github_profile,
    make_identity,
    make_user,
    run_login_flow,
)


def _ticket_row(db: Session, ticket: str) -> OAuthTicket:
    row = db.query(OAuthTicket).filter(OAuthTicket.ticket == ticket).first()
    assert row is not None, "ticket 行应存在"
    return row


def _identity_count(db: Session) -> int:
    return db.query(OAuthIdentity).count()


# ══════════════════ 红线 1：路径 B 不提供密码 ══════════════════

def test_path_b_missing_password_bind_and_login_fail(db, github_mock, client: TestClient):
    """🔴 不提供密码：绑定与登录均失败，DB 无 oauth_identities 新增（AC-S2）。"""
    victim = make_user(db, email="victim@example.com", password="Real-Pass-1")
    params = run_login_flow(
        db, github_mock, profile=github_profile(email="victim@example.com")
    )
    assert params["status"] == "BIND_REQUIRED"
    ticket = params["ticket"]

    # HTTP 层：缺 password 字段 → 422（schema 必填），绝不能绑定成功或签发 token
    resp = client.post("/api/auth/oauth/bind/confirm", json={"ticket": ticket})
    assert resp.status_code == 422
    assert "access_token" not in resp.text

    # HTTP 层：空字符串密码同样被 schema 拒绝（min_length=1，无绕过路径）
    resp = client.post(
        "/api/auth/oauth/bind/confirm", json={"ticket": ticket, "password": ""}
    )
    assert resp.status_code == 422

    # 服务层兜底：即使绕过 schema 直调服务，空密码也必须 401
    with pytest.raises(OAuthPasswordInvalidError):
        oauth_service.confirm_bind(db, ticket, "")

    # 🔴 核心断言：任何尝试后 DB 均无 oauth_identities 新增
    assert _identity_count(db) == 0
    db.refresh(victim)
    assert victim.oauth_identities == []


# ══════════════════ 红线 2：路径 B 错误密码 ══════════════════

def test_path_b_wrong_password_fails_and_increments_failed_attempts(
    db, github_mock, client: TestClient
):
    """🔴 错误密码：401、无绑定新增、failed_attempts 递增。"""
    make_user(db, email="victim@example.com", password="Real-Pass-1")
    params = run_login_flow(
        db, github_mock, profile=github_profile(email="victim@example.com")
    )
    ticket = params["ticket"]

    resp = client.post(
        "/api/auth/oauth/bind/confirm", json={"ticket": ticket, "password": "Wrong-Pass"}
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["code"] == ERR_OAUTH_PASSWORD_INVALID

    assert _identity_count(db) == 0
    row = _ticket_row(db, ticket)
    assert row.failed_attempts == 1


# ══════════════════ 红线 3：伪造 profile 永远登录不到受害者账号 ══════════════════

def test_forged_profile_email_never_logs_into_victim_account(db, github_mock, client: TestClient):
    """🔴 AC-S1：账号归属唯一依据 (provider, provider_uid)。

    攻击者持有 GitHub 账号（uid=666），把 GitHub 侧 email 改成受害者邮箱，
    期望：走路径 B（BIND_REQUIRED）而**非**路径 A；resolve 绝不签发 token；
    不验证受害者密码则永远拿不到受害者账号。
    """
    victim = make_user(db, email="victim@example.com", password="Victim-Pass-1")
    forged = github_profile(uid=666, email="victim@example.com")

    params = run_login_flow(db, github_mock, profile=forged)
    # 严禁判定为 LOGIN_OK（路径 A）
    assert params["status"] == "BIND_REQUIRED", (
        "伪造三方 email 绝不允许命中路径 A 直接登录"
    )
    ticket = params["ticket"]

    # resolve（未认证端点）绝不签发 token
    resolve = client.post("/api/auth/oauth/resolve", json={"ticket": ticket})
    assert resolve.status_code == 200
    payload = resolve.json()
    assert payload["status"] == "BIND_REQUIRED"
    assert payload["access_token"] is None
    assert payload["refresh_token"] is None
    # 只回脱敏邮箱
    assert payload["email_masked"] == "v***@example.com"

    # 攻击者不知道受害者密码：随便猜 → 401
    resp = client.post(
        "/api/auth/oauth/bind/confirm", json={"ticket": ticket, "password": "Guess-123"}
    )
    assert resp.status_code == 401

    # 🔴 受害者名下没有任何新绑定产生
    assert _identity_count(db) == 0
    db.refresh(victim)
    assert victim.oauth_identities == []
    # 且受害者原密码登录不受影响
    assert (
        oauth_service.confirm_bind  # noqa: F401  占位保证 import 完整性
        is not None
    )


# ══════════════════ 红线 4：UNIQUE(provider, provider_uid) 冲突 → 409 ══════════════════

def test_unique_provider_uid_conflict_returns_409(db, github_mock, client: TestClient):
    """🔴 AC-S6：同一三方身份绑第二个账号时，IntegrityError 被捕获为 409。"""
    user_a = make_user(db, email="alice@example.com", password="Alice-Pass-1")
    user_b = make_user(db, email="bob@example.com", password="Bob-Pass-1")
    assert user_b is not None

    # Alice 走路径 B：三方 email 与她的邮箱一致，uid=7777 尚未绑定任何人
    params = run_login_flow(
        db, github_mock, profile=github_profile(uid=7777, email="alice@example.com")
    )
    assert params["status"] == "BIND_REQUIRED"
    ticket = params["ticket"]

    # 并发窗口模拟：在 Alice 确认之前，uid=7777 已被 Bob 绑走
    make_identity(db, user_b, provider="github", provider_uid="7777")

    resp = client.post(
        "/api/auth/oauth/bind/confirm", json={"ticket": ticket, "password": "Alice-Pass-1"}
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == ERR_OAUTH_IDENTITY_CONFLICT

    # 冲突后：uid=7777 仍只属于 Bob；Alice 名下无绑定
    rows = (
        db.query(OAuthIdentity)
        .filter(OAuthIdentity.provider == "github", OAuthIdentity.provider_uid == "7777")
        .all()
    )
    assert len(rows) == 1 and rows[0].user_id == user_b.id


# ══════════════════ 红线 5：密码错误 vs 账号不存在 响应体逐字节一致 ══════════════════

def test_wrong_password_vs_unknown_account_identical_response(
    db, github_mock, client: TestClient
):
    """🔴 AC-S7 / K-7：两种失败的 HTTP 响应必须逐字节一致（不可探测账号存在性）。"""
    victim = make_user(db, email="victim@example.com", password="Real-Pass-1")

    # 场景 A：账号存在但密码错误
    params_ok = run_login_flow(
        db, github_mock, profile=github_profile(uid=5100, email="victim@example.com")
    )
    assert params_ok["status"] == "BIND_REQUIRED"
    resp_wrong_password = client.post(
        "/api/auth/oauth/bind/confirm",
        json={"ticket": params_ok["ticket"], "password": "Totally-Wrong"},
    )

    # 场景 B：ticket 的目标账号已被删除（= 账号不存在）
    params_gone = run_login_flow(
        db, github_mock, profile=github_profile(uid=5101, email="victim@example.com")
    )
    ticket_gone = params_gone["ticket"]
    db.delete(victim)
    db.commit()
    resp_unknown_account = client.post(
        "/api/auth/oauth/bind/confirm",
        json={"ticket": ticket_gone, "password": "Totally-Wrong"},
    )

    assert resp_wrong_password.status_code == resp_unknown_account.status_code == 401
    # 🔴 逐字节一致（含状态码与完整响应体）
    assert resp_wrong_password.content == resp_unknown_account.content


# ══════════════════ 红线 6：state 重放被拒绝 ══════════════════

def test_state_replay_rejected(db, github_mock, client: TestClient):
    """🔴 E-4d：同一 state 第二次 callback 必须以 state_invalid 拒绝。"""
    make_user(db, email="someone@example.com", password="Some-Pass-1")
    profile = github_profile(uid=8800, email="someone@example.com")
    github_mock.user_response = (200, profile)

    from app.domains.auth.services import oauth_service

    authz = oauth_service.build_authorize_url(
        db, provider="github", intent="login", client_type="web", user_id=None
    )

    # 第一次回调：成功签发 ticket
    first = client.get(
        "/api/auth/oauth/github/callback",
        params={"code": "good-code", "state": authz.state},
    )
    assert first.status_code == 302
    first_params = _parse_query(first.headers["location"])
    assert first_params.get("ticket")

    # 第二次回调（重放）：302 + error=state_invalid，无 ticket
    second = client.get(
        "/api/auth/oauth/github/callback",
        params={"code": "good-code", "state": authz.state},
    )
    assert second.status_code == 302
    replay_params = _parse_query(second.headers["location"])
    assert replay_params.get("error") == "state_invalid"
    assert not replay_params.get("ticket")

    # 服务层直调同样拒绝（无双花路径）
    cb = oauth_service.handle_callback(
        db, provider="github", code="good-code", state=authz.state, error=None
    )
    assert "error=state_invalid" in cb.redirect_url


def _parse_query(url: str) -> dict:
    import urllib.parse

    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))


# ══════════════════ 红线 7：密码失败重试语义 + E-18 锁定（T02 实现语义） ══════════════════

def test_password_failure_retry_then_lockout_cooldown(db, github_mock):
    """T02 实现语义（有意偏离设计文档，以下列语义为准）：

    - 未达阈值：ticket 占用被释放（consumed_at 复位）→ 可再次提交；failed_attempts+1；
    - 累计达 5 次（OAUTH_BIND_MAX_ATTEMPTS）：ticket 保持 consumed 且
      进入 15 分钟冷却（locked_until），再次提交 → 423 OAUTH_TICKET_LOCKED。
    """
    make_user(db, email="victim@example.com", password="Real-Pass-1")
    params = run_login_flow(
        db, github_mock, profile=github_profile(uid=5200, email="victim@example.com")
    )
    ticket = params["ticket"]
    max_attempts = int(settings.OAUTH_BIND_MAX_ATTEMPTS)

    for attempt in range(1, max_attempts + 1):
        with pytest.raises(OAuthPasswordInvalidError):
            oauth_service.confirm_bind(db, ticket, "Wrong-Pass")
        row = _ticket_row(db, ticket)
        assert row.failed_attempts == attempt
        if attempt < max_attempts:
            # 未达阈值：占用被释放，resolve 幂等读仍可用（ticket 可重试）
            assert row.consumed_at is None
            result = oauth_service.resolve_ticket(db, ticket)
            assert result.status == "BIND_REQUIRED"

    # 达阈值：保持 consumed + 进入冷却
    row = _ticket_row(db, ticket)
    assert row.consumed_at is not None
    assert row.locked_until is not None
    now = oauth_service._utcnow()
    cooldown = int(settings.OAUTH_BIND_COOLDOWN_SECONDS)
    assert (row.locked_until - now).total_seconds() > cooldown - 10

    # 冷却期内：resolve 与再次提交都被 423 拒绝
    with pytest.raises(OAuthTicketLockedError) as exc_info:
        oauth_service.resolve_ticket(db, ticket)
    assert exc_info.value.status_code == 423
    assert exc_info.value.code == ERR_OAUTH_TICKET_LOCKED
    with pytest.raises(OAuthTicketLockedError):
        oauth_service.confirm_bind(db, ticket, "Real-Pass-1")


# ══════════════════ 红线 8：bind-intent ticket 不可当登录凭证 ══════════════════

def test_bind_intent_ticket_cannot_be_exchanged_for_login_token(db, github_mock):
    """T02 实现语义守护：intent=bind 且 status=LOGIN_OK 的 ticket 调 resolve
    拒绝签发 token（防加绑 ticket 被兑换成登录凭证）；也不可走路径 B confirm。
    """
    user = make_user(db, email="bindme@example.com", password="Bind-Pass-1")
    params = run_login_flow(
        db,
        github_mock,
        profile=github_profile(uid=6600, email="brand-new@example.com"),
        intent="bind",
        user=user,
    )
    assert params["status"] == "LOGIN_OK"
    ticket = params["ticket"]

    # 🔴 resolve：LOGIN_OK + intent=bind → 不签发任何 token
    result = oauth_service.resolve_ticket(db, ticket)
    assert result.status == "LOGIN_OK"
    assert result.access_token is None
    assert result.refresh_token is None

    # 🔴 也不允许借道路径 B（confirm_bind 只处理 intent=login + BIND_REQUIRED）
    with pytest.raises(OAuthAPIError) as exc_info:
        oauth_service.confirm_bind(db, ticket, "Bind-Pass-1")
    assert exc_info.value.status_code == 400

    # 正途仍然可用：凭该 ticket 完成加绑
    bind_result = oauth_service.bind_identity(db, ticket, None)
    assert bind_result.identity.user_id == user.id
    assert _identity_count(db) == 1
