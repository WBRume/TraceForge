"""
RAG 推送 Outbox 持久化模型。

业务侧只负责写入 outbox；后台 worker 负责消费并调用 RagProvider。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, JSON, func

from app.database import Base
from app.domains.auth.models.user import generate_uuid
from app.domains.rag.schemas import RagOutboxStatus


class SddRagOutbox(Base):
    __tablename__ = "sdd_rag_outbox"


    id = Column(String(36), primary_key=True, default=generate_uuid)
    doc_key = Column(String(200), nullable=False, unique=True, index=True)
    payload_json = Column(JSON, nullable=False, default=dict)
    status = Column(
        String(20),
        nullable=False,
        default=RagOutboxStatus.PENDING.value,
        index=True,
    )
    retry_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    next_retry_at = Column(DateTime, nullable=True, index=True)
    locked_until = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )