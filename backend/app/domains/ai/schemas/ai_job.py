"""
Schemas for unified AI async jobs.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class AiJobResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: Optional[str] = None
    asset_id: Optional[str] = None
    thread_id: Optional[str] = None
    channel: str
    queue_key: str
    status: str
    progress: int
    message: Optional[str] = None
    prompt_text: Optional[str] = None
    context_json: Optional[Dict[str, Any]] = None
    result_json: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    session_id: Optional[str] = None
    interrupt_reason: Optional[str] = None
    interrupted_by_id: Optional[str] = None
    interrupted_at: Optional[datetime] = None
    creator_id: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AiJobListResponse(BaseModel):
    items: List[AiJobResponse]
    total: int


class AssetThreadAiJobCreateRequest(BaseModel):
    prompt: Optional[str] = None
