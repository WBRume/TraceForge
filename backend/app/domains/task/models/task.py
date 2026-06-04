"""
SDD 任务与计划节点模型
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, DateTime, ForeignKey, Enum, Text, Integer, Float, BigInteger, JSON, func
)
from sqlalchemy.orm import relationship
from app.database import Base
from app.domains.auth.models.user import generate_uuid


class TaskStatus(str, PyEnum):
    PENDING = "PENDING"
    BRAINSTORMING = "BRAINSTORMING"
    PLANNING = "PLANNING"
    CODING = "CODING"
    TESTING = "TESTING"
    REVIEWING = "REVIEWING"
    DEPLOYING = "DEPLOYING"
    DONE = "DONE"
    FAILED = "FAILED"
    SUSPENDED = "SUSPENDED"  # HITL 挂起
    INTERRUPTED = "INTERRUPTED"  # 用户临时中断，可恢复
    BASELINED = "BASELINED"


class PlanNodeStatus(str, PyEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class SddTask(Base):
    __tablename__ = "sdd_tasks"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    spec_doc_path = Column(String(500), nullable=True)
    project_path = Column(String(500), nullable=False)
    git_repo_url = Column(String(500), nullable=True)
    status = Column(Enum(TaskStatus), nullable=False, default=TaskStatus.PENDING)
    retry_count = Column(Integer, nullable=False, default=0)
    current_phase = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    session_id = Column(String(120), nullable=True)
    interrupt_reason = Column(Text, nullable=True)
    interrupted_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    interrupted_at = Column(DateTime, nullable=True)
    baselined_at = Column(DateTime, nullable=True)
    baselined_by_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    baseline_snapshot_json = Column(JSON, nullable=True)
    baseline_version = Column(Integer, nullable=False, default=0)
    requirement_duration_hours = Column(Integer, nullable=False, default=0) # 预估需求耗时(小时)
    total_cost_usd = Column(Float, nullable=False, default=0.0) # 累计消耗费用
    total_duration_ms = Column(BigInteger, nullable=False, default=0) # 累计执行耗时(ms)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    workspace = relationship("Workspace", back_populates="tasks")
    creator = relationship("User", foreign_keys=[creator_id])
    interrupted_by = relationship("User", foreign_keys=[interrupted_by_id])
    baselined_by = relationship("User", foreign_keys=[baselined_by_id])
    plan_nodes = relationship("SddPlanNode", back_populates="task", cascade="all, delete-orphan")
    execution_logs = relationship("SddExecutionLog", back_populates="task", cascade="all, delete-orphan")
    test_results = relationship("SddTestResult", back_populates="task", cascade="all, delete-orphan")
    assets = relationship("SddAsset", back_populates="task", cascade="all, delete-orphan")
    messages = relationship("ChatMessage", back_populates="task", cascade="all, delete-orphan")
    dashboard_metrics = relationship("SddDashboardMetric", back_populates="task", cascade="all, delete-orphan")
    skill_links = relationship("SddTaskSkill", back_populates="task", cascade="all, delete-orphan")
    api_mock_projects = relationship("SddApiMockProject", back_populates="task", cascade="all, delete-orphan")
    ai_jobs = relationship("SddAiJob", back_populates="task", cascade="all, delete-orphan")
    requirement_links = relationship("SddTaskRequirement", back_populates="task", cascade="all, delete-orphan")
    ai_outputs = relationship("SddAiOutput", back_populates="task", cascade="all, delete-orphan")
    human_reviews = relationship("SddHumanReview", back_populates="task", cascade="all, delete-orphan")
    human_review_comments = relationship("SddHumanReviewComment", back_populates="task", cascade="all, delete-orphan")
    human_deltas = relationship("SddHumanDelta", back_populates="task", cascade="all, delete-orphan")
    evidence_items = relationship("SddEvidence", back_populates="task")
    decisions = relationship("SddDecision", back_populates="task", cascade="all, delete-orphan")
    clarifications = relationship("SddClarification", back_populates="task", cascade="all, delete-orphan")
    final_summary = relationship(
        "SddTaskFinalSummary",
        back_populates="task",
        cascade="all, delete-orphan",
        uselist=False,
    )
    process_audit_logs = relationship(
        "SddTaskProcessAuditLog",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="SddTaskProcessAuditLog.created_at.desc()",
    )
    baselines = relationship(
        "SddTaskBaseline",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="SddTaskBaseline.version.desc()",
    )
    change_proposals = relationship("SddTaskChangeProposal", back_populates="task", cascade="all, delete-orphan")
    verification_runs = relationship("SddTaskVerificationRun", back_populates="task", cascade="all, delete-orphan")
    conflict_reports = relationship("SddTaskConflictReport", back_populates="task", cascade="all, delete-orphan")
    cli_bootstrap = relationship(
        "SddTaskCliBootstrap",
        back_populates="task",
        cascade="all, delete-orphan",
        uselist=False,
    )

    @property
    def skill_ids(self):
        return [link.skill_id for link in self.skill_links]

    @property
    def creator_name(self):
        return self.creator.display_name if self.creator else None


class SddPlanNode(Base):
    __tablename__ = "sdd_plan_nodes"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False, index=True)
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    parent_id = Column(String(36), ForeignKey("sdd_plan_nodes.id"), nullable=True)
    title = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Enum(PlanNodeStatus), nullable=False, default=PlanNodeStatus.PENDING)
    order_index = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    task = relationship("SddTask", back_populates="plan_nodes")
    children = relationship("SddPlanNode", back_populates="parent", cascade="all, delete-orphan")
    parent = relationship("SddPlanNode", back_populates="children", remote_side=[id])
