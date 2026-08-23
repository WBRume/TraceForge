"""
问题定位任务：定位结果模型

定位结果由 AI 会话收敛时自动反填（extracted_from_ai=True），
用户在会话内的「定位结果」卡片中可继续编辑，「一键转案例」以此为数据来源。
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    Column,
    DateTime,
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
    func,
)
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

    # ── 定位结果产出（基础字段，案例映射视图） ──
    summary = Column(Text, nullable=True)            # AI 返回的结果内容（结论概述）
    root_cause = Column(Text, nullable=True)         # 根因结论
    evidence_chain = Column(Text, nullable=True)     # 证据链
    fix_suggestion = Column(Text, nullable=True)     # 修复方案说明
    fix_code = Column(Text, nullable=True)           # 修复代码/补丁（仅方案建议）
    confidence = Column(Integer, nullable=False, default=0)  # 置信度 0-100

    # ── 结构化章节（完整结果返回） ──
    code_context_json = Column(JSON, nullable=True)      # 相关代码上下文 [{file_path,start_line,end_line,snippet,note}]
    similar_cases_json = Column(JSON, nullable=True)     # 相似案例 [{title,similarity,summary,reference}]
    call_chain_json = Column(JSON, nullable=True)        # 调用链路 [{seq,module,function,file_path,description}]

    # ── 来源与会话卡片关联 ──
    source_chat_message_id = Column(
        String(36),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )  # 会话内「定位结果」卡片消息 id（编辑同步用）
    extracted_from_ai = Column(Boolean, nullable=False, default=True)  # 内容是否来自 AI 会话反填
    extracted_at = Column(DateTime, nullable=True)  # 最近一次 AI 反填时间

    status = Column(
        String(20),
        nullable=False,
        default=DiagnosisResultStatus.DRAFT.value,
    )
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    task = relationship("SddTask", back_populates="diagnosis_result", uselist=False)
    created_by = relationship("User", foreign_keys=[created_by_id])
    source_chat_message = relationship("ChatMessage", foreign_keys=[source_chat_message_id])
