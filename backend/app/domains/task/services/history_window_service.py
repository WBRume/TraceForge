"""任务域共享的历史消息 keyset 窗口服务。

从 app.domains.search.context.py 抽取，由现有搜索路由与
reading_resume_service 共同调用；保持旧搜索接口行为不变。
签名/授权仍由各调用方自带（搜索 cursor 用 search purpose，
阅读窗口令牌用 reading purpose），本模块只负责窗口几何。
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Sequence, Tuple

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.domains.task.models.chat import ChatMessage

ORDER_COLUMNS = (ChatMessage.created_at, ChatMessage.sort_seq, ChatMessage.id)


def order_key_of(message: ChatMessage) -> Tuple[datetime, Optional[int], str]:
    return (message.created_at, message.sort_seq, str(message.id))


def parse_order_key(raw: Sequence) -> Tuple[datetime, Optional[int], str]:
    created, seq, identity = raw[0], raw[1], raw[2]
    if isinstance(created, str):
        created = datetime.fromisoformat(created)
    return (created, int(seq) if seq is not None else None, str(identity))


def keyset(key: Tuple[datetime, Optional[int], str], direction: str):
    """双向 keyset 谓词：(created_at, sort_seq, id) 严格前/后。"""
    created, seq, identity = key
    if isinstance(created, str):
        created = datetime.fromisoformat(created)
    compare = (lambda a, b: a < b) if direction == "before" else (lambda a, b: a > b)
    return or_(
        compare(ORDER_COLUMNS[0], created),
        and_(ORDER_COLUMNS[0] == created, compare(ORDER_COLUMNS[1], seq)),
        and_(ORDER_COLUMNS[0] == created, ORDER_COLUMNS[1] == seq, compare(ORDER_COLUMNS[2], identity)),
    )


def find_neighbor_message(
    db: Session,
    task_id: str,
    key: Tuple[datetime, Optional[int], str],
    direction: str,
) -> Optional[ChatMessage]:
    """同任务内按历史排序键找最近的一条仍存在消息（源被删后的邻域定位）。"""
    query = db.query(ChatMessage).filter(ChatMessage.task_id == task_id)
    if direction == "before":
        return (
            query.filter(keyset(key, "before"))
            .order_by(ChatMessage.created_at.desc(), ChatMessage.sort_seq.desc(), ChatMessage.id.desc())
            .first()
        )
    return (
        query.filter(keyset(key, "after"))
        .order_by(ChatMessage.created_at.asc(), ChatMessage.sort_seq.asc(), ChatMessage.id.asc())
        .first()
    )


def fetch_bounded_window(
    db: Session,
    task_id: str,
    *,
    anchor: ChatMessage,
    before: int = 15,
    after: int = 15,
) -> dict:
    """以 anchor 为中心的双向有界窗口（与旧搜索 window 相同语义）。"""
    query = db.query(ChatMessage).filter(ChatMessage.task_id == task_id)
    if query.filter(ChatMessage.sort_seq.is_(None)).with_entities(ChatMessage.id).first():
        raise HTTPException(409, "READING_HISTORY_NOT_READY")

    def fetch(key, way, count):
        rows = (
            query.filter(keyset(key, way))
            .order_by(*[c.desc() if way == "before" else c.asc() for c in ORDER_COLUMNS])
            .limit(count + 1)
            .all()
        )
        more = len(rows) > count
        return (list(reversed(rows[:count])) if way == "before" else rows[:count]), more

    key = order_key_of(anchor)
    left, has_before = fetch(key, "before", before)
    right, has_after = fetch(key, "after", after)
    rows: List[ChatMessage] = left + [anchor] + right
    return {
        "anchor": anchor,
        "rows": rows,
        "has_before": has_before,
        "has_after": has_after,
    }
