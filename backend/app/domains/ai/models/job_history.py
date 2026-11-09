"""Durable attempts and committed job events; no provider event is authoritative."""

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.database import Base
from app.domains.auth.models.user import generate_uuid


class JobAttempt(Base):
    __tablename__ = "sdd_job_attempts"
    __table_args__ = (UniqueConstraint("job_id", "number", name="uq_job_attempt_number"),)

    id = Column(String(36), primary_key=True, default=generate_uuid)
    job_id = Column(String(36), ForeignKey("sdd_ai_jobs.id", ondelete="CASCADE"), nullable=False)
    number = Column(Integer, nullable=False)
    run_token = Column(String(36), nullable=False)
    worker_id = Column(String(190), nullable=True)
    worker_boot_id = Column(String(36), nullable=True)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    outcome = Column(String(40), nullable=True)
    failure_code = Column(String(64), nullable=True)
    job = relationship("SddAiJob")


class JobEvent(Base):
    __tablename__ = "sdd_job_events"
    __table_args__ = (
        UniqueConstraint("job_id", "version", name="uq_job_event_version"),
        Index("ix_job_event_delivery", "published_at", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    job_id = Column(String(36), ForeignKey("sdd_ai_jobs.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    attempt = Column(Integer, nullable=False)
    payload_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    published_at = Column(DateTime, nullable=True)
    job = relationship("SddAiJob")


def record_event(db, job):
    """Persist a versioned snapshot alongside the state that produced it."""
    from datetime import datetime

    db.add(
        JobEvent(
            job=job,
            version=job.version,
            attempt=int(job.attempt_count or 0),
            payload_json={
                "id": job.id,
                "version": job.version,
                "attempt_count": int(job.attempt_count or 0),
                "status": str(getattr(job.status, "value", job.status)),
                "progress": int(job.progress or 0),
                "stage": job.stage,
                "message": job.message,
                "error_message": job.error_message,
                "completion": job.completion_json,
                "cancel_requested": bool(job.cancel_requested_at),
                "updated_at": job.state_changed_at.isoformat(),
            },
        )
    )
    number = int(job.attempt_count or 0)
    if not number:
        return
    attempt = db.query(JobAttempt).filter_by(job_id=job.id, number=number).first()
    if attempt is None and job.run_token:
        attempt = JobAttempt(
            job=job,
            number=number,
            run_token=job.run_token,
            worker_id=job.worker_id,
            worker_boot_id=job.worker_boot_id,
            started_at=job.started_at or datetime.utcnow(),
        )
        db.add(attempt)
    if attempt and not job.run_token:
        attempt.finished_at = datetime.utcnow()
        attempt.outcome = str(getattr(job.status, "value", job.status))
        attempt.failure_code = job.failure_code


from sqlalchemy import event, inspect  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402


@event.listens_for(Session, "before_flush")
def capture_changes(db, _context, _instances):
    from app.domains.ai.models.ai_job import SddAiJob

    visible_fields = (
        "status",
        "progress",
        "stage",
        "message",
        "error_message",
        "result_json",
        "completion_json",
        "cancel_requested_at",
        "manual_intervention_required",
        "context_json",
        "queue_source",
        "workspace_id",
        "task_id",
    )
    for job in list(db.new) + list(db.dirty):
        if not isinstance(job, SddAiJob):
            continue
        state = inspect(job)
        if job in db.new:
            job.id = job.id or generate_uuid()
            job.version = 1
        elif any(state.attrs[name].history.has_changes() for name in visible_fields):
            # Long-lived domain sessions can hold an older identity while a
            # heartbeat/finalizer uses another connection. Allocate the event
            # version under the database lock, never from that cached identity.
            current = db.query(SddAiJob.version).filter(SddAiJob.id == job.id).with_for_update().scalar()
            job.version = int(current or 1) + 1
        else:
            continue
        # Listing/history timestamps share the database clock with created_at
        # and migrated records. Lease deadlines keep their separate UTC clock.
        job.state_changed_at = db.query(func.now()).scalar()
        record_event(db, job)
