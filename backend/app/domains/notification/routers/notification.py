"""
站内信 REST 路由：列表 / 未读数 / 标记已读 / 删除（消息消费）。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User
from app.domains.notification.services import notification_service
from app.domains.notification.types import list_notification_types

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


class DeleteNotificationResponse(BaseModel):
    ok: bool
    was_unread: bool


class ClearNotificationsResponse(BaseModel):
    deleted: int
    unread_deleted: int


class NotificationTypeInfoResponse(BaseModel):
    code: str
    category: str
    description: str
    payload_keys: list[str]


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


@router.get("/types", response_model=list[NotificationTypeInfoResponse])
def get_notification_types(
    current_user: User = Depends(get_current_user),
):
    """已注册的通知类型元信息（接入新通知来源时前端可据此适配展示）。"""
    return [
        NotificationTypeInfoResponse(
            code=info.code,
            category=info.category,
            description=info.description,
            payload_keys=list(info.payload_keys),
        )
        for info in list_notification_types()
    ]


@router.delete("/{notification_id}", response_model=DeleteNotificationResponse)
def delete_notification(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    was_unread: Optional[bool] = notification_service.delete_notification(
        db, current_user.id, notification_id
    )
    if was_unread is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return DeleteNotificationResponse(ok=True, was_unread=was_unread)


@router.delete("", response_model=ClearNotificationsResponse)
def clear_notifications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    total, unread = notification_service.delete_all_notifications(db, current_user.id)
    return ClearNotificationsResponse(deleted=total, unread_deleted=unread)
