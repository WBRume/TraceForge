"""Scoped webhook settings and snapshots for explicitly initiated runs."""

from datetime import datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.config import settings
from app.core.offload import run_db_txn_with_bind
from app.dependencies import get_current_user, get_db
from app.domains.ai.models.ai_job import SddAiJob
from app.domains.auth.models.user import User, Workspace
from app.domains.notification.models.task_awareness import TaskAwarenessEvent, TaskWebhookEndpoint
from app.domains.notification.services.task_awareness import BUSINESS_EVENTS, DEFAULT_EVENTS, RUNTIME_EVENTS, iso, run_payload
from app.domains.notification.services.task_webhooks import claim_deliveries, finish_delivery, post_webhook, validate_url
from app.domains.workspace.services import workspace_service

router = APIRouter(tags=["Task Awareness"])


class EndpointInput(BaseModel):
    model_config = {"extra": "forbid"}
    enabled: bool = False
    url: str = Field(default="", max_length=2048)
    delivery_location: Literal["server", "desktop"] = "server"
    events: list[str] = Field(default_factory=lambda: DEFAULT_EVENTS.copy(), max_length=len(RUNTIME_EVENTS + BUSINESS_EVENTS))

    @field_validator("events")
    @classmethod
    def valid_events(cls, events):
        if any(item not in RUNTIME_EVENTS + BUSINESS_EVENTS for item in events):
            raise ValueError("Unsupported subscription event")
        return list(dict.fromkeys(events))


def scope_endpoint(db, user, ws_id=None):
    if ws_id:
        workspace = db.get(Workspace, ws_id)
        if not workspace or workspace.owner_id != user.id:
            raise HTTPException(403, "仅工作区所有者可以管理工作区 Webhook")
    key = f"workspace:{ws_id}" if ws_id else f"user:{user.id}"
    return key, db.query(TaskWebhookEndpoint).filter(TaskWebhookEndpoint.scope_key == key).first()


def serialize(row):
    return {"enabled": bool(row.enabled), "url": row.url,
            "delivery_location": row.delivery_location, "events": row.events_json} if row else EndpointInput().model_dump()


@router.get("/users/me/task-webhook")
@router.get("/workspaces/{ws_id}/task-webhook")
def get_endpoint(ws_id: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return serialize(scope_endpoint(db, user, ws_id)[1])


@router.put("/users/me/task-webhook")
@router.put("/workspaces/{ws_id}/task-webhook")
def save_endpoint(body: EndpointInput, ws_id: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    key, row = scope_endpoint(db, user, ws_id)
    if ws_id and body.delivery_location != "server":
        raise HTTPException(422, "工作区 Webhook 从服务端投递")
    if body.url or body.enabled:
        try:
            validate_url(body.url)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    if row is None:
        row = TaskWebhookEndpoint(scope_key=key, user_id=None if ws_id else user.id, workspace_id=ws_id)
        db.add(row)
    for field in ("enabled", "url", "delivery_location"):
        setattr(row, field, getattr(body, field))
    row.events_json = body.events
    db.commit()
    return serialize(row)


def build_test_request(db, user_id, body, ws_id):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(403, "当前用户不可用")
    scope_endpoint(db, user, ws_id)
    if ws_id and body.delivery_location != "server":
        raise HTTPException(422, "工作区 Webhook 从服务端投递")
    try:
        validate_url(body.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    event_id = str(uuid4())
    workspace = db.get(Workspace, ws_id) if ws_id else None
    payload = {"schema_version": 1, "event_id": event_id, "event_type": "WEBHOOK_TEST", "occurred_at": iso(datetime.utcnow()),
               "workspace": {"id": ws_id, "name": workspace.name if workspace else "个人设置"},
               "task": {"id": None, "title": "连接测试", "url": settings.FRONTEND_BASE_URL},
               "initiator": {"id": user.id, "name": user.display_name}, "run": None, "summary": "Webhook 已收到 TraceForge 测试消息。"}
    request = {"url": body.url, "body": payload, "event_id": event_id}
    return request


@router.post("/users/me/task-webhook/test")
@router.post("/workspaces/{ws_id}/task-webhook/test")
async def test_endpoint(body: EndpointInput, ws_id: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user_id, bind = user.id, db.get_bind()
    db.close()
    request = await run_db_txn_with_bind(bind, lambda session: build_test_request(session, user_id, body, ws_id))
    if body.delivery_location == "desktop":
        return {"request": request}
    ok, error = await post_webhook(**request)
    return {"ok": ok, "error": error}


@router.get("/task-awareness/runs")
def get_runs(job_ids: str = Query(default="", max_length=4000), client_message_ids: str = Query(default="", max_length=8000),
             user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ids = list(dict.fromkeys(job_ids.split(",")))[:100]
    requests = [item for item in dict.fromkeys(client_message_ids.split(",")) if item][:100]
    result = []
    for job in db.query(SddAiJob).filter(or_(SddAiJob.id.in_(ids), SddAiJob.context_json["client_message_id"].as_string().in_(requests)), SddAiJob.creator_id == user.id,
                                        SddAiJob.awareness_version > 0).all():
        workspace = db.get(Workspace, job.workspace_id)
        if not workspace or (workspace.owner_id != user.id and not workspace_service.get_workspace_member(db, job.workspace_id, user.id)):
            continue
        event = db.query(TaskAwarenessEvent).filter(TaskAwarenessEvent.event_key == f"run:{job.id}:{job.awareness_version}").first()
        result.append(event.payload_json if event else run_payload(db, job))
    return {"runs": result}


class DeliveryResult(BaseModel):
    id: str = Field(max_length=36)
    lease_token: str = Field(max_length=36)
    ok: bool
    # Renderer supplies a category, never an endpoint/response text containing secrets.
    error: Literal["NetworkError", "TimeoutError", "HttpError", "ResponseTooLarge"] | None = None


@router.post("/task-awareness/desktop-deliveries/claim")
def claim_desktop(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = claim_deliveries(db, location="desktop", user_id=user.id, limit=10)
    db.commit()
    return {"items": items}


@router.post("/task-awareness/desktop-deliveries/ack")
def ack_desktop(body: DeliveryResult, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ok = finish_delivery(db, body.id, body.lease_token, body.ok, body.error, user_id=user.id)
    db.commit()
    return {"ok": ok}
