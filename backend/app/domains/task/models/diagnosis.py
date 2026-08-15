"""
问题定位任务：定位结果模型

定位结果由用户在 AI 会话收敛后人工确认填写，是「一键转案例」的数据来源。
"""

from enum import Enum as PyEnum

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship
from app.database import Base
from app.domains.auth.models.user import generate_uuid


class DiagnosisResultStatus(str, PyEnum):
    DRAFT = "DRAFT"          # 草稿：会话收敛中，可继续编辑
    CONFIRMED = "CONFIRMED"  # 已确认采纳：已生成案例草稿


class SddDiagnosisResult(Base):
    __tablename__ = "sdd_diagnosis_results"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id = Column(String(36), ForeignKey("users.id"), nullable=False)

    # 定位结果产出
    root_cause = Column(Text, nullable=True)        # 根因结论
    evidence_chain = Column(Text, nullable=True)    # 证据链
    fix_suggestion = Column(Text, nullable=True)    # 修复建议
    confidence = Column(Integer, nullable=False, default=0)  # 置信度 0-100

    status = Column(
        String(20),
        nullable=False,
        default=DiagnosisResultStatus.DRAFT.value,
    )
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    task = relationship("SddTask", back_populates="diagnosis_result", uselist=False)
    created_by = relationship("User", foreign_keys=[created_by_id])
