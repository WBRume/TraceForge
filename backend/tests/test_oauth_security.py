"""
🔴 T03 OAuth 安全红线测试套件（R1–R8）。

本文件是"账号接管防护"的守护网，每条用例对应任务书中的一条红线：

- R1  路径 A：身份已存在 → 直登，签发可用 JWT
- R2  路径 B 接管红线：邮箱已注册 + 错误密码 → 拒绝、零绑定、受害者账号无损、ticket 释放可重试
- R3  路径 B 正确密码 → 绑定到既有账号、签发 JWT、不新建用户
- R4  路径 C：全新邮箱 → 先 REGISTER_REQUIRED 且不建号；补全注册后建号 + 绑定 + 签发 JWT
- R5  接管负向：拿不出密码就永远登不进受害者账号
- R6  ticket 原子重放：终态接口消费一次即失效（resolve 按设计是幂等读，见用例说明）
- R7  密码错误 与 账号不存在 响应逐字节一致（无邮箱枚举）
- R8  ticket 释放语义：未达阈值释放占用可重试，达阈值保持消费并锁定

⚠️ 实现语义与任务书措辞的两处差异（已核对源码，属设计约定而非缺陷）：
1. 端点前缀是 ``/api/auth/oauth/...``（``routers/oauth.py`` 的 router prefix
   为 ``/auth/oauth``，``main.py`` 再加 ``/api``），不是 ``/api/oauth/...``。
2. ``POST /resolve`` 是**幂等读**，不消费 ticket（``oauth_service.resolve_ticket``
   文档与实现一致：路径 B/C 需要多次 resolve）。因此 R6 的"消费一次即失效"
   在**终态接口**（bind/confirm、register、bind）上验证——那里才是
   ``_consume_ticket`` 的原子 UPDATE 所在。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.domains.auth.errors import (
    ERR_OAUTH_EMAIL_TAKEN,
    ERR_OAUTH_PASSWORD_INVALID,
    ERR_OAUTH_TICKET_INVALID,
    ERR_OAUTH_TICKET_LOCKED,
    OAuthPasswordInvalidError,
    OAuthTicketInvalidError,
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

VICTIM_EMAIL = "victim@example.com"
VICTIM_PASSWORD = "Victim-Pass-1"
ATTACKER_UID = 4242


# ══════════════════ 断言助手 ══════════════════

def ticket_row(db: Session, ticket: str) -> OAuthTicket:
    """按 ticket 值取行（每次重查，避免 session 缓存导致的假通过）。"""
    db.expire_all()
    row = db.query(OAuthTicket).filter(OAuthTicket.ticket == ticket).first()
    assert row is not None, f"ticket 行应存在: {ticket}"
    return row


def identity_count(db: Session) -> int:
    return db.query(OAuthIdentity).count()


def user_count(db: Session) -> int:
    return db.query(User).count()


def assert_no_token_leaked(resp) -> None:
    """响应体中不得出现任何可用凭证（含 null 字段视为未泄漏）。"""
    assert "access_token" not in resp.text or resp.json().get("access_token") is None, (
        f"响应不应包含可用 access_token: {resp.text}"
    )
    assert "refresh_token" not in resp.text or resp.json().get("refresh_token") is None


def assert_valid_access_token_for(token: str, user_id: str) -> None:
    """用应用自身的解码路径校验 JWT 主体正确（不是随手拼的字符串）。"""
    assert token, "应签发 access_token"
    payload = auth_service.decode_token(token, expected_type="access")
    assert payload["sub"] == user_id, f"JWT sub 应为 {user_id}，实际 {payload.get('sub')}"


# ══════════════════════════════════════════════════════════════════════
# R1. 路径 A：身份已存在 → 直接登录
# ══════════════════════════════════════════════════════════════════════

def test_r1_existing_identity_logs_in_directly_and_resolve_issues_jwt(
    db, github_mock, client: TestClient
):
    """R1：已绑定身份的用户回调 → ticket intent=login/LOGIN_OK，resolve 换出可用 JWT。"""
    user = make_user(db, email="bound@example.com", password="Bound-Pass-1")
    make_identity(db, user, provider="github", provider_uid="9001")

    params = run_login_flow(db, github_mock, profile=github_profile(uid=9001))

    # 判定结果：路径 A
    assert params["status"] == "LOGIN_OK"
    ticket = params["ticket"]
    assert ticket, "路径 A 必须签发 ticket"
    # 🔴 302 URL 中只有 ticket，绝不含 JWT
    assert "access_token" not in ticket

    row = ticket_row(db, ticket)
    assert row.intent == "login"
    assert row.user_id == user.id, "ticket 必须指向该身份所属账号"

    # resolve → 兑换真实可用的 JWT
    resp = client.post("/api/auth/oauth/resolve", json={"ticket": ticket})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "LOGIN_OK"
    assert_valid_access_token_for(body["access_token"], user.id)
    assert body["refresh_token"], "应同时签发 refresh_token"

    # 路径 A 不产生新绑定，也不建号
    assert identity_count(db) == 1
    assert user_count(db) == 1


# ══════════════════════════════════════════════════════════════════════
# R2. 路径 B 接管红线：错误密码
# ══════════════════════════════════════════════════════════════════════

def test_r2_hijack_wrong_password_rejected_no_binding_ticket_released(
    db, github_mock, client: TestClient
):
    """🔴 R2 账号接管红线。

    攻击者持有自己的 GitHub 账号（uid=4242），把三方 email 改成受害者邮箱。
    错误密码必须：401、零绑定、受害者账号字段无损、ticket 释放以便正常用户重试。
    """
    victim = make_user(db, email=VICTIM_EMAIL, password=VICTIM_PASSWORD)
    hash_before = victim.hashed_password
    email_before = victim.email
    display_before = victim.display_name

    params = run_login_flow(
        db, github_mock, profile=github_profile(uid=ATTACKER_UID, email=VICTIM_EMAIL)
    )
    # 🔴 绝不允许判定为 LOGIN_OK（那就是自动合并 = 账号接管）
    assert params["status"] == "BIND_REQUIRED", (
        "邮箱已注册但身份未绑定时，必须走需验密码的路径 B"
    )
    ticket = params["ticket"]
    assert ticket_row(db, ticket).user_id == victim.id

    resp = client.post(
        "/api/auth/oauth/bind/confirm",
        json={"ticket": ticket, "password": "Attacker-Guess-1"},
    )

    # ① 必须拒绝
    assert resp.status_code == 401, resp.text
    assert resp.json()["code"] == ERR_OAUTH_PASSWORD_INVALID
    assert_no_token_leaked(resp)

    # ② 🔴 绝无绑定产生
    assert identity_count(db) == 0, "错误密码时严禁创建任何 oauth_identity"
    db.refresh(victim)
    assert victim.oauth_identities == []

    # ③ 🔴 受害者账号未被篡改
    assert victim.hashed_password == hash_before
    assert victim.email == email_before
    assert victim.display_name == display_before
    assert user_count(db) == 1, "严禁旁路新建账号"

    # ④ ticket 占用被释放，失败计数 +1（T02 语义）
    row = ticket_row(db, ticket)
    assert row.consumed_at is None, "未达阈值时应释放 ticket 占用以便重试"
    assert row.failed_attempts == 1

    # ⑤ 释放语义是真的可用：真正的账号主人用正确密码重试成功
    retry = client.post(
        "/api/auth/oauth/bind/confirm",
        json={"ticket": ticket, "password": VICTIM_PASSWORD},
    )
    assert retry.status_code == 200, retry.text
    assert_valid_access_token_for(retry.json()["access_token"], victim.id)
    assert identity_count(db) == 1


# ══════════════════════════════════════════════════════════════════════
# R3. 路径 B 成功：正确密码
# ══════════════════════════════════════════════════════════════════════

def test_r3_correct_password_binds_to_existing_user_without_creating_new_one(
    db, github_mock, client: TestClient
):
    """R3：正确密码 → 身份绑到既有账号、签发 JWT、不新建用户。"""
    victim = make_user(db, email=VICTIM_EMAIL, password=VICTIM_PASSWORD)
    assert user_count(db) == 1

    params = run_login_flow(
        db, github_mock, profile=github_profile(uid=ATTACKER_UID, email=VICTIM_EMAIL)
    )
    assert params["status"] == "BIND_REQUIRED"

    resp = client.post(
        "/api/auth/oauth/bind/confirm",
        json={"ticket": params["ticket"], "password": VICTIM_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "BOUND"
    assert_valid_access_token_for(body["access_token"], victim.id)

    # 绑定落到既有账号，而不是新建
    assert user_count(db) == 1, "路径 B 严禁新建账号"
    assert identity_count(db) == 1
    identity = db.query(OAuthIdentity).one()
    assert identity.user_id == victim.id
    assert identity.provider == "github"
    assert identity.provider_uid == str(ATTACKER_UID)

    # 绑定后原密码登录仍然可用（绑定不改动本地凭据）
    assert auth_service.authenticate_user(db, VICTIM_EMAIL, VICTIM_PASSWORD) is not None


# ══════════════════════════════════════════════════════════════════════
# R4. 路径 C：全新邮箱
# ══════════════════════════════════════════════════════════════════════

def test_r4_new_email_defers_user_creation_until_completion_register(
    db, github_mock, client: TestClient
):
    """R4：全新邮箱 → REGISTER_REQUIRED 且**此刻不建号**；补全注册后建号+绑定+签发 JWT。

    同时守护"手填优先"：以用户手填邮箱建号，三方 email 只作 provider_email 快照。
    """
    assert user_count(db) == 0

    params = run_login_flow(
        db, github_mock, profile=github_profile(uid=7001, email="fresh@example.com")
    )
    assert params["status"] == "REGISTER_REQUIRED"
    ticket = params["ticket"]

    # 🔴 补全注册之前，数据库里绝不能有账号或绑定
    assert user_count(db) == 0, "路径 C 在补全注册前严禁建号"
    assert identity_count(db) == 0
    row = ticket_row(db, ticket)
    assert row.user_id is None

    # resolve 预填建议值（幂等读，不签发 token）
    resolved = client.post("/api/auth/oauth/resolve", json={"ticket": ticket})
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["suggested_email"] == "fresh@example.com"
    assert_no_token_leaked(resolved)

    # 补全注册：手填邮箱与三方 email 故意不同，验证"手填优先"
    resp = client.post(
        "/api/auth/oauth/register",
        json={
            "ticket": ticket,
            "email": "typed-by-hand@example.com",
            "password": "Fresh-Pass-1",
            "display_name": "Fresh User",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "REGISTERED"

    # 建号 + 绑定 + 可用 JWT
    assert user_count(db) == 1
    user = db.query(User).one()
    assert user.email == "typed-by-hand@example.com", "必须以手填邮箱建号"
    assert user.display_name == "Fresh User"
    assert (user.hashed_password or "").strip(), "OAuth 建号也必须落密码（兜底凭据）"
    assert_valid_access_token_for(body["access_token"], user.id)

    assert identity_count(db) == 1
    identity = db.query(OAuthIdentity).one()
    assert identity.user_id == user.id
    assert identity.provider_uid == "7001"
    assert identity.provider_email == "fresh@example.com", "三方 email 仅作快照"


# ══════════════════════════════════════════════════════════════════════
# R5. 接管负向：拿不出密码就登不进受害者账号
# ══════════════════════════════════════════════════════════════════════

def test_r5_actor_without_password_never_obtains_victim_session(
    db, github_mock, client: TestClient, monkeypatch
):
    """🔴 R5：三方 email 命中已注册账号，但行为人拿不出密码 → 永远拿不到受害者会话。

    穷举所有可能的兑换姿势：resolve（多次）、bind/confirm（多次猜密码）、
    register（借道路径 C）、bind（借道加绑），每一条都不得产出受害者的 token。
    """
    monkeypatch.setattr(settings, "OAUTH_BIND_MAX_ATTEMPTS", 3)
    victim = make_user(db, email=VICTIM_EMAIL, password=VICTIM_PASSWORD)
    victim_id = victim.id

    params = run_login_flow(
        db, github_mock, profile=github_profile(uid=ATTACKER_UID, email=VICTIM_EMAIL)
    )
    assert params["status"] == "BIND_REQUIRED"
    ticket = params["ticket"]

    collected: list = []

    # ① resolve 多次：只回脱敏邮箱，永不签发 token
    for _ in range(3):
        resolved = client.post("/api/auth/oauth/resolve", json={"ticket": ticket})
        assert resolved.status_code == 200, resolved.text
        payload = resolved.json()
        assert payload["status"] == "BIND_REQUIRED"
        assert payload["access_token"] is None
        assert payload["refresh_token"] is None
        # 🔴 未认证端点只允许脱敏邮箱，严禁完整邮箱回显
        assert payload["email_masked"] == "v***@example.com"
        assert VICTIM_EMAIL not in resolved.text
        collected.append(resolved)

    # ② 借道路径 C 注册（企图不验密码就拿账号）→ 状态不符，拒绝
    hijack_register = client.post(
        "/api/auth/oauth/register",
        json={
            "ticket": ticket,
            "email": VICTIM_EMAIL,
            "password": "Attacker-Pass-1",
            "display_name": "Attacker",
        },
    )
    assert hijack_register.status_code in (400, 409), hijack_register.text
    collected.append(hijack_register)

    # ③ 借道加绑 → intent 不符，拒绝
    hijack_bind = client.post("/api/auth/oauth/bind", json={"ticket": ticket})
    assert hijack_bind.status_code == 400, hijack_bind.text
    collected.append(hijack_bind)

    # ④ 猜密码直到锁定 → 全部 401，最后 423
    for guess in ("guess-1", "guess-2", "guess-3"):
        resp = client.post(
            "/api/auth/oauth/bind/confirm", json={"ticket": ticket, "password": guess}
        )
        assert resp.status_code == 401, resp.text
        collected.append(resp)
    locked = client.post(
        "/api/auth/oauth/bind/confirm", json={"ticket": ticket, "password": "guess-4"}
    )
    assert locked.status_code == 423, locked.text
    assert locked.json()["code"] == ERR_OAUTH_TICKET_LOCKED
    collected.append(locked)

    # 🔴 终局断言：全过程没有任何一个响应泄漏出可用凭证
    for resp in collected:
        assert_no_token_leaked(resp)

    # 🔴 受害者账号完全没有被接管：无绑定、无新账号、密码可用
    assert identity_count(db) == 0
    assert user_count(db) == 1
    db.refresh(victim)
    assert victim.id == victim_id
    assert victim.oauth_identities == []
    assert auth_service.authenticate_user(db, VICTIM_EMAIL, VICTIM_PASSWORD) is not None


# ══════════════════════════════════════════════════════════════════════
# R6. ticket 原子重放
# ══════════════════════════════════════════════════════════════════════

def test_r6_resolve_is_idempotent_read_by_design(db, github_mock, client: TestClient):
    """R6 前提说明：``/resolve`` 是**幂等读**，不消费 ticket。

    这是 ``oauth_service.resolve_ticket`` 的显式设计（路径 B/C 需多次 resolve），
    因此"第二次 resolve 必须失败"不成立；真正的一次性消费在终态接口上，
    由下面三条用例守护。本用例把该设计钉住，防止将来被误改成消费型。
    """
    user = make_user(db, email="bound@example.com", password="Bound-Pass-1")
    make_identity(db, user, provider="github", provider_uid="9001")
    params = run_login_flow(db, github_mock, profile=github_profile(uid=9001))
    ticket = params["ticket"]

    first = client.post("/api/auth/oauth/resolve", json={"ticket": ticket})
    second = client.post("/api/auth/oauth/resolve", json={"ticket": ticket})
    assert first.status_code == 200 and second.status_code == 200
    assert ticket_row(db, ticket).consumed_at is None, "resolve 不得消费 ticket"


def test_r6_bind_confirm_ticket_cannot_be_replayed(db, github_mock, client: TestClient):
    """🔴 R6a：路径 B 终态成功后，同一 ticket 重放必须失败，且不得产生第二条绑定。"""
    victim = make_user(db, email=VICTIM_EMAIL, password=VICTIM_PASSWORD)
    params = run_login_flow(
        db, github_mock, profile=github_profile(uid=ATTACKER_UID, email=VICTIM_EMAIL)
    )
    ticket = params["ticket"]

    first = client.post(
        "/api/auth/oauth/bind/confirm",
        json={"ticket": ticket, "password": VICTIM_PASSWORD},
    )
    assert first.status_code == 200, first.text
    assert identity_count(db) == 1
    assert ticket_row(db, ticket).consumed_at is not None

    # 🔴 重放：即使密码正确也必须失败
    replay = client.post(
        "/api/auth/oauth/bind/confirm",
        json={"ticket": ticket, "password": VICTIM_PASSWORD},
    )
    assert replay.status_code == 404, replay.text
    assert replay.json()["code"] == ERR_OAUTH_TICKET_INVALID
    assert_no_token_leaked(replay)
    assert identity_count(db) == 1, "重放不得产生第二条绑定"
    assert user_count(db) == 1
    assert victim.id == db.query(OAuthIdentity).one().user_id


def test_r6_register_ticket_cannot_be_replayed(db, github_mock, client: TestClient):
    """🔴 R6b：路径 C 终态成功后重放必须失败，不得建出第二个账号。"""
    params = run_login_flow(
        db, github_mock, profile=github_profile(uid=7002, email="fresh@example.com")
    )
    ticket = params["ticket"]
    payload = {
        "ticket": ticket,
        "password": "Fresh-Pass-1",
        "display_name": "Fresh User",
    }

    first = client.post(
        "/api/auth/oauth/register", json={**payload, "email": "first@example.com"}
    )
    assert first.status_code == 200, first.text
    assert user_count(db) == 1

    # 重放（换一个未注册邮箱，绕开唯一性前置校验，直抵原子消费判定）
    replay = client.post(
        "/api/auth/oauth/register", json={**payload, "email": "second@example.com"}
    )
    assert replay.status_code == 404, replay.text
    assert replay.json()["code"] == ERR_OAUTH_TICKET_INVALID
    assert_no_token_leaked(replay)
    assert user_count(db) == 1, "重放不得建出第二个账号"
    assert identity_count(db) == 1

    # 重放（同邮箱）：被唯一性校验挡在消费之前，同样不产生副作用
    replay_same = client.post(
        "/api/auth/oauth/register", json={**payload, "email": "first@example.com"}
    )
    assert replay_same.status_code == 409, replay_same.text
    assert replay_same.json()["code"] == ERR_OAUTH_EMAIL_TAKEN
    assert user_count(db) == 1


def test_r6_bind_ticket_cannot_be_replayed(db, github_mock, client: TestClient):
    """🔴 R6c：加绑终态成功后重放必须失败，不得产生重复绑定。"""
    user = make_user(db, email="binder@example.com", password="Binder-Pass-1")
    params = run_login_flow(
        db,
        github_mock,
        profile=github_profile(uid=6601, email="brand-new@example.com"),
        intent="bind",
        user=user,
    )
    assert params["status"] == "LOGIN_OK"
    ticket = params["ticket"]

    first = client.post("/api/auth/oauth/bind", json={"ticket": ticket})
    assert first.status_code == 200, first.text
    assert identity_count(db) == 1

    replay = client.post("/api/auth/oauth/bind", json={"ticket": ticket})
    assert replay.status_code == 404, replay.text
    assert replay.json()["code"] == ERR_OAUTH_TICKET_INVALID
    assert identity_count(db) == 1


def test_r6_consume_ticket_primitive_is_single_shot(db, github_mock):
    """R6d：直击原子消费原语——同一 ticket 连续 ``_consume_ticket`` 只允许成功一次。

    这是防并发双花的最小证明（单条 ``UPDATE ... WHERE consumed_at IS NULL``
    + rowcount 判定）。
    """
    user = make_user(db, email="bound@example.com", password="Bound-Pass-1")
    make_identity(db, user, provider="github", provider_uid="9001")
    params = run_login_flow(db, github_mock, profile=github_profile(uid=9001))
    ticket = params["ticket"]

    claimed = oauth_service._consume_ticket(db, ticket)
    assert claimed.consumed_at is not None

    with pytest.raises(OAuthTicketInvalidError) as exc_info:
        oauth_service._consume_ticket(db, ticket)
    assert exc_info.value.status_code == 404
    assert exc_info.value.code == ERR_OAUTH_TICKET_INVALID


# ══════════════════════════════════════════════════════════════════════
# R7. 密码错误 vs 账号不存在：逐字节一致
# ══════════════════════════════════════════════════════════════════════

def test_r7_unknown_account_and_wrong_password_are_byte_identical(
    db, github_mock, client: TestClient
):
    """🔴 R7：两种失败的 HTTP 响应逐字节一致 → 无法用 OAuth 端点枚举邮箱。

    可达性说明：``BIND_REQUIRED`` 的前提就是邮箱已注册，所以"账号不存在"
    只能通过 ticket 签发后账号消失来构造（也正是并发删号的真实场景）。
    两个 ticket 用不同 provider_uid，避免 E-18 冷却互相污染。
    """
    victim = make_user(db, email=VICTIM_EMAIL, password=VICTIM_PASSWORD)

    ticket_wrong_pwd = run_login_flow(
        db, github_mock, profile=github_profile(uid=5100, email=VICTIM_EMAIL)
    )["ticket"]
    ticket_no_user = run_login_flow(
        db, github_mock, profile=github_profile(uid=5101, email=VICTIM_EMAIL)
    )["ticket"]

    # 场景 A：账号存在，密码错误
    resp_wrong_pwd = client.post(
        "/api/auth/oauth/bind/confirm",
        json={"ticket": ticket_wrong_pwd, "password": "Definitely-Wrong-1"},
    )

    # 场景 B：账号不存在（ticket 签发后被删号）
    db.delete(victim)
    db.commit()
    resp_no_user = client.post(
        "/api/auth/oauth/bind/confirm",
        json={"ticket": ticket_no_user, "password": "Definitely-Wrong-1"},
    )

    # 🔴 状态码 / 错误码 / 文案 / 原始字节 / content-type 全部一致
    assert resp_wrong_pwd.status_code == 401
    assert resp_no_user.status_code == 401
    assert resp_wrong_pwd.json()["code"] == ERR_OAUTH_PASSWORD_INVALID
    assert resp_no_user.json()["code"] == ERR_OAUTH_PASSWORD_INVALID
    assert resp_wrong_pwd.json()["detail"] == resp_no_user.json()["detail"]
    assert resp_wrong_pwd.content == resp_no_user.content, (
        "两种失败的响应体必须逐字节一致，否则可枚举邮箱"
    )
    assert resp_wrong_pwd.headers.get("content-type") == resp_no_user.headers.get(
        "content-type"
    )
    # 响应体中不得出现邮箱本身
    assert VICTIM_EMAIL not in resp_wrong_pwd.text


def test_r7_service_layer_raises_the_same_exception_for_both_cases(db, github_mock):
    """R7 补强：服务层对两种情形抛出同一异常类，且 code/message/status 完全相同。"""
    victim = make_user(db, email=VICTIM_EMAIL, password=VICTIM_PASSWORD)
    ticket_a = run_login_flow(
        db, github_mock, profile=github_profile(uid=5200, email=VICTIM_EMAIL)
    )["ticket"]
    ticket_b = run_login_flow(
        db, github_mock, profile=github_profile(uid=5201, email=VICTIM_EMAIL)
    )["ticket"]

    with pytest.raises(OAuthPasswordInvalidError) as exc_wrong:
        oauth_service.confirm_bind(db, ticket_a, "Definitely-Wrong-1")

    db.delete(victim)
    db.commit()
    with pytest.raises(OAuthPasswordInvalidError) as exc_missing:
        oauth_service.confirm_bind(db, ticket_b, "Definitely-Wrong-1")

    assert type(exc_wrong.value) is type(exc_missing.value)
    assert exc_wrong.value.status_code == exc_missing.value.status_code == 401
    assert exc_wrong.value.code == exc_missing.value.code == ERR_OAUTH_PASSWORD_INVALID
    assert exc_wrong.value.message == exc_missing.value.message
    assert exc_wrong.value.extra == exc_missing.value.extra


# ══════════════════════════════════════════════════════════════════════
# R8. ticket 释放 / 锁定语义
# ══════════════════════════════════════════════════════════════════════

def test_r8_release_before_threshold_and_lock_at_threshold(
    db, github_mock, client: TestClient, monkeypatch
):
    """🔴 R8：未达阈值每次失败都释放 ticket（consumed_at=NULL）并递增 failed_attempts；
    达阈值后 ticket 保持消费 + 写入 locked_until，后续请求一律 423 不可重试。

    阈值调小到 3（走 ``settings.OAUTH_BIND_MAX_ATTEMPTS``，顺带证明阈值确实读配置）。
    """
    threshold = 3
    monkeypatch.setattr(settings, "OAUTH_BIND_MAX_ATTEMPTS", threshold)

    make_user(db, email=VICTIM_EMAIL, password=VICTIM_PASSWORD)
    ticket = run_login_flow(
        db, github_mock, profile=github_profile(uid=5300, email=VICTIM_EMAIL)
    )["ticket"]

    for attempt in range(1, threshold + 1):
        resp = client.post(
            "/api/auth/oauth/bind/confirm",
            json={"ticket": ticket, "password": f"wrong-{attempt}"},
        )
        assert resp.status_code == 401, f"第 {attempt} 次失败应为 401：{resp.text}"
        assert resp.json()["code"] == ERR_OAUTH_PASSWORD_INVALID
        row = ticket_row(db, ticket)
        assert row.failed_attempts == attempt, "每次失败必须递增 failed_attempts"

        if attempt < threshold:
            # 阈值前：释放占用，ticket 仍可用
            assert row.consumed_at is None, (
                f"第 {attempt} 次失败（未达阈值）应释放 ticket 占用"
            )
            assert row.locked_until is None
            # 释放不是纸面语义：resolve 仍可读到 BIND_REQUIRED
            probe = client.post("/api/auth/oauth/resolve", json={"ticket": ticket})
            assert probe.status_code == 200
            assert probe.json()["status"] == "BIND_REQUIRED"
        else:
            # 达阈值：保持消费 + 锁定
            assert row.consumed_at is not None, "达阈值后 ticket 必须保持消费（作废）"
            assert row.locked_until is not None, "达阈值后必须写入冷却时间"
            remaining = (row.locked_until - oauth_service._utcnow()).total_seconds()
            cooldown = int(settings.OAUTH_BIND_COOLDOWN_SECONDS)
            assert cooldown - 30 < remaining <= cooldown

    # 锁定后：正确密码也不可再用（不能靠撞库后补正确密码翻盘）
    locked = client.post(
        "/api/auth/oauth/bind/confirm",
        json={"ticket": ticket, "password": VICTIM_PASSWORD},
    )
    assert locked.status_code == 423, locked.text
    assert locked.json()["code"] == ERR_OAUTH_TICKET_LOCKED
    assert locked.json()["retry_after"] > 0
    assert_no_token_leaked(locked)

    # resolve 也被冷却拦截
    assert client.post("/api/auth/oauth/resolve", json={"ticket": ticket}).status_code == 423

    # 🔴 全程零绑定
    assert identity_count(db) == 0


def test_r8_cooldown_applies_across_tickets_for_same_provider_uid(
    db, github_mock, client: TestClient, monkeypatch
):
    """R8 补强：冷却按 provider_uid 生效（跨 ticket），换新 ticket 也不能绕过撞库限制。"""
    threshold = 2
    monkeypatch.setattr(settings, "OAUTH_BIND_MAX_ATTEMPTS", threshold)
    make_user(db, email=VICTIM_EMAIL, password=VICTIM_PASSWORD)

    ticket_one = run_login_flow(
        db, github_mock, profile=github_profile(uid=5400, email=VICTIM_EMAIL)
    )["ticket"]
    for attempt in range(threshold):
        resp = client.post(
            "/api/auth/oauth/bind/confirm",
            json={"ticket": ticket_one, "password": f"wrong-{attempt}"},
        )
        assert resp.status_code == 401, resp.text
    assert ticket_row(db, ticket_one).locked_until is not None

    # 同一 provider_uid 重新走一遍授权拿到全新 ticket
    ticket_two = run_login_flow(
        db, github_mock, profile=github_profile(uid=5400, email=VICTIM_EMAIL)
    )["ticket"]
    assert ticket_two != ticket_one

    # 🔴 新 ticket 依然被冷却拦截，正确密码也不放行
    blocked = client.post(
        "/api/auth/oauth/bind/confirm",
        json={"ticket": ticket_two, "password": VICTIM_PASSWORD},
    )
    assert blocked.status_code == 423, blocked.text
    assert blocked.json()["code"] == ERR_OAUTH_TICKET_LOCKED
    assert identity_count(db) == 0
