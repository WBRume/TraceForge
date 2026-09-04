"""
系统配置 Pydantic Schemas
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SystemConfigItem(BaseModel):
    key: str
    value: str
    description: Optional[str] = None
    updated_at: Optional[datetime] = None


class SystemConfigListResponse(BaseModel):
    items: list[SystemConfigItem] = Field(default_factory=list)


class SystemConfigUpdate(BaseModel):
    value: bool
