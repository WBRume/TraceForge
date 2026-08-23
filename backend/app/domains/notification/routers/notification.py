"""
站内信 REST 路由：列表 / 未读数 / 标记已读。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User
from app.domains.notification.services import notification_service

router = APIRouter(prefix="/notifications", tags=["Notifications"])


class NotificationListResponse(BaseModel):
    items: list[dict]
    total: int
    page: int
    page_size: int


class UnreadCountResponse(BaseModel):
    count: int


class MarkReadResponse(BaseModel):
    ok: bool


class MarkAllReadResponse(BaseModel):
    updated: int


@router.get("", response_model=NotificationListResponse)
def list_notifications(
    unread_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items, total = notification_service.list_notifications(
        db, current_user.id, unread_only=unread_only, page=page, page_size=page_size
    )
    return NotificationListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/unread-count", response_model=UnreadCountResponse)
def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return UnreadCountResponse(count=notification_service.unread_count(db, current_user.id))


@router.post("/{notification_id}/read", response_model=MarkReadResponse)
def mark_notification_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not notification_service.mark_read(db, current_user.id, notification_id):
        raise HTTPException(status_code=404, detail="Notification not found")
    return MarkReadResponse(ok=True)


@router.post("/read-all", response_model=MarkAllReadResponse)
def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updated = notification_service.mark_all_read(db, current_user.id)
    return MarkAllReadResponse(updated=updated)
