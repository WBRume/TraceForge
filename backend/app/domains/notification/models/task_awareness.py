"""Durable execution events and independent webhook delivery leases."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func

from app.database import Base
from app.domains.auth.models.user import generate_uuid


class TaskAwarenessEvent(Base):
    __tablename__ = "task_awareness_events"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    event_key = Column(String(190), nullable=False, unique=True)
    creator_id = Column(String(36), nullable=False, index=True)
    workspace_id = Column(String(36), nullable=False)
    task_id = Column(String(36), nullable=False)
    job_id = Column(String(36), nullable=True)
    event_type = Column(String(40), nullable=False)
    payload_json = Column(JSON, nullable=False)
    available_at = Column(DateTime, nullable=False)
    published_at = Column(DateTime, nullable=True)
    lease_token = Column(String(36), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    __table_args__ = (Index("ix_task_awareness_event_pending", "published_at", "available_at"),)


class TaskWebhookEndpoint(Base):
    __tablename__ = "task_webhook_endpoints"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    scope_key = Column(String(80), nullable=False, unique=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True)
    enabled = Column(Boolean, nullable=False, default=False)
    url = Column(Text, nullable=False)
    delivery_location = Column(String(20), nullable=False, default="server")
    events_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class TaskWebhookDelivery(Base):
    __tablename__ = "task_webhook_deliveries"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    event_id = Column(String(36), ForeignKey("task_awareness_events.id", ondelete="CASCADE"), nullable=False)
    endpoint_id = Column(String(36), ForeignKey("task_webhook_endpoints.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")
    attempts = Column(Integer, nullable=False, default=0)
    available_at = Column(DateTime, nullable=False)
    lease_token = Column(String(36), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    last_error = Column(String(300), nullable=True)
    notified_at = Column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("event_id", "endpoint_id", name="uq_task_webhook_event_endpoint"),
        Index("ix_task_webhook_delivery_pending", "status", "available_at"),
    )
