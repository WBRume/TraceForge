"""Shared protocol primitives for reliable WebSocket room delivery.

The room journal is a short-lived transport recovery mechanism.  Durable
state remains in the domain REST/SQL APIs; an epoch change or an expired
cursor therefore produces an explicit ``resync_required`` control frame.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


SERVER_EPOCH = uuid.uuid4().hex


def json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8"))


@dataclass(frozen=True)
class EventEnvelope:
    """One sequenced business event in a room journal."""

    room: str
    epoch: str
    sequence: int
    event_id: str
    event_type: str
    payload: Any
    aggregate_id: Optional[str] = None
    aggregate_version: Optional[int] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "event",
            "room": self.room,
            "epoch": self.epoch,
            "sequence": self.sequence,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "aggregate_id": self.aggregate_id,
            "aggregate_version": self.aggregate_version,
            "payload": self.payload,
            "created_at": self.created_at,
        }


def control_frame(
    frame_type: str,
    *,
    epoch: Optional[str] = None,
    from_sequence: Optional[int] = None,
    to_sequence: Optional[int] = None,
    barrier_sequence: Optional[int] = None,
    high_watermark: Optional[int] = None,
    reason: Optional[str] = None,
) -> dict[str, Any]:
    frame: dict[str, Any] = {"type": frame_type}
    if epoch is not None:
        frame["epoch"] = epoch
    if from_sequence is not None:
        frame["from_sequence"] = from_sequence
    if to_sequence is not None:
        frame["to_sequence"] = to_sequence
    if barrier_sequence is not None:
        frame["barrier_sequence"] = barrier_sequence
    if high_watermark is not None:
        frame["high_watermark"] = high_watermark
    if reason is not None:
        frame["reason"] = reason
    return frame


CONTROL_FRAME_TYPES = {
    "ping",
    "pong",
    "resume",
    "resume_ok",
    "resync_required",
    "resync_complete",
    "resync_ok",
}

NON_SEQUENCED_EVENT_TYPES = {
    "ping",
    "pong",
    "presence",
    "typing",
}
