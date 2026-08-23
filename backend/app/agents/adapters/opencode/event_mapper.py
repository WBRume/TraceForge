"""OpenCode Server/SSE 事件 → 统一 AgentEvent 映射。

映射基于 OpenCode 1.18.19 实测 SSE 事件样本（`/api/session/{id}/event`）。
事件 JSON 形如：
    {"id":"evt_...","type":"session.next.text.ended","data":{...}}
OpenAPI schema 中同样事件可能把字段放在 `properties`，这里两种都兼容。
"""

from __future__ import annotations

import json
from typing import Any, List, Optional

from app.agents.events import AgentEvent

PROVIDER = "opencode"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _iso_time() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _event_data(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        return {}
    data = event.get("data")
    if isinstance(data, dict):
        return data
    properties = event.get("properties")
    if isinstance(properties, dict):
        return properties
    return {}


def _json_text(value: Any, max_len: int = 5000) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = str(value)
    if len(text) > max_len:
        return f"{text[:max_len]}..."
    return text


def _extract_usage(data: dict[str, Any]) -> Optional[dict[str, Any]]:
    """从 step.ended 的 tokens 中提取统一 usage 字段。"""
    tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
    cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
    input_tokens = tokens.get("input")
    output_tokens = tokens.get("output")
    reasoning_tokens = tokens.get("reasoning")
    cache_read = cache.get("read")
    cache_write = cache.get("write")
    if input_tokens is None and output_tokens is None:
        return None
    known_parts = [v for v in (input_tokens, output_tokens, reasoning_tokens, cache_read, cache_write) if v is not None]
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": cache_write,
        "thinking_tokens": reasoning_tokens,
        "total_tokens": sum(known_parts) if known_parts else None,
    }


def _normalize_finish_reason(finish: str) -> Optional[str]:
    """把 OpenCode finish 值归一化到契约受控词表。"""
    return {
        "stop": "completed",
        "max_tokens": "max-tokens",
        "max-tokens": "max-tokens",
        "cancelled": "aborted",
        "aborted": "aborted",
        "error": "error",
    }.get(finish)


def _tool_output_text(data: dict[str, Any]) -> str:
    """从 tool.success/failed 中提取可读的输出文本。"""
    parts: list[str] = []
    structured = data.get("structured")
    if isinstance(structured, dict):
        # read/list 等内建工具返回结构化 entries
        entries = structured.get("entries")
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict):
                    path = _text(entry.get("path"))
                    if path:
                        parts.append(path)
        else:
            parts.append(_json_text(structured, 4000))
    content = data.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(_text(text))
    return "\n".join(p for p in parts if p) or _json_text(data.get("result") or {}, 4000)


