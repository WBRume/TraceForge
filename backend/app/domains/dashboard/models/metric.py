"""
看板指标模型
"""

from sqlalchemy import (
    Column, String, DateTime, ForeignKey, Float, func
)
from sqlalchemy.orm import relationship
from app.database import Base
from app.domains.auth.models.user import generate_uuid


class SddDashboardMetric(Base):
    __tablename__ = "sdd_dashboard_metrics"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False, index=True)
    metric_type = Column(String(100), nullable=False)
    metric_value = Column(Float, nullable=False)
    recorded_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    task = relationship("SddTask", back_populates="dashboard_metrics")
