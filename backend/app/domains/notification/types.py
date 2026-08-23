"""
站内信类型注册表

各业务线接入站内信时在此注册类型元信息（编码 / 分组 / 说明 / payload 契约）。
新增通知来源只需两步：
1. 这里 register 一条 NotificationTypeInfo；
2. 前端 registry.ts 中注册同名类型的图标与点击跳转行为。

dispatch_notifications 会对未注册的类型告警（仍会投递，不阻断业务）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class NotificationTypeInfo:
    code: str
    category: str          # 展示分组：collab / task / system ...
    description: str
    payload_keys: tuple[str, ...] = field(default=())  # payload_json 约定字段，用于文档与排障


_REGISTRY: dict[str, NotificationTypeInfo] = {}


def register(info: NotificationTypeInfo) -> NotificationTypeInfo:
    _REGISTRY[info.code] = info
    return info


def get_notification_type(code: str) -> Optional[NotificationTypeInfo]:
    return _REGISTRY.get(str(code or ""))


def list_notification_types() -> list[NotificationTypeInfo]:
    return sorted(_REGISTRY.values(), key=lambda info: (info.category, info.code))


def is_registered(code: str) -> bool:
    return code in _REGISTRY


# ── 内置类型：协作预输入 ──

register(NotificationTypeInfo(
    code="pre_input_mention",
    category="collab",
    description="协作预输入 @提醒：邀请被 @ 成员参与会话预输入",
    payload_keys=("task_id", "task_name", "workspace_id", "pre_input_id", "deadline_at"),
))

register(NotificationTypeInfo(
    code="pre_input_submitted",
    category="collab",
    description="协作预输入已提交执行：通知发起人与参与成员",
    payload_keys=("task_id", "task_name", "workspace_id", "pre_input_id", "submit_reason"),
))
