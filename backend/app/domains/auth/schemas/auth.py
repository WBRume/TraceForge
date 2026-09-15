"""
认证相关 Pydantic Schemas
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=100)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefresh(BaseModel):
    refresh_token: str


class UserAvatarUpdate(BaseModel):
    avatar_svg: str = Field(..., min_length=1, max_length=20000)


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    avatar_url: Optional[str] = None
    avatar_svg: Optional[str] = None
    is_admin: bool = False
    created_at: datetime
    # OAuth 增量（接口 11 / GET /auth/me）：已绑定的三方 provider 名列表，如 ["github"]。
    # 纯增量字段，现有前端无感；由 router 从 current_user.oauth_identities 组装。
    bound_providers: list[str] = []

    model_config = {"from_attributes": True}
