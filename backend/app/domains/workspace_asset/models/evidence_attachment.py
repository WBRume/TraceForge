"""Files uploaded for task closeout and their eventual evidence association."""

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, func

from app.database import Base
from app.domains.auth.models.user import generate_uuid


class TaskEvidenceAttachment(Base):
    __tablename__ = "task_evidence_attachments"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    uploader_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    evidence_id = Column(String(36), ForeignKey("sdd_evidence.id", ondelete="CASCADE"), nullable=True, index=True)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(255), nullable=False)
    size = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
