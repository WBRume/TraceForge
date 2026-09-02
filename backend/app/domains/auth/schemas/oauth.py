"""
OAuth 三方登录 Pydantic Schemas（对应设计文档 §2.3 接口契约）。

所有 schema 仅做数据搬运与基础校验；账号判定逻辑集中在
``services/oauth_service.py``（T02），不得前移到 schema 层。
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.domains.auth.schemas.auth import TokenResponse

# ── ticket status 常量（与 models/oauth.py 保持同一组值；schema 层引用避免循环导入）──
from app.domains.auth.models.oauth import (  # noqa: F401
    TICKET_STATUS_ALREADY_BOUND,
    TICKET_STATUS_BIND_CONFLICT,
    TICKET_STATUS_BIND_REQUIRED,
    TICKET_STATUS_CONFIRM_REQUIRED,
    TICKET_STATUS_LOGIN_OK,
    TICKET_STATUS_REGISTER_REQUIRED,
)


# ══════════════════ 接口 1：GET /auth/oauth/providers ══════════════════

class ProviderInfo(BaseModel):
    """已启用 provider 的展示信息（登录页动态渲染用）。"""

    name: str
    display_name: str
    authorize_path: str
    icon_key: str


class ProviderListResponse(BaseModel):
    """未配置 client_id 的 provider 不会出现在列表中（NFR-M2）；空列表时前端隐藏三方按钮区。"""

    providers: list[ProviderInfo]


# ══════════════════ 接口 2：GET /auth/oauth/{provider}/authorize ══════════════════

class AuthorizeParams(BaseModel):
    """authorize 端点的 query 参数（FastAPI 以 Depends 形式消费）。"""

    intent: str = Field(default="login", pattern="^(login|bind)$")
    client_type: str = Field(default="web", pattern="^(web|desktop)$")
    # 授权完成后前端应落地的站内相对路径；禁止 // 与绝对 URL（防开放重定向，router 层校验）
    redirect_after: Optional[str] = None


class AuthorizeResponse(BaseModel):
    """前端拿到 authorize_url 后 window.location.href 跳转；state 校验是服务端职责。"""

    authorize_url: str
    state: str
    expires_in: int


# ══════════════════ 接口 4：POST /auth/oauth/resolve（幂等读） ══════════════════

class TicketResolveRequest(BaseModel):
    ticket: str = Field(..., min_length=1, max_length=64)


class ResolveResponse(BaseModel):
    """按 status 分支的统一响应体。

    - LOGIN_OK：access_token / refresh_token / token_type 有值
    - BIND_REQUIRED：🔴 只回脱敏邮箱 email_masked，严禁完整邮箱（AC-S7 / NFR-S7）
    - REGISTER_REQUIRED：suggested_email / suggested_display_name / suggested_avatar_url 预填
    - CONFIRM_REQUIRED：reason="admin_bind"
    - ALREADY_BOUND：bound_at
    - BIND_CONFLICT：仅 provider
    """

    status: str
    provider: Optional[str] = None
    email_masked: Optional[str] = None
    suggested_email: Optional[str] = None
    suggested_display_name: Optional[str] = None
    suggested_avatar_url: Optional[str] = None
    email_verified: Optional[bool] = None
    # CONFIRM_REQUIRED（管理员加绑）：reason="admin_bind" + provider 展示名（§2.3 接口 4 契约）
    provider_display_name: Optional[str] = None
    reason: Optional[str] = None
    bound_at: Optional[datetime] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: Optional[str] = None


# ══════════════════ 接口 5/6/7：终态请求体 ══════════════════

class OAuthBindRequest(BaseModel):
    """加绑终态（已登录态，设置页）。管理员账号加绑必须传 password（拍板 #8）。"""

    ticket: str = Field(..., min_length=1, max_length=64)
    password: Optional[str] = Field(default=None, max_length=128)


class OAuthBindConfirmRequest(BaseModel):
    """路径 B 确认绑定（未登录态）。🔴 必须验证密码，错误响应与"账号不存在"不可区分。"""

    ticket: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class OAuthRegisterRequest(BaseModel):
    """路径 C 补全注册。🔴 手填优先（拍板 #6）：email 以用户手填为准建号。

    校验顺序见 §2.3 接口 7：原子消费 ticket → status 校验 → normalize →
    格式 → 域名白名单 → 密码长度 → 邮箱唯一性 → 建号绑定。
    """

    ticket: str = Field(..., min_length=1, max_length=64)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)  # 与 UserRegister 一致
    display_name: str = Field(..., min_length=1, max_length=100)


# ══════════════════ 接口 5/6/7：终态响应体 ══════════════════

class BindResultResponse(BaseModel):
    """加绑成功响应。"""

    status: str = "BOUND"
    identity: "OAuthIdentityResponse"


class BindConfirmResponse(TokenResponse):
    """路径 B 成功：绑定 + 登录（含 token 对）。"""

    status: str = "BOUND"


class OAuthRegisterResponse(TokenResponse):
    """路径 C 成功：建号 + 绑定 + 登录（含 token 对）。"""

    status: str = "REGISTERED"


# ══════════════════ 接口 8/9：身份列表与解绑 ══════════════════

class OAuthIdentityResponse(BaseModel):
    """已绑定身份（设置页展示）。不暴露 provider_uid 明文之外的敏感字段。"""

    id: str
    provider: str
    provider_display_name: Optional[str] = None
    provider_email: Optional[str] = None
    provider_avatar_url: Optional[str] = None
    email_verified: Optional[bool] = None
    created_at: datetime
    last_login_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class IdentityListResponse(BaseModel):
    """当前用户已绑定身份列表 + 当前启用的 provider（前端渲染"可绑定"按钮）。"""

    identities: list[OAuthIdentityResponse]
    available_providers: list[str]


# BindResultResponse 对 OAuthIdentityResponse 的前向引用在此解析
BindResultResponse.model_rebuild()
