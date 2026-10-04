"""Schemas for task context-window token attribution."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ContextTokenSnapshotResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    ai_job_id: str | None = None
    session_id: str | None = None
    model: str | None = None
    agent_backend: str | None = None
    status: str
    total_cost_usd: float | None = None
    duration_ms: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ContextProviderTokensResponse(BaseModel):
    available: bool = False
    status: str = "unavailable"
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None
    thinking_tokens: int | None = None
    tool_io_tokens: int | None = None
    total_tokens: int | None = None


class ContextTokenCategorySummary(BaseModel):
    category: str
    segment_count: int = 0
    provider_tokens: int | None = None
    attribution_units: int = 0
    char_count: int = 0
    byte_count: int = 0
    percentage: float = 0.0


class ContextTokenSegmentResponse(BaseModel):
    id: str
    snapshot_id: str
    category: str
    provider_tokens: int | None = None
    attribution_units: int = 0
    char_count: int = 0
    byte_count: int = 0
    source_kind: str
    source_ref_id: str | None = None
    chat_message_id: str | None = None
    asset_id: str | None = None
    asset_version_id: str | None = None
    skill_runtime_event_id: str | None = None
    tool_use_id: str | None = None
    content_hash: str | None = None
    locator_json: dict[str, Any] | None = None
    title: str | None = None
    preview: str | None = None
    metadata_json: dict[str, Any] | None = None
    created_at: datetime | None = None


class ContextCompactionReference(BaseModel):
    turn_index: int | None = None
    ai_job_id: str | None = None
    chat_message_id: str | None = None
    log_id: str | None = None
    label: str | None = None


class ContextCompactionRiskRef(BaseModel):
    id: str
    category: str
    source_kind: str
    source_ref_id: str | None = None
    chat_message_id: str | None = None
    asset_id: str | None = None
    skill_runtime_event_id: str | None = None
    tool_use_id: str | None = None
    title: str | None = None


class ContextCompactionRisk(BaseModel):
    kind: str
    label: str
    level: str = "unknown"
    reason: str | None = None
    affected_segments: int = 0
    sample_refs: list[ContextCompactionRiskRef] = Field(default_factory=list)
    estimated: bool = True


class ContextCompactionEvent(BaseModel):
    id: str
    phase_before: int
    phase_after: int
    detected_at: datetime | None = None
    source: str
    source_ref_id: str | None = None
    source_label: str | None = None
    event_type: str = "context_compaction"
    token_before_estimate: int | None = None
    token_after_estimate: int | None = None
    token_reduction_estimate: int | None = None
    tokens_estimated: bool = True
    preview: str | None = None
    trigger: ContextCompactionReference | None = None
    risks: list[ContextCompactionRisk] = Field(default_factory=list)
    locator: dict[str, Any] = Field(default_factory=dict)


class ContextCompactionPhase(BaseModel):
    phase_index: int
    started_at: datetime | None = None
    ended_at: datetime | None = None
    token_before_estimate: int | None = None
    token_after_estimate: int | None = None
    phase_new_tokens_estimate: int | None = None
    trigger: ContextCompactionReference | None = None
    compaction_event_id: str | None = None
    estimation_note: str | None = None


class ContextCompactionDataSource(BaseModel):
    source: str
    status: str
    event_count: int = 0
    note: str | None = None


class ContextCompactionResponse(BaseModel):
    task_id: str
    workspace_id: str
    status: str = "not_detected"
    has_detected_events: bool = False
    empty_reason: str | None = None
    events: list[ContextCompactionEvent] = Field(default_factory=list)
    phases: list[ContextCompactionPhase] = Field(default_factory=list)
    data_sources: list[ContextCompactionDataSource] = Field(default_factory=list)
    generated_at: datetime | None = None
    parser_version: str = "compaction-v1"


class ContextWindowResponse(BaseModel):
    task_id: str
    workspace_id: str
    snapshot: ContextTokenSnapshotResponse | None = None
    provider_tokens: ContextProviderTokensResponse = Field(default_factory=ContextProviderTokensResponse)
    categories: list[ContextTokenCategorySummary] = Field(default_factory=list)
    segments: list[ContextTokenSegmentResponse] = Field(default_factory=list)
    segments_total: int = 0
    segments_page: int = 1
    segments_page_size: int = 50
    selected_category: str | None = None
    empty_reason: str | None = None
    compaction: ContextCompactionResponse | None = None
