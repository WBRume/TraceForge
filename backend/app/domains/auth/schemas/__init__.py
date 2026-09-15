"""
认证域 Pydantic Schemas 统一导出。

新增 OAuth schemas 在此导出（B-06），供 routers / services / 测试统一引用。
"""

from app.domains.auth.schemas.auth import (
    TokenRefresh,
    TokenResponse,
    UserAvatarUpdate,
    UserLogin,
    UserRegister,
    UserResponse,
)
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
    ProviderInfo,
    ProviderListResponse,
    ResolveResponse,
    TicketResolveRequest,
)

__all__ = [
    # auth
    "TokenRefresh",
    "TokenResponse",
    "UserAvatarUpdate",
    "UserLogin",
    "UserRegister",
    "UserResponse",
    # oauth
    "AuthorizeParams",
    "AuthorizeResponse",
    "BindConfirmResponse",
    "BindResultResponse",
    "IdentityListResponse",
    "OAuthBindConfirmRequest",
    "OAuthBindRequest",
    "OAuthIdentityResponse",
    "OAuthRegisterRequest",
    "OAuthRegisterResponse",
    "ProviderInfo",
    "ProviderListResponse",
    "ResolveResponse",
    "TicketResolveRequest",
]
