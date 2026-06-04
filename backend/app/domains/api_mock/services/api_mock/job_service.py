"""
API MOCK Job Service.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

import anyio
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domains.api_mock.models.api_mock import ApiMockJobStatus, SddApiMockJob, SddApiMockProject
from app.domains.api_mock.ws.api_mock_manager import api_mock_ws_manager
from .constants import AUTO_MOCK_JOB_TYPE, JOB_EVENT_MAX_ITEMS, JOB_EVENT_TEXT_MAX_LEN, JOB_LOG_MAX_LINE_LEN, JOB_LOG_MAX_LINES

logger = get_logger(__name__, category="api_mock")


class JobCancelledError(RuntimeError):
    """Raised when an API MOCK background job receives a cancel signal."""


_JOB_CANCEL_EVENTS: Dict[str, threading.Event] = {}
_JOB_CANCEL_LOCK = threading.Lock()


def create_job(
    db: Session,
    project: SddApiMockProject,
    *,
    creator_id: str,
    job_type: str,
    message: Optional[str] = None,
) -> SddApiMockJob:
    initial_result: Dict[str, Any] = {"live_logs": [], "live_events": []}
    job = SddApiMockJob(
        project_id=project.id,
        creator_id=creator_id,
        job_type=job_type,
        status=ApiMockJobStatus.PENDING,
        progress=0,
        message=message,
        result_json=initial_result,
    )
    db.add(job)
    _commit_job_state(db, project.id, job)
    _get_or_create_cancel_event(job.id)
    if message:
        _append_job_log(db, project.id, job, message)
    else:
        _commit_job_state(db, project.id, job)
    return job


def get_job(db: Session, project_id: str, job_id: str) -> Optional[SddApiMockJob]:
    return (
        db.query(SddApiMockJob)
        .filter(
            SddApiMockJob.project_id == project_id,
            SddApiMockJob.id == job_id,
        )
        .first()
    )


def list_jobs(
    db: Session,
    project_id: str,
    *,
    job_type: Optional[str] = None,
    active_only: bool = False,
    limit: int = 50,
) -> List[SddApiMockJob]:
    query = db.query(SddApiMockJob).filter(SddApiMockJob.project_id == project_id)
    if job_type:
        query = query.filter(SddApiMockJob.job_type == job_type)
    if active_only:
        query = query.filter(SddApiMockJob.status.in_([ApiMockJobStatus.PENDING, ApiMockJobStatus.RUNNING]))
    safe_limit = max(1, min(int(limit), 200))
    return query.order_by(SddApiMockJob.created_at.desc()).limit(safe_limit).all()


def _is_job_active(job: Optional[SddApiMockJob]) -> bool:
    if not job:
        return False
    return job.status in (ApiMockJobStatus.PENDING, ApiMockJobStatus.RUNNING)


def _job_target_endpoint_id(job: SddApiMockJob) -> Optional[str]:
    payload = _job_result_payload(job)
    endpoint_id = str(payload.get("target_endpoint_id") or "").strip()
    return endpoint_id or None


def get_active_auto_mock_job(
    db: Session,
    project_id: str,
    *,
    endpoint_id: Optional[str] = None,
) -> Optional[SddApiMockJob]:
    candidates = (
        db.query(SddApiMockJob)
        .filter(
            SddApiMockJob.project_id == project_id,
            SddApiMockJob.job_type == AUTO_MOCK_JOB_TYPE,
            SddApiMockJob.status.in_([ApiMockJobStatus.PENDING, ApiMockJobStatus.RUNNING]),
        )
        .order_by(SddApiMockJob.created_at.desc())
        .all()
    )
    if not candidates:
        return None
    if not endpoint_id:
        return candidates[0]
    for candidate in candidates:
        if _job_target_endpoint_id(candidate) == endpoint_id:
            return candidate
    return None


def build_auto_mock_locked_detail(
    *,
    code: str,
    message: str,
    job: Optional[SddApiMockJob] = None,
    endpoint_id: Optional[str] = None,
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    if endpoint_id:
        meta["endpoint_id"] = endpoint_id
    if job:
        meta["job_id"] = job.id
        meta["job_status"] = job.status.value if hasattr(job.status, "value") else str(job.status)
        target_endpoint_id = _job_target_endpoint_id(job)
        if target_endpoint_id:
            meta["target_endpoint_id"] = target_endpoint_id
    return {"code": code, "message": message, "meta": meta}


def set_auto_mock_job_target(
    db: Session,
    project_id: str,
    job: SddApiMockJob,
    *,
    endpoint_id: str,
) -> SddApiMockJob:
    payload = _job_result_payload(job)
    payload["job_kind"] = AUTO_MOCK_JOB_TYPE
    payload["target_endpoint_id"] = endpoint_id
    payload.setdefault("live_logs", _job_logs_from_payload(payload))
    payload.setdefault("live_events", _job_events_from_payload(payload))
    job.result_json = payload
    _commit_job_state(db, project_id, job)
    return job


def _job_result_payload(job: SddApiMockJob) -> Dict[str, Any]:
    if isinstance(job.result_json, dict):
        return dict(job.result_json)
    return {}


def _job_logs_from_payload(payload: Dict[str, Any]) -> List[str]:
    raw_logs = payload.get("live_logs")
    if not isinstance(raw_logs, list):
        return []
    logs: List[str] = []
    for item in raw_logs:
        text = str(item or "").strip()
        if text:
            logs.append(text)
    return logs


def _job_events_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_events = payload.get("live_events")
    if not isinstance(raw_events, list):
        return []
    events: List[Dict[str, Any]] = []
    for item in raw_events:
        if isinstance(item, dict):
            events.append(dict(item))
    return events


def _append_job_log(db: Session, project_id: str, job: SddApiMockJob, text: str) -> None:
    line = str(text or "").strip()
    if not line:
        return
    if len(line) > JOB_LOG_MAX_LINE_LEN:
        line = f"{line[:JOB_LOG_MAX_LINE_LEN]}..."
    payload = _job_result_payload(job)
    logs = _job_logs_from_payload(payload)
    timestamp = datetime.utcnow().strftime("%H:%M:%S")
    logs.append(f"{timestamp} {line}")
    if len(logs) > JOB_LOG_MAX_LINES:
        logs = logs[-JOB_LOG_MAX_LINES:]
    payload["live_logs"] = logs
    payload["latest_log"] = logs[-1]
    job.result_json = payload
    logger.info(f"[API MOCK JOB {job.id}] {line}")
    _commit_job_state(db, project_id, job)


def _trim_event_payload(value: Any, *, max_len: int = JOB_EVENT_TEXT_MAX_LEN) -> Any:
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if len(text) > max_len:
            return f"{text[:max_len]}..."
        return text
    if isinstance(value, dict):
        trimmed: Dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)[:120]
            trimmed[key_text] = _trim_event_payload(item, max_len=max_len)
        return trimmed
    if isinstance(value, list):
        return [_trim_event_payload(item, max_len=max_len) for item in value[:200]]
    text = str(value)
    if len(text) > max_len:
        return f"{text[:max_len]}..."
    return text


def _append_job_event(db: Session, project_id: str, job: SddApiMockJob, event_payload: Dict[str, Any]) -> None:
    payload = _job_result_payload(job)
    events = _job_events_from_payload(payload)
    safe_event = _trim_event_payload(event_payload)
    if not isinstance(safe_event, dict):
        safe_event = {"type": "unknown", "text": str(safe_event)}
    safe_event.setdefault("ts", datetime.utcnow().isoformat() + "Z")
    safe_event.setdefault("type", "unknown")
    events.append(safe_event)
    if len(events) > JOB_EVENT_MAX_ITEMS:
        events = events[-JOB_EVENT_MAX_ITEMS:]
    payload["live_events"] = events
    payload["latest_event_type"] = str(safe_event.get("type") or "unknown")
    payload["latest_event_at"] = str(safe_event.get("ts") or datetime.utcnow().isoformat() + "Z")
    job.result_json = payload
    _commit_job_state(db, project_id, job)


def _serialize_job(job: SddApiMockJob) -> Dict[str, Any]:
    status = job.status.value if hasattr(job.status, "value") else str(job.status)
    return {
        "id": job.id,
        "project_id": job.project_id,
        "creator_id": job.creator_id,
        "job_type": job.job_type,
        "status": status,
        "progress": int(job.progress or 0),
        "message": job.message,
        "result_json": _job_result_payload(job),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def _broadcast_job_state(project_id: str, job: SddApiMockJob, *, done: bool = False) -> None:
    payload = {
        "type": "job_done" if done else "job_update",
        "project_id": project_id,
        "job": _serialize_job(job),
    }

    try:
        anyio.from_thread.run(api_mock_ws_manager.broadcast_job_state, project_id, payload)
        return
    except RuntimeError:
        pass
    except Exception as exc:
        logger.debug(f"API MOCK WS push skipped in thread context: {exc}")
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.run(api_mock_ws_manager.broadcast_job_state(project_id, payload))
        except Exception as exc:
            logger.debug(f"API MOCK WS push skipped (standalone loop failed): {exc}")
    except Exception as exc:
        logger.debug(f"API MOCK WS push failed: {exc}")
    else:
        loop.create_task(api_mock_ws_manager.broadcast_job_state(project_id, payload))


def _commit_job_state(db: Session, project_id: str, job: SddApiMockJob, *, done: bool = False) -> None:
    db.commit()
    db.refresh(job)
    _broadcast_job_state(project_id, job, done=done)


def _mark_job_cancel_requested(job: SddApiMockJob) -> None:
    payload = _job_result_payload(job)
    payload["cancel_requested"] = True
    payload["cancel_requested_at"] = datetime.utcnow().isoformat() + "Z"
    job.result_json = payload


def _mark_job_cancelled(job: SddApiMockJob) -> None:
    payload = _job_result_payload(job)
    payload["cancelled"] = True
    payload["cancelled_at"] = datetime.utcnow().isoformat() + "Z"
    job.result_json = payload


def _get_or_create_cancel_event(job_id: str) -> threading.Event:
    with _JOB_CANCEL_LOCK:
        event = _JOB_CANCEL_EVENTS.get(job_id)
        if event is None:
            event = threading.Event()
            _JOB_CANCEL_EVENTS[job_id] = event
        return event


def _is_cancel_requested(job_id: str) -> bool:
    with _JOB_CANCEL_LOCK:
        event = _JOB_CANCEL_EVENTS.get(job_id)
        return bool(event and event.is_set())


def _clear_cancel_event(job_id: str) -> None:
    with _JOB_CANCEL_LOCK:
        _JOB_CANCEL_EVENTS.pop(job_id, None)


def _raise_if_cancel_requested(db: Session, project_id: str, job: SddApiMockJob, job_id: str) -> None:
    if _is_cancel_requested(job_id):
        _append_job_log(db, project_id, job, "Cancellation signal received, stopping job.")
        raise JobCancelledError("Job cancelled by user")


def request_job_cancel(db: Session, project_id: str, job_id: str) -> SddApiMockJob:
    job = get_job(db, project_id, job_id)
    if not job:
        raise ValueError("Job not found")

    if job.status in (ApiMockJobStatus.SUCCESS, ApiMockJobStatus.FAILED):
        return job

    _get_or_create_cancel_event(job_id).set()
    _mark_job_cancel_requested(job)
    _append_job_log(db, project_id, job, "Cancellation requested by user.")

    already_committed = False
    if job.status == ApiMockJobStatus.PENDING:
        _set_job_failed(db, project_id, job, "Job cancelled before execution")
        _mark_job_cancelled(job)
        already_committed = True

    if already_committed:
        _commit_job_state(db, project_id, job, done=True)
    else:
        _commit_job_state(db, project_id, job, done=job.status == ApiMockJobStatus.FAILED)
    return job


def _set_job_running(db: Session, project_id: str, job: SddApiMockJob, message: str) -> None:
    job.status = ApiMockJobStatus.RUNNING
    job.progress = 1
    job.started_at = datetime.utcnow()
    job.message = message
    _commit_job_state(db, project_id, job)


def _set_job_progress(db: Session, project_id: str, job: SddApiMockJob, progress: int, message: str) -> None:
    job.progress = max(0, min(100, int(progress)))
    job.message = message
    _commit_job_state(db, project_id, job)


def _set_job_success(db: Session, project_id: str, job: SddApiMockJob, result: Dict[str, Any], message: str) -> None:
    merged_result = _job_result_payload(job)
    merged_result.update(result)
    job.status = ApiMockJobStatus.SUCCESS
    job.progress = 100
    job.result_json = merged_result
    job.message = message
    job.finished_at = datetime.utcnow()
    _commit_job_state(db, project_id, job, done=True)


def _set_job_failed(db: Session, project_id: str, job: SddApiMockJob, message: str) -> None:
    job.status = ApiMockJobStatus.FAILED
    job.message = message
    job.finished_at = datetime.utcnow()
    _commit_job_state(db, project_id, job, done=True)
