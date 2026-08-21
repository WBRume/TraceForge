"""Claude Code CLI raw NDJSON 事件 → 统一 AgentEvent 映射。"""

from __future__ import annotations

import json
from typing import Any, List

from app.agents.events import AgentEvent
from app.engine.claude_event_adapter import (
    extract_claude_compaction_event,
    extract_claude_usage,
    format_claude_event_log_line,
)

PROVIDER = "claude-code"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _iso_time() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _json_text(value: Any, max_len: int = 5000) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = str(value)
    if len(text) > max_len:
        return f"{text[:max_len]}..."
    return text


def _map_assistant_block(block: dict[str, Any]) -> List[AgentEvent]:
    events: List[AgentEvent] = []
    block_type = _text(block.get("type")).lower()
    if block_type == "thinking":
        thinking = _text(block.get("thinking"))
        if thinking:
            events.append(AgentEvent(
                type="thinking",
                payload={"text": thinking},
                provider=PROVIDER,
                raw=block,
                time=_iso_time(),
            ))
    elif block_type == "text":
        text = _text(block.get("text"))
        if text:
            events.append(AgentEvent(
                type="text",
                payload={"text": text},
                provider=PROVIDER,
                raw=block,
                time=_iso_time(),
            ))
    elif block_type == "tool_use":
        tool_name = _text(block.get("name"))
        tool_use_id = _text(block.get("id"))
        events.append(AgentEvent(
            type="tool_use",
            payload={
                "tool_use_id": tool_use_id,
                "tool_name": tool_name,
                "tool_input": block.get("input", {}),
            },
            provider=PROVIDER,
            raw=block,
            time=_iso_time(),
        ))
    elif block_type == "tool_result":
        output = block.get("output", block.get("content"))
        if isinstance(output, list):
            parts: List[str] = []
            for item in output:
                if isinstance(item, dict):
                    parts.append(_text(item.get("text") or item.get("output")))
                else:
                    parts.append(_text(item))
            output_text = "\n".join(p for p in parts if p)
        else:
            output_text = _text(output)
        events.append(AgentEvent(
            type="tool_result",
            payload={
                "tool_use_id": _text(block.get("tool_use_id")),
                "output": output_text,
                "is_error": bool(block.get("is_error")),
            },
            provider=PROVIDER,
            raw=block,
            time=_iso_time(),
        ))
    return events


def map_claude_event(event: dict[str, Any]) -> List[AgentEvent]:
    """把一个 Claude CLI stream-json 事件转换为 0~N 个 AgentEvent。"""
    if not isinstance(event, dict):
        return []

    events: List[AgentEvent] = []
    event_type = _text(event.get("type")).lower()
    subtype = _text(event.get("subtype")).lower()

    compaction = extract_claude_compaction_event(event)
    if compaction:
        events.append(AgentEvent(
            type="context_compacted",
            payload={
                "summary": "",
                "source": "claude-code",
                "token_before": compaction.get("token_before"),
                "token_after": compaction.get("token_after"),
                "event_type": compaction.get("event_type"),
                "subtype": compaction.get("subtype"),
            },
            provider=PROVIDER,
            raw=event,
            time=_iso_time(),
        ))
        return events

    if event_type == "system" and subtype == "init":
        return [AgentEvent(
            type="session_started",
            payload={
                "provider_session_id": _text(event.get("session_id")),
                "model": _text(event.get("model")),
            },
            provider=PROVIDER,
            raw=event,
            time=_iso_time(),
        )]

    if event_type == "assistant":
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        blocks = message.get("content") if isinstance(message.get("content"), list) else []
        for block in blocks:
            if isinstance(block, dict):
                events.extend(_map_assistant_block(block))
        usage = extract_claude_usage(event)
        if usage:
            events.append(AgentEvent(
                type="usage",
                payload={key: value for key, value in usage.items() if key != "raw_usage"},
                provider=PROVIDER,
                raw=event,
                time=_iso_time(),
            ))
        return events

    if event_type == "result":
        is_error = bool(event.get("is_error")) or subtype == "error"
        usage = extract_claude_usage(event)
        result_text = _text(event.get("result"))
        if not result_text:
            result_text = _json_text({k: event.get(k) for k in ("duration_ms", "total_cost_usd") if event.get(k) is not None})
        payload: dict[str, Any] = {
            "success": not is_error,
            "result": result_text,
            "finish_reason": "error" if is_error else "completed",
            "session_id": _text(event.get("session_id")),
            "duration_ms": event.get("duration_ms"),
            "cost_usd": event.get("total_cost_usd"),
        }
        if usage:
            payload["usage"] = {key: value for key, value in usage.items() if key != "raw_usage"}
        event_type_out = "error" if is_error else "result"
        events.append(AgentEvent(
            type=event_type_out,
            payload=payload,
            provider=PROVIDER,
            raw=event,
            time=_iso_time(),
        ))
        return events

    # 其他事件统一作为 log 上行，避免信息丢失
    text = format_claude_event_log_line({"type": event_type, "text": _json_text(event)})
    events.append(AgentEvent(
        type="log",
        payload={"level": "info", "message": text or _json_text(event)},
        provider=PROVIDER,
        raw=event,
        time=_iso_time(),
    ))
    return events