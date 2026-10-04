"""Persist chat messages, durable ordering and reading receipts in one transaction."""

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domains.task.models.chat import ChatMessage
from app.domains.task.services.conversation import notifications

logger = get_logger(__name__, category="task_execution")


def save_chat_message(
    db: Session,
    task_id: str,
    workspace_id: str,
    creator_id: str,
    role: str,
    content: str,
    message_type: str = "text",
    metadata_json: dict | None = None,
    session_turn_id: str | None = None,
    session_generation: int | None = None,
) -> ChatMessage:
    # 落库序号：同一秒内多条消息的稳定顺序依据（解决历史重载时气泡乱序）。
    # followers 与 task_name 合并为一条 join 查询，减少每条消息的 DB 往返。
    from app.domains.search.capture import allocate_chat_seq

    order_index = allocate_chat_seq(db, task_id)
    merged_metadata = dict(metadata_json or {})
    if session_turn_id:
        from app.domains.task.models.chat_submission import TaskChatSubmission
        from app.domains.task.models.session_turn import TaskSessionTurn

        turn = db.get(TaskSessionTurn, session_turn_id)
        submission = (
            db.query(TaskChatSubmission).filter_by(ai_job_id=turn.ai_job_id).first()
            if turn and turn.ai_job_id
            else None
        )
        if submission:
            merged_metadata["submission_id"] = submission.id
            merged_metadata["knowledge_state"] = "published" if submission.status == "SUCCEEDED" else "pending"
    merged_metadata["order_index"] = order_index
    msg = ChatMessage(
        task_id=task_id,
        workspace_id=workspace_id,
        creator_id=creator_id,
        role=role,
        content=content,
        message_type=message_type,
        metadata_json=merged_metadata,
        sort_seq=order_index,
        session_turn_id=session_turn_id,
        session_generation=session_generation,
    )
    db.add(msg)
    db.flush()
    # 阅读捕获与源消息同事务：task 行锁（allocate_chat_seq 已取得）内分配
    # change_seq；捕获失败让源事务回滚，不允许吞错造成永久漏记录。
    from app.domains.task.services import reading_capture_service

    reading_capture_service.record_message_change(db, task_id=task_id, message=msg)
    db.commit()
    db.refresh(msg)
    notifications.notify_followers(db, msg)
    return msg
