"""
Unified queue schemas for background jobs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


QueueSourceValue = Literal["provision", "api_mock", "bootstrap", "skill_analysis"]
QueueStatusValue = Literal["PENDING", "RUNNING", "SUCCESS", "FAILED"]
QueueViewValue = Literal["mine", "workspace_all"]
QueueActionValue = Literal["stop", "retry"]


class QueueJobActions(BaseModel):
    can_stop: bool = False
    can_retry: bool = False
    can_open: bool = False


class QueueJobItem(BaseModel):
    source: QueueSourceValue
    job_id: str
    job_type: str
    status: QueueStatusValue
    progress: int
    stage: Optional[str] = None
    message: Optional[str] = None
    error_message: Optional[str] = None
    workspace_id: Optional[str] = None
    task_id: Optional[str] = None
    creator_id: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    target_path: Optional[str] = None
    case_id: Optional[str] = None
    doc_key: Optional[str] = None
    version: Optional[int] = None
    retry_count: Optional[int] = None
    actions: QueueJobActions


class QueueJobListResponse(BaseModel):
    items: list[QueueJobItem]
    total: int
    page: int
    page_size: int


class QueueJobActionResponse(BaseModel):
    ok: bool = True
    action: QueueActionValue
    source: QueueSourceValue
    job_id: str
    message: Optional[str] = None
    new_job_id: Optional[str] = None