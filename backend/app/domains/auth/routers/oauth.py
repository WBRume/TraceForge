"""
OAuth 三方登录路由（B-12 / T02，9 端点，对应设计文档 §2.3 契约）。

1. GET    /auth/oauth/providers                    已启用 provider 列表
2. GET    /auth/oauth/{provider}/authorize          返回三方授权 URL（intent=bind 需 JWT）
3. GET    /auth/oauth/{provider}/callback           三方回调，302 回前端携带 ticket
4. POST   /auth/oauth/resolve                       幂等读 ticket 前置状态
5. POST   /auth/oauth/bind                          加绑终态（已登录态 ticket）
6. POST   /auth/oauth/bind/confirm                  🔴 路径 B 终态（ticket + password）
7. POST   /auth/oauth/register                      路径 C 终态（手填优先）
8. GET    /auth/oauth/identities                    当前用户已绑定身份（需 JWT）
9. DELETE /auth/oauth/identities/{identity_id}      解绑（需 JWT）

所有 handler 均为同步 ``def``（K-10）；判定逻辑全部在
``services/oauth_service.py``，本文件只做参数搬运与响应组装。
"""

from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.security.utils import get_authorization_scheme_param
from jose import JWTError
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.domains.auth.errors import AuthRequiredError
from app.domains.auth.models.user import User
from app.domains.auth.providers import list_enabled_providers
from app.domains.auth.schemas.oauth import (
    AuthorizeParams,
    AuthorizeResponse,
    BindConfirmResponse,
    BindResultResponse,
    IdentityListResponse,
    OAuthBindConfirmRequest,
    OAuthBindRequest,
    OAuthIdentityResponse,
    OAuthRegisterRequest,
    OAuthRegisterResponse,
    ProviderListResponse,
    ResolveResponse,
    TicketResolveRequest,
)
from app.domains.auth.services import auth_service, oauth_service

router = APIRouter(prefix="/auth/oauth", tags=["OAuth"])


def get_optional_current_user(
    request: Request, db: Session = Depends(get_db)
) -> Optional[User]:
    """可选认证：有合法 Bearer token 则返回用户，否则返回 None。

    供 authorize 端点区分 intent=login（匿名可用）与 intent=bind（需 JWT → 401 AUTH_REQUIRED）。
    """
    authorization = request.headers.get("Authorization") or ""
    scheme, token = get_authorization_scheme_param(authorization)
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        payload = auth_service.decode_token(token, expected_type="access")
    except JWTError:
        return None
    user_id = str(payload.get("sub") or "").strip()
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


def _validate_redirect_after(raw: Optional[str]) -> Optional[str]:
    """防开放重定向（§2.3 接口 2）：仅接受站内相对路径。

    禁止 ``//`` 开头（协议相对 URL）、禁止含 ``://`` 的绝对 URL；
    非法值静默丢弃（不报错，避免泄露校验规则细节）。
    """
    if not raw:
        return None
    value = raw.strip()
    if not value.startswith("/") or value.startswith("//") or "://" in value:
        return None
    return value


# ── 1. GET /providers ──
@router.get("/providers", response_model=ProviderListResponse)
def list_providers():
    """已启用 provider 列表；未配置 client_id 的不出现在返回中（NFR-M2）。"""
    return ProviderListResponse(providers=list_enabled_providers())


# ── 2. GET /{provider}/authorize ──
@router.get("/{provider}/authorize", response_model=AuthorizeResponse)
def authorize(
    provider: str,
    params: AuthorizeParams = Depends(),
    loopback_port: Optional[int] = Query(
        default=None, ge=1, le=65535, description="Electron 本地回环端口（client_type=desktop）"
    ),
    current_user: Optional[User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db),
):
    """返回三方授权 URL。intent=bind 需有效 JWT（401 AUTH_REQUIRED）。"""
    user_id = None
    if params.intent == "bind":
        if current_user is None:
            raise AuthRequiredError()
        user_id = current_user.id
    result = oauth_service.build_authorize_url(
        db,
        provider=provider,
        intent=params.intent,
        client_type=params.client_type,
        user_id=user_id,
        redirect_after=_validate_redirect_after(params.redirect_after),
        loopback_port=loopback_port,
    )
    return AuthorizeResponse(
        authorize_url=result.authorize_url,
        state=result.state,
        expires_in=result.expires_in,
    )


# ── 3. GET /{provider}/callback ──
@router.get("/{provider}/callback", response_class=RedirectResponse)
def callback(
    provider: str,
    code: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """三方回调：所有失败统一 302 + 语义化 error 码（浏览器导航，不返回 JSON 4xx）。

    🔴 302 Location 中只有 ticket / status / error，绝无 JWT。
    """
    result = oauth_service.handle_callback(
        db, provider=provider, code=code, state=state, error=error
    )
    return RedirectResponse(result.redirect_url, status_code=302)


# ── 4. POST /resolve ──
@router.post("/resolve", response_model=ResolveResponse)
def resolve(payload: TicketResolveRequest, db: Session = Depends(get_db)):
    """幂等读：不消费 ticket，可重复调用；🔴 BIND_REQUIRED 只回脱敏邮箱。"""
    result = oauth_service.resolve_ticket(db, payload.ticket)
    return ResolveResponse(**asdict(result))


# ── 5. POST /bind ──
@router.post("/bind", response_model=BindResultResponse)
def bind(payload: OAuthBindRequest, db: Session = Depends(get_db)):
    """加绑终态：用户身份来自 state 中记录的 user_id（ticket 由 intent=bind 回调产生）。"""
    result = oauth_service.bind_identity(db, payload.ticket, payload.password)
    return BindResultResponse(
        status="BOUND",
        identity=OAuthIdentityResponse.model_validate(result.identity),
    )


# ── 6. POST /bind/confirm 🔴 ──
@router.post("/bind/confirm", response_model=BindConfirmResponse)
def bind_confirm(payload: OAuthBindConfirmRequest, db: Session = Depends(get_db)):
    """路径 B 终态：ticket + password → 绑定并登录。

    🔴 密码错误与账号不存在的响应体逐字节一致（401 OAUTH_PASSWORD_INVALID）。
    """
    tokens = oauth_service.confirm_bind(db, payload.ticket, payload.password)
    return BindConfirmResponse(status="BOUND", **tokens.model_dump())


# ── 7. POST /register ──
@router.post("/register", response_model=OAuthRegisterResponse)
def oauth_register(payload: OAuthRegisterRequest, db: Session = Depends(get_db)):
    """路径 C 终态：🔴 手填优先（拍板 #6），以手填 email 建号；三方 email 仅快照。"""
    tokens = oauth_service.complete_register(
        db, payload.ticket, payload.email, payload.password, payload.display_name
    )
    return OAuthRegisterResponse(status="REGISTERED", **tokens.model_dump())


# ── 8. GET /identities ──
@router.get("/identities", response_model=IdentityListResponse)
def list_identities(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """当前用户已绑定身份列表 + 当前启用的 provider（前端渲染"可绑定"按钮）。"""
    identities = oauth_service.list_identities(db, current_user)
    return IdentityListResponse(
        identities=[OAuthIdentityResponse.model_validate(i) for i in identities],
        available_providers=[p.name for p in list_enabled_providers()],
    )


# ── 9. DELETE /identities/{identity_id} ──
@router.delete("/identities/{identity_id}")
def unbind_identity(
    identity_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """解绑指定身份；不属于当前用户返回 404（不返回 403，避免泄漏存在性）。"""
    oauth_service.unbind_identity(db, current_user, identity_id)
    return {"status": "UNBOUND"}
