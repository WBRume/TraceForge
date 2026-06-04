"""
执行日志模型
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, DateTime, ForeignKey, Enum, Text, func
)
from sqlalchemy.orm import relationship
from app.database import Base
from app.domains.auth.models.user import generate_uuid


class Phase(str, PyEnum):
    BRAINSTORM = "BRAINSTORM"
    GIT_WORKTREE = "GIT_WORKTREE"
    PLAN = "PLAN"
    CODE = "CODE"
    UT = "UT"
    CODE_REVIEW = "CODE_REVIEW"
    BUILD = "BUILD"
    E2E_UI = "E2E_UI"
    E2E_API = "E2E_API"


class LogType(str, PyEnum):
    STDOUT = "STDOUT"
    STDERR = "STDERR"
    STATUS = "STATUS"
    HITL_REQUEST = "HITL_REQUEST"
    HITL_RESPONSE = "HITL_RESPONSE"
    AGENT_STATE = "AGENT_STATE"


class SddExecutionLog(Base):
    __tablename__ = "sdd_execution_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False, index=True)
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    plan_node_id = Column(String(36), ForeignKey("sdd_plan_nodes.id"), nullable=True)
    phase = Column(Enum(Phase), nullable=True)
    log_type = Column(Enum(LogType), nullable=False, default=LogType.STDOUT)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    task = relationship("SddTask", back_populates="execution_logs")
