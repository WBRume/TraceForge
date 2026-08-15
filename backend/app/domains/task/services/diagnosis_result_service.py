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
from typing import Optional

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

# fenced json 代码块（允许 ```json / ```）
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)

_SUMMARY_MAX_CHARS = 4000


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
    try:
        confidence = int(float(value))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, confidence))


def extract_payload_from_text(text: str) -> Optional[DiagnosisResultPayload]:
    """从 AI 回复文本中提取最后一个合法 fenced JSON 定位结果块。

    降级策略：无合法 JSON 块时返回 summary-only 载荷（内容仍来自 AI 会话原文），
    由调用方决定是否落库。
    """
    raw = str(text or "").strip()
    if not raw:
        return None

    for block in reversed(_FENCED_JSON_RE.findall(raw)):
        try:
            data = json.loads(block)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        if isinstance(data.get("diagnosis"), dict):
            data = data["diagnosis"]
        try:
            payload = DiagnosisResultPayload.model_validate(data)
        except Exception:
            continue
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
            continue
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
    if existing:
        existing.content = summary
        existing.metadata_json = _payload_dict(payload)
        message = existing
    else:
        message = ChatMessage(
            task_id=task.id,
            workspace_id=task.workspace_id,
            creator_id=actor_user_id,
            role=MessageRole.ASSISTANT,
            content=summary,
            message_type=MessageType.DIAGNOSIS_RESULT,
            metadata_json=_payload_dict(payload),
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
