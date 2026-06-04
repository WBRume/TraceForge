"""Schemas for task context-window token attribution."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ContextTokenSnapshotResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    ai_job_id: Optional[str] = None
    session_id: Optional[str] = None
    model: Optional[str] = None
    status: str
    total_cost_usd: Optional[float] = None
    duration_ms: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ContextProviderTokensResponse(BaseModel):
    available: bool = False
    status: str = "unavailable"
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_read_tokens: Optional[int] = None
    cache_creation_tokens: Optional[int] = None
    thinking_tokens: Optional[int] = None
    tool_io_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class ContextTokenCategorySummary(BaseModel):
    category: str
    segment_count: int = 0
    provider_tokens: Optional[int] = None
    attribution_units: int = 0
    char_count: int = 0
    byte_count: int = 0
    percentage: float = 0.0


class ContextTokenSegmentResponse(BaseModel):
    id: str
    snapshot_id: str
    category: str
    provider_tokens: Optional[int] = None
    attribution_units: int = 0
    char_count: int = 0
    byte_count: int = 0
    source_kind: str
    source_ref_id: Optional[str] = None
    chat_message_id: Optional[str] = None
    asset_id: Optional[str] = None
    asset_version_id: Optional[str] = None
    skill_runtime_event_id: Optional[str] = None
    tool_use_id: Optional[str] = None
    content_hash: Optional[str] = None
    locator_json: Optional[Dict[str, Any]] = None
    title: Optional[str] = None
    preview: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None


class ContextCompactionReference(BaseModel):
    turn_index: Optional[int] = None
    ai_job_id: Optional[str] = None
    chat_message_id: Optional[str] = None
    log_id: Optional[str] = None
    label: Optional[str] = None


class ContextCompactionRiskRef(BaseModel):
    id: str
    category: str
    source_kind: str
    source_ref_id: Optional[str] = None
    chat_message_id: Optional[str] = None
    asset_id: Optional[str] = None
    skill_runtime_event_id: Optional[str] = None
    tool_use_id: Optional[str] = None
    title: Optional[str] = None


class ContextCompactionRisk(BaseModel):
    kind: str
    label: str
    level: str = "unknown"
    reason: Optional[str] = None
    affected_segments: int = 0
    sample_refs: List[ContextCompactionRiskRef] = Field(default_factory=list)
    estimated: bool = True


class ContextCompactionEvent(BaseModel):
    id: str
    phase_before: int
    phase_after: int
    detected_at: Optional[datetime] = None
    source: str
    source_ref_id: Optional[str] = None
    source_label: Optional[str] = None
    event_type: str = "context_compaction"
    token_before_estimate: Optional[int] = None
    token_after_estimate: Optional[int] = None
    token_reduction_estimate: Optional[int] = None
    tokens_estimated: bool = True
    preview: Optional[str] = None
    trigger: Optional[ContextCompactionReference] = None
    risks: List[ContextCompactionRisk] = Field(default_factory=list)
    locator: Dict[str, Any] = Field(default_factory=dict)


class ContextCompactionPhase(BaseModel):
    phase_index: int
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    token_before_estimate: Optional[int] = None
    token_after_estimate: Optional[int] = None
    phase_new_tokens_estimate: Optional[int] = None
    trigger: Optional[ContextCompactionReference] = None
    compaction_event_id: Optional[str] = None
    estimation_note: Optional[str] = None


class ContextCompactionDataSource(BaseModel):
    source: str
    status: str
    event_count: int = 0
    note: Optional[str] = None


class ContextCompactionResponse(BaseModel):
    task_id: str
    workspace_id: str
    status: str = "not_detected"
    has_detected_events: bool = False
    empty_reason: Optional[str] = None
    events: List[ContextCompactionEvent] = Field(default_factory=list)
    phases: List[ContextCompactionPhase] = Field(default_factory=list)
    data_sources: List[ContextCompactionDataSource] = Field(default_factory=list)
    generated_at: Optional[datetime] = None
    parser_version: str = "compaction-v1"


class ContextWindowResponse(BaseModel):
    task_id: str
    workspace_id: str
    snapshot: Optional[ContextTokenSnapshotResponse] = None
    provider_tokens: ContextProviderTokensResponse = Field(default_factory=ContextProviderTokensResponse)
    categories: List[ContextTokenCategorySummary] = Field(default_factory=list)
    segments: List[ContextTokenSegmentResponse] = Field(default_factory=list)
    segments_total: int = 0
    segments_page: int = 1
    segments_page_size: int = 50
    selected_category: Optional[str] = None
    empty_reason: Optional[str] = None
    compaction: Optional[ContextCompactionResponse] = None
