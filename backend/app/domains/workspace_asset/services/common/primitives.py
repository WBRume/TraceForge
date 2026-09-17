"""Workspace Asset 全域共享的值处理与查询小工具。

只放无业务分支的通用助手与跨子域复用的证据谓词；带业务语义的过程资产
展示器见 ``common.process_presenters``，写入侧校验见 ``task_process.writes_support``。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domains.workspace_asset.models.workspace_asset import (
    EvidenceSourceType,
    EvidenceStatus,
)
from app.domains.workspace_asset.schemas.workspace_asset import (
    WorkspaceAssetConnectionStatus,
    WorkspaceAssetListState,
)
from app.domains.workspace_asset.services.common.errors import WorkspaceAssetError


def enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def clean_optional(value: Optional[str], *, limit: Optional[int] = None) -> Optional[str]:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return normalized[:limit] if limit else normalized


def normalize_list(values: Optional[Iterable[Any]]) -> List[str]:
    if not values:
        return []
    return [text for value in values if (text := str(value or "").strip())]


def json_dict(value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return value if isinstance(value, dict) and value else None


def payload_has_field(payload: Any, field_name: str) -> bool:
    fields_set = getattr(payload, "model_fields_set", None)
    if fields_set is None:
        fields_set = getattr(payload, "__fields_set__", set())
    return field_name in fields_set


def normalize_enum(enum_cls: Any, value: Optional[str], default: Optional[Any] = None, label: str = "value") -> Any:
    raw = str(value or (default.value if hasattr(default, "value") else default) or "").strip().upper()
    if not raw:
        return None
    try:
        return enum_cls(raw)
    except ValueError as exc:
        raise WorkspaceAssetError(f"Unsupported {label}: {value}", status_code=422) from exc


def short_text(value: Any, limit: int = 280) -> Optional[str]:
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    text = text.strip()
    if not text:
        return None
    return text if len(text) <= limit else f"{text[:limit].rstrip()}..."


def json_text(payload: Optional[Dict[str, Any]], keys: Iterable[str]) -> Optional[str]:
    """从 result/context JSON 里按候选 key 取第一个非空短文本。"""
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if value:
            return short_text(value)
    return None


def dedupe_by_id(items: Iterable[Any]) -> List[Any]:
    seen = set()
    result = []
    for item in items:
        item_id = getattr(item, "id", None)
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        result.append(item)
    return result


def count_rows(db: Session, model: Any, workspace_id: str, **filters: Any) -> int:
    query = db.query(func.count(model.id)).filter(model.workspace_id == workspace_id)
    for field, value in filters.items():
        query = query.filter(getattr(model, field) == value)
    return int(query.scalar() or 0)


def make_connection(key: str, label: str, state: str, detail: str) -> WorkspaceAssetConnectionStatus:
    return WorkspaceAssetConnectionStatus(key=key, label=label, state=state, detail=detail)


def collection_state(total: int, message: str) -> WorkspaceAssetListState:
    return WorkspaceAssetListState(empty=total == 0, message=message if total == 0 else None)


# ---------------------------------------------------------------------------
# 证据 / Coverage 谓词（Requirement 视图、Task 视图、追溯矩阵共用）
# ---------------------------------------------------------------------------


def is_human_confirmation(evidence: Any) -> bool:
    """证据是否为「已确认的人工确认」——Verified coverage 的唯一依据。"""
    return (
        enum_value(evidence.source_type) == EvidenceSourceType.HUMAN_CONFIRMATION.value
        and enum_value(evidence.status) == EvidenceStatus.CONFIRMED.value
        and bool(evidence.confirmed_by_id)
        and evidence.confirmed_at is not None
    )


def coverage_status(requirement_count: int, evidence_items: Iterable[Any]) -> str:
    """基于关联任务数与证据集合的 coverage 状态推导。"""
    if requirement_count <= 0:
        return "not_available"

    evidence_list = list(evidence_items)
    confirmed = [
        item
        for item in evidence_list
        if enum_value(item.status) == EvidenceStatus.CONFIRMED.value
    ]
    if not confirmed:
        return "waiting_evidence"
    if not any(is_human_confirmation(item) for item in confirmed):
        return "waiting_human_confirmation"
    return "verified"
