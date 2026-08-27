"""DSH（DeepSeek Harness）SDK session.event → 统一 AgentEvent 映射。

事件样本来自 DSH 仓库官方 SDK 快照：
    scripts/snapshots/python-sdk-single-exe/advanced/session.jsonl
结构为 JSONL 行：{"type": "...", "seq": N, "time": ..., "data": {...}}
"""

from __future__ import annotations

import json
from typing import Any, List, Optional

from app.agents.events import AgentEvent

PROVIDER = "dsh"


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


def _extract_usage(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    """从 assistant/chunk usage 或 assistant/message usage 中提取统一 usage。"""
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    if event.get("type") == "assistant/chunk":
        chunk = data.get("chunk") if isinstance(data.get("chunk"), dict) else {}
        usage = chunk.get("usage") or data.get("usage") or {}
    else:
        usage = data.get("usage") or {}
    if not isinstance(usage, dict):
        return None
    input_tokens = usage.get("inputTokens") or usage.get("input_tokens")
    output_tokens = usage.get("outputTokens") or usage.get("output_tokens")
    if input_tokens is None and output_tokens is None:
        return None
    thinking_tokens = usage.get("reasoningTokens") or usage.get("thinking_tokens")
    total_tokens = usage.get("totalTokens") or usage.get("total_tokens")
    known = [v for v in (input_tokens, output_tokens, thinking_tokens) if v is not None]
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "thinking_tokens": thinking_tokens,
        "total_tokens": total_tokens if total_tokens is not None else (sum(known) if known else None),
    }


def _tool_output_text(data: dict[str, Any]) -> str:
    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    content = message.get("content") if isinstance(message.get("content"), list) else []
    parts: List[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "tool-result":
            continue
        inner = block.get("content")
        if isinstance(inner, list):
            for item in inner:
                if isinstance(item, dict):
                    parts.append(_text(item.get("text")))
    return "\n".join(p for p in parts if p)


def map_dsh_event(event: dict[str, Any]) -> List[AgentEvent]:
    """把一个 DSH session.event 转换为 0~N 个 AgentEvent。"""
    if not isinstance(event, dict):
        return []

    events: List[AgentEvent] = []
    event_type = _text(event.get("type"))
    data = event.get("data") if isinstance(event.get("data"), dict) else {}

    if event_type == "assistant/message":
        message = data.get("message") if isinstance(data.get("message"), dict) else {}
        content = message.get("content") if isinstance(message.get("content"), list) else []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = _text(block.get("type"))
            if block_type == "text":
                text = _text(block.get("text"))
                if text:
                    events.append(AgentEvent(
                        type="text",
                        payload={"text": text},
                        provider=PROVIDER,
                        raw=event,
                        time=_iso_time(),
                    ))
            elif block_type == "reasoning":
                reasoning = _text(block.get("text") or block.get("content"))
                if reasoning:
                    events.append(AgentEvent(
                        type="thinking",
                        payload={"text": reasoning},
                        provider=PROVIDER,
                        raw=event,
                        time=_iso_time(),
                    ))
            # tool-call 由 tool/call 事件统一映射，避免重复
        usage = _extract_usage(event)
        if usage:
            events.append(AgentEvent(
                type="usage",
                payload=usage,
                provider=PROVIDER,
                raw=event,
                time=_iso_time(),
            ))
    elif event_type == "assistant/chunk":
        chunk = data.get("chunk") if isinstance(data.get("chunk"), dict) else {}
        chunk_type = _text(chunk.get("type"))
        if chunk_type == "text-delta":
            text = _text(chunk.get("text"))
            if text:
                events.append(AgentEvent(
                    type="text_delta",
                    payload={"delta": text, "text": text},
                    provider=PROVIDER,
                    raw=event,
                    time=_iso_time(),
                ))
        elif chunk_type == "reasoning-delta" or chunk_type == "thinking-delta":
            text = _text(chunk.get("text"))
            if text:
                events.append(AgentEvent(
                    type="thinking",
                    payload={"text": text, "delta": text},
                    provider=PROVIDER,
                    raw=event,
                    time=_iso_time(),
                ))
        elif chunk_type == "usage":
            usage = _extract_usage(event)
            if usage:
                events.append(AgentEvent(
                    type="usage",
                    payload=usage,
                    provider=PROVIDER,
                    raw=event,
                    time=_iso_time(),
                ))
    elif event_type == "tool/call":
        events.append(AgentEvent(
            type="tool_use",
            payload={
                "tool_use_id": _text(data.get("callId")),
                "tool_name": _text(data.get("name")),
                "tool_input": _parse_json_arguments(data.get("arguments")),
            },
            provider=PROVIDER,
            raw=event,
            time=_iso_time(),
        ))
    elif event_type == "tool/result":
        message = data.get("message") if isinstance(data.get("message"), dict) else {}
        is_error = False
        content = message.get("content") if isinstance(message.get("content"), list) else []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool-result":
                is_error = bool(block.get("isError"))
        events.append(AgentEvent(
            type="tool_result",
            payload={
                "tool_use_id": _text((message.get("source") or {}).get("callId") if isinstance(message.get("source"), dict) else ""),
                "output": _tool_output_text(data),
                "is_error": is_error,
            },
            provider=PROVIDER,
            raw=event,
            time=_iso_time(),
        ))
    elif event_type == "turn/end":
        reason = data.get("reason") if isinstance(data.get("reason"), dict) else {}
        kind = _text(reason.get("kind"))
        is_error = kind in ("error", "failed")
        events.append(AgentEvent(
            type="error" if is_error else "result",
            payload={
                "success": not is_error,
                "result": "",
                "finish_reason": kind or "completed",
                "session_id": "",
            },
            provider=PROVIDER,
            raw=event,
            time=_iso_time(),
        ))
    elif event_type in ("step/start", "step/end", "turn/start", "user/message", "request/header",
                        "request/context", "session/title", "agent/inbox/spliced", "session"):
        events.append(AgentEvent(
            type="log",
            payload={"level": "debug", "message": f"[dsh:{event_type}] {_json_text(data, 1200)}"},
            provider=PROVIDER,
            raw=event,
            time=_iso_time(),
        ))
    else:
        events.append(AgentEvent(
            type="log",
            payload={"level": "info", "message": f"[dsh:{event_type}] {_json_text(event, 2000)}"},
            provider=PROVIDER,
            raw=event,
            time=_iso_time(),
        ))
    return events


def _parse_json_arguments(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    text = _text(value)
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}