def map_opencode_event(event: dict[str, Any]) -> List[AgentEvent]:
    """把一个 OpenCode SSE/JSON 事件转换为 0~N 个 AgentEvent。"""
    if not isinstance(event, dict):
        return []

    events: List[AgentEvent] = []
    event_type = _text(event.get("type"))
    data = _event_data(event)
    session_id = _text(data.get("sessionID"))

    if event_type == "session.next.text.ended":
        text = _text(data.get("text"))
        if text:
            events.append(AgentEvent(
                type="text",
                payload={"text": text},
                provider=PROVIDER,
                raw=event,
                time=_iso_time(),
            ))
    elif event_type == "session.next.text.delta":
        delta = _text(data.get("delta"))
        if delta:
            events.append(AgentEvent(
                type="text_delta",
                payload={"delta": delta, "text": delta},
                provider=PROVIDER,
                raw=event,
                time=_iso_time(),
            ))
    elif event_type == "session.next.reasoning.ended":
        text = _text(data.get("text"))
        if text:
            events.append(AgentEvent(
                type="thinking",
                payload={"text": text},
                provider=PROVIDER,
                raw=event,
                time=_iso_time(),
            ))
    elif event_type == "session.next.reasoning.delta":
        delta = _text(data.get("delta"))
        if delta:
            # 统一事件目前没有 thinking_delta；骨架先按 thinking 上行。
            events.append(AgentEvent(
                type="thinking",
                payload={"text": delta},
                provider=PROVIDER,
                raw=event,
                time=_iso_time(),
            ))
    elif event_type == "session.next.tool.called":
        events.append(AgentEvent(
            type="tool_use",
            payload={
                "tool_use_id": _text(data.get("callID")),
                "tool_name": _text(data.get("tool")),
                "tool_input": data.get("input", {}),
            },
            provider=PROVIDER,
            raw=event,
            time=_iso_time(),
        ))
    elif event_type == "session.next.tool.success":
        events.append(AgentEvent(
            type="tool_result",
            payload={
                "tool_use_id": _text(data.get("callID")),
                "output": _tool_output_text(data),
                "is_error": False,
            },
            provider=PROVIDER,
            raw=event,
            time=_iso_time(),
        ))
    elif event_type == "session.next.tool.failed":
        error = data.get("error")
        if isinstance(error, dict):
            error_message = _text(error.get("message") or error.get("name"))
        else:
            error_message = _text(error)
        events.append(AgentEvent(
            type="tool_result",
            payload={
                "tool_use_id": _text(data.get("callID")),
                "output": error_message or _json_text(error or {}, 4000),
                "is_error": True,
            },
            provider=PROVIDER,
            raw=event,
            time=_iso_time(),
        ))
    elif event_type == "session.next.step.ended":
        usage = _extract_usage(data)
        if usage:
            events.append(AgentEvent(
                type="usage",
                payload=usage,
                provider=PROVIDER,
                raw=event,
                time=_iso_time(),
            ))
        finish = _text(data.get("finish"))
        normalized_finish = _normalize_finish_reason(finish)
        if normalized_finish:
            is_error = normalized_finish == "error"
            events.append(AgentEvent(
                type="error" if is_error else "result",
                payload={
                    "success": not is_error,
                    "result": "",
                    "finish_reason": normalized_finish,
                    "session_id": session_id,
                    "usage": usage or {},
                    "cost_usd": data.get("cost"),
                },
                provider=PROVIDER,
                raw=event,
                time=_iso_time(),
            ))
        # finish=tool-calls 只是步骤结束，等待后续文本/结果步骤
    elif event_type == "session.next.step.failed":
        usage = _extract_usage(data)
        if usage:
            events.append(AgentEvent(
                type="usage",
                payload=usage,
                provider=PROVIDER,
                raw=event,
                time=_iso_time(),
            ))
        error = data.get("error")
        if isinstance(error, dict):
            error_message = _text(error.get("message") or error.get("name") or error)
        else:
            error_message = _text(error)
        events.append(AgentEvent(
            type="error",
            payload={
                "success": False,
                "result": error_message or "OpenCode step failed",
                "finish_reason": "error",
                "session_id": session_id,
                "usage": usage or {},
                "cost_usd": data.get("cost"),
            },
            provider=PROVIDER,
            raw=event,
            time=_iso_time(),
        ))
    elif event_type == "session.error":
        error = data.get("error")
        if isinstance(error, dict):
            error_message = _text(error.get("message") or error.get("name") or error)
        else:
            error_message = _text(error)
        events.append(AgentEvent(
            type="error",
            payload={
                "success": False,
                "result": error_message or "OpenCode session error",
                "finish_reason": "error",
                "session_id": session_id,
            },
            provider=PROVIDER,
            raw=event,
            time=_iso_time(),
        ))
    elif event_type == "message.part.updated":
        part = data.get("part") if isinstance(data.get("part"), dict) else {}
        part_type = _text(part.get("type"))
        if part_type == "text":
            text = _text(part.get("text"))
            if text:
                events.append(AgentEvent(
                    type="text",
                    payload={"text": text},
                    provider=PROVIDER,
                    raw=event,
                    time=_iso_time(),
                ))
        elif part_type == "reasoning":
            text = _text(part.get("text"))
            if text:
                events.append(AgentEvent(
                    type="thinking",
                    payload={"text": text},
                    provider=PROVIDER,
                    raw=event,
                    time=_iso_time(),
                ))
        elif part_type == "tool":
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            status = _text(state.get("status"))
            tool_use_id = _text(part.get("callID") or part.get("id"))
            tool_name = _text(part.get("tool") or part.get("name")) or "unknown"
            tool_input = state.get("input", {}) if isinstance(state, dict) else {}
            if status in ("pending", "running", ""):
                events.append(AgentEvent(
                    type="tool_use",
                    payload={
                        "tool_use_id": tool_use_id,
                        "tool_name": tool_name,
                        "tool_input": tool_input,
                    },
                    provider=PROVIDER,
                    raw=event,
                    time=_iso_time(),
                ))
            if status in ("completed", "error"):
                output = _tool_output_text(state)
                if status == "error":
                    error = state.get("error")
                    if isinstance(error, dict):
                        error_text = _text(error.get("message") or error.get("name") or error)
                    else:
                        error_text = _text(error)
                    output = f"{output}\n{error_text}".strip()
                events.append(AgentEvent(
                    type="tool_result",
                    payload={
                        "tool_use_id": tool_use_id,
                        "output": output,
                        "is_error": status == "error",
                    },
                    provider=PROVIDER,
                    raw=event,
                    time=_iso_time(),
                ))
        elif part_type == "step-finish":
            usage = _extract_usage({"tokens": part.get("tokens")}) if isinstance(part.get("tokens"), dict) else None
            if usage:
                events.append(AgentEvent(
                    type="usage",
                    payload=usage,
                    provider=PROVIDER,
                    raw=event,
                    time=_iso_time(),
                ))
            reason = _text(part.get("reason"))
            normalized_finish = _normalize_finish_reason(reason)
            if normalized_finish:
                is_error = normalized_finish == "error"
                events.append(AgentEvent(
                    type="error" if is_error else "result",
                    payload={
                        "success": not is_error,
                        "result": "",
                        "finish_reason": normalized_finish,
                        "session_id": session_id,
                        "usage": usage or {},
                        "cost_usd": part.get("cost"),
                    },
                    provider=PROVIDER,
                    raw=event,
                    time=_iso_time(),
                ))
    elif event_type == "message.part.delta":
        delta = _text(data.get("delta"))
        field = _text(data.get("field"))
        if delta:
            if field in ("reasoning", "thinking"):
                events.append(AgentEvent(
                    type="thinking",
                    payload={"text": delta},
                    provider=PROVIDER,
                    raw=event,
                    time=_iso_time(),
                ))
            else:
                events.append(AgentEvent(
                    type="text_delta",
                    payload={"delta": delta, "text": delta},
                    provider=PROVIDER,
                    raw=event,
                    time=_iso_time(),
                ))
    elif event_type == "session.updated":
        info = data.get("info") if isinstance(data.get("info"), dict) else {}
        tokens = info.get("tokens") if isinstance(info.get("tokens"), dict) else None
        usage = _extract_usage({"tokens": tokens}) if tokens else None
        if usage:
            events.append(AgentEvent(
                type="usage",
                payload=usage,
                provider=PROVIDER,
                raw=event,
                time=_iso_time(),
            ))
    elif event_type == "message.updated":
        info = data.get("info") if isinstance(data.get("info"), dict) else {}
        role = _text(info.get("role"))
        if role == "assistant":
            finish = _text(info.get("finish"))
            normalized_finish = _normalize_finish_reason(finish)
            if normalized_finish:
                usage = _extract_usage({"tokens": info.get("tokens")}) if isinstance(info.get("tokens"), dict) else None
                if usage:
                    events.append(AgentEvent(
                        type="usage",
                        payload=usage,
                        provider=PROVIDER,
                        raw=event,
                        time=_iso_time(),
                    ))
                is_error = normalized_finish == "error"
                events.append(AgentEvent(
                    type="error" if is_error else "result",
                    payload={
                        "success": not is_error,
                        "result": "",
                        "finish_reason": normalized_finish,
                        "session_id": session_id,
                        "usage": usage or {},
                        "cost_usd": info.get("cost"),
                    },
                    provider=PROVIDER,
                    raw=event,
                    time=_iso_time(),
                ))
            else:
                events.append(AgentEvent(
                    type="log",
                    payload={"level": "debug", "message": f"[opencode:message.updated] assistant message {info.get('id')}"},
                    provider=PROVIDER,
                    raw=event,
                    time=_iso_time(),
                ))
    elif event_type in ("permission.v2.asked", "permission.asked"):
        events.append(AgentEvent(
            type="ask_user",
            payload={
                "ask_user_id": _text(data.get("id") or data.get("requestID")),
                "question": f"OpenCode permission: {_text(data.get('action'))}",
                "permission_request": True,
                "resources": data.get("resources", []),
            },
            provider=PROVIDER,
            raw=event,
            time=_iso_time(),
        ))
    elif event_type in ("question.v2.asked", "question.asked"):
        questions = data.get("questions")
        if isinstance(questions, list) and questions:
            first = questions[0] if isinstance(questions[0], dict) else {}
            events.append(AgentEvent(
                type="ask_user",
                payload={
                    "ask_user_id": _text(data.get("id") or data.get("requestID")),
                    "question": _text(first.get("prompt") or first.get("question") or first.get("text")),
                    "resource": data,
                },
                provider=PROVIDER,
                raw=event,
                time=_iso_time(),
            ))
    elif event_type in ("session.next.text.started", "session.next.step.started",
                        "session.next.tool.input.started", "session.next.tool.input.ended",
                        "session.next.tool.progress", "session.next.prompted",
                        "session.next.prompt.admitted", "session.idle", "message.updated"):
        # 这些事件对 WorkflowEngine 不是必需事件；作为 log 保留审计信息。
        events.append(AgentEvent(
            type="log",
            payload={"level": "debug", "message": f"[opencode:{event_type}] {_json_text(data, 1200)}"},
            provider=PROVIDER,
            raw=event,
            time=_iso_time(),
        ))
    else:
        events.append(AgentEvent(
            type="log",
            payload={"level": "info", "message": f"[opencode:{event_type}] {_json_text(event, 2000)}"},
            provider=PROVIDER,
            raw=event,
            time=_iso_time(),
        ))
    return events