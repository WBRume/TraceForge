"""
OAuth 三方登录核心服务（B-07 / T02）—— 🔴 三路判定安全红线所在地。

实现设计文档 §2.4 三路判定树与 §4.4 全部函数签名：

- ``build_authorize_url``   authorize 端点：建一次性 state（防 CSRF）
- ``handle_callback``       回调端点：state 原子消费 → 换 token → 拉 profile → 三路判定 → 建 ticket
- ``resolve_ticket``        幂等读，不消费 ticket（路径 B/C 需多次 resolve）
- ``confirm_bind``          路径 B 终态：🔴 必须验证密码，失败与"账号不存在"响应逐字节一致
- ``complete_register``     路径 C 终态：手填优先（拍板 #6），建号与绑定同一事务
- ``bind_identity``         加绑终态（已登录态 / 管理员二次确认）
- ``list_identities`` / ``unbind_identity``

🔴 红线条款（评审逐条核对，后续 T03 负向测试守护）：
1. 判断账号归属的唯一可信依据是 ``(provider, provider_uid)``，永远不是三方 email。
2. 路径 B 绝不允许在未验证密码的情况下创建绑定或直接登录——本文件中该分支无任何绕过路径。
3. 三方 email 不参与任何账号判定，只存快照、只作预填。
4. 加绑场景（intent=bind）不触发路径 B。
5. ticket 消费只允许 ``_consume_ticket`` 的单条 UPDATE + rowcount 判定（防并发双花）。
6. 三方 access_token 只存在于 ``handle_callback`` 局部变量中，用后即弃：
   不落库、不写日志、不返回前端（拍板 #9）。
7. 回调 302 URL 中只有 ticket，不含 JWT；token 只通过 resolve 用 ticket 兑换。

⏱ Q-J 时区修正：MySQL 会话时区为本地（UTC+8），``server_default=func.now()`` 落库为
本地时间。本模块所有时间字段（``expires_at`` / ``consumed_at`` / ``used_at`` /
``locked_until`` / ``last_login_at``）一律由**应用侧写入 UTC naive 值**
（``_utcnow()``），过期/冷却比较也只用应用侧 UTC 值，
**绝不**与 DB ``func.now()`` 生成的 ``created_at`` 比较（否则有 8 小时偏移）。
"""

import json
import secrets
import urllib.parse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.core.logging import audit_log
from app.domains.auth.errors import (
    ERR_OAUTH_TICKET_INVALID,
    OAuthAPIError,
    OAuthEmailTakenError,
    OAuthIdentityConflictError,
    OAuthNoPasswordError,
    OAuthPasswordInvalidError,
    OAuthPasswordRequiredError,
    OAuthTicketExpiredError,
    OAuthTicketInvalidError,
    OAuthTicketLockedError,
    OAuthUpstreamError,
)
from app.domains.auth.models.oauth import (
    INTENT_BIND,
    INTENT_LOGIN,
    TICKET_STATUS_ALREADY_BOUND,
    TICKET_STATUS_BIND_CONFLICT,
    TICKET_STATUS_BIND_REQUIRED,
    TICKET_STATUS_CONFIRM_REQUIRED,
    TICKET_STATUS_LOGIN_OK,
    TICKET_STATUS_REGISTER_REQUIRED,
    OAuthIdentity,
    OAuthState,
    OAuthTicket,
)
from app.domains.auth.models.user import User
from app.domains.auth.providers import get_provider
from app.domains.auth.providers.base import (
    OAuthCodeInvalidError,
    OAuthProfile,
)
from app.domains.auth.schemas.auth import TokenResponse
from app.domains.auth.services import auth_service


