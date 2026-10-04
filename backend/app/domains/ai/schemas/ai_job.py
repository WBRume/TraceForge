"""
Schemas for unified AI async jobs.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AiJobResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str | None = None
    asset_id: str | None = None
    thread_id: str | None = None
    channel: str
    queue_key: str
    status: str
    progress: int
    message: str | None = None
    prompt_text: str | None = None
    context_json: dict[str, Any] | None = None
    result_json: dict[str, Any] | None = None
    error_message: str | None = None
    session_id: str | None = None
    interrupt_reason: str | None = None
    interrupted_by_id: str | None = None
    interrupted_at: datetime | None = None
    creator_id: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class AiJobListResponse(BaseModel):
    items: list[AiJobResponse]
    total: int


class AssetThreadAiJobCreateRequest(BaseModel):
    prompt: str | None = None
