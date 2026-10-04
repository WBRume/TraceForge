"""
系统配置 Pydantic Schemas
"""

from datetime import datetime

from pydantic import BaseModel, Field


class SystemConfigItem(BaseModel):
    key: str
    value: str
    description: str | None = None
    updated_at: datetime | None = None


class SystemConfigListResponse(BaseModel):
    items: list[SystemConfigItem] = Field(default_factory=list)


class SystemConfigUpdate(BaseModel):
    # bool：开关型配置；str：字符串型配置（如工作区根目录，空字符串表示清空配置）
    value: bool | str
