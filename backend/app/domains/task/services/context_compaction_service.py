"""Context compaction detection and conservative phase estimation.

This service deliberately treats Claude compaction signals as best-effort
observability data. It reports explicit token numbers when available and marks
derived values as estimates so the UI does not overstate precision.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.config import settings
from app.engine.claude_event_adapter import extract_claude_compaction_event
from app.domains.ai.models.ai_job import SddAiJob
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.context_token import (
    ContextTokenCategory,
    SddContextTokenSegment,
    SddContextTokenSnapshot,
)
from app.domains.task.models.log import SddExecutionLog
from app.domains.task.models.task import SddTask


MAX_LOG_SCAN_ROWS = 5000
MAX_JOB_SCAN_ROWS = 300
MAX_TRACE_FILES = 80
MAX_SESSION_FILES = 8
MAX_FILE_SCAN_BYTES = 5 * 1024 * 1024
MAX_PREVIEW_LEN = 420

COMPACTION_EVENT_TEXT_RE = re.compile(
    r"(\[compaction\]|context[_\s-]*compaction\s+detected|context_compaction|compaction\s+event|auto[-_\s]*compact|context\s+(?:was\s+)?compacted|conversation\s+(?:was\s+)?compacted)",
    re.IGNORECASE,
)
TOKEN_PAIR_PATTERNS = (
    re.compile(
        r"\b(?:tokens?|context[_\s-]*tokens?)\b\D{0,20}(?P<before>\d[\d,._ ]{0,18})\s*(?:->|=>|→|to|down\s+to)\s*(?P<after>\d[\d,._ ]{0,18})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:token_before|tokens_before|before_tokens|pre[-_\s]*compact(?:ion)?[-_\s]*tokens?|context[_\s-]*tokens?[_\s-]*before|before)\b\D{0,40}(?P<before>\d[\d,._ ]{0,18})\D{0,80}\b(?:token_after|tokens_after|after_tokens|post[-_\s]*compact(?:ion)?[-_\s]*tokens?|context[_\s-]*tokens?[_\s-]*after|after)\b\D{0,40}(?P<after>\d[\d,._ ]{0,18})",
        re.IGNORECASE,
    ),
)

RISK_DEFINITIONS = (
    {
        "kind": "history",
        "label": "可能被压缩的历史对话",
        "categories": [ContextTokenCategory.HISTORY],
        "reason": "历史对话通常是长任务压缩的主要候选上下文。",
    },
    {
        "kind": "spec",
        "label": "可能被压缩的 Spec 信息",
        "categories": [ContextTokenCategory.SPEC_DOCS],
        "reason": "需求文档或 Spec 摘要若被过度压缩，可能影响后续实现细节。",
    },
    {
        "kind": "tool_result",
        "label": "可能被压缩的 tool result",
        "categories": [ContextTokenCategory.TOOL_RESULT],
        "reason": "工具返回内容可能包含文件内容、错误输出或验证结果。",
    },
    {
        "kind": "skills_constraints",
        "label": "可能影响后续执行的 Skills / 约束",
        "categories": [ContextTokenCategory.RUNTIME_SKILLS, ContextTokenCategory.SUPERPOWERS_RULES],
        "reason": "运行时 Skill 证据和项目规则如果只剩摘要，可能影响后续约束遵循。",
    },
)


@dataclass
class DetectedCompactionEvent:
    source: str
    source_ref_id: str
    source_label: str
    detected_at: Optional[datetime]
    preview: str
    token_before: Optional[int] = None
    token_after: Optional[int] = None
    ai_job_id: Optional[str] = None
    chat_message_id: Optional[str] = None
    log_id: Optional[str] = None
    locator: Optional[Dict[str, Any]] = None


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def _clip(value: Any, limit: int = MAX_PREVIEW_LEN) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _safe_json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
    except Exception:
        return str(value)


def _text_has_compaction_signal(text: Any) -> bool:
    return bool(COMPACTION_EVENT_TEXT_RE.search(str(text or "")))


def _safe_int_token(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        parsed = int(str(value).replace(",", "").replace("_", "").replace(" ", "").split(".", 1)[0])
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _extract_token_pair_from_text(text: str) -> tuple[Optional[int], Optional[int]]:
    for pattern in TOKEN_PAIR_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        before = _safe_int_token(match.group("before"))
        after = _safe_int_token(match.group("after"))
        if before is not None or after is not None:
            return _normalize_token_pair(before, after)
    return None, None


def _normalize_token_pair(before: Optional[int], after: Optional[int]) -> tuple[Optional[int], Optional[int]]:
    if before is not None and after is not None and after >= before:
        return None, None
    return before, after


def _parse_json_candidate(text: str) -> Optional[Any]:
    raw = str(text or "").strip()
    if not raw:
        return None
    if raw.startswith("{") or raw.startswith("["):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return None


def _extract_token_pair(raw: Any, text: str) -> tuple[Optional[int], Optional[int]]:
    if isinstance(raw, dict):
        parsed = extract_claude_compaction_event(raw)
        if parsed:
            before = _safe_int_token(parsed.get("token_before"))
            after = _safe_int_token(parsed.get("token_after"))
            if before is not None or after is not None:
                return _normalize_token_pair(before, after)
    return _extract_token_pair_from_text(text)


def _event_identity(event: DetectedCompactionEvent) -> str:
    raw = "|".join(
        [
            event.source,
            event.source_ref_id,
            event.detected_at.isoformat() if event.detected_at else "",
            event.preview[:120],
        ]
    )
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _source_status(source: str, status: str, *, event_count: int = 0, note: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "source": source,
        "status": status,
        "event_count": int(event_count or 0),
    }
    if note:
        payload["note"] = note
    return payload


def _nearest_trigger_refs(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    detected_at: Optional[datetime],
    ai_job_id: Optional[str],
    chat_message_id: Optional[str],
) -> Dict[str, Any]:
    trigger_job_id = ai_job_id
    if not trigger_job_id and detected_at:
        job = (
            db.query(SddAiJob)
            .filter(SddAiJob.workspace_id == workspace_id, SddAiJob.task_id == task_id)
            .filter(SddAiJob.created_at <= detected_at)
            .order_by(SddAiJob.created_at.desc(), SddAiJob.id.desc())
            .first()
        )
        if job:
            trigger_job_id = job.id

    trigger_message_id = chat_message_id
    turn_index = None
    if detected_at:
        turn_index = int(
            db.query(sqlfunc.count(ChatMessage.id))
            .filter(ChatMessage.workspace_id == workspace_id, ChatMessage.task_id == task_id)
            .filter(ChatMessage.created_at <= detected_at)
            .scalar()
            or 0
        )
        if not trigger_message_id:
            message = (
                db.query(ChatMessage)
                .filter(ChatMessage.workspace_id == workspace_id, ChatMessage.task_id == task_id)
                .filter(ChatMessage.created_at <= detected_at)
                .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
                .first()
            )
            if message:
                trigger_message_id = message.id

    label_parts = []
    if turn_index:
        label_parts.append(f"turn {turn_index}")
    if trigger_job_id:
        label_parts.append(f"AI Job {trigger_job_id[:8]}")
    if trigger_message_id:
        label_parts.append(f"message {trigger_message_id[:8]}")
    return {
        "turn_index": turn_index,
        "ai_job_id": trigger_job_id,
        "chat_message_id": trigger_message_id,
        "label": " / ".join(label_parts) if label_parts else None,
    }


def _risk_query(
    db: Session,
    *,
    snapshot_id: str,
    categories: List[ContextTokenCategory],
    detected_at: Optional[datetime],
) -> List[SddContextTokenSegment]:
    query = db.query(SddContextTokenSegment).filter(
        SddContextTokenSegment.snapshot_id == snapshot_id,
        SddContextTokenSegment.category.in_(categories),
    )
    if detected_at:
        query = query.filter(SddContextTokenSegment.created_at <= detected_at)
    return query.order_by(SddContextTokenSegment.created_at.asc(), SddContextTokenSegment.id.asc()).limit(500).all()


def _segment_ref(segment: SddContextTokenSegment) -> Dict[str, Any]:
    return {
        "id": segment.id,
        "category": _enum_value(segment.category),
        "source_kind": segment.source_kind,
        "source_ref_id": segment.source_ref_id,
        "chat_message_id": segment.chat_message_id,
        "asset_id": segment.asset_id,
        "skill_runtime_event_id": segment.skill_runtime_event_id,
        "tool_use_id": segment.tool_use_id,
        "title": segment.title,
    }


def _build_risks(
    db: Session,
    *,
    snapshot: Optional[SddContextTokenSnapshot],
    detected_at: Optional[datetime],
) -> List[Dict[str, Any]]:
    if snapshot is None:
        return []

    risks = []
    for definition in RISK_DEFINITIONS:
        rows = _risk_query(
            db,
            snapshot_id=snapshot.id,
            categories=definition["categories"],
            detected_at=detected_at,
        )
        risks.append(
            {
                "kind": definition["kind"],
                "label": definition["label"],
                "level": "medium" if rows else "unknown",
                "reason": definition["reason"],
                "affected_segments": len(rows),
                "sample_refs": [_segment_ref(row) for row in rows[:4]],
                "estimated": True,
            }
        )

    subagent_candidates = _risk_query(
        db,
        snapshot_id=snapshot.id,
        categories=[ContextTokenCategory.TOOL_RESULT, ContextTokenCategory.RUNTIME_SKILLS],
        detected_at=detected_at,
    )
    subagent_rows = [
        row
        for row in subagent_candidates
        if re.search(r"\b(subagent|agent|task tool|worker|reviewer)\b", " ".join([row.title or "", row.preview or "", row.source_kind or ""]), re.IGNORECASE)
    ]
    risks.insert(
        3,
        {
            "kind": "subagent",
            "label": "可能被压缩的 subagent 输出",
            "level": "medium" if subagent_rows else "unknown",
            "reason": "subagent 输出常通过 tool result 或 runtime skill 证据进入上下文。",
            "affected_segments": len(subagent_rows),
            "sample_refs": [_segment_ref(row) for row in subagent_rows[:4]],
            "estimated": True,
        },
    )
    return risks


def _snapshot_total_tokens(snapshot: Optional[SddContextTokenSnapshot]) -> Optional[int]:
    if snapshot is None:
        return None
    if snapshot.total_tokens is not None:
        return int(snapshot.total_tokens)
    parts = [
        snapshot.input_tokens,
        snapshot.output_tokens,
        snapshot.cache_read_tokens,
        snapshot.cache_creation_tokens,
        snapshot.thinking_tokens,
        snapshot.tool_io_tokens,
    ]
    known = [int(value) for value in parts if value is not None]
    return sum(known) if known else None


def _serialize_event(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    snapshot: Optional[SddContextTokenSnapshot],
    event: DetectedCompactionEvent,
    phase_after: int,
) -> Dict[str, Any]:
    event_id = _event_identity(event)
    trigger = _nearest_trigger_refs(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        detected_at=event.detected_at,
        ai_job_id=event.ai_job_id,
        chat_message_id=event.chat_message_id,
    )
    if event.log_id:
        trigger["log_id"] = event.log_id
    token_reduction = None
    if event.token_before is not None and event.token_after is not None:
        token_reduction = max(0, int(event.token_before) - int(event.token_after))
    return {
        "id": event_id,
        "phase_before": max(1, phase_after - 1),
        "phase_after": phase_after,
        "detected_at": event.detected_at,
        "source": event.source,
        "source_ref_id": event.source_ref_id,
        "source_label": event.source_label,
        "event_type": "context_compaction",
        "token_before_estimate": event.token_before,
        "token_after_estimate": event.token_after,
        "token_reduction_estimate": token_reduction,
        "tokens_estimated": True,
        "preview": event.preview,
        "trigger": trigger,
        "risks": _build_risks(db, snapshot=snapshot, detected_at=event.detected_at),
        "locator": event.locator or {},
    }


def _phase_new_tokens(token_before: Optional[int], previous_after: Optional[int]) -> Optional[int]:
    if token_before is None:
        return None
    if previous_after is None:
        return int(token_before)
    return max(0, int(token_before) - int(previous_after))


def _build_phases(
    *,
    snapshot: Optional[SddContextTokenSnapshot],
    events: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    current_total = _snapshot_total_tokens(snapshot)
    start_at = snapshot.created_at if snapshot is not None else None
    end_at = snapshot.updated_at or snapshot.created_at if snapshot is not None else None
    if not events:
        return [
            {
                "phase_index": 1,
                "started_at": start_at,
                "ended_at": end_at,
                "token_before_estimate": None,
                "token_after_estimate": current_total,
                "phase_new_tokens_estimate": current_total,
                "trigger": None,
                "compaction_event_id": None,
                "estimation_note": "未检测到 compaction 事件；该 phase 使用当前上下文快照估算。",
            }
        ]

    phases: List[Dict[str, Any]] = []
    previous_started_at = start_at
    previous_after: Optional[int] = None
    for index, event in enumerate(events, start=1):
        token_before = event.get("token_before_estimate")
        token_after = event.get("token_after_estimate")
        phases.append(
            {
                "phase_index": index,
                "started_at": previous_started_at,
                "ended_at": event.get("detected_at"),
                "token_before_estimate": token_before,
                "token_after_estimate": token_after,
                "phase_new_tokens_estimate": _phase_new_tokens(token_before, previous_after),
                "trigger": event.get("trigger"),
                "compaction_event_id": event.get("id"),
                "estimation_note": "phase token 数值来自 Claude 事件或日志解析估算；来源分类请查看 Token 归因视图。",
            }
        )
        previous_started_at = event.get("detected_at")
        previous_after = int(token_after) if token_after is not None else previous_after

    phases.append(
        {
            "phase_index": len(events) + 1,
            "started_at": previous_started_at,
            "ended_at": end_at,
            "token_before_estimate": previous_after,
            "token_after_estimate": current_total,
            "phase_new_tokens_estimate": _phase_new_tokens(current_total, previous_after),
            "trigger": None,
            "compaction_event_id": None,
            "estimation_note": "最后一个 phase 表示最近一次压缩后的当前上下文估算。",
        }
    )
    return phases


def _event_from_text_source(
    *,
    source: str,
    source_ref_id: str,
    source_label: str,
    text: str,
    detected_at: Optional[datetime],
    raw: Any = None,
    ai_job_id: Optional[str] = None,
    chat_message_id: Optional[str] = None,
    log_id: Optional[str] = None,
    locator: Optional[Dict[str, Any]] = None,
) -> Optional[DetectedCompactionEvent]:
    has_signal = _text_has_compaction_signal(text)
    if not has_signal and isinstance(raw, dict):
        has_signal = extract_claude_compaction_event(raw) is not None
    if not has_signal:
        return None
    token_before, token_after = _extract_token_pair(raw, text)
    return DetectedCompactionEvent(
        source=source,
        source_ref_id=source_ref_id,
        source_label=source_label,
        detected_at=detected_at,
        preview=_clip(text),
        token_before=token_before,
        token_after=token_after,
        ai_job_id=ai_job_id,
        chat_message_id=chat_message_id,
        log_id=log_id,
        locator=locator,
    )


def _dedupe_events(events: Iterable[DetectedCompactionEvent]) -> List[DetectedCompactionEvent]:
    seen: set[str] = set()
    unique: List[DetectedCompactionEvent] = []
    for event in events:
        key = _event_identity(event)
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    unique.sort(key=lambda item: (item.detected_at or datetime.min, item.source, item.source_ref_id))
    return unique


def _scan_execution_logs(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
) -> List[DetectedCompactionEvent]:
    events = []
    rows = (
        db.query(SddExecutionLog)
        .filter(SddExecutionLog.workspace_id == workspace_id, SddExecutionLog.task_id == task_id)
        .order_by(SddExecutionLog.created_at.asc(), SddExecutionLog.id.asc())
        .limit(MAX_LOG_SCAN_ROWS)
        .all()
    )
    for row in rows:
        text = str(row.content or "")
        raw = _parse_json_candidate(text)
        event = _event_from_text_source(
            source="execution_log",
            source_ref_id=row.id,
            source_label="Execution log",
            text=text,
            raw=raw,
            detected_at=row.created_at,
            log_id=row.id,
            locator={"log_id": row.id},
        )
        if event:
            events.append(event)
    return events


def _scan_ai_jobs(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
) -> List[DetectedCompactionEvent]:
    events = []
    jobs = (
        db.query(SddAiJob)
        .filter(SddAiJob.workspace_id == workspace_id, SddAiJob.task_id == task_id)
        .order_by(SddAiJob.created_at.asc(), SddAiJob.id.asc())
        .limit(MAX_JOB_SCAN_ROWS)
        .all()
    )
    for job in jobs:
        fields = [
            ("message", job.message),
            ("error_message", job.error_message),
            ("context_json", job.context_json),
            ("result_json", job.result_json),
        ]
        for field_name, value in fields:
            text = _safe_json_text(value)
            event = _event_from_text_source(
                source="ai_job",
                source_ref_id=job.id,
                source_label=f"AI Job {field_name}",
                text=text,
                raw=value,
                detected_at=job.updated_at or job.created_at,
                ai_job_id=job.id,
                locator={"ai_job_id": job.id, "field": field_name},
            )
            if event:
                events.append(event)
    return events


def _scan_snapshot_raw_usage(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
) -> List[DetectedCompactionEvent]:
    events = []
    snapshots = (
        db.query(SddContextTokenSnapshot)
        .filter(SddContextTokenSnapshot.workspace_id == workspace_id, SddContextTokenSnapshot.task_id == task_id)
        .order_by(SddContextTokenSnapshot.created_at.asc(), SddContextTokenSnapshot.id.asc())
        .limit(MAX_JOB_SCAN_ROWS)
        .all()
    )
    for snapshot in snapshots:
        if snapshot.raw_usage_json is None:
            continue
        text = _safe_json_text(snapshot.raw_usage_json)
        event = _event_from_text_source(
            source="stream_json_usage",
            source_ref_id=snapshot.id,
            source_label="Claude usage payload",
            text=text,
            raw=snapshot.raw_usage_json,
            detected_at=snapshot.updated_at or snapshot.created_at,
            ai_job_id=snapshot.ai_job_id,
            locator={"snapshot_id": snapshot.id, "ai_job_id": snapshot.ai_job_id},
        )
        if event:
            events.append(event)
    return events


def _parse_trace_timestamp(line: str) -> Optional[datetime]:
    raw = str(line or "")[:23]
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return None


def _iter_recent_trace_files() -> Iterable[Path]:
    trace_dir = Path(str(settings.AI_SESSION_LOG_DIR or "")).expanduser()
    if not trace_dir.exists() or not trace_dir.is_dir():
        return []
    files = [path for path in trace_dir.glob("*.log") if path.is_file()]
    files.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)
    return files[:MAX_TRACE_FILES]


def _file_looks_related(path: Path, *, task: Optional[SddTask], session_ids: set[str]) -> bool:
    name = path.name
    if any(sid and sid[:12] in name for sid in session_ids):
        return True
    project_path = str(task.project_path or "").strip() if task else ""
    if not project_path and not session_ids:
        return False
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            head = "".join(handle.readline() for _ in range(40))
    except OSError:
        return False
    return bool((project_path and project_path in head) or any(sid and sid in head for sid in session_ids))


def _scan_text_file_for_compaction(
    path: Path,
    *,
    source: str,
    source_label: str,
    source_ref_prefix: str,
) -> List[DetectedCompactionEvent]:
    events = []
    try:
        if path.stat().st_size > MAX_FILE_SCAN_BYTES:
            return events
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line_no, line in enumerate(handle, start=1):
                if not _text_has_compaction_signal(line):
                    continue
                raw = _parse_json_candidate(line)
                event = _event_from_text_source(
                    source=source,
                    source_ref_id=f"{source_ref_prefix}:{line_no}",
                    source_label=source_label,
                    text=line,
                    raw=raw,
                    detected_at=_parse_trace_timestamp(line),
                    locator={"path": str(path), "line": line_no},
                )
                if event:
                    events.append(event)
    except OSError:
        return events
    return events


def _known_session_ids(db: Session, *, task: Optional[SddTask], workspace_id: str, task_id: str) -> set[str]:
    session_ids = {str(task.session_id or "").strip()} if task else set()
    for (session_id,) in (
        db.query(SddAiJob.session_id)
        .filter(SddAiJob.workspace_id == workspace_id, SddAiJob.task_id == task_id)
        .filter(SddAiJob.session_id.isnot(None))
        .all()
    ):
        if session_id:
            session_ids.add(str(session_id).strip())
    for (session_id,) in (
        db.query(SddContextTokenSnapshot.session_id)
        .filter(SddContextTokenSnapshot.workspace_id == workspace_id, SddContextTokenSnapshot.task_id == task_id)
        .filter(SddContextTokenSnapshot.session_id.isnot(None))
        .all()
    ):
        if session_id:
            session_ids.add(str(session_id).strip())
    return {sid for sid in session_ids if sid}


def _scan_session_traces(
    db: Session,
    *,
    task: Optional[SddTask],
    workspace_id: str,
    task_id: str,
) -> List[DetectedCompactionEvent]:
    session_ids = _known_session_ids(db, task=task, workspace_id=workspace_id, task_id=task_id)
    events = []
    for path in _iter_recent_trace_files():
        if not _file_looks_related(path, task=task, session_ids=session_ids):
            continue
        events.extend(
            _scan_text_file_for_compaction(
                path,
                source="session_trace",
                source_label="Claude session trace",
                source_ref_prefix=str(path),
            )
        )
    return events


def _claude_session_file_candidates(session_ids: set[str]) -> List[Path]:
    if not session_ids:
        return []
    root = Path.home() / ".claude" / "projects"
    if not root.exists() or not root.is_dir():
        return []
    candidates: List[Path] = []
    for session_id in session_ids:
        candidates.extend(path for path in root.rglob(f"{session_id}.jsonl") if path.is_file())
        candidates.extend(path for path in root.rglob(f"{session_id}.json") if path.is_file())
    seen: set[str] = set()
    unique: List[Path] = []
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    unique.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)
    return unique[:MAX_SESSION_FILES]


def _scan_claude_session_files(
    db: Session,
    *,
    task: Optional[SddTask],
    workspace_id: str,
    task_id: str,
) -> List[DetectedCompactionEvent]:
    session_ids = _known_session_ids(db, task=task, workspace_id=workspace_id, task_id=task_id)
    events = []
    for path in _claude_session_file_candidates(session_ids):
        events.extend(
            _scan_text_file_for_compaction(
                path,
                source="claude_session_file",
                source_label="~/.claude session file",
                source_ref_prefix=str(path),
            )
        )
    return events


def get_context_compaction(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    snapshot: Optional[SddContextTokenSnapshot] = None,
) -> Dict[str, Any]:
    task = db.query(SddTask).filter(SddTask.workspace_id == workspace_id, SddTask.id == task_id).first()
    source_events: List[DetectedCompactionEvent] = []
    data_sources: List[Dict[str, Any]] = []

    log_events = _scan_execution_logs(db, workspace_id=workspace_id, task_id=task_id)
    source_events.extend(log_events)
    data_sources.append(_source_status("execution_log", "scanned", event_count=len(log_events)))

    job_events = _scan_ai_jobs(db, workspace_id=workspace_id, task_id=task_id)
    source_events.extend(job_events)
    data_sources.append(_source_status("ai_job", "scanned", event_count=len(job_events)))

    usage_events = _scan_snapshot_raw_usage(db, workspace_id=workspace_id, task_id=task_id)
    source_events.extend(usage_events)
    data_sources.append(_source_status("stream_json_usage", "scanned", event_count=len(usage_events)))

    trace_events = _scan_session_traces(db, task=task, workspace_id=workspace_id, task_id=task_id)
    source_events.extend(trace_events)
    data_sources.append(
        _source_status(
            "session_trace",
            "scanned" if os.path.isdir(str(settings.AI_SESSION_LOG_DIR or "")) else "unavailable",
            event_count=len(trace_events),
            note=None if trace_events else "未在可关联的 Claude session trace 中检测到 compaction 信号。",
        )
    )

    claude_file_events = _scan_claude_session_files(db, task=task, workspace_id=workspace_id, task_id=task_id)
    source_events.extend(claude_file_events)
    data_sources.append(
        _source_status(
            "claude_session_file",
            "scanned" if _known_session_ids(db, task=task, workspace_id=workspace_id, task_id=task_id) else "no_session_id",
            event_count=len(claude_file_events),
            note=None if claude_file_events else "仅在已知 Claude session_id 时扫描 ~/.claude 会话文件。",
        )
    )

    detected = _dedupe_events(source_events)
    serialized_events = [
        _serialize_event(
            db,
            workspace_id=workspace_id,
            task_id=task_id,
            snapshot=snapshot,
            event=event,
            phase_after=index + 1,
        )
        for index, event in enumerate(detected, start=1)
    ]
    phases = _build_phases(snapshot=snapshot, events=serialized_events)
    status = "detected" if serialized_events else "not_detected"
    return {
        "task_id": task_id,
        "workspace_id": workspace_id,
        "status": status,
        "has_detected_events": bool(serialized_events),
        "empty_reason": None if serialized_events else "NO_COMPACTION_EVENTS",
        "events": serialized_events,
        "phases": phases,
        "data_sources": data_sources,
        "generated_at": datetime.utcnow(),
        "parser_version": "compaction-v1",
    }
