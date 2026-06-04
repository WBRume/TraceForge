"""
测试结果模型
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, DateTime, ForeignKey, Enum, Text, Integer, JSON, func
)
from sqlalchemy.orm import relationship
from app.database import Base
from app.domains.auth.models.user import generate_uuid


class TestType(str, PyEnum):
    UT = "UT"
    E2E_UI = "E2E_UI"
    E2E_API = "E2E_API"
    E2E_FULL = "E2E_FULL"


class TestStatus(str, PyEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIP = "SKIP"


class SddTestResult(Base):
    __tablename__ = "sdd_test_results"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False, index=True)
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    plan_node_id = Column(String(36), ForeignKey("sdd_plan_nodes.id"), nullable=True)
    test_type = Column(Enum(TestType), nullable=False)
    test_name = Column(String(300), nullable=False)
    status = Column(Enum(TestStatus), nullable=False)
    duration_ms = Column(Integer, nullable=True)
    error_detail = Column(Text, nullable=True)
    report_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    task = relationship("SddTask", back_populates="test_results")
