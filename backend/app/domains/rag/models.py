"""
RAG 推送 Outbox 持久化模型。

业务侧只负责写入 outbox（追加到当前 RUNNING 的案例同步队列）；
操作人员在案例同步队列页面打包下载后，案例标记为 EXPORTED，队列进入 CONSUMED 终态。
自动 RAG 摄入（INDEXING/INDEXED）已停用，下载后由操作人员自行导入 RAG。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, JSON, func

from app.database import Base
from app.domains.auth.models.user import generate_uuid
from app.domains.rag.schemas import RagOutboxStatus, RagQueueStatus


class SddRagSyncQueue(Base):
    """案例同步队列（批次）：按工作区隔离，审批通过案例的载体，打包下载后进入终态。"""

    __tablename__ = "sdd_rag_sync_queue"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(64), nullable=False, unique=True, index=True)
    workspace_id = Column(String(36), nullable=True, index=True)
    status = Column(
        String(20),
        nullable=False,
        default=RagQueueStatus.RUNNING.value,
        index=True,
    )
    consumed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SddRagOutbox(Base):
    __tablename__ = "sdd_rag_outbox"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    doc_key = Column(String(200), nullable=False, unique=True, index=True)
    case_id = Column(String(36), nullable=True, index=True)
    workspace_id = Column(String(36), nullable=True, index=True)
    title = Column(String(500), nullable=True)
    version = Column(Integer, nullable=True)
    queue_id = Column(String(36), nullable=True, index=True)
    payload_json = Column(JSON, nullable=False, default=dict)
    status = Column(
        String(20),
        nullable=False,
        default=RagOutboxStatus.QUEUED.value,
        index=True,
    )
    exported_at = Column(DateTime, nullable=True)
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