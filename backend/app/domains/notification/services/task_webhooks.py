"""Standard JSON webhook transport and durable delivery claims."""

import asyncio
from datetime import datetime, timedelta
from ipaddress import ip_address
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from sqlalchemy import or_

from app.domains.ai.models.ai_job import SddAiJob
from app.domains.auth.models.user import Workspace, WorkspaceMember
from app.domains.notification.models.task_awareness import TaskAwarenessEvent, TaskWebhookDelivery, TaskWebhookEndpoint
from app.domains.notification.services.task_awareness import (
    BUSINESS_EVENTS,
    LONG_RUN_SECONDS,
    RUNTIME_EVENTS,
    webhook_eligible,
)

MAX_ATTEMPTS = 3
LEASE_SECONDS = 30


def validate_url(url):
    parts = urlsplit(url)
    if (
        len(url) > 2048
        or parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.fragment
    ):
        raise ValueError("请输入有效的 HTTP(S) Webhook URL，不支持账号密码或片段")
    try:
        address = ip_address(parts.hostname)
    except ValueError:
        address = None
    if address and (address.is_link_local or address.is_unspecified or address.is_multicast):
        raise ValueError("该 Webhook 地址不可用")
    try:
        _ = parts.port  # Access validates the parsed port and may raise ValueError.
    except ValueError as exc:
        raise ValueError("Webhook 端口无效") from exc
    return url


async def post_webhook(url, body, event_id):
    try:
        return await asyncio.wait_for(_post_webhook(url, body, event_id), timeout=3)
    except TimeoutError:
        return False, "TimeoutError"


async def _post_webhook(url, body, event_id):
    # HTTP status is the only acknowledgement; discard endpoint-specific bodies.
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0), follow_redirects=False, trust_env=False) as client:
            async with client.stream(
                "POST", validate_url(url), json=body, headers={"X-TraceForge-Event-Id": event_id}
            ) as response:
                if not 200 <= response.status_code < 300:
                    return False, f"HTTP {response.status_code}"
        return True, None
    except (httpx.HTTPError, ValueError) as exc:
        return False, type(exc).__name__


def endpoint_authorized(db, endpoint, event):
    if not endpoint.enabled or event.event_type not in (endpoint.events_json or []):
        return False
    workspace = db.get(Workspace, event.workspace_id)
    if not workspace:
        return False
    is_member = (
        workspace.owner_id == event.creator_id
        or db.query(WorkspaceMember.id)
        .filter(WorkspaceMember.workspace_id == event.workspace_id, WorkspaceMember.user_id == event.creator_id)
        .first()
        is not None
    )
    return is_member and (
        endpoint.user_id == event.creator_id if endpoint.user_id else endpoint.workspace_id == event.workspace_id
    )


def prepare_deliveries(db, event, now):
    job = db.get(SddAiJob, event.job_id) if event.job_id else None
    if event.event_type not in RUNTIME_EVENTS + BUSINESS_EVENTS:
        return
    # A still-suspended short run can become eligible at its 10-second boundary.
    pending_hitl = event.event_type == "AI_HITL_SUSPENDED" and job and job.awareness_state == "AI_HITL_SUSPENDED"
    if not webhook_eligible(event, job, now) and not pending_hitl:
        return
    endpoints = (
        db.query(TaskWebhookEndpoint)
        .filter(
            or_(TaskWebhookEndpoint.user_id == event.creator_id, TaskWebhookEndpoint.workspace_id == event.workspace_id)
        )
        .all()
    )
    for endpoint in endpoints:
        if not endpoint_authorized(db, endpoint, event) or endpoint.created_at > event.created_at:
            continue
        existing = (
            db.query(TaskWebhookDelivery.id)
            .filter(TaskWebhookDelivery.event_id == event.id, TaskWebhookDelivery.endpoint_id == endpoint.id)
            .first()
        )
        if existing:
            continue
        gate = job.started_at + timedelta(seconds=LONG_RUN_SECONDS) if pending_hitl else now
        db.add(TaskWebhookDelivery(event_id=event.id, endpoint_id=endpoint.id, available_at=max(now, gate)))


def claim_deliveries(db, *, location, user_id=None, limit=20):
    now = datetime.utcnow()
    query = (
        db.query(TaskWebhookDelivery)
        .join(TaskWebhookEndpoint)
        .filter(
            TaskWebhookEndpoint.delivery_location == location,
            TaskWebhookDelivery.status.in_(["PENDING", "SENDING"]),
            TaskWebhookDelivery.available_at <= now,
            or_(TaskWebhookDelivery.lease_expires_at.is_(None), TaskWebhookDelivery.lease_expires_at <= now),
        )
    )
    if user_id:
        query = query.filter(TaskWebhookEndpoint.user_id == user_id)
    claimed = []
    for row in query.order_by(TaskWebhookDelivery.available_at).limit(limit).with_for_update(skip_locked=True).all():
        event = db.get(TaskAwarenessEvent, row.event_id)
        endpoint = db.get(TaskWebhookEndpoint, row.endpoint_id)
        job = db.get(SddAiJob, event.job_id) if event.job_id else None
        if row.attempts >= MAX_ATTEMPTS:
            row.status = "FAILED"
            continue
        if not endpoint_authorized(db, endpoint, event) or not webhook_eligible(event, job, now):
            row.status = "SKIPPED"
            continue
        row.status = "SENDING"
        row.attempts += 1
        row.lease_token = str(uuid4())
        row.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        claimed.append(
            {
                "id": row.id,
                "lease_token": row.lease_token,
                "url": endpoint.url,
                "body": event.payload_json,
                "event_id": event.id,
            }
        )
    return claimed


def finish_delivery(db, delivery_id, token, ok, error=None, *, user_id=None):
    row = (
        db.query(TaskWebhookDelivery)
        .filter(
            TaskWebhookDelivery.id == delivery_id,
            TaskWebhookDelivery.lease_token == token,
            TaskWebhookDelivery.status == "SENDING",
        )
        .with_for_update()
        .first()
    )
    if not row:
        return False
    endpoint = db.get(TaskWebhookEndpoint, row.endpoint_id)
    if user_id and (endpoint.user_id != user_id or endpoint.delivery_location != "desktop"):
        return False
    row.status = "SENT" if ok else ("FAILED" if row.attempts >= MAX_ATTEMPTS else "PENDING")
    row.last_error = None if ok else str(error or "Delivery failed")[:300]
    row.available_at = datetime.utcnow() + timedelta(seconds=(2, 10, 30)[min(row.attempts - 1, 2)])
    row.lease_token = row.lease_expires_at = None
    row.notified_at = None
    return True
