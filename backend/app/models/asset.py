"""
过程资产模型
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, DateTime, ForeignKey, Enum, Text, JSON, func
)
from sqlalchemy.orm import relationship
from app.database import Base
from app.models.user import generate_uuid


class AssetType(str, PyEnum):
    SPEC = "SPEC"
    PROMPT = "PROMPT"
    DESIGN_DOC = "DESIGN_DOC"
    PLAN = "PLAN"
    CODE_DIFF = "CODE_DIFF"
    UT_REPORT = "UT_REPORT"
    E2E_REPORT = "E2E_REPORT"
    ERROR_STACK = "ERROR_STACK"


class SddAsset(Base):
    __tablename__ = "sdd_assets"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False, index=True)
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    asset_type = Column(Enum(AssetType), nullable=False)
    name = Column(String(300), nullable=False)
    content_text = Column(Text, nullable=True)
    content_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    task = relationship("SddTask", back_populates="assets")
