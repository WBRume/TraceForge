"""
站内信服务：创建、列表、已读、未读数、删除（消息消费）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.domains.notification.models.notification import SddUserNotification


def create_notifications(
    db: Session,
    recipient_user_ids: list[str],
    *,
    type: str,
    title: str,
    body: Optional[str] = None,
    payload_json: Optional[dict] = None,
    workspace_id: Optional[str] = None,
) -> list[SddUserNotification]:
    """为一批收件人各创建一条站内信（去重收件人，忽略空 id）。"""
    seen: set[str] = set()
    rows: list[SddUserNotification] = []
    for user_id in recipient_user_ids:
        uid = str(user_id or "").strip()
        if not uid or uid in seen:
            continue
        seen.add(uid)
        rows.append(
            SddUserNotification(
                workspace_id=workspace_id,
                recipient_user_id=uid,
                type=type,
                title=title,
                body=body,
                payload_json=payload_json,
            )
        )
    if rows:
        db.add_all(rows)
        db.commit()
    return rows


def _serialize(item: SddUserNotification) -> dict:
    return {
        "id": item.id,
        "workspace_id": item.workspace_id,
        "type": item.type,
        "title": item.title,
        "body": item.body,
        "payload": item.payload_json if isinstance(item.payload_json, dict) else None,
        "read_at": item.read_at.isoformat() if item.read_at else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def list_notifications(
    db: Session,
    user_id: str,
    *,
    unread_only: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    query = db.query(SddUserNotification).filter(
        SddUserNotification.recipient_user_id == user_id
    )
    if unread_only:
        query = query.filter(SddUserNotification.read_at.is_(None))
    total = query.count()
    rows = (
        query.order_by(SddUserNotification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [_serialize(row) for row in rows], total


def unread_count(db: Session, user_id: str) -> int:
    return (
        db.query(SddUserNotification)
        .filter(
            SddUserNotification.recipient_user_id == user_id,
            SddUserNotification.read_at.is_(None),
        )
        .count()
    )


def mark_read(db: Session, user_id: str, notification_id: str) -> bool:
    row = (
        db.query(SddUserNotification)
        .filter(
            SddUserNotification.id == notification_id,
            SddUserNotification.recipient_user_id == user_id,
        )
        .first()
    )
    if not row:
        return False
    if row.read_at is None:
        row.read_at = datetime.utcnow()
        db.commit()
    return True


def mark_all_read(db: Session, user_id: str) -> int:
    now = datetime.utcnow()
    updated = (
        db.query(SddUserNotification)
        .filter(
            SddUserNotification.recipient_user_id == user_id,
            SddUserNotification.read_at.is_(None),
        )
        .update({"read_at": now}, synchronize_session=False)
    )
    if updated:
        db.commit()
    return updated


def delete_notification(db: Session, user_id: str, notification_id: str) -> Optional[bool]:
    """删除单条通知。返回被删通知此前是否未读（调用方据此修正未读数）；通知不存在返回 None。"""
    row = (
        db.query(SddUserNotification)
        .filter(
            SddUserNotification.id == notification_id,
            SddUserNotification.recipient_user_id == user_id,
        )
        .first()
    )
    if not row:
        return None
    was_unread = row.read_at is None
    db.delete(row)
    db.commit()
    return was_unread


def delete_all_notifications(db: Session, user_id: str) -> tuple[int, int]:
    """清空用户全部通知。返回 (删除总数, 其中未读条数)。"""
    rows = (
        db.query(SddUserNotification)
        .filter(SddUserNotification.recipient_user_id == user_id)
        .all()
    )
    total = len(rows)
    unread = sum(1 for row in rows if row.read_at is None)
    if total:
        for row in rows:
            db.delete(row)
        db.commit()
    return total, unread
