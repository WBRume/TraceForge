"""
问题定位任务：定位结果服务

职责：
- 构建诊断会话 prompt 契约（定位优先 / 辅助改码与测试 / 禁止全量修复 / 多轮 HITL / 结构化结果输出）
- 从 AI 会话最终输出提取结构化定位结果（fenced JSON 块）
- AI 结果反填 upsert（DRAFT）并同步「定位结果」卡片消息
- 用户编辑结果 upsert（路由 PUT 复用）
- 构造 WS 推送载荷，把卡片消息广播到任务房间
"""

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domains.task.models.chat import ChatMessage, MessageRole, MessageType
from app.domains.task.models.diagnosis import (
    DiagnosisResultStatus,
    SddDiagnosisResult,
)
from app.domains.task.schemas.diagnosis import DiagnosisResultPayload
from app.domains.ai.schemas.websocket import WSChatPayload, WSMessage
from app.domains.websocket.ws.manager import manager as ws_manager

logger = get_logger(__name__, category="diagnosis_result")

# fenced json 代码块（允许 ```json / ```JSON / ```，兼容 AI 输出变体）
_FENCED_JSON_RE = re.compile(r"```(?:json|JSON)?\s*\n?(.*?)```", re.DOTALL)

_SUMMARY_MAX_CHARS = 4000

# raw_decode 扫描 `{` 位置的最大数量（防性能退化）
_MAX_RAW_DECODE_SCANS = 300


# ────────────────────────── Prompt 契约 ──────────────────────────


def build_diagnosis_prompt_suffix(task) -> str:
    """问题定位任务：把任务性质与工作契约注入 AI 会话初始 prompt。"""
    if getattr(task, "task_type", None) != "DIAGNOSIS":
        return ""
    task_meta = task.task_meta_json if isinstance(task.task_meta_json, dict) else {}
    parts = ["[问题定位任务]"]
    phenomenon = str(task_meta.get("phenomenon") or "").strip()
    if phenomenon:
        parts.append(f"现象: {phenomenon}")
    priority = str(task_meta.get("priority") or "").strip()
    if priority:
        parts.append(f"优先级: {priority}")

    parts.append(
        "你现在处理的是「问题定位任务」，目标是快速、准确地定位问题根因，而不是一次性全量修复。\n"
        "工作方式：\n"
        "1. 允许以辅助定位为目的修改代码、编写并执行测试用例（复现、隔离、验证性最小改动），"
        "但禁止一次性全量修复——定位优先，避免长时间占用；现网问题请保持最小侵入、快速收敛。\n"
        "2. 修复方案不需要在会话内大规模实施，请以建议形式写入最终结果 JSON 的 fix_suggestion 与 fix_code 字段。\n"
        "3. 本会话支持多轮交互（HITL）：你可以通过提问向用户索取新的问题线索（日志、复现步骤、环境信息、变更记录等），"
        "收到新线索后继续收敛定位。\n"
        "4. 每轮回复结束时，请在回复末尾输出一个 ```json 代码块，包含定位结果，结构如下：\n"
        "{\n"
        '  "summary": "结果内容概述",\n'
        '  "root_cause": "根因结论（未收敛时写当前最可能根因）",\n'
        '  "evidence_chain": "证据链（日志片段、复现步骤、调用栈、测试用例输出）",\n'
        '  "fix_suggestion": "修复方案说明",\n'
        '  "fix_code": "修复代码/补丁",\n'
        '  "code_context": [{"file_path": "", "start_line": 0, "end_line": 0, "snippet": "", "note": ""}],\n'
        '  "similar_cases": [{"title": "", "similarity": "高/中/低", "summary": "", "reference": ""}],\n'
        '  "call_chain": [{"seq": 1, "module": "", "function": "", "file_path": "", "description": ""}],\n'
        '  "confidence": 0\n'
        "}\n"
        "confidence 为 0-100 的整数，反映当前定位的确定性；定位未收敛时也要输出当前进展，后续轮次会原位刷新结果。"
    )
    return "\n\n" + "\n".join(parts)


# ────────────────────────── 结果提取 ──────────────────────────


