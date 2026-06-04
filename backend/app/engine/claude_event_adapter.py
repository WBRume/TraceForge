"""
Utilities for normalizing Claude CLI stream-json events.

The same adapter is used by task workflow and API MOCK sync pipelines so
both surfaces share consistent event semantics and log rendering.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List

MAX_TEXT_LEN = 2000
MAX_RAW_JSON_LEN = 5000

COMPACTION_SIGNAL_RE = re.compile(
    r"(compact(?:ion|ed|ing)?|context[_\s-]*(?:compress|compact|summar)|conversation[_\s-]*(?:compress|compact)|上下文压缩|压缩上下文)",
    re.IGNORECASE,
)
COMPACTION_EVENT_METADATA_KEYS = ("type", "subtype", "event", "name", "kind", "reason")


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _to_text(value: Any, *, max_len: int = MAX_TEXT_LEN) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if len(text) > max_len:
        return f"{text[:max_len]}..."
    return text


def _safe_json_text(value: Any, *, max_len: int = MAX_RAW_JSON_LEN) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        raw = _to_text(value, max_len=max_len)
    if len(raw) > max_len:
        return f"{raw[:max_len]}..."
    return raw


def _normalize_usage_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _flatten_usage(value: Any, prefix: str = "") -> Dict[str, Any]:
    flat: Dict[str, Any] = {}
    if not isinstance(value, dict):
        return flat
    for key, child in value.items():
        key_text = str(key or "")
        path = f"{prefix}.{key_text}" if prefix else key_text
        if isinstance(child, dict):
            flat.update(_flatten_usage(child, path))
            continue
        normalized_path = _normalize_usage_key(path)
        normalized_leaf = _normalize_usage_key(key_text)
        if normalized_path:
            flat.setdefault(normalized_path, child)
        if normalized_leaf:
            flat.setdefault(normalized_leaf, child)
    return flat


def _first_usage_int(flat: Dict[str, Any], aliases: List[str]) -> int | None:
    for alias in aliases:
        value = _safe_int(flat.get(_normalize_usage_key(alias)))
        if value is not None:
            return value
    return None


def _event_metadata_has_compaction_signal(event: Dict[str, Any]) -> bool:
    metadata: List[str] = []
    for key in COMPACTION_EVENT_METADATA_KEYS:
        metadata.append(str(key))
        metadata.append(_to_text(event.get(key), max_len=200))
    metadata.extend(str(key) for key in event.keys())
    return bool(COMPACTION_SIGNAL_RE.search(" ".join(item for item in metadata if item)))


def _usage_candidate_from_event(event: Dict[str, Any]) -> Any:
    event_type = _to_text(event.get("type"), max_len=64).lower()
    if event_type == "assistant":
        message = event.get("message")
        if isinstance(message, dict) and isinstance(message.get("usage"), dict):
            return message.get("usage")
    if isinstance(event.get("usage"), dict):
        return event.get("usage")
    tokenish_keys = {
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_read_input_tokens",
        "cache_creation_tokens",
        "cache_creation_input_tokens",
        "thinking_tokens",
        "tool_io_tokens",
        "total_tokens",
    }
    if any(key in event for key in tokenish_keys):
        return {key: event.get(key) for key in tokenish_keys if key in event}
    return None


def normalize_claude_usage(raw_usage: Any) -> Dict[str, Any] | None:
    """
    Normalize Claude stream-json usage into provider token fields.

    Only explicit usage fields are returned. Character counts or attribution
    units are intentionally not used as token estimates.
    """
    if not isinstance(raw_usage, dict):
        return None
    flat = _flatten_usage(raw_usage)
    normalized: Dict[str, Any] = {
        "input_tokens": _first_usage_int(flat, ["input_tokens", "input"]),
        "output_tokens": _first_usage_int(flat, ["output_tokens", "output"]),
        "cache_read_tokens": _first_usage_int(flat, ["cache_read_input_tokens", "cache_read_tokens", "cache_read"]),
        "cache_creation_tokens": _first_usage_int(
            flat,
            ["cache_creation_input_tokens", "cache_creation_tokens", "cache_create_tokens", "cache_write_tokens"],
        ),
        "thinking_tokens": _first_usage_int(
            flat,
            ["thinking_tokens", "reasoning_tokens", "output_tokens_details.thinking_tokens", "output_tokens_details.reasoning_tokens"],
        ),
        "tool_io_tokens": _first_usage_int(flat, ["tool_io_tokens", "server_tool_use_tokens"]),
        "total_tokens": _first_usage_int(flat, ["total_tokens", "tokens_total"]),
    }
    if normalized["tool_io_tokens"] is None:
        tool_parts = [
            _first_usage_int(flat, ["tool_input_tokens"]),
            _first_usage_int(flat, ["tool_output_tokens", "tool_result_tokens"]),
        ]
        known_tool_parts = [value for value in tool_parts if value is not None]
        if known_tool_parts:
            normalized["tool_io_tokens"] = sum(known_tool_parts)
    if normalized["total_tokens"] is None:
        parts = [
            normalized["input_tokens"],
            normalized["output_tokens"],
            normalized["cache_read_tokens"],
            normalized["cache_creation_tokens"],
            normalized["thinking_tokens"],
            normalized["tool_io_tokens"],
        ]
        known = [value for value in parts if value is not None]
        if known:
            normalized["total_tokens"] = sum(known)
    if not any(value is not None for value in normalized.values()):
        return None
    normalized["raw_usage"] = raw_usage
    return normalized


def extract_claude_usage(event: Dict[str, Any]) -> Dict[str, Any] | None:
    return normalize_claude_usage(_usage_candidate_from_event(event))


def extract_claude_compaction_event(event: Dict[str, Any]) -> Dict[str, Any] | None:
    """
    Detect Claude stream-json context compaction events.

    Claude CLI event names are not treated as a stable public contract here, so
    this parser intentionally accepts a small family of compact/compression
    signals and only reports explicit token values when the event carries them.
    """
    if not isinstance(event, dict):
        return None
    if not _event_metadata_has_compaction_signal(event):
        return None

    flat = _flatten_usage(event)
    token_before = _first_usage_int(
        flat,
        [
            "token_before",
            "tokens_before",
            "before_tokens",
            "pre_compaction_tokens",
            "pre_compact_tokens",
            "context_tokens_before",
            "input_tokens_before",
            "total_tokens_before",
            "original_tokens",
        ],
    )
    token_after = _first_usage_int(
        flat,
        [
            "token_after",
            "tokens_after",
            "after_tokens",
            "post_compaction_tokens",
            "post_compact_tokens",
            "context_tokens_after",
            "input_tokens_after",
            "total_tokens_after",
            "compacted_tokens",
        ],
    )
    event_type = _to_text(event.get("type"), max_len=80) or "compaction"
    subtype = _to_text(event.get("subtype") or event.get("event") or event.get("name"), max_len=80)
    return {
        "event_type": event_type,
        "subtype": subtype,
        "session_id": _to_text(event.get("session_id"), max_len=120),
        "token_before": token_before,
        "token_after": token_after,
        "raw_event": event,
    }


def _normalized_entry(
    *,
    entry_type: str,
    subtype: str = "",
    text: str = "",
    tool_name: str = "",
    tool_use_id: str = "",
    session_id: str = "",
    is_error: bool = False,
    raw: Any = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ts": _utc_now_iso(),
        "type": _to_text(entry_type, max_len=64) or "unknown",
    }
    subtype_text = _to_text(subtype, max_len=64)
    if subtype_text:
        payload["subtype"] = subtype_text
    body_text = _to_text(text)
    if body_text:
        payload["text"] = body_text
    tool_name_text = _to_text(tool_name, max_len=200)
    if tool_name_text:
        payload["tool_name"] = tool_name_text
    tool_use_text = _to_text(tool_use_id, max_len=200)
    if tool_use_text:
        payload["tool_use_id"] = tool_use_text
    session_text = _to_text(session_id, max_len=100)
    if session_text:
        payload["session_id"] = session_text
    if is_error:
        payload["is_error"] = True
    if raw is not None:
        payload["raw"] = raw
    return payload


def _tool_result_output_to_text(output: Any) -> str:
    if isinstance(output, list):
        lines: List[str] = []
        for item in output:
            if isinstance(item, dict):
                line = _to_text(item.get("text") or item.get("output"))
            else:
                line = _to_text(item)
            if line:
                lines.append(line)
        return _to_text("\n".join(lines))
    return _to_text(output)


def flatten_claude_event(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convert one Claude stream-json event into normalized timeline entries.
    """
    entries: List[Dict[str, Any]] = []
    event_type = _to_text(event.get("type"), max_len=64).lower()
    compaction = extract_claude_compaction_event(event)
    if compaction:
        parts = ["context compaction detected"]
        if compaction.get("token_before") is not None or compaction.get("token_after") is not None:
            parts.append(f"tokens {compaction.get('token_before') or '?'} -> {compaction.get('token_after') or '?'}")
        entries.append(
            _normalized_entry(
                entry_type="compaction",
                subtype=str(compaction.get("subtype") or event_type or ""),
                text="; ".join(parts),
                session_id=str(compaction.get("session_id") or ""),
                raw={
                    "type": event.get("type"),
                    "subtype": event.get("subtype"),
                    "event": event.get("event"),
                    "name": event.get("name"),
                    "token_before": compaction.get("token_before"),
                    "token_after": compaction.get("token_after"),
                },
            )
        )
        return entries

    if event_type == "system":
        subtype = _to_text(event.get("subtype"), max_len=64)
        session_id = _to_text(event.get("session_id"), max_len=120)
        model = _to_text(event.get("model"), max_len=120)
        text = f"system {subtype or 'event'}"
        if subtype == "init":
            suffix: List[str] = []
            if model:
                suffix.append(f"model={model}")
            if session_id:
                suffix.append(f"session={session_id}")
            if suffix:
                text = f"session initialized ({', '.join(suffix)})"
            else:
                text = "session initialized"
        entries.append(
            _normalized_entry(
                entry_type="system",
                subtype=subtype,
                text=text,
                session_id=session_id,
                raw={
                    "type": event.get("type"),
                    "subtype": event.get("subtype"),
                    "session_id": event.get("session_id"),
                    "model": event.get("model"),
                },
            )
        )
        return entries

    if event_type == "assistant":
        message = event.get("message")
        content_blocks = message.get("content", []) if isinstance(message, dict) else []
        if not isinstance(content_blocks, list):
            content_blocks = []
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            block_type = _to_text(block.get("type"), max_len=64).lower()
            if block_type == "thinking":
                text = _to_text(block.get("thinking"))
                if text:
                    entries.append(
                        _normalized_entry(
                            entry_type="thinking",
                            text=text,
                            raw={"type": "thinking", "thinking": text},
                        )
                    )
                continue
            if block_type == "text":
                text = _to_text(block.get("text"))
                if text:
                    entries.append(
                        _normalized_entry(
                            entry_type="text",
                            text=text,
                            raw={"type": "text", "text": text},
                        )
                    )
                continue
            if block_type == "tool_use":
                tool_name = _to_text(block.get("name"), max_len=200)
                tool_use_id = _to_text(block.get("id"), max_len=200)
                input_text = _safe_json_text(block.get("input"))
                summary = f"{tool_name} {input_text}".strip()
                entries.append(
                    _normalized_entry(
                        entry_type="tool_use",
                        text=summary,
                        tool_name=tool_name,
                        tool_use_id=tool_use_id,
                        raw={
                            "type": "tool_use",
                            "name": tool_name,
                            "id": tool_use_id,
                            "input": block.get("input"),
                        },
                    )
                )
                continue
            if block_type == "tool_result":
                tool_use_id = _to_text(block.get("tool_use_id"), max_len=200)
                output_text = _tool_result_output_to_text(block.get("output", block.get("content")))
                entries.append(
                    _normalized_entry(
                        entry_type="tool_result",
                        text=output_text,
                        tool_use_id=tool_use_id,
                        is_error=bool(block.get("is_error")),
                        raw={
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "is_error": bool(block.get("is_error")),
                            "output": block.get("output", block.get("content")),
                        },
                    )
                )
                continue
            entries.append(
                _normalized_entry(
                    entry_type="assistant_event",
                    subtype=block_type or "unknown",
                    text=_safe_json_text(block),
                    raw={"type": block_type, "block": block},
                )
            )
        return entries

    if event_type == "result":
        subtype = _to_text(event.get("subtype"), max_len=64)
        result_text = _to_text(event.get("result"))
        usage = extract_claude_usage(event)
        if not result_text:
            result_text = _safe_json_text(
                {
                    "duration_ms": event.get("duration_ms"),
                    "total_cost_usd": event.get("total_cost_usd"),
                    "usage": {key: value for key, value in (usage or {}).items() if key != "raw_usage"} if usage else None,
                }
            )
        entries.append(
            _normalized_entry(
                entry_type="result",
                subtype=subtype,
                text=result_text,
                session_id=_to_text(event.get("session_id"), max_len=120),
                is_error=bool(event.get("is_error")),
                raw={
                    "type": event.get("type"),
                    "subtype": event.get("subtype"),
                    "is_error": bool(event.get("is_error")),
                    "duration_ms": event.get("duration_ms"),
                    "total_cost_usd": event.get("total_cost_usd"),
                    "usage": {key: value for key, value in (usage or {}).items() if key != "raw_usage"} if usage else None,
                    "result": event.get("result"),
                },
            )
        )
        return entries

    entries.append(
        _normalized_entry(
            entry_type=event_type or "unknown",
            text=_safe_json_text(event),
            raw={"event": event},
        )
    )
    return entries


