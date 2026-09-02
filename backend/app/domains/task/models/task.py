"""
SDD 任务与计划节点模型
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, DateTime, ForeignKey, Enum, Text, Integer, Float, BigInteger, JSON, func,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from app.database import Base
from app.domains.auth.models.user import generate_uuid


class TaskStatus(str, PyEnum):
    PROVISIONING = "PROVISIONING"  # 任务资源准备中（git worktree/clone 未完成，禁止启动会话）
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


class TaskType(str, PyEnum):
    DEVELOPMENT = "DEVELOPMENT"  # 研发态任务（默认，存量数据兼容）
    DIAGNOSIS = "DIAGNOSIS"      # 问题定位任务


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
    task_type = Column(String(40), nullable=False, default=TaskType.DEVELOPMENT.value, index=True)
    task_meta_json = Column(JSON, nullable=True)  # 任务类型扩展元数据，如问题定位的 {phenomenon, priority}
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
    # generation 隔离初始化前历史；revision 用来拒绝迟到 provider 事件。
    session_generation = Column(Integer, nullable=False, default=0, server_default="0", index=True)
    session_revision = Column(Integer, nullable=False, default=0, server_default="0", index=True)
    # 粘性 agent backend：任务首次运行后固定，工作区切换 backend 不影响已有会话
    agent_backend = Column(String(40), nullable=True)
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
    diagnosis_result = relationship(
        "SddDiagnosisResult",
        back_populates="task",
        cascade="all, delete-orphan",
        uselist=False,
    )
    dashboard_metrics = relationship("SddDashboardMetric", back_populates="task", cascade="all, delete-orphan")
    skill_links = relationship("SddTaskSkill", back_populates="task", cascade="all, delete-orphan")
    api_mock_projects = relationship("SddApiMockProject", back_populates="task", cascade="all, delete-orphan")
    ai_jobs = relationship("SddAiJob", back_populates="task", cascade="all, delete-orphan")
    session_turns = relationship("TaskSessionTurn", back_populates="task", cascade="all, delete-orphan")
    session_operations = relationship("TaskSessionOperation", back_populates="task", cascade="all, delete-orphan")
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
    repo_bindings = relationship(
        "SddTaskRepository",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="SddTaskRepository.created_at.asc()",
    )
    conflict_reports = relationship("SddTaskConflictReport", back_populates="task", cascade="all, delete-orphan")
    cli_bootstrap = relationship(
        "SddTaskCliBootstrap",
        back_populates="task",
        cascade="all, delete-orphan",
        uselist=False,
    )
    followers = relationship(
        "SddTaskFollower",
        back_populates="task",
        cascade="all, delete-orphan",
    )

    @property
    def skill_ids(self):
        return [link.skill_id for link in self.skill_links]

    @property
    def creator_name(self):
        return self.creator.display_name if self.creator else None


class SddTaskFollower(Base):
    """A user's durable subscription to task messages."""

    __tablename__ = "sdd_task_followers"
    __table_args__ = (
        UniqueConstraint("task_id", "user_id", name="uq_sdd_task_followers_task_user"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    task = relationship("SddTask", back_populates="followers")
    workspace = relationship("Workspace")
    user = relationship("User")


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


# Late import registers sdd_task_repositories into Base.metadata for
# create_all / autogenerate completeness.
from app.domains.task.models import task_repository as _task_repo_models  # noqa: E402,F401
