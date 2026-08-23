"""
通知投递编排：站内信落库 → 用户级 WS 实时推送 → 外部 provider。

调用方只需构造收件人与内容；推送失败静默（前端有未读数兜底拉取）。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.config import settings
from app.domains.notification.providers.base import build_configured_providers
from app.domains.notification.services import notification_service
from app.domains.notification.types import is_registered
from app.domains.notification.ws.notification_manager import notification_ws_manager

logger = get_logger(__name__, category="task_execution")

# 惰性构建，避免测试环境导入时读配置
_providers = None


def _get_providers():
    global _providers
    if _providers is None:
        _providers = build_configured_providers(settings.NOTIFICATION_PROVIDERS)
    return _providers


async def dispatch_notifications(
    db: Session,
    recipient_user_ids: list[str],
    *,
    type: str,
    title: str,
    body: str | None = None,
    payload_json: dict | None = None,
    workspace_id: str | None = None,
) -> list[dict]:
    # 新通知来源需在 notification/types.py 注册；未注册仍投递，但留下告警便于排查遗漏
    if not is_registered(type):
        logger.warning(f"Dispatching unregistered notification type '{type}' — register it in app.domains.notification.types")
    created = notification_service.create_notifications(
        db,
        recipient_user_ids,
        type=type,
        title=title,
        body=body,
        payload_json=payload_json,
        workspace_id=workspace_id,
    )
    serialized = [
        {
            "id": row.id,
            "workspace_id": row.workspace_id,
            "recipient_user_id": row.recipient_user_id,
            "type": row.type,
            "title": row.title,
            "body": row.body,
            "payload": row.payload_json if isinstance(row.payload_json, dict) else None,
            "read_at": None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in created
    ]
    for item in serialized:
        try:
            await notification_ws_manager.send_message_to_user(item["recipient_user_id"], item)
        except Exception as exc:
            logger.warning(f"Notification realtime push failed for user {item['recipient_user_id']}: {exc}")

    providers = _get_providers()
    if providers and serialized:
        for provider in providers:
            try:
                await provider.send(serialized)
            except Exception as exc:
                logger.warning(f"Notification provider '{provider.name}' failed: {exc}")

    return serialized
