"""
任务会话协作预输入模型

发起人写下主文本并 @成员，窗口期内成员填写各自的输入段，
超时 / 全员完成 / 手动提交后合并为一条用户消息交给 agent。
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, DateTime, ForeignKey, Enum, Text, Integer, JSON, UniqueConstraint, func
)
from sqlalchemy.orm import relationship
from app.database import Base
from app.domains.auth.models.user import generate_uuid


class PreInputStatus(str, PyEnum):
    COLLECTING = "COLLECTING"    # 收集窗口进行中
    SUBMITTED = "SUBMITTED"      # 已合并提交给 agent
    CANCELLED = "CANCELLED"      # 发起人取消 / 任务终态自动取消


class PreInputEditPermission(str, PyEnum):
    ALL = "ALL"                  # 所有工作区成员可编辑主文本与他人输入段
    MENTIONED = "MENTIONED"      # 仅被 @ 成员可编辑
    EXPERTS = "EXPERTS"          # 仅工作区专家可编辑
    NONE = "NONE"                # 不可编辑（仅发起人可编辑）


class SddTaskPreInput(Base):
    __tablename__ = "sdd_task_pre_inputs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    main_text = Column(Text, nullable=False)
    mentioned_user_ids = Column(JSON, nullable=False, default=list)
    edit_permission = Column(
        Enum(PreInputEditPermission, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False, default=PreInputEditPermission.NONE,
    )
    status = Column(
        Enum(PreInputStatus, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False, default=PreInputStatus.COLLECTING, index=True,
    )
    wait_seconds = Column(Integer, nullable=False, default=180)
    deadline_at = Column(DateTime, nullable=False, index=True)
    submitted_at = Column(DateTime, nullable=True)
    submitted_message_id = Column(String(36), ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True)
    submitted_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    submit_reason = Column(String(20), nullable=True)  # timeout / all_done / manual
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    task = relationship("SddTask", foreign_keys=[task_id])
    creator = relationship("User", foreign_keys=[creator_id])
    contributions = relationship(
        "SddTaskPreInputContribution",
        back_populates="pre_input",
        cascade="all, delete-orphan",
        order_by="SddTaskPreInputContribution.created_at.asc()",
    )


class SddTaskPreInputContribution(Base):
    __tablename__ = "sdd_task_pre_input_contributions"
    __table_args__ = (
        UniqueConstraint("pre_input_id", "user_id", name="uq_pre_input_contribution_user"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    pre_input_id = Column(String(36), ForeignKey("sdd_task_pre_inputs.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    pre_input = relationship("SddTaskPreInput", back_populates="contributions")
    user = relationship("User", foreign_keys=[user_id])