def _clean(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_confidence(value) -> int:
    if isinstance(value, str):
        value = value.strip().rstrip("%").strip()
    try:
        confidence = int(float(value))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, confidence))


def _coerce_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _str_list_field(raw: Any, key: str) -> Optional[str]:
    if not isinstance(raw, dict):
        return None
    return _clean(raw.get(key))


def _normalize_code_context(raw: Any) -> List[Dict[str, Any]]:
    items = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        entry: Dict[str, Any] = {}
        file_path = _clean(item.get("file_path"))
        if not file_path:
            continue
        entry["file_path"] = file_path
        start = _coerce_int(item.get("start_line"))
        end = _coerce_int(item.get("end_line"))
        if start is not None:
            entry["start_line"] = start
        if end is not None:
            entry["end_line"] = end
        snippet = _clean(item.get("snippet"))
        note = _clean(item.get("note"))
        if snippet:
            entry["snippet"] = snippet
        if note:
            entry["note"] = note
        items.append(entry)
    return items


def _normalize_similar_cases(raw: Any) -> List[Dict[str, Any]]:
    items = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        title = _clean(item.get("title"))
        if not title:
            continue
        entry: Dict[str, Any] = {"title": title}
        for key in ("similarity", "summary", "reference"):
            value = _clean(item.get(key))
            if value:
                entry[key] = value
        items.append(entry)
    return items


def _normalize_call_chain(raw: Any) -> List[Dict[str, Any]]:
    items = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        entry: Dict[str, Any] = {}
        seq = _coerce_int(item.get("seq"))
        if seq is not None:
            entry["seq"] = seq
        for key in ("module", "function", "file_path", "description"):
            value = _clean(item.get(key))
            if value:
                entry[key] = value
        if not entry:
            continue
        items.append(entry)
    return items


def _normalize_payload(data: Dict[str, Any]) -> Optional[DiagnosisResultPayload]:
    """字段级容错归一化：任何单个字段异常（越界/类型不符）都不应导致整体提取失败。"""
    try:
        payload = DiagnosisResultPayload(
            summary=_clean(data.get("summary")),
            root_cause=_clean(data.get("root_cause")),
            evidence_chain=_clean(data.get("evidence_chain")),
            fix_suggestion=_clean(data.get("fix_suggestion")),
            fix_code=_clean(data.get("fix_code")),
            code_context=_normalize_code_context(data.get("code_context")),
            similar_cases=_normalize_similar_cases(data.get("similar_cases")),
            call_chain=_normalize_call_chain(data.get("call_chain")),
            confidence=_coerce_confidence(data.get("confidence")),
        )
    except Exception:
        return None
    if not any(
        (
            payload.summary,
            payload.root_cause,
            payload.evidence_chain,
            payload.fix_suggestion,
            payload.fix_code,
            payload.code_context,
            payload.similar_cases,
            payload.call_chain,
        )
    ):
        return None
    return payload


def _try_parse_payload(candidate: str) -> Optional[DiagnosisResultPayload]:
    """尝试把一个候选文本解析为定位结果载荷（支持直接 json / 含散文包裹的 json）。"""
    text = str(candidate or "").strip()
    if not text:
        return None

    # 1) 直接整体解析
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            if isinstance(data.get("diagnosis"), dict):
                data = data["diagnosis"]
            payload = _normalize_payload(data)
            if payload:
                return payload
    except (json.JSONDecodeError, TypeError):
        pass

    # 2) raw_decode 扫描：从每个 `{` 位置尝试解码（能正确处理字符串内括号与嵌套代码块）
    decoder = json.JSONDecoder()
    scanned = 0
    for match in re.finditer(r"\{", text):
        scanned += 1
        if scanned > _MAX_RAW_DECODE_SCANS:
            break
        try:
            data, _ = decoder.raw_decode(text, match.start())
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if isinstance(data.get("diagnosis"), dict):
            data = data["diagnosis"]
        payload = _normalize_payload(data)
        if payload:
            return payload
    return None


