"""
案例知识中心：结构化功能案例模型与专家评审记录。

案例来源：问题定位任务「确认采纳 → 一键转案例」生成的草稿，或手工创建。
生命周期：草稿 → 待评审 → 评审中 → 已入库 / 已驳回（附评审意见），驳回后可重新提交。
"""

from enum import Enum as PyEnum

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, JSON, func
from sqlalchemy.orm import relationship
from app.database import Base
from app.domains.auth.models.user import Workspace, generate_uuid


class CaseCategory(str, PyEnum):
    PUBLIC = "PUBLIC"        # 公共
    PRODUCT = "PRODUCT"      # 产品
    SITE = "SITE"            # 局点
    TEMPORARY = "TEMPORARY"  # 临时


class CasePriority(str, PyEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class CaseStatus(str, PyEnum):
    DRAFT = "DRAFT"                    # 草稿
    PENDING_REVIEW = "PENDING_REVIEW"  # 待评审
    IN_REVIEW = "IN_REVIEW"            # 评审中
    APPROVED = "APPROVED"              # 已入库
    REJECTED = "REJECTED"              # 已驳回（附评审意见，可重新提交）


class CaseReviewAction(str, PyEnum):
    START = "START"      # 专家接单
    APPROVE = "APPROVE"  # 通过入库
    REJECT = "REJECT"    # 驳回打回


class SddCase(Base):
    __tablename__ = "sdd_cases"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    source_task_id = Column(
        String(36),
        ForeignKey("sdd_tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # 结构化案例模型
    title = Column(String(300), nullable=False)
    problem_description = Column(Text, nullable=True)  # 问题描述
    product_name = Column(String(200), nullable=True)  # 产品
    product_version = Column(String(100), nullable=True)  # 版本
    site_name = Column(String(200), nullable=True)  # 局点
    code_context = Column(Text, nullable=True)  # 代码上下文
    analysis_process = Column(Text, nullable=True)  # 分析过程
    root_cause = Column(Text, nullable=True)  # 根因
    solution = Column(Text, nullable=True)  # 方案

    # 分类与优先级
    category = Column(String(20), nullable=False, default=CaseCategory.TEMPORARY.value, index=True)
    priority = Column(String(10), nullable=False, default=CasePriority.P2.value, index=True)

    # 生命周期
    status = Column(String(20), nullable=False, default=CaseStatus.DRAFT.value, index=True)
    review_round = Column(Integer, nullable=False, default=1)  # 评审轮次，驳回重提后 +1
    conversation_snapshot_json = Column(JSON, nullable=True)  # 对话回放快照
    diagnosis_detail_json = Column(JSON, nullable=True)  # 问题定位结构化明细 {similar_cases, call_chain, code_context, fix_code}
    submitted_at = Column(DateTime, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    rejected_comment = Column(Text, nullable=True)  # 最近一次驳回意见

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    creator = relationship("User", foreign_keys=[creator_id])
    source_task = relationship("SddTask", foreign_keys=[source_task_id])
    workspace = relationship("Workspace", foreign_keys=[workspace_id])
    review_records = relationship(
        "SddCaseReviewRecord",
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="SddCaseReviewRecord.created_at.asc()",
    )


class SddCaseReviewRecord(Base):
    __tablename__ = "sdd_case_review_records"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=generate_uuid)
    case_id = Column(String(36), ForeignKey("sdd_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    reviewer_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String(20), nullable=False)  # CaseReviewAction
    comment = Column(Text, nullable=True)  # 评审意见
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    case = relationship("SddCase", back_populates="review_records")
    reviewer = relationship("User", foreign_keys=[reviewer_id])
