"""团队会话阅读进度 DTO（严格合同，未知字段拒绝）。

所有 BIGINT 序号 / epoch / revision 对外使用十进制字符串（第 8 节合同）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ReadingReceiptEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_key: str = Field(min_length=1, max_length=100)
    change_seq: str = Field(pattern="^[0-9]+$")


class ReadingResumePosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1, max_length=36)
    content_seq: str = Field(pattern="^[0-9]+$")
    offset_ratio: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    expected_revision: str = Field(pattern="^[0-9]+$")


class ReadingReceiptsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reading_epoch: str = Field(pattern="^[0-9]+$")
    items: List[ReadingReceiptEntry] = Field(default_factory=list, max_length=50)
    resume: Optional[ReadingResumePosition] = None


class ReadingSessionOpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadingAcknowledgementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reading_epoch: str = Field(pattern="^[0-9]+$")
    window_token: str = Field(min_length=1, max_length=4096)
    scope: Literal["all-through-window"]


class ReadingCompactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reading_epoch: str = Field(pattern="^[0-9]+$")


class ReadingUnreadCount(BaseModel):
    value: int
    relation: Literal["eq", "gte"]


class ReadingResumeSnapshot(BaseModel):
    message_id: str
    order_key: Optional[str] = None
    content_seq: Optional[str] = None
    offset_ratio: Optional[float] = None
    revision: str
    updated_at: Optional[str] = None


class ReadingProgressState(BaseModel):
    initialized: bool
    task_id: str
    reading_epoch: str
    baseline_seq: Optional[str] = None
    read_frontier_seq: Optional[str] = None
    latest_change_seq: str
    state_revision: Optional[str] = None
    has_unread: Optional[bool] = None
    unread_count: Optional[ReadingUnreadCount] = None
    compact_pending: Optional[bool] = None
    resume: Optional[ReadingResumeSnapshot] = None
    reading_ready: Optional[bool] = None


class ReadingSessionOpened(BaseModel):
    state: ReadingProgressState
    window_token: str


class ReadingReceiptResponse(BaseModel):
    state: ReadingProgressState
    accepted_items: List[Dict[str, str]]
    skipped_items: List[Dict[str, str]]
    resume_applied: bool
    compact_pending: bool


class ReadingCompactResponse(BaseModel):
    state: ReadingProgressState
    advanced: bool
    compact_pending: bool


class ReadingAcknowledgementResponse(BaseModel):
    state: ReadingProgressState
    applied_upper_seq: str


class ReadingItemIdentity(BaseModel):
    message_id: str
    item_key: str
    change_seq: str
    kind: str
    active: bool


class ReadingItemsResponse(BaseModel):
    items: List[ReadingItemIdentity]
