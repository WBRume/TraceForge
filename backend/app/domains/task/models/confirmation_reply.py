"""A live Agent reply receipt, private until its delivery is confirmed."""

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func

from app.database import Base
from app.domains.auth.models.user import generate_uuid


class TaskConfirmationReply(Base):
    __tablename__ = "sdd_task_confirmation_replies"
    __table_args__ = (
        UniqueConstraint("task_id", "creator_id", "client_message_id", name="uq_task_confirmation_reply_client"),
        CheckConstraint(
            "status IN ('PENDING', 'SENDING', 'ACCEPTED', 'DELIVERED', 'FAILED')",
            name="ck_task_confirmation_reply_status",
        ),
        Index("ix_task_confirmation_replies_recovery", "status", "updated_at"),
        Index("ix_task_confirmation_replies_question", "question_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(String(36), ForeignKey("sdd_ai_jobs.id", ondelete="CASCADE"), nullable=False)
    question_id = Column(String(36), ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False)
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    client_message_id = Column(String(128), nullable=False)
    interaction_id = Column(String(36), nullable=False)
    content = Column(Text, nullable=False)
    confirmation_value = Column(JSON, nullable=True)
    status = Column(String(16), nullable=False)
    delivery_token = Column(String(36), nullable=True)
    message_id = Column(String(36), ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
