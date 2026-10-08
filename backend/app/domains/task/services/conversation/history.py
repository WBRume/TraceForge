"""Query, order, serialize and export the task conversation."""

from datetime import datetime

from sqlalchemy import func as sqlfunc
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.domains.auth.models.user import User, WorkspaceMember
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.log import LogType, SddExecutionLog
from app.domains.task.models.session_turn import TaskSessionTurn, TaskSessionTurnStatus
from app.domains.task.models.task import SddTask

TERMINAL_LOG_HISTORY_LIMIT = 500


def _terminal_execution_log_filter():
    """Select replayable terminal records while excluding provider debug noise."""
    return or_(
        SddExecutionLog.log_type != LogType.STDOUT,
        SddExecutionLog.content.like('{"tool_name":%'),
        SddExecutionLog.content.like('{"tool_use_id":%'),
    )


def _message_order_index(msg) -> int:
    meta = msg.metadata_json if isinstance(msg.metadata_json, dict) else {}
    try:
        return int(meta.get("order_index") or 0)
    except (TypeError, ValueError):
        return 0


def sort_chat_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    """按真实落库先后稳定排序：created_at -> 写入序号 -> id 兜底。

    created_at 只有秒级精度，同一轮流式回复的多条消息会落在同一秒；
    必须用写入时分配的 order_index 兜底，否则按随机 uuid id 排序会
    导致重新加载历史时气泡顺序被随机打乱（逆序 / 不稳定）。
    """
    return sorted(
        messages,
        key=lambda msg: (
            msg.created_at or datetime.min,
            _message_order_index(msg),
            msg.id,
        ),
    )


def export_task_session(db: Session, task_id: str, workspace_id: str) -> dict | None:
    task = db.query(SddTask).filter(SddTask.id == task_id, SddTask.workspace_id == workspace_id).first()
    if not task:
        return None

    return {
        "task_name": task.name,
        "description": task.description,
        "status": task.status,
        "project_path": task.project_path,
        "execution_location": task.execution_location,
        "local_resource_id": task.local_resource_id,
        "created_at": task.created_at.isoformat(),
        "messages": [
            {
                "role": msg.role,
                "content": msg.content,
                "message_type": msg.message_type,
                "created_at": msg.created_at.isoformat(),
            }
            for msg in sort_chat_messages(list(task.messages or []))
        ],
        "logs": [
            {"log_type": log.log_type, "content": log.content, "created_at": log.created_at.isoformat()}
            for log in task.execution_logs
        ],
    }


