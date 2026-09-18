"""
任务会话分享 DTO：管理侧（登录用户）与公开侧（分享凭证）请求/响应。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum as PyEnum
from typing import List, Optional

from pydantic import BaseModel, Field


# ── 管理侧：创建 / 列表 / 撤销 ──


class SessionShareCreate(BaseModel):
    mode: str = Field(pattern="^(READ|INPUT)$")
    # 有效期天数：1 / 7 / 30（第一版不提供永久）
    expires_in_days: int = Field(ge=1, le=30)
    instruction_text: Optional[str] = Field(default=None, max_length=2000)


class SessionShareCreated(BaseModel):
    id: str
    mode: str
    expires_at: datetime
    instruction_text: Optional[str] = None
    session_generation: int
    # 原始分享令牌，只在创建成功时返回一次
    share_token: str
    # 服务端拼好的公开页地址（fragment 携带令牌）
    share_url: str


class SessionShareItem(BaseModel):
    id: str
    mode: str
    instruction_text: Optional[str] = None
    session_generation: int
    expires_at: datetime
    revoked_at: Optional[datetime] = None
    revoke_reason: Optional[str] = None
    created_at: datetime
    status: str  # ACTIVE / EXPIRED / REVOKED / SESSION_INVALID
    # 明文令牌 + 完整链接（与 workspace_invite_links 对齐：列表随时可复制）；
    # 迁移前的旧行可能没有明文（token 为 NULL）
    token: Optional[str] = None
    share_url: Optional[str] = None


class SessionShareListResponse(BaseModel):
    items: List[SessionShareItem]
    total: int


# ── 管理侧：待采纳输入 ──


class ShareSuggestionAction(str, PyEnum):
    EDIT = "edit"
    ADOPT = "adopt"
    DISMISS = "dismiss"


class ShareSuggestionPatch(BaseModel):
    action: ShareSuggestionAction
    expected_version: int = Field(ge=1)
    edited_content: Optional[str] = Field(default=None, max_length=20000)


class ShareSuggestionItem(BaseModel):
    id: str
    task_id: str
    session_generation: int
    visitor_id: str
    sender_user_id: Optional[str] = None
    display_name: Optional[str] = None
    original_content: str
    edited_content: Optional[str] = None
    status: str
    version: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    adopted_at: Optional[datetime] = None
    # 采纳 / 填入草稿时使用的有效内容（edited_content 优先）
    effective_content: str


class ShareSuggestionListResponse(BaseModel):
    items: List[ShareSuggestionItem]
    next_cursor: Optional[str] = None


# ── 公开侧：exchange / resolve ──


class ShareExchangeRequest(BaseModel):
    token: str = Field(min_length=16, max_length=128)


class ShareExchangeResponse(BaseModel):
    view_mode: str  # NORMAL_REDIRECT / READ_ONLY / INPUT_ONLY
    access_token: str
    access_expires_at: datetime
    visitor_id: str
    # READ_ONLY：分享 id（公开实时通道 /ws/public/session-shares/{share_id} 用）
    share_id: str
    task_name: Optional[str] = None
    instruction_text: Optional[str] = None
    expires_at: datetime
    # NORMAL_REDIRECT：服务端生成的站内目标（不接受任意 return_url）
    redirect_path: Optional[str] = None


class ShareResolveResponse(BaseModel):
    view_mode: str
    task_name: Optional[str] = None
    instruction_text: Optional[str] = None
    expires_at: datetime
    redirect_path: Optional[str] = None


# ── 公开侧：历史（READ 模式，白名单投影） ──


class SharedHistoryMessage(BaseModel):
    message_id: str
    role: str
    content: str
    safe_message_type: str
    created_at: datetime
    safe_card_summary: Optional[str] = None


class SharedHistoryResponse(BaseModel):
    messages: List[SharedHistoryMessage]
    has_more: bool
    next_cursor: Optional[str] = None


# ── 公开侧：提交输入（INPUT 模式） ──


class ShareSuggestionSubmit(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    display_name: Optional[str] = Field(default=None, max_length=100)
    client_submission_id: str = Field(min_length=1, max_length=128)


class ShareSuggestionReceipt(BaseModel):
    submission_id: str
    client_submission_id: str
    created_at: datetime
    status: str
