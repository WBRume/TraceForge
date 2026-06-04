"""Redis-backed idempotency guard for task chat messages."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from app.config import settings
from app.core.redis_client import get_redis_client


class ChatMessageIdempotencyUnavailable(RuntimeError):
    """Raised when Redis cannot provide the idempotency gate."""


@dataclass(frozen=True)
class ChatMessageClaim:
    status: str
    key: str
    client_message_id: str
    content_hash: str
    existing: Optional[Dict[str, Any]] = None

    @property
    def claimed(self) -> bool:
        return self.status == "claimed"


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _normalize_part(value: str, *, field: str, max_length: int = 256) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    if len(normalized) > max_length:
        raise ValueError(f"{field} is too long")
    return normalized


def _content_hash(content: str) -> str:
    return hashlib.sha256(str(content or "").encode("utf-8")).hexdigest()


def _claim_key(task_id: str, user_id: str, client_message_id: str) -> str:
    raw = "|".join([task_id, user_id, client_message_id])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    prefix = str(settings.DISTRIBUTED_LOCK_KEY_PREFIX or "sdd-native").strip() or "sdd-native"
    return f"{prefix}:chat-message-idempotency:{digest}"


def _encode(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def _decode(raw: Any) -> Optional[Dict[str, Any]]:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(str(raw))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _ttl() -> int:
    value = int(settings.CHAT_MESSAGE_IDEMPOTENCY_TTL_SECONDS or 86400)
    return max(value, 60)


async def claim_message(
    *,
    task_id: str,
    user_id: str,
    client_message_id: str,
    content: str,
) -> ChatMessageClaim:
    task_id = _normalize_part(task_id, field="task_id")
    user_id = _normalize_part(user_id, field="user_id")
    client_message_id = _normalize_part(
        client_message_id,
        field="client_message_id",
        max_length=128,
    )
    digest = _content_hash(content)
    key = _claim_key(task_id, user_id, client_message_id)
    payload = {
        "state": "processing",
        "task_id": task_id,
        "user_id": user_id,
        "client_message_id": client_message_id,
        "content_hash": digest,
        "created_at": _now_iso(),
    }

    try:
        client = await get_redis_client()
        claimed = await client.set(key, _encode(payload), nx=True, ex=_ttl())
    except Exception as exc:  # pragma: no cover - exact redis exception types vary
        raise ChatMessageIdempotencyUnavailable(str(exc)) from exc

    if claimed:
        return ChatMessageClaim(
            status="claimed",
            key=key,
            client_message_id=client_message_id,
            content_hash=digest,
        )

    existing = await get_message_claim_by_key(key)
    if not existing:
        return ChatMessageClaim(
            status="processing",
            key=key,
            client_message_id=client_message_id,
            content_hash=digest,
        )

    if str(existing.get("content_hash") or "") != digest:
        return ChatMessageClaim(
            status="conflict",
            key=key,
            client_message_id=client_message_id,
            content_hash=digest,
            existing=existing,
        )

    state = str(existing.get("state") or "processing").lower()
    return ChatMessageClaim(
        status="done" if state == "done" else "processing",
        key=key,
        client_message_id=client_message_id,
        content_hash=digest,
        existing=existing,
    )


async def get_message_claim_by_key(key: str) -> Optional[Dict[str, Any]]:
    try:
        client = await get_redis_client()
        raw = await client.get(str(key or ""))
    except Exception as exc:  # pragma: no cover - exact redis exception types vary
        raise ChatMessageIdempotencyUnavailable(str(exc)) from exc
    return _decode(raw)


async def mark_message_done(
    claim: ChatMessageClaim,
    *,
    chat_message_id: str,
    ai_job_id: Optional[str] = None,
) -> None:
    existing = dict(claim.existing or {})
    existing.update(
        {
            "state": "done",
            "client_message_id": claim.client_message_id,
            "content_hash": claim.content_hash,
            "chat_message_id": str(chat_message_id or ""),
            "ai_job_id": str(ai_job_id or "") or None,
            "finished_at": _now_iso(),
        }
    )
    try:
        client = await get_redis_client()
        await client.set(claim.key, _encode(existing), ex=_ttl())
    except Exception as exc:  # pragma: no cover - exact redis exception types vary
        raise ChatMessageIdempotencyUnavailable(str(exc)) from exc


async def mark_message_failed(claim: ChatMessageClaim) -> None:
    try:
        client = await get_redis_client()
        await client.delete(claim.key)
    except Exception as exc:  # pragma: no cover - exact redis exception types vary
        raise ChatMessageIdempotencyUnavailable(str(exc)) from exc