def get_task_history(
    db: Session,
    task_id: str,
    workspace_id: str,
    page: int = 1,
    page_size: int = 50,
    log_limit: int = TERMINAL_LOG_HISTORY_LIMIT,
) -> dict:
    task = db.query(SddTask).filter(SddTask.id == task_id, SddTask.workspace_id == workspace_id).first()

    if not task:
        return {
            "messages": [],
            "logs": [],
            "page": page,
            "page_size": page_size,
            "total": 0,
            "has_more": False,
            "logs_has_more": False,
        }

    # 分页与统计全部下推 SQL，避免聊天全量 .all() 后内存切片。
    # 第 1 页返回“最新一页”，块内仍按真实落库顺序正序；
    # 后续页向前翻，方便前端“向上加载更早消息”直接 prepend。
    page = max(1, int(page or 1))
    page_size = max(1, int(page_size or 50))
    offset_from_end = (page - 1) * page_size

    # 排序键与 sort_chat_messages 保持一致：created_at -> 写入序号 -> id 兜底。
    # order_index 存于 metadata_json（JSON 列），用可移植的 JSON 下标提取，
    # 缺失时 coalesce 0，与 _message_order_index 的兜底一致。
    order_index_expr = sqlfunc.coalesce(
        ChatMessage.sort_seq,
        ChatMessage.metadata_json["order_index"].as_integer(),
        0,
    )
    total = db.query(sqlfunc.count(ChatMessage.id)).filter(ChatMessage.task_id == task_id).scalar() or 0
    rows_desc = (
        db.query(ChatMessage)
        .filter(ChatMessage.task_id == task_id)
        .order_by(
            ChatMessage.created_at.desc(),
            order_index_expr.desc(),
            ChatMessage.id.desc(),
        )
        .offset(offset_from_end)
        .limit(page_size)
        .all()
    )
    msg_query = list(reversed(rows_desc))
    messages = serialize_history_messages(db, task, msg_query, workspace_id, task_id)

    has_more = offset_from_end + len(msg_query) < total

    # 终端历史只返回可回放的结构化事件。provider debug、assistant 文本副本等
    # 已在文件日志/聊天消息中有权威来源，不应放大 CLI 历史响应。
    log_limit = max(1, int(log_limit or TERMINAL_LOG_HISTORY_LIMIT))
    log_rows_desc = (
        db.query(SddExecutionLog)
        .filter(
            SddExecutionLog.task_id == task_id,
            SddExecutionLog.workspace_id == workspace_id,
            _terminal_execution_log_filter(),
        )
        .order_by(
            SddExecutionLog.event_order.desc(),
            SddExecutionLog.created_at.desc(),
            SddExecutionLog.id.desc(),
        )
        .limit(log_limit + 1)
        .all()
    )
    logs_has_more = len(log_rows_desc) > log_limit
    log_rows = list(reversed(log_rows_desc[:log_limit]))
    logs = [
        {
            "id": log.id,
            "type": log.log_type.value if hasattr(log.log_type, "value") else log.log_type,
            "content": log.content,
            "created_at": log.created_at.isoformat(),
        }
        for log in log_rows
    ]

    return {
        "messages": messages,
        "logs": logs,
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": has_more,
        "logs_has_more": logs_has_more,
    }


def clear_task_history(db: Session, task_id: str, workspace_id: str) -> dict:
    from app.domains.search.capture import enqueue_scope

    enqueue_scope(db, task_id=task_id, workspace_id=workspace_id)
    """
    Clear chat history and execution logs for a task.
    Old-data compatibility is intentionally not required.
    """
    task = (
        db.query(SddTask)
        .filter(
            SddTask.id == task_id,
            SddTask.workspace_id == workspace_id,
        )
        .first()
    )
    if not task:
        raise ValueError("Task not found")

    from app.domains.task.models.chat_submission import TaskChatSubmission
    from app.domains.task.services.chat_submission_service import SubmissionError, assert_no_preparing_submission

    assert_no_preparing_submission(db, task_id)
    if db.query(TaskChatSubmission.id).filter_by(active_task_id=task_id).first():
        raise SubmissionError("当前消息正在执行，请等待完成")
    db.query(TaskChatSubmission).filter_by(task_id=task_id).delete(synchronize_session=False)
    deleted_messages = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.task_id == task_id,
            ChatMessage.workspace_id == workspace_id,
        )
        .delete(synchronize_session=False)
    )

    deleted_logs = (
        db.query(SddExecutionLog)
        .filter(
            SddExecutionLog.task_id == task_id,
            SddExecutionLog.workspace_id == workspace_id,
        )
        .delete(synchronize_session=False)
    )

    # 清空历史与阅读状态失效同事务：递增 reading_epoch / change_seq，
    # 旧条目与旧 notice 失效并创建 history_cleared 提示（第 7.3 节）。
    from app.domains.task.services import reading_capture_service

    reading_capture_service.record_history_clear(db, task_id=task_id)

    db.commit()
    return {
        "deleted_chat_messages": int(deleted_messages),
        "deleted_execution_logs": int(deleted_logs),
        "deleted_total": int(deleted_messages + deleted_logs),
    }


