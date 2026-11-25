from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.orm import deferred

from app.database import Base
from app.domains.auth.models.user import generate_uuid


class SddRequirementDocument(Base):
    __tablename__ = "sdd_requirement_documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    creator_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    filename = Column(String(300), nullable=False)
    markdown = Column(Text, nullable=False)
    content = deferred(Column(LargeBinary, nullable=True))
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class SddRequirementDocumentLink(Base):
    __tablename__ = "sdd_requirement_document_links"
    __table_args__ = (
        UniqueConstraint("requirement_id", "document_id", name="uq_requirement_document"),
        UniqueConstraint("requirement_id", "task_asset_id", name="uq_requirement_task_document"),
        CheckConstraint(
            "(document_id IS NULL) <> (task_asset_id IS NULL)",
            name="ck_requirement_document_source",
        ),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    requirement_id = Column(
        String(36), ForeignKey("sdd_requirements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id = Column(
        String(36), ForeignKey("sdd_requirement_documents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    task_asset_id = Column(String(36), ForeignKey("sdd_assets.id", ondelete="CASCADE"), nullable=True, index=True)
    creator_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
