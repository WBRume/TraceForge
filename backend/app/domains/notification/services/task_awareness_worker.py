"""Outbox relay and bounded webhook delivery, separate from AI execution."""

import asyncio
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_

from app.core.logging import get_logger
from app.core.offload import run_db_txn
from app.domains.ai.models.ai_job import SddAiJob
from app.domains.auth.models.user import Workspace, WorkspaceMember
from app.domains.notification.models.task_awareness import TaskAwarenessEvent, TaskWebhookDelivery, TaskWebhookEndpoint
from app.domains.notification.services.task_webhooks import claim_deliveries, finish_delivery, post_webhook, prepare_deliveries
from app.domains.notification.ws.notification_manager import notification_ws_manager

logger = get_logger(__name__, category="task_execution")


def _claim_events(db):
    now = datetime.utcnow()
    rows = db.query(TaskAwarenessEvent).filter(
        TaskAwarenessEvent.published_at.is_(None), TaskAwarenessEvent.available_at <= now,
        or_(TaskAwarenessEvent.lease_expires_at.is_(None), TaskAwarenessEvent.lease_expires_at <= now),
    ).order_by(TaskAwarenessEvent.created_at).limit(30).with_for_update(skip_locked=True).all()
    result = []
    for row in rows:
        row.lease_token = str(uuid4())
        row.lease_expires_at = now + timedelta(seconds=30)
        prepare_deliveries(db, row, now)
        job = db.get(SddAiJob, row.job_id) if row.job_id else None
        workspace = db.get(Workspace, row.workspace_id)
        has_access = workspace and (workspace.owner_id == row.creator_id or db.query(WorkspaceMember.id).filter_by(
            workspace_id=row.workspace_id, user_id=row.creator_id).first() is not None)
        # Old transient states must not appear as fresh changes after an outage.
        notify = bool(has_access and job and row.event_key == f"run:{job.id}:{job.awareness_version}")
        result.append({"id": row.id, "token": row.lease_token, "creator_id": row.creator_id,
                       "payload": row.payload_json, "notify": notify})
    return result


def _mark_published(db, event):
    db.query(TaskAwarenessEvent).filter(TaskAwarenessEvent.id == event["id"],
                                       TaskAwarenessEvent.lease_token == event["token"]).update(
        {"published_at": datetime.utcnow(), "lease_token": None, "lease_expires_at": None})


def _desktop_recipients(db):
    now = datetime.utcnow()
    # A one-time event per due delivery attempt, including retry/recovered leases.
    rows = db.query(TaskWebhookDelivery, TaskWebhookEndpoint.user_id).join(TaskWebhookEndpoint).filter(
        TaskWebhookEndpoint.enabled.is_(True), TaskWebhookEndpoint.delivery_location == "desktop",
        TaskWebhookDelivery.status.in_(["PENDING", "SENDING"]), TaskWebhookDelivery.available_at <= now,
        or_(TaskWebhookDelivery.lease_expires_at.is_(None), TaskWebhookDelivery.lease_expires_at <= now),
        or_(TaskWebhookDelivery.notified_at.is_(None), TaskWebhookDelivery.notified_at < TaskWebhookDelivery.available_at,
            TaskWebhookDelivery.notified_at < TaskWebhookDelivery.lease_expires_at),
    ).limit(50).with_for_update(skip_locked=True).all()
    for row, _ in rows:
        row.notified_at = now
    return {user_id for _, user_id in rows if user_id}


async def relay_events_once():
    for event in await run_db_txn(_claim_events):
        if event["notify"]:
            await notification_ws_manager.send_message_to_user(event["creator_id"],
                {"type": "task_runtime_event", "event": event["payload"]})
        await run_db_txn(lambda db: _mark_published(db, event))
    for user_id in await run_db_txn(_desktop_recipients):
        await notification_ws_manager.send_message_to_user(user_id, {"type": "task_webhook_ready"})


async def deliver_webhooks_once():
    deliveries = await run_db_txn(lambda db: claim_deliveries(db, location="server", limit=8))
    async def deliver(item):
        ok, error = await post_webhook(item["url"], item["body"], item["event_id"])
        await run_db_txn(lambda db: finish_delivery(db, item["id"], item["lease_token"], ok, error))
        if not ok:
            logger.warning("Task webhook delivery {} failed: {}", item["id"], error)
    await asyncio.gather(*(deliver(item) for item in deliveries))


async def relay_once():
    """One complete sweep for integration checks; production loops are independent."""
    await relay_events_once()
    await deliver_webhooks_once()


async def _run_loop(callback):
    while True:
        try:
            await callback()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Task awareness relay failed: {}", type(exc).__name__)
        await asyncio.sleep(1)


async def run_worker():
    # Slow external endpoints cannot hold up runtime events or desktop nudges.
    await asyncio.gather(_run_loop(relay_events_once), _run_loop(deliver_webhooks_once))