def serialize_history_messages(db, task, msg_query, workspace_id, task_id):
    creator_ids = sorted({str(msg.creator_id or "") for msg in msg_query if str(msg.creator_id or "").strip()})
    message_ids = [msg.id for msg in msg_query]
    creators_by_id = (
        {user.id: user for user in db.query(User).filter(User.id.in_(creator_ids)).all()} if creator_ids else {}
    )
    expert_user_ids = (
        {
            member.user_id
            for member in db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id.in_(creator_ids),
                WorkspaceMember.is_expert.is_(True),
            )
            .all()
        }
        if creator_ids
        else set()
    )
    from app.domains.workspace_asset.models.workspace_asset import SddDecision

    decisions_by_message_id = (
        {
            decision.source_chat_message_id: decision.id
            for decision in db.query(SddDecision)
            .filter(
                SddDecision.workspace_id == workspace_id,
                SddDecision.task_id == task_id,
                SddDecision.source_chat_message_id.in_(message_ids),
            )
            .all()
        }
        if message_ids
        else {}
    )
    turn_ids = {str(msg.session_turn_id) for msg in msg_query if msg.session_turn_id}
    active_turn_ids = (
        {
            str(turn_id)
            for (turn_id,) in db.query(TaskSessionTurn.id)
            .filter(
                TaskSessionTurn.id.in_(turn_ids),
                TaskSessionTurn.status == TaskSessionTurnStatus.ACTIVE,
                TaskSessionTurn.checkpoint_path.isnot(None),
            )
            .all()
        }
        if turn_ids
        else set()
    )

    # 阅读身份批量装配（避免 N+1）：共享内容版本，不含任何个人进度
    reading_by_message_id = {}
    if message_ids:
        from app.domains.task.models.reading import TaskReadingItem
        from app.domains.task.services.reading_capture_service import message_item_key

        item_keys = [message_item_key(mid) for mid in message_ids]
        reading_by_message_id = {
            item.message_id: item
            for item in db.query(TaskReadingItem)
            .filter(
                TaskReadingItem.task_id == task_id,
                TaskReadingItem.item_key.in_(item_keys),
            )
            .all()
        }

    messages = []
    for msg in msg_query:
        metadata = msg.metadata_json if isinstance(msg.metadata_json, dict) else {}
        reading_item = reading_by_message_id.get(str(msg.id))
        messages.append(
            {
                "id": msg.id,
                "role": msg.role.value if hasattr(msg.role, "value") else msg.role,
                "content": msg.content,
                "type": msg.message_type.value if hasattr(msg.message_type, "value") else msg.message_type,
                "created_at": msg.created_at.isoformat(),
                "creator_id": msg.creator_id,
                "creator_display_name": creators_by_id[msg.creator_id].display_name
                if msg.creator_id in creators_by_id
                else None,
                "creator_is_workspace_expert": msg.creator_id in expert_user_ids,
                "creator_avatar_url": creators_by_id[msg.creator_id].avatar_url
                if msg.creator_id in creators_by_id
                else None,
                "creator_avatar_svg": creators_by_id[msg.creator_id].avatar_svg
                if msg.creator_id in creators_by_id
                else None,
                "client_message_id": metadata.get("client_message_id"),
                "decision_id": decisions_by_message_id.get(msg.id),
                "metadata": metadata or None,
                "session_turn_id": msg.session_turn_id,
                "session_generation": msg.session_generation,
                "reading_item_key": reading_item.item_key if reading_item is not None else None,
                "reading_change_seq": str(int(reading_item.change_seq)) if reading_item is not None else None,
                "can_undo": bool(
                    getattr(msg.role, "value", msg.role) == "user"
                    and msg.session_turn_id
                    and str(msg.session_turn_id) in active_turn_ids
                    and msg.session_generation == getattr(task, "session_generation", None)
                    and msg.id not in decisions_by_message_id
                ),
            }
        )

    from app.domains.task.services.task_confirmation_service import enrich_history

    enrich_history(db, task_id, messages)
    return messages
