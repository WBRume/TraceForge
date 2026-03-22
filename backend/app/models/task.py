"""
SDD 任务与计划节点模型
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, DateTime, ForeignKey, Enum, Text, Integer, func
)
from sqlalchemy.orm import relationship
from app.database import Base
from app.models.user import generate_uuid


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


class PlanNodeStatus(str, PyEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class SddTask(Base):
    __tablename__ = "sdd_tasks"

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
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    workspace = relationship("Workspace", back_populates="tasks")
    creator = relationship("User")
    plan_nodes = relationship("SddPlanNode", back_populates="task", cascade="all, delete-orphan")
    execution_logs = relationship("SddExecutionLog", back_populates="task", cascade="all, delete-orphan")
    test_results = relationship("SddTestResult", back_populates="task", cascade="all, delete-orphan")
    assets = relationship("SddAsset", back_populates="task", cascade="all, delete-orphan")
    messages = relationship("ChatMessage", back_populates="task", cascade="all, delete-orphan")


class SddPlanNode(Base):
    __tablename__ = "sdd_plan_nodes"

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
