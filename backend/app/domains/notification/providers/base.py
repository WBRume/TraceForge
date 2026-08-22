"""
外部通知渠道 provider 抽象。

本期仅实现 logging 占位 provider（写日志）；webhook / 邮件等真实渠道
后续按需追加，并在 config.NOTIFICATION_PROVIDERS 中启用。
"""

from abc import ABC, abstractmethod

from app.core.logging import get_logger

logger = get_logger(__name__, category="task_execution")

PROVIDER_NAME = "logging"


class NotificationProvider(ABC):
    """外部通知渠道接口：send 失败仅记录日志，不影响站内信投递。"""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    async def send(self, notifications: list[dict]) -> bool:
        """将一组已落库的通知发往外部渠道，返回是否全部成功。"""
        ...


class LoggingNotificationProvider(NotificationProvider):
    @property
    def name(self) -> str:
        return PROVIDER_NAME

    async def send(self, notifications: list[dict]) -> bool:
        for item in notifications:
            logger.info(
                f"[external-notification:{self.name}] -> user {item.get('recipient_user_id')}: "
                f"{item.get('title')}"
            )
        return True


_PROVIDER_REGISTRY: dict[str, type[NotificationProvider]] = {
    PROVIDER_NAME: LoggingNotificationProvider,
}


def create_provider(name: str) -> NotificationProvider | None:
    cls = _PROVIDER_REGISTRY.get(name.strip())
    return cls() if cls else None


def build_configured_providers(configured: str) -> list[NotificationProvider]:
    providers: list[NotificationProvider] = []
    for name in [part.strip() for part in (configured or "").split(",") if part.strip()]:
        provider = create_provider(name)
        if provider:
            providers.append(provider)
        else:
            logger.warning(f"Unknown notification provider configured: {name}")
    return providers
