"""Bounded bidirectional indexed history windows with shared history DTOs.

窗口几何（keyset/双向取窗）已抽取到任务域共享模块 history_window_service，
本模块保留搜索专用签名与授权语义，行为与抽取前一致。
"""
from datetime import datetime
import time
from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from app.domains.task.models.task import SddTask
from app.domains.task.models.chat import ChatMessage
from app.domains.task.services.history_window_service import keyset, ORDER_COLUMNS
from app.domains.task.services.task_service import serialize_history_messages
from app.domains.search.service import authorized_scope
from app.domains.search.sessions import sign, unsign


def window(db: Session, user, ws, task_id, message_id=None, cursor=None, direction="before", before=15, after=15, limit=30):
    authorized_scope(db, user, ws, task_id)
    task = db.query(SddTask).filter(SddTask.id == task_id, SddTask.workspace_id == ws).first()
    query = db.query(ChatMessage).filter(ChatMessage.task_id == task_id, ChatMessage.workspace_id == ws)
    if query.filter(ChatMessage.sort_seq.is_(None)).with_entities(ChatMessage.id).first():
        raise HTTPException(409, "SEARCH_HISTORY_NOT_READY")
    def fetch(key, way, count):
        rows = query.filter(keyset(key, way)).order_by(*[c.desc() if way == "before" else c.asc() for c in ORDER_COLUMNS]).limit(count + 1).all()
        more = len(rows) > count
        return (list(reversed(rows[:count])) if way == "before" else rows[:count]), more
    anchor = None
    if cursor:
        token = unsign(cursor, "context", user)
        if token.get("workspace") != ws or token.get("task") != task_id or token.get("direction") != direction:
            raise HTTPException(410, "SEARCH_CURSOR_EXPIRED")
        rows, more = fetch(tuple(token["key"]), direction, limit)
        has_before, has_after = (more, True) if direction == "before" else (True, more)
    else:
        anchor = query.filter(ChatMessage.id == message_id).first()
        if not anchor:
            raise HTTPException(404, "Message not found")
        key = (anchor.created_at, anchor.sort_seq, anchor.id)
        left, has_before = fetch(key, "before", before)
        right, has_after = fetch(key, "after", after)
        rows = left + [anchor] + right
    def token_for(row, way):
        return sign(dict(purpose="context", user=user, workspace=ws, task=task_id, direction=way,
            key=[row.created_at.isoformat(), row.sort_seq, row.id], expires=int(time.time()) + 300))
    return dict(anchor_message_id=message_id, messages=serialize_history_messages(db, task, rows, ws, task_id),
        before_cursor=token_for(rows[0], "before") if rows and has_before else None,
        after_cursor=token_for(rows[-1], "after") if rows and has_after else None,
        has_before=has_before, has_after=has_after, at_latest=not has_after)
