"""
问题定位任务：定位结果 Pydantic Schemas
"""

from typing import Optional
from datetime import datetime

from pydantic import BaseModel, Field


class DiagnosisResultUpsertRequest(BaseModel):
    root_cause: Optional[str] = None
    evidence_chain: Optional[str] = None
    fix_suggestion: Optional[str] = None
    confidence: Optional[int] = Field(default=None, ge=0, le=100)


class DiagnosisResultResponse(BaseModel):
    id: str
    task_id: str
    workspace_id: str
    created_by_id: str
    root_cause: Optional[str] = None
    evidence_chain: Optional[str] = None
    fix_suggestion: Optional[str] = None
    confidence: int = 0
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