def _utcnow() -> datetime:
    """应用侧 UTC naive（Q-J 时区修正，见模块 docstring）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ══════════════════ 服务层结果载体（router 层转为 response schema） ══════════════════

@dataclass(frozen=True)
class AuthorizeResult:
    authorize_url: str
    state: str
    expires_in: int


@dataclass(frozen=True)
class CallbackResult:
    """回调端点只负责 302：成功带 ticket，失败带语义化 error 码（§2.3 接口 3）。"""

    redirect_url: str


@dataclass(frozen=True)
class ResolveResult:
    status: str
    provider: Optional[str] = None
    email_masked: Optional[str] = None
    suggested_email: Optional[str] = None
    suggested_display_name: Optional[str] = None
    suggested_avatar_url: Optional[str] = None
    email_verified: Optional[bool] = None
    provider_display_name: Optional[str] = None
    reason: Optional[str] = None
    bound_at: Optional[datetime] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: Optional[str] = None


@dataclass(frozen=True)
class BindResult:
    identity: OAuthIdentity


# ══════════════════ 内部工具 ══════════════════

def mask_email(email: Optional[str]) -> str:
    """脱敏邮箱：``zhangsan@example.com`` → ``z***@example.com``。

    🔴 ``resolve`` 是未认证端点，只允许返回脱敏结果（AC-S7 / NFR-S7）。
    """
    local, _, domain = (email or "").partition("@")
    if not domain:
        return "***"
    return f"{local[:1]}***@{domain}" if local else f"***@{domain}"


def _cleanup_expired(db: Session, *, include_states: bool, include_tickets: bool) -> None:
    """§4.7 顺带清理：authorize 清 states、callback 清 tickets。

    只删过期且不在冷却中的行；不设 LIMIT（数据量极小，避免 MySQL 方言纠缠）。
    """
    now = _utcnow()
    if include_states:
        db.query(OAuthState).filter(OAuthState.expires_at < now).delete(
            synchronize_session=False
        )
    if include_tickets:
        db.query(OAuthTicket).filter(
            OAuthTicket.expires_at < now,
            (OAuthTicket.locked_until.is_(None)) | (OAuthTicket.locked_until < now),
        ).delete(synchronize_session=False)


def _load_profile(ticket_row: OAuthTicket) -> OAuthProfile:
    """从 ticket 的 profile_json 快照还原 OAuthProfile（不再触达三方）。"""
    data = json.loads(ticket_row.profile_json or "{}")
    return OAuthProfile(
        provider_uid=str(data.get("provider_uid") or ""),
        email=data.get("email"),
        email_verified=data.get("email_verified"),
        display_name=data.get("display_name"),
        avatar_url=data.get("avatar_url"),
        raw=data.get("raw") or {},
    )


def _raise_if_provider_uid_locked(db: Session, ticket_row: OAuthTicket, now: datetime) -> None:
    """E-18：对该 ``provider_uid`` 的 15 分钟冷却（跨 ticket 生效）→ 423。"""
    locked_until = db.query(func.max(OAuthTicket.locked_until)).filter(
        OAuthTicket.provider_uid == ticket_row.provider_uid,
        OAuthTicket.locked_until.isnot(None),
        OAuthTicket.locked_until > now,
    ).scalar()
    if locked_until is not None:
        retry_after = max(1, int((locked_until - now).total_seconds()))
        raise OAuthTicketLockedError(retry_after=retry_after)


def _get_valid_ticket(db: Session, ticket_value: str) -> OAuthTicket:
    """按 ticket 取行并做存在性 / 过期 / 冷却校验（消费前的公共前置）。"""
    row = db.query(OAuthTicket).filter(OAuthTicket.ticket == ticket_value).first()
    if row is None:
        raise OAuthTicketInvalidError()
    now = _utcnow()
    if row.expires_at <= now:
        raise OAuthTicketExpiredError()
    _raise_if_provider_uid_locked(db, row, now)
    return row


def _frontend_redirect(
    *,
    base: Optional[str],
    ticket: Optional[str] = None,
    status: Optional[str] = None,
    client_type: Optional[str] = None,
    provider: Optional[str] = None,
    error: Optional[str] = None,
) -> str:
    """构造回调 302 目标。

    - web：``{FRONTEND_BASE_URL}/oauth/callback?...``
    - desktop：Electron 本地回环服务地址（state 中快照的 redirect_uri）

    🔴 URL 中只允许 ticket / status / error，**严禁出现 JWT**（C-2 / AC-S8）。
    """
    if not base:
        base = f"{(settings.FRONTEND_BASE_URL or '').rstrip('/')}/oauth/callback"
    params: dict[str, str] = {}
    if error:
        params["error"] = error
        params["provider"] = provider or ""
    else:
        params["ticket"] = ticket or ""
        params["status"] = status or ""
        params["client_type"] = client_type or ""
    return f"{base}?{urllib.parse.urlencode(params)}"


def _audit_oauth_callback_failed(
    *,
    provider: Optional[str],
    reason: str,
    resource_id: Optional[str] = None,
) -> None:
    """§4.6 ``oauth_callback/failed``：state_invalid 为疑似 CSRF（WARN 语义），
    upstream_error 为三方故障（ERROR 语义）；audit_log 统一 info 落盘，
    级别语义经由 reason 字段承载。
    """
    audit_log(
        action="oauth_callback",
        outcome="failed",
        resource_type="auth",
        resource_id=resource_id,
        provider=provider or "",
        reason=reason,
    )


# ══════════════════ authorize：发起授权（建一次性 state） ══════════════════

def build_authorize_url(
    db: Session,
    *,
    provider: str,
    intent: str,
    client_type: str,
    user_id: Optional[str],
    redirect_after: Optional[str] = None,
    loopback_port: Optional[int] = None,
) -> AuthorizeResult:
    """创建一次性 state 并返回三方授权 URL（§2.3 接口 2）。

    - ``redirect_after`` 仅做防开放重定向校验后由 router 决定去留；
      T01 的 ``oauth_states`` 表无对应列，本实现不持久化（偏离已报备）。
    - ``loopback_port``：desktop（Electron RFC 8252）本地回环端口。
    """
    _cleanup_expired(db, include_states=True, include_tickets=False)
    db.commit()

    oauth = get_provider(provider)  # 未注册 / 未配置 → 404（providers 层抛出）
    state_value = secrets.token_urlsafe(32)  # 256bit 随机（C-3）
    redirect_uri = oauth.resolve_redirect_uri(client_type, loopback_port)
    expires_in = int(settings.OAUTH_STATE_TTL_SECONDS)

    db.add(
        OAuthState(
            state=state_value,
            provider=provider,
            intent=intent,
            client_type=client_type,
            user_id=user_id if intent == INTENT_BIND else None,
            redirect_uri=redirect_uri,
            expires_at=_utcnow() + timedelta(seconds=expires_in),
        )
    )
    db.commit()

    return AuthorizeResult(
        authorize_url=oauth.authorize_url(state_value, redirect_uri),
        state=state_value,
        expires_in=expires_in,
    )


# ══════════════════ callback：state 校验 → 换 token → 三路判定 → 建 ticket ══════════════════

def handle_callback(
    db: Session,
    *,
    provider: str,
    code: Optional[str],
    state: Optional[str],
    error: Optional[str],
) -> CallbackResult:
    """三方回调核心（§2.3 接口 3 / §3.1）。

    所有失败统一返回 302 + 语义化 error 码（浏览器导航场景，不返回 JSON 4xx）；
    ``state_invalid`` 与 ``state_expired`` 文案由前端映射为一致（E-4d）。
    """
    _cleanup_expired(db, include_states=False, include_tickets=True)
    db.commit()

    # ── 1. 三方回传 error（E-4a 用户取消授权等）→ 不透传原文，归并为语义化错误 ──
    if error:
        reason = "access_denied" if error == "access_denied" else "provider_unavailable"
        _audit_oauth_callback_failed(provider=provider, reason=reason)
        return CallbackResult(
            redirect_url=_frontend_redirect(base=None, error=reason, provider=provider)
        )

    if not state or not code:
        _audit_oauth_callback_failed(provider=provider, reason="state_invalid")
        return CallbackResult(
            redirect_url=_frontend_redirect(base=None, error="state_invalid", provider=provider)
        )

    # ── 2. 校验 state：存在 / 未使用 / 未过期 / provider 匹配 ──
    state_row = db.query(OAuthState).filter(OAuthState.state == state).first()
    now = _utcnow()
    if state_row is None:
        _audit_oauth_callback_failed(provider=provider, reason="state_invalid")
        return CallbackResult(
            redirect_url=_frontend_redirect(base=None, error="state_invalid", provider=provider)
        )
    if state_row.expires_at <= now:
        _audit_oauth_callback_failed(provider=provider, reason="state_expired")
        return CallbackResult(
            redirect_url=_frontend_redirect(base=None, error="state_expired", provider=provider)
        )
    if state_row.provider != provider:
        _audit_oauth_callback_failed(provider=provider, reason="state_invalid")
        return CallbackResult(
            redirect_url=_frontend_redirect(base=None, error="state_invalid", provider=provider)
        )

    # ── 3. 原子标记 used_at（一次性；rowcount=0 即重放，E-4d）──
    rowcount = (
        db.query(OAuthState)
        .filter(OAuthState.state == state, OAuthState.used_at.is_(None))
        .update({OAuthState.used_at: now}, synchronize_session=False)
    )
    db.commit()
    if rowcount == 0:
        _audit_oauth_callback_failed(provider=provider, reason="state_invalid")
        return CallbackResult(
            redirect_url=_frontend_redirect(base=None, error="state_invalid", provider=provider)
        )

    # ── 4. 换 token → 拉 profile（🔴 token 只存在于局部变量，用后即弃）──
    try:
        oauth = get_provider(provider)  # 未注册 / 未配置 → provider_disabled
        access_token = oauth.exchange_code(code, state_row.redirect_uri)
        profile = oauth.fetch_profile(access_token)
    except OAuthCodeInvalidError:
        # E-4c：code 失效 / 重复使用，与上游 502 区分
        _audit_oauth_callback_failed(provider=provider, reason="code_invalid")
        return CallbackResult(
            redirect_url=_frontend_redirect(base=None, error="code_invalid", provider=provider)
        )
    except (OAuthUpstreamError, httpx.HTTPError):
        # E-9：三方超时 / 5xx / 网络异常；严禁透传三方原始错误（NFR-U2）
        _audit_oauth_callback_failed(provider=provider, reason="upstream_error")
        return CallbackResult(
            redirect_url=_frontend_redirect(
                base=None, error="provider_unavailable", provider=provider
            )
        )
    except OAuthAPIError:
        # provider 未注册 / 未配置 → provider_disabled（authorize 阶段理论上已拦截）
        _audit_oauth_callback_failed(provider=provider, reason="provider_disabled")
        return CallbackResult(
            redirect_url=_frontend_redirect(
                base=None, error="provider_disabled", provider=provider
            )
        )
    # 🔴 此处 access_token 已无引用，生命周期终止；profile 中不含任何 token 字段

    # ── 5. 三路判定（§2.4）+ 建 ticket + 302 ──
    if state_row.intent == INTENT_BIND:
        status, ticket_user_id, normalized_email = _decide_bind_outcome(
            db, provider=provider, profile=profile, state_user_id=state_row.user_id
        )
    else:
        status, ticket_user_id, normalized_email = _decide_login_outcome(
            db, provider=provider, profile=profile
        )

    if status is None:
        # 加绑场景发起者已不存在（脏数据）：按 state 异常处理
        _audit_oauth_callback_failed(
            provider=provider, reason="state_invalid", resource_id=state_row.user_id
        )
        return CallbackResult(
            redirect_url=_frontend_redirect(base=None, error="state_invalid", provider=provider)
        )

    ticket_value = secrets.token_urlsafe(32)
    db.add(
        OAuthTicket(
            ticket=ticket_value,
            provider=provider,
            provider_uid=profile.provider_uid,
            intent=state_row.intent,
            client_type=state_row.client_type,
            status=status,
            user_id=ticket_user_id,
            profile_json=json.dumps(asdict(profile), ensure_ascii=False, default=str),
            normalized_email=normalized_email,
            expires_at=now + timedelta(seconds=int(settings.OAUTH_TICKET_TTL_SECONDS)),
        )
    )
    db.commit()

    redirect_base = (
        state_row.redirect_uri if state_row.client_type == "desktop" else None
    )
    return CallbackResult(
        redirect_url=_frontend_redirect(
            base=redirect_base,
            ticket=ticket_value,
            status=status,
            client_type=state_row.client_type,
        )
    )


def _decide_login_outcome(
    db: Session, *, provider: str, profile: OAuthProfile
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """登录意图的三路判定（§2.4 分支 1~3）。返回 ``(status, user_id, normalized_email)``。

    🔴 红线：账号归属唯一依据 ``(provider, provider_uid)``；三方 email 只用于
    区分路径 B / 路径 C，绝不自动合并（C-1）。
    """
    # [1] 身份已存在 → 路径 A：LOGIN_OK
    identity = (
        db.query(OAuthIdentity)
        .filter(
            OAuthIdentity.provider == provider,
            OAuthIdentity.provider_uid == profile.provider_uid,
        )
        .first()
    )
    if identity is not None:
        # 路径 A：更新 last_login_at / 资料快照（UTC naive，Q-J）
        identity.last_login_at = _utcnow()
        identity.provider_display_name = profile.display_name or identity.provider_display_name
        identity.provider_avatar_url = profile.avatar_url or identity.provider_avatar_url
        identity.email_verified = profile.email_verified
        identity.raw_profile_json = json.dumps(profile.raw, ensure_ascii=False, default=str)
        db.commit()
        audit_log(
            action="oauth_login",
            outcome="success",
            resource_type="oauth_identity",
            resource_id=identity.user_id,
            provider=provider,
        )
        return TICKET_STATUS_LOGIN_OK, identity.user_id, None

    # [2] 三方 email 为空 → 路径 C（E-11：邮箱留空由用户手填）
    normalized_email = auth_service.normalize_email(profile.email) if profile.email else None
    if not normalized_email:
        return TICKET_STATUS_REGISTER_REQUIRED, None, None

    # [3] email 已注册 → 路径 B：BIND_REQUIRED 🔴（必须验密码，严禁自动合并）
    # 安全红线：仅凭三方 email 与已注册用户匹配，绝不能直接下发该用户 JWT，
    # 否则攻击者可借"持有同邮箱的三方账号"实现账号接管（account takeover）。
    # 必须回到 /bind/confirm 走密码校验分支（confirm_bind 中的 🔴 红线）。
    existing_user = db.query(User).filter(User.email == normalized_email).first()
    if existing_user is not None:
        return TICKET_STATUS_BIND_REQUIRED, existing_user.id, normalized_email
    # email 未注册 → 路径 C：REGISTER_REQUIRED
    return TICKET_STATUS_REGISTER_REQUIRED, None, normalized_email


def _decide_bind_outcome(
    db: Session, *, provider: str, profile: OAuthProfile, state_user_id: Optional[str]
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """加绑意图的判定（§2.4 分支 4）。返回 ``(status, user_id, normalized_email)``。

    🔴 红线条款 4：加绑场景**不触发路径 B**——用户已持有有效 token，
    身份已确认；该身份已绑他人则直接 BIND_CONFLICT（E-2）。
    """
    if not state_user_id:
        return None, None, None
    user = db.get(User, state_user_id)
    if user is None:
        # 发起加绑的账号已不存在（脏数据）
        return None, None, None

    identity = (
        db.query(OAuthIdentity)
        .filter(
            OAuthIdentity.provider == provider,
            OAuthIdentity.provider_uid == profile.provider_uid,
        )
        .first()
    )
    if identity is not None:
        if identity.user_id == state_user_id:
            # 8a 幂等：已绑当前用户
            return TICKET_STATUS_ALREADY_BOUND, state_user_id, None
        # 8b / E-2：已绑其他账号 → 冲突 + 审计 WARN
        audit_log(
            action="oauth_bind_conflict",
            outcome="failed",
            resource_type="oauth_identity",
            resource_id=identity.user_id,
            provider=provider,
            provider_uid=profile.provider_uid,
            reason="identity_bound_to_other_user",
        )
        return TICKET_STATUS_BIND_CONFLICT, state_user_id, None

    # 未被任何账号绑定：管理员账号需二次密码确认（拍板 #8 / E-8 / Q9）
    if bool(user.is_admin):
        return TICKET_STATUS_CONFIRM_REQUIRED, state_user_id, None
    # 普通用户：以 LOGIN_OK 标记 intent=bind（§3.5），凭 ticket 调 /bind 完成绑定
    return TICKET_STATUS_LOGIN_OK, state_user_id, None


# ══════════════════ resolve：幂等读（不消费 ticket） ══════════════════

def resolve_ticket(db: Session, ticket: str) -> ResolveResult:
    """兑现 ticket 的前置状态（§2.3 接口 4）。

    - 幂等：不写库、不消费；仅过期（410）/ 无效（404）/ 冷却（423）时抛错。
    - 🔴 ``BIND_REQUIRED`` 只返回脱敏邮箱 ``email_masked``，严禁完整邮箱。
    - 🔴 ``intent=bind`` 的 ``LOGIN_OK`` 仅是"可直接绑定"标记，**不签发 token**，
      防止加绑 ticket 被当作登录凭证兑换。
    """
    row = _get_valid_ticket(db, ticket)
    profile = _load_profile(row)

    if row.status == TICKET_STATUS_LOGIN_OK:
        if row.intent == INTENT_LOGIN and row.user_id:
            tokens = auth_service.issue_token_pair(row.user_id)
            return ResolveResult(
                status=row.status,
                provider=row.provider,
                access_token=tokens.access_token,
                refresh_token=tokens.refresh_token,
                token_type=tokens.token_type,
            )
        return ResolveResult(status=row.status, provider=row.provider)

    if row.status == TICKET_STATUS_BIND_REQUIRED:
        return ResolveResult(
            status=row.status,
            provider=row.provider,
            email_masked=mask_email(row.normalized_email or profile.email),
            email_verified=profile.email_verified,
        )

    if row.status == TICKET_STATUS_REGISTER_REQUIRED:
        return ResolveResult(
            status=row.status,
            provider=row.provider,
            suggested_email=profile.email or "",
            suggested_display_name=profile.display_name or "",
            suggested_avatar_url=profile.avatar_url or "",
            email_verified=profile.email_verified,
        )

    if row.status == TICKET_STATUS_CONFIRM_REQUIRED:
        return ResolveResult(
            status=row.status,
            provider=row.provider,
            provider_display_name=profile.display_name or row.provider,
            reason="admin_bind",
        )

    if row.status == TICKET_STATUS_ALREADY_BOUND:
        return ResolveResult(
            status=row.status,
            provider=row.provider,
            bound_at=row.created_at,
        )

    if row.status == TICKET_STATUS_BIND_CONFLICT:
        return ResolveResult(status=row.status, provider=row.provider)

    # 未知状态：按无效 ticket 处理
    raise OAuthTicketInvalidError()


# ══════════════════ ticket 原子消费（🔴 必须单条 UPDATE + rowcount） ══════════════════

def _consume_ticket(db: Session, ticket_value: str) -> OAuthTicket:
    """原子抢占式消费。返回 ticket 对象；抢不到则抛异常。

    🔴 安全关键：此处必须用单条 UPDATE + rowcount 判定，
       不得改写为「SELECT 检查 consumed_at 再 UPDATE」——
       那样在并发下会出现双花（NFR-P4 要求 ≥20 并发安全）。

    Q-J：``consumed_at`` / 过期比较均使用应用侧 UTC naive 值。
    """
    now = _utcnow()
    rowcount = (
        db.query(OAuthTicket)
        .filter(
            OAuthTicket.ticket == ticket_value,
            OAuthTicket.consumed_at.is_(None),
            OAuthTicket.expires_at > now,
        )
        .update({OAuthTicket.consumed_at: now}, synchronize_session=False)
    )
    if rowcount == 0:
        raise OAuthTicketInvalidError()
    db.commit()
    return db.query(OAuthTicket).filter(OAuthTicket.ticket == ticket_value).one()


def _release_ticket(db: Session, ticket_row: OAuthTicket) -> None:
    """释放消费占用（仅用于"校验失败后允许重试"的场景：E-1b 路径 C 换邮箱重试）。"""
    ticket_row.consumed_at = None
    db.commit()


# ══════════════════ 绑定写入（含 IntegrityError → 409 / 幂等兜底） ══════════════════

def _create_identity(
    db: Session, user: User, ticket_row: OAuthTicket, profile: OAuthProfile
) -> OAuthIdentity:
    """创建绑定，依赖 DB ``UNIQUE(provider, provider_uid)`` 兜底（E-13）。

    - IntegrityError 后回滚重查：若身份已属于同一用户 → 幂等成功；
      绑在他人账号 → 409 OAUTH_IDENTITY_CONFLICT + 审计 WARN。
    """
    identity = OAuthIdentity(
        user_id=user.id,
        provider=ticket_row.provider,
        provider_uid=profile.provider_uid,
        provider_email=profile.email,  # 🔴 三方 email 仅快照，不参与账号判定
        provider_display_name=profile.display_name,
        provider_avatar_url=profile.avatar_url,
        email_verified=profile.email_verified,
        raw_profile_json=(
            json.dumps(profile.raw, ensure_ascii=False, default=str) if profile.raw else None
        ),
    )
    db.add(identity)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(OAuthIdentity)
            .filter(
                OAuthIdentity.provider == ticket_row.provider,
                OAuthIdentity.provider_uid == profile.provider_uid,
            )
            .first()
        )
        if existing is not None and existing.user_id == user.id:
            return existing  # 并发幂等：绑定已存在且属于当前用户
        audit_log(
            action="oauth_bind_conflict",
            outcome="failed",
            resource_type="oauth_identity",
            resource_id=existing.user_id if existing is not None else profile.provider_uid,
            provider=ticket_row.provider,
            provider_uid=profile.provider_uid,
            reason="identity_bound_to_other_user",
        )
        raise OAuthIdentityConflictError()
    db.refresh(identity)
    return identity


def _register_password_failure(db: Session, ticket_row: OAuthTicket) -> None:
    """路径 B 密码失败处理（E-18）：失败计数 → 达阈值锁定 provider_uid 并作废 ticket。

    - 未达阈值：**释放消费占用**（``consumed_at=None``），ticket 仍可重试；
      计数保留在行上，直至 TTL 过期或被锁定。
    - 达阈值：写 ``locked_until``（UTC naive）并**保持 consumed**（作废）。
    - 两次分支均记 ``oauth_bind_failed/failed`` WARN 审计（疑似账号接管尝试）。
    """
    now = _utcnow()
    ticket_row.failed_attempts = (ticket_row.failed_attempts or 0) + 1
    max_attempts = int(settings.OAUTH_BIND_MAX_ATTEMPTS)
    resource_id = ticket_row.user_id or ticket_row.provider_uid
    if ticket_row.failed_attempts >= max_attempts:
        ticket_row.locked_until = now + timedelta(
            seconds=int(settings.OAUTH_BIND_COOLDOWN_SECONDS)
        )
        ticket_row.consumed_at = now  # 作废 ticket
        db.commit()
        audit_log(
            action="oauth_bind_failed",
            outcome="failed",
            resource_type="oauth_identity",
            resource_id=resource_id,
            provider=ticket_row.provider,
            reason="lockout",
        )
    else:
        ticket_row.consumed_at = None  # 释放占用，允许重试
        db.commit()
        audit_log(
            action="oauth_bind_failed",
            outcome="failed",
            resource_type="oauth_identity",
            resource_id=resource_id,
            provider=ticket_row.provider,
            reason="bad_password",
            attempts=ticket_row.failed_attempts,
        )


# ══════════════════ 路径 B 终态：confirm_bind（🔴 安全红线核心） ══════════════════

def confirm_bind(db: Session, ticket: str, password: str) -> TokenResponse:
    """路径 B 确认绑定（§2.3 接口 6 / §3.3）。

    🔴 红线（T03 负向用例逐条守护）：
    1. 密码验证分支**无任何绕过路径**——user 查不到与密码错误返回
       **逐字节一致**的 ``401 OAUTH_PASSWORD_INVALID``（AC-S7）。
    2. 消费为单条 ``UPDATE ... WHERE consumed_at IS NULL`` + rowcount。
    3. 本函数仅处理 ``intent=login`` 且 ``status=BIND_REQUIRED`` 的 ticket；
       加绑走 ``bind_identity``。
    """
    ticket_row = _get_valid_ticket(db, ticket)
    if ticket_row.status != TICKET_STATUS_BIND_REQUIRED:
        raise OAuthAPIError(
            status_code=400,
            code=ERR_OAUTH_TICKET_INVALID,
            message="登录凭证状态不支持该操作",
        )

    # 原子抢占消费：防并发双花（C-4）；失败（重放/过期）→ 404
    claimed = _consume_ticket(db, ticket)

    user: Optional[User] = None
    if claimed.user_id:
        user = db.get(User, claimed.user_id)
    if user is None and claimed.normalized_email:
        user = db.query(User).filter(User.email == claimed.normalized_email).first()

    try:
        # 🔴 账号不存在与密码错误：同一异常类 → 同码同文案，响应体逐字节一致
        if user is None:
            raise OAuthPasswordInvalidError()
        if not auth_service.verify_password(password, user.hashed_password):
            raise OAuthPasswordInvalidError()
    except OAuthPasswordInvalidError:
        # E-18：失败计数 / 锁定；未达阈值时释放占用以便重试
        _register_password_failure(db, claimed)
        raise

    profile = _load_profile(claimed)
    _create_identity(db, user, claimed, profile)
    audit_log(
        action="oauth_bind",
        outcome="success",
        resource_type="oauth_identity",
        resource_id=user.id,
        provider=claimed.provider,
        reason=claimed.provider,
    )
    return auth_service.issue_token_pair(user)


# ══════════════════ 加绑终态：bind_identity（已登录态 / 管理员二次确认） ══════════════════

def bind_identity(db: Session, ticket: str, password: Optional[str]) -> BindResult:
    """加绑终态（§2.3 接口 5 / §3.5）。

    - 普通用户（``LOGIN_OK`` + intent=bind）：无需密码（拍板 #8）。
    - 管理员（``CONFIRM_REQUIRED``）：🔴 必须传密码并验证通过（E-8 / Q9）。
    - ``ALREADY_BOUND``：幂等返回成功。
    - ``BIND_CONFLICT`` 状态的 ticket 在回调阶段已审计 WARN，此处拒绝绑定。
    """
    ticket_row = _get_valid_ticket(db, ticket)
    if ticket_row.intent != INTENT_BIND:
        raise OAuthAPIError(
            status_code=400,
            code=ERR_OAUTH_TICKET_INVALID,
            message="登录凭证状态不支持该操作",
        )

    claimed = _consume_ticket(db, ticket)
    profile = _load_profile(claimed)

    if claimed.status == TICKET_STATUS_ALREADY_BOUND:
        existing = (
            db.query(OAuthIdentity)
            .filter(
                OAuthIdentity.provider == claimed.provider,
                OAuthIdentity.provider_uid == profile.provider_uid,
            )
            .first()
        )
        if existing is not None:
            return BindResult(identity=existing)
        # 脏数据兜底：按可绑定状态继续
        claimed.status = TICKET_STATUS_LOGIN_OK

    user: Optional[User] = db.get(User, claimed.user_id) if claimed.user_id else None

    if claimed.status == TICKET_STATUS_CONFIRM_REQUIRED:
        # 🔴 管理员加绑：必须二次密码确认，无任何绕过路径
        if not password:
            raise OAuthPasswordRequiredError()
        if user is None or not auth_service.verify_password(password, user.hashed_password):
            raise OAuthPasswordInvalidError()
    elif claimed.status == TICKET_STATUS_LOGIN_OK:
        if user is None:
            raise OAuthTicketInvalidError()
    else:
        # BIND_REQUIRED / REGISTER_REQUIRED / BIND_CONFLICT 等状态不可用于加绑
        raise OAuthAPIError(
            status_code=400,
            code=ERR_OAUTH_TICKET_INVALID,
            message="登录凭证状态不支持该操作",
        )

    identity = _create_identity(db, user, claimed, profile)
    audit_log(
        action="oauth_bind",
        outcome="success",
        resource_type="oauth_identity",
        resource_id=user.id,
        provider=claimed.provider,
        reason=(
            f"{claimed.provider};admin_bind_confirmed"
            if claimed.status == TICKET_STATUS_CONFIRM_REQUIRED
            else claimed.provider
        ),
    )
    return BindResult(identity=identity)


# ══════════════════ 路径 C 终态：complete_register（手填优先） ══════════════════

def complete_register(
    db: Session, ticket: str, email: str, password: str, display_name: str
) -> TokenResponse:
    """路径 C 补全注册（§2.3 接口 7 / §3.4）。

    🔴 手填优先（拍板 #6 / E-1）：以用户手填 ``email`` 建号；
    三方 email 仅写 ``provider_email`` 快照，不参与任何账号判定。

    校验顺序（严格按 §2.3）：ticket 有效性 → status → normalize → 白名单 →
    邮箱唯一性（409 且 **ticket 不消费**，E-1b）→ 原子消费 → 建号+绑定同一事务。
    """
    ticket_row = _get_valid_ticket(db, ticket)
    if ticket_row.status != TICKET_STATUS_REGISTER_REQUIRED:
        raise OAuthAPIError(
            status_code=400,
            code=ERR_OAUTH_TICKET_INVALID,
            message="登录凭证状态不支持该操作",
        )

    # [E-12] 归一化 + [拍板 #4] 域名白名单（留空 = 不限制）
    normalized = auth_service.normalize_email(email)
    auth_service.assert_email_allowed(normalized)

    # E-1b：唯一性前置校验失败 → 409 且不消费 ticket（用户可换邮箱重试）
    if db.query(User.id).filter(User.email == normalized).first() is not None:
        raise OAuthEmailTakenError()

    claimed = _consume_ticket(db, ticket)

    try:
        user_count = db.query(User).count()
        user = User(
            email=normalized,
            hashed_password=auth_service.hash_password(password),
            display_name=display_name,
            is_admin=user_count == 0,  # 与 /auth/register 相同的 bootstrap 规则
        )
        db.add(user)
        db.flush()  # 取得 user.id，保证建号与建绑定同事务提交（AC-5）

        profile = _load_profile(claimed)
        db.add(
            OAuthIdentity(
                user_id=user.id,
                provider=claimed.provider,
                provider_uid=profile.provider_uid,
                provider_email=profile.email,  # 🔴 仅快照
                provider_display_name=profile.display_name,
                provider_avatar_url=profile.avatar_url,
                email_verified=profile.email_verified,
                raw_profile_json=(
                    json.dumps(profile.raw, ensure_ascii=False, default=str)
                    if profile.raw
                    else None
                ),
            )
        )
        db.commit()
    except IntegrityError:
        # E-13：并发下唯一约束兜底（同邮箱并发注册 / 身份被并发绑定）
        db.rollback()
        _release_ticket(db, claimed)  # 释放占用，允许重试
        if db.query(User.id).filter(User.email == normalized).first() is not None:
            raise OAuthEmailTakenError()
        raise OAuthIdentityConflictError()

    db.refresh(user)
    audit_log(
        action="oauth_register",
        outcome="success",
        resource_type="oauth_identity",
        resource_id=user.id,
        provider=claimed.provider,
        reason=claimed.provider,
    )
    return auth_service.issue_token_pair(user)


# ══════════════════ 身份列表与解绑 ══════════════════

def list_identities(db: Session, user: User) -> list[OAuthIdentity]:
    """当前用户已绑定身份（设置页展示）。"""
    return (
        db.query(OAuthIdentity)
        .filter(OAuthIdentity.user_id == user.id)
        .order_by(OAuthIdentity.created_at)
        .all()
    )


def unbind_identity(db: Session, user: User, identity_id: str) -> None:
    """解绑指定身份（§3.6）。

    - 不属于当前用户 → 404（不返回 403，避免泄漏资源存在性）。
    - E-6b 防御：账号无密码（脏数据）→ 400 + WARN 审计。
    - E-6：允许解绑最后一个身份（D-3 保证密码恒存在）。
    """
    identity = (
        db.query(OAuthIdentity)
        .filter(OAuthIdentity.id == identity_id, OAuthIdentity.user_id == user.id)
        .first()
    )
    if identity is None:
        raise HTTPException(status_code=404, detail="绑定关系不存在")
    if not (user.hashed_password or "").strip():
        audit_log(
            action="oauth_unbind",
            outcome="failed",
            resource_type="oauth_identity",
            resource_id=identity.id,
            username=user.email,
            reason="no_password",
        )
        raise OAuthNoPasswordError()
    provider = identity.provider
    db.delete(identity)
    db.commit()
    audit_log(
        action="oauth_unbind",
        outcome="success",
        resource_type="oauth_identity",
        resource_id=identity.id,
        username=user.email,
        reason=provider,
    )