def extract_payload_from_text(text: str) -> Optional[DiagnosisResultPayload]:
    """从 AI 回复文本中提取结构化定位结果。

    候选来源（按优先级）：
    1. fenced JSON 代码块（```json / ```JSON / ```），多个块时取最后一个合法结果；
    2. 未使用 fence 的裸 JSON（raw_decode 逐 `{` 扫描）。
    字段级容错：confidence 越界/类型异常、列表项缺失等都不会导致整体失败。

    降级策略：全部失败时返回 summary-only 载荷（内容仍来自 AI 会话原文）。
    """
    raw = str(text or "").strip()
    if not raw:
        return None

    # fence 候选：最后一个合法块优先
    fenced_candidates = [block for block in _FENCED_JSON_RE.findall(raw) if block.strip()]
    for candidate in reversed(fenced_candidates):
        payload = _try_parse_payload(candidate)
        if payload:
            return payload

    # 非 fence 裸 JSON 候选（整段文本）
    payload = _try_parse_payload(raw)
    if payload:
        return payload

    logger.warning("No valid diagnosis JSON block in AI reply; falling back to summary-only payload")
    return DiagnosisResultPayload(summary=raw[:_SUMMARY_MAX_CHARS])


# ────────────────────────── 持久化 ──────────────────────────


def _apply_payload(result: SddDiagnosisResult, payload: DiagnosisResultPayload) -> None:
    result.summary = _clean(payload.summary)
    result.root_cause = _clean(payload.root_cause)
    result.evidence_chain = _clean(payload.evidence_chain)
    result.fix_suggestion = _clean(payload.fix_suggestion)
    result.fix_code = _clean(payload.fix_code)
    result.confidence = _coerce_confidence(payload.confidence)
    result.code_context_json = (
        [item.model_dump(exclude_none=True) for item in payload.code_context] or None
    )
    result.similar_cases_json = (
        [item.model_dump(exclude_none=True) for item in payload.similar_cases] or None
    )
    result.call_chain_json = (
        [item.model_dump(exclude_none=True) for item in payload.call_chain] or None
    )


def _payload_dict(payload: DiagnosisResultPayload) -> dict:
    return payload.model_dump()


def _sync_card_message(
    db: Session,
    *,
    task,
    result: SddDiagnosisResult,
    payload: DiagnosisResultPayload,
    actor_user_id: str,
) -> Optional[ChatMessage]:
    """定位结果卡片消息：同一任务只保留一条，多轮会话原位更新。"""
    existing = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.task_id == task.id,
            ChatMessage.message_type == MessageType.DIAGNOSIS_RESULT,
        )
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .first()
    )
    summary = _clean(payload.summary) or _clean(payload.root_cause) or "Diagnosis result"
    metadata = _payload_dict(payload)
    if existing:
        # 原位更新时间内容，但保留它首次创建时的顺序位（多轮会话卡片不后移）
        previous_meta = existing.metadata_json if isinstance(existing.metadata_json, dict) else {}
        if previous_meta.get("order_index") is not None:
            metadata["order_index"] = previous_meta["order_index"]
        existing.content = summary
        existing.metadata_json = metadata
        message = existing
    else:
        # 卡片消息同样要分配 order_index，否则重新加载历史时它会按 0 排到
        # 最后一条 assistant 文本之前，造成“定位结果卡片”与最后回复顺序倒转。
        order_index = (
            db.query(func.count(ChatMessage.id))
            .filter(ChatMessage.task_id == task.id)
            .scalar()
            or 0
        )
        metadata["order_index"] = order_index
        message = ChatMessage(
            task_id=task.id,
            workspace_id=task.workspace_id,
            creator_id=actor_user_id,
            role=MessageRole.ASSISTANT,
            content=summary,
            message_type=MessageType.DIAGNOSIS_RESULT,
            metadata_json=metadata,
        )
        db.add(message)
    db.flush()
    result.source_chat_message_id = message.id
    return message


def _find_result(db: Session, task_id: str) -> Optional[SddDiagnosisResult]:
    return (
        db.query(SddDiagnosisResult)
        .filter(SddDiagnosisResult.task_id == task_id)
        .first()
    )