def format_claude_event_log_line(entry: Dict[str, Any]) -> str:
    """
    Render one normalized timeline entry into a concise human-readable line.
    """
    event_type = _to_text(entry.get("type"), max_len=64).lower()
    subtype = _to_text(entry.get("subtype"), max_len=64)
    text = _to_text(entry.get("text"))
    tool_name = _to_text(entry.get("tool_name"), max_len=200)
    tool_use_id = _to_text(entry.get("tool_use_id"), max_len=200)
    is_error = bool(entry.get("is_error"))

    if event_type == "thinking":
        return f"[thinking] {text}" if text else "[thinking]"
    if event_type == "text":
        return f"[assistant] {text}" if text else "[assistant]"
    if event_type == "tool_use":
        tool_label = tool_name or "tool"
        suffix = f"#{tool_use_id}" if tool_use_id else ""
        if text:
            return f"[tool_use] {tool_label}{suffix} {text}"
        return f"[tool_use] {tool_label}{suffix}"
    if event_type == "tool_result":
        suffix = f"#{tool_use_id}" if tool_use_id else ""
        prefix = "[tool_result:error]" if is_error else "[tool_result]"
        if text:
            return f"{prefix}{suffix} {text}"
        return f"{prefix}{suffix}"
    if event_type == "system":
        return f"[system{':' + subtype if subtype else ''}] {text}".strip()
    if event_type == "result":
        prefix = "[result:error]" if is_error else "[result]"
        if subtype:
            prefix = f"{prefix}:{subtype}"
        if text:
            return f"{prefix} {text}"
        return prefix
    if event_type == "compaction":
        prefix = "[compaction]"
        if subtype:
            prefix = f"{prefix}:{subtype}"
        if text:
            return f"{prefix} {text}"
        return prefix
    if text:
        return f"[{event_type or 'event'}] {text}"
    return f"[{event_type or 'event'}]"
