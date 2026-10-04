"""Follower notification policy for persisted conversation messages."""

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domains.task.models.chat import ChatMessage, MessageRole
from app.domains.task.models.task import SddTask, SddTaskFollower

logger = get_logger(__name__, category="task_execution")


def notify_followers(db: Session, message: ChatMessage) -> None:
    try:
        role_value = getattr(message.role, "value", message.role)
        if str(role_value or "").lower() == MessageRole.USER.value:
            recipient_filter = SddTaskFollower.user_id != str(message.creator_id)
        else:
            recipient_filter = True
        # 单条 join：关注者 + task_name 一次往返
        follower_rows = (
            db.query(SddTaskFollower.user_id, SddTask.name)
            .outerjoin(SddTask, SddTask.id == SddTaskFollower.task_id)
            .filter(
                SddTaskFollower.task_id == message.task_id,
                SddTaskFollower.workspace_id == message.workspace_id,
                recipient_filter,
            )
            .all()
        )
        task_name = str(follower_rows[0][1] or "任务") if follower_rows else "任务"
        follower_ids = [str(row[0]) for row in follower_rows]
        if follower_ids:
            from app.domains.notification.models.notification import SddUserNotification
            from app.domains.notification.services.notification_service import create_notifications

            # Streaming providers may persist several assistant text chunks for one
            # reply. Keep one unread notification per follower/task until it is
            # consumed, so following a task does not turn into notification spam.
            existing_rows = (
                db.query(
                    SddUserNotification.recipient_user_id,
                    SddUserNotification.payload_json,
                )
                .filter(
                    SddUserNotification.workspace_id == message.workspace_id,
                    SddUserNotification.type == "task_message",
                    SddUserNotification.read_at.is_(None),
                    SddUserNotification.recipient_user_id.in_(follower_ids),
                )
                .all()
            )
            already_notified = {
                str(recipient_id)
                for recipient_id, payload in existing_rows
                if isinstance(payload, dict) and str(payload.get("task_id") or "") == str(message.task_id)
            }
            follower_ids = [uid for uid in follower_ids if uid not in already_notified]
        if follower_ids:
            create_notifications(
                db,
                follower_ids,
                type="task_message",
                title=f"「{task_name}」有新消息",
                body=str(message.content or "")[:120],
                payload_json={
                    "task_id": message.task_id,
                    "task_name": task_name,
                    "workspace_id": message.workspace_id,
                    "message_id": message.id,
                    "message_type": message.message_type,
                },
                workspace_id=message.workspace_id,
            )
    except Exception:
        db.rollback()
        logger.exception("Failed to create task message notifications")
