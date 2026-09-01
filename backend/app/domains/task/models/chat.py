"""
对话消息模型
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, DateTime, ForeignKey, Enum, Text, JSON, Integer, func
)
from sqlalchemy.orm import relationship
from app.database import Base
from app.domains.auth.models.user import generate_uuid


class MessageRole(str, PyEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MessageType(str, PyEnum):
    TEXT = "text"
    THINKING = "thinking"
    PLAN_CARD = "plan_card"
    PROGRESS_CARD = "progress_card"
    TEST_REPORT_CARD = "test_report_card"
    HITL_BOOLEAN = "hitl_boolean"
    HITL_SELECT = "hitl_select"
    FILE_UPLOAD = "file_upload"
    ERROR = "error"
    INIT_REASON = "init_reason"    # 初始化原因（用于会话分隔线）
    DIAGNOSIS_RESULT = "diagnosis_result"  # 问题定位结果卡片（AI 会话反填）


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False, index=True)
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    role = Column(Enum(MessageRole, values_callable=lambda obj: [e.value for e in obj]), nullable=False)
    content = Column(Text, nullable=False)
    message_type = Column(Enum(MessageType, values_callable=lambda obj: [e.value for e in obj]), nullable=False, default=MessageType.TEXT)
    metadata_json = Column(JSON, nullable=True)
    session_turn_id = Column(
        String(36),
        ForeignKey("sdd_task_session_turns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    session_generation = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    task = relationship("SddTask", back_populates="messages")
    session_turn = relationship("TaskSessionTurn", foreign_keys=[session_turn_id])
