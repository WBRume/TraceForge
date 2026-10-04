"""团队会话阅读进度 DTO（严格合同，未知字段拒绝）。

所有 BIGINT 序号 / epoch / revision 对外使用十进制字符串（第 8 节合同）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReadingReceiptEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_key: str = Field(min_length=1, max_length=100)
    change_seq: str = Field(pattern="^[0-9]+$")


class ReadingResumePosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1, max_length=36)
    content_seq: str = Field(pattern="^[0-9]+$")
    offset_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    expected_revision: str = Field(pattern="^[0-9]+$")


class ReadingReceiptsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reading_epoch: str = Field(pattern="^[0-9]+$")
    items: list[ReadingReceiptEntry] = Field(default_factory=list, max_length=50)
    resume: ReadingResumePosition | None = None


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
    order_key: str | None = None
    content_seq: str | None = None
    offset_ratio: float | None = None
    revision: str
    updated_at: str | None = None


class ReadingProgressState(BaseModel):
    initialized: bool
    task_id: str
    reading_epoch: str
    baseline_seq: str | None = None
    read_frontier_seq: str | None = None
    latest_change_seq: str
    state_revision: str | None = None
    has_unread: bool | None = None
    unread_count: ReadingUnreadCount | None = None
    compact_pending: bool | None = None
    resume: ReadingResumeSnapshot | None = None
    reading_ready: bool | None = None


class ReadingSessionOpened(BaseModel):
    state: ReadingProgressState
    window_token: str


class ReadingReceiptResponse(BaseModel):
    state: ReadingProgressState
    accepted_items: list[dict[str, str]]
    skipped_items: list[dict[str, str]]
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
    items: list[ReadingItemIdentity]