def upsert_diagnosis_result_from_ai(
    db: Session,
    *,
    task,
    payload: DiagnosisResultPayload,
    actor_user_id: str,
) -> Optional[SddDiagnosisResult]:
    """AI 会话收敛后反填定位结果（仅 DIAGNOSIS 任务；CONFIRMED 后跳过保护快照）。"""
    if getattr(task, "task_type", None) != "DIAGNOSIS":
        return None
    result = _find_result(db, task.id)
    if result is not None and result.status == DiagnosisResultStatus.CONFIRMED.value:
        return None
    if result is None:
        result = SddDiagnosisResult(
            task_id=task.id,
            workspace_id=task.workspace_id,
            created_by_id=actor_user_id,
            status=DiagnosisResultStatus.DRAFT.value,
        )
        db.add(result)
    _apply_payload(result, payload)
    result.extracted_from_ai = True
    result.extracted_at = datetime.utcnow()
    db.flush()
    _sync_card_message(
        db,
        task=task,
        result=result,
        payload=payload,
        actor_user_id=actor_user_id,
    )
    db.commit()
    db.refresh(result)
    return result


def upsert_diagnosis_result_from_user(
    db: Session,
    *,
    task,
    data: DiagnosisResultPayload,
    actor_user_id: str,
) -> SddDiagnosisResult:
    """用户编辑定位结果（卡片保存）。"""
    result = _find_result(db, task.id)
    if result is None:
        result = SddDiagnosisResult(
            task_id=task.id,
            workspace_id=task.workspace_id,
            created_by_id=actor_user_id,
            status=DiagnosisResultStatus.DRAFT.value,
            extracted_from_ai=False,
        )
        db.add(result)
    _apply_payload(result, data)
    db.flush()
    _sync_card_message(
        db,
        task=task,
        result=result,
        payload=data,
        actor_user_id=actor_user_id,
    )
    db.commit()
    db.refresh(result)
    return result


# ────────────────────────── 序列化 ──────────────────────────


def serialize_diagnosis_result(result: SddDiagnosisResult) -> dict:
    return {
        "id": result.id,
        "task_id": result.task_id,
        "workspace_id": result.workspace_id,
        "created_by_id": result.created_by_id,
        "summary": result.summary,
        "root_cause": result.root_cause,
        "evidence_chain": result.evidence_chain,
        "fix_suggestion": result.fix_suggestion,
        "fix_code": result.fix_code,
        "code_context": result.code_context_json if isinstance(result.code_context_json, list) else [],
        "similar_cases": result.similar_cases_json if isinstance(result.similar_cases_json, list) else [],
        "call_chain": result.call_chain_json if isinstance(result.call_chain_json, list) else [],
        "confidence": int(result.confidence or 0),
        "status": result.status,
        "extracted_from_ai": bool(result.extracted_from_ai),
        "extracted_at": result.extracted_at.isoformat() if result.extracted_at else None,
        "source_chat_message_id": result.source_chat_message_id,
        "created_at": result.created_at.isoformat(),
        "updated_at": result.updated_at.isoformat() if result.updated_at else None,
    }


async def publish_diagnosis_result_message(db: Session, *, task, message: ChatMessage) -> None:
    """把定位结果卡片消息广播到任务房间（多端原位更新）。"""
    from app.domains.auth.models.user import User, WorkspaceMember

    creator = db.query(User).filter(User.id == message.creator_id).first()
    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == task.workspace_id,
            WorkspaceMember.user_id == message.creator_id,
        )
        .first()
    )
    payload = WSChatPayload(
        task_id=task.id,
        role=MessageRole.ASSISTANT.value,
        content=message.content,
        message_type=MessageType.DIAGNOSIS_RESULT.value,
        metadata=message.metadata_json if isinstance(message.metadata_json, dict) else None,
        id=message.id,
        creator_id=message.creator_id,
        creator_display_name=creator.display_name if creator else None,
        creator_is_workspace_expert=bool(member.is_expert) if member else False,
        created_at=message.created_at.isoformat() if message.created_at else None,
    ).model_dump()
    await ws_manager.send_message_to_room(task.id, WSMessage(type="chat_message", payload=payload))
