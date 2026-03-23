"""
Skill related schemas.
"""

from datetime import datetime
from typing import Optional, List, Literal

from pydantic import BaseModel, Field


SkillDimensionValue = Literal["GLOBAL", "WORKSPACE"]


class SkillCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    content: str = Field(..., min_length=1)
    dimension: SkillDimensionValue = "WORKSPACE"
    workspace_id: Optional[str] = None


class SkillUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    content: Optional[str] = None
    dimension: Optional[SkillDimensionValue] = None
    workspace_id: Optional[str] = None


class SkillResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    dimension: SkillDimensionValue
    workspace_id: Optional[str] = None
    creator_id: str
    file_path: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    can_manage: bool = False

    model_config = {"from_attributes": True}


class SkillListResponse(BaseModel):
    items: List[SkillResponse]
    total: int


class SkillDetailResponse(SkillResponse):
    content: str
