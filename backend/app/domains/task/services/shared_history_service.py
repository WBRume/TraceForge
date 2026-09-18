"""
公开分享历史：有效历史查询与白名单投影。

公开 history 不复用内部响应 JSON：
- 只返回 message_id / role / content / safe_message_type / created_at /
  safe_card_summary，不返回 metadata_json、系统提示、内部推理、
  执行日志、终端事件、绝对文件路径与签名下载地址；
- 只读卡片转成文字摘要；未适配卡片显示“此内容不支持分享展示”；
- `session_generation IS NULL` 的历史数据不直接对外放行；
- 游标绑定 share_id + generation + 稳定排序位置；代次或 revision
  变化时游标失效返回 409。
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.domains.task.models.chat import ChatMessage, MessageRole, MessageType
from app.domains.task.models.session_share import TaskSessionShare
from app.domains.task.models.session_turn import TaskSessionTurn, TaskSessionTurnStatus
from app.domains.task.models.task import SddTask
from app.domains.task.services.session_share_service import ShareError

PAGE_SIZE_DEFAULT = 50
PAGE_SIZE_MAX = 100

# 公开页安全展示的消息类型；其余类型仅给可读摘要或占位
_SAFE_MESSAGE_TYPES = {
    MessageType.TEXT.value,
    MessageType.THINKING.value,
    MessageType.PLAN_CARD.value,
    MessageType.PROGRESS_CARD.value,
    MessageType.TEST_REPORT_CARD.value,
    MessageType.HITL_BOOLEAN.value,
    MessageType.HITL_SELECT.value,
    MessageType.DIAGNOSIS_RESULT.value,
}


class SharedHistoryCursorError(ShareError):
    """游标失效（历史已变化）：前端应清空缓存重新拉取。"""

    def __init__(self, message: str = "历史已变化，请刷新页面重新加载") -> None:
        super().__init__(message, code="SHARE_HISTORY_STALE", status_code=409)


def _encode_cursor(share_id: str, generation: int, revision: int, offset: int) -> str:
    payload = json.dumps(
        {"s": share_id, "g": int(generation), "r": int(revision), "o": int(offset)},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> Dict[str, int]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        return {
            "share_id": str(payload["s"]),
            "generation": int(payload["g"]),
            "revision": int(payload["r"]),
            "offset": int(payload["o"]),
        }
    except Exception as exc:
        raise SharedHistoryCursorError("分页游标无效") from exc


def _card_summary(metadata: Optional[dict], content: str) -> Optional[str]:
    """结构化卡片的只读摘要；不可用时返回占位提示。"""
    if not isinstance(metadata, dict):
        return None
    summary = metadata.get("summary") or metadata.get("title") or metadata.get("message")
    if summary and isinstance(summary, str):
        return summary[:300]
    text = (content or "").strip()
    if text:
        return text[:300]
    return "此内容不支持分享展示"


def _order_index_expr():
    # 与 task_service.get_task_history 的排序键一致
    return sqlfunc.coalesce(
        ChatMessage.sort_seq,
        ChatMessage.metadata_json["order_index"].as_integer(),
        0,
    )


def _project_message(msg: ChatMessage) -> Dict[str, Any]:
    message_type = msg.message_type.value if hasattr(msg.message_type, "value") else str(msg.message_type)
    safe_type = message_type if message_type in _SAFE_MESSAGE_TYPES else "unsupported"
    metadata = msg.metadata_json if isinstance(msg.metadata_json, dict) else {}
    return {
        "message_id": msg.id,
        "role": msg.role.value if hasattr(msg.role, "value") else str(msg.role),
        "content": msg.content or "",
        "safe_message_type": safe_type,
        "created_at": msg.created_at,
        # 仅结构化卡片给摘要；普通文本消息 content 已可见
        "safe_card_summary": _card_summary(metadata, msg.content) if message_type not in (
            MessageType.TEXT.value, MessageType.THINKING.value
        ) else None,
    }


def _effective_generation_filter(share: TaskSessionShare):
    """分享范围内只含绑定代次且 generation 非 NULL 的消息。"""
    return (
        ChatMessage.task_id == share.task_id,
        ChatMessage.session_generation == int(share.session_generation or 0),
    )


def load_shared_history(
    db: Session,
    *,
    share: TaskSessionShare,
    task: SddTask,
    cursor: Optional[str],
    page_size: int,
) -> Dict[str, Any]:
    """按绑定代次分页读取公开历史（倒序分页 + 块内正序，与内部历史一致）。"""
    page_size = max(1, min(int(page_size or PAGE_SIZE_DEFAULT), PAGE_SIZE_MAX))
    generation = int(share.session_generation or 0)

    offset = 0
    if cursor:
        decoded = _decode_cursor(cursor)
        if decoded["share_id"] != share.id or decoded["generation"] != generation:
            raise SharedHistoryCursorError()
        # revision 变化不必撤销分享，但必须使旧游标失效
        if decoded["revision"] != int(task.session_revision or 0):
            raise SharedHistoryCursorError()
        offset = max(0, decoded["offset"])

    task_filter, generation_filter = _effective_generation_filter(share)
    total = (
        db.query(sqlfunc.count(ChatMessage.id))
        .filter(task_filter, generation_filter)
        .scalar()
        or 0
    )

    rows_desc = (
        db.query(ChatMessage)
        .filter(task_filter, generation_filter)
        .order_by(
            ChatMessage.created_at.desc(),
            _order_index_expr().desc(),
            ChatMessage.id.desc(),
        )
        .offset(offset)
        .limit(page_size)
        .all()
    )
    # 与内部历史一致：向前翻页，块内按落库顺序正序
    msg_query = list(reversed(rows_desc))
    messages = [_project_message(msg) for msg in msg_query]

    next_offset = offset + len(rows_desc)
    has_more = next_offset < total
    next_cursor = (
        _encode_cursor(share.id, generation, int(task.session_revision or 0), next_offset)
        if has_more
        else None
    )

    return {
        "messages": messages,
        "has_more": has_more,
        "next_cursor": next_cursor,
    }
