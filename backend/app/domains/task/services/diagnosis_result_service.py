"""
问题定位任务：定位结果服务

职责：
- 构建诊断会话 prompt 契约（定位优先 / 辅助改码与测试 / 禁止全量修复 / 多轮 HITL / 结构化结果输出）
- 接收领域工具提交的强类型定位结果
- AI 结果反填 upsert（DRAFT）并同步「定位结果」卡片消息
- 用户编辑结果 upsert（路由 PUT 复用）
- 构造 WS 推送载荷，把卡片消息广播到任务房间
"""

from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.offload import run_db
from app.database import SessionLocal
from app.domains.ai.schemas.websocket import WSChatPayload, WSMessage
from app.domains.ai.services.jobs.store import (
    create_diagnosis_summary_job,
    find_active_chat_job,
    find_active_summary_job,
    serialize_job,
)
from app.domains.case_center.models.case import CaseStatus, SddCase
from app.domains.rag.services import outbox_service as rag_outbox_service
from app.domains.task.models.chat import ChatMessage, MessageRole, MessageType
from app.domains.task.models.diagnosis import (
    DiagnosisResultStatus,
    SddDiagnosisResult,
)
from app.domains.task.models.task import SddTask
from app.domains.task.schemas.diagnosis import DiagnosisResultPayload
from app.domains.websocket.ws.manager import manager as ws_manager

logger = get_logger(__name__, category="diagnosis_result")

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
        "辅助材料：任务可能已上传需求、日志、CSV、压缩包等辅助文档，其中可能包含与本次问题相关的日志信息，"
        "统一存放于任务工作目录 .sdd/diagnosis/ 下。开始定位前请先检查该目录：若存在文件，请逐一阅读与问题相关的内容"
        "（压缩包请先解压再查看）；若目录不存在或为空，则说明暂无辅助文档，可忽略。"
    )

    parts.append(
        "你现在处理的是「问题定位任务」，目标是快速、准确地定位问题根因，而不是一次性全量修复。\n"
        "工作方式：\n"
        "1. 允许以辅助定位为目的修改代码、编写并执行测试用例（复现、隔离、验证性最小改动），"
        "但禁止一次性全量修复——定位优先，避免长时间占用；现网问题请保持最小侵入、快速收敛。\n"
        "2. 修复方案不需要在会话内大规模实施，请以建议形式给出修复方案与示例代码/补丁，避免一次性全量修复。\n"
        "3. 本会话支持多轮交互（HITL）：你可以通过提问向用户索取新的问题线索（日志、复现步骤、环境信息、变更记录等），"
        "收到新线索后继续收敛定位。"
    )
    return "\n\n" + "\n".join(parts)


def build_diagnosis_summary_prompt(task) -> str:
    """Summarize the fork's inherited evidence; submit through the domain tool."""
    meta = task.task_meta_json if isinstance(task.task_meta_json, dict) else {}
    prompt = (
        "请把当前问题排查会话总结为问题案例。仅总结已观察的事实，区分已验证根因与未验证假设。"
        "不要继续排查、执行命令、修改文件或执行修复。调用 submit_diagnosis 工具提交结果。"
        "证据不足时明确说明缺失信息并降低 confidence；不得补造证据。\n"
        "字段要求：\n"
        "1. summary：一段结论概述，说明现象、影响与是否已修复；\n"
        "2. root_cause：明确的根因结论，无法确认时写清未验证部分；\n"
        "3. evidence：字符串数组，每项一条独立、可核验的证据；不要写序号、项目符号或 Markdown 列表标记；\n"
        "4. fix_steps：字符串数组，每项一个可执行建议；不要写序号、项目符号或 Markdown 列表标记；\n"
        "5. fix_code：可选，给出示例补丁；\n"
        "6. code_context / call_chain / confidence：按结构化字段提交。\n"
        f"现象: {meta.get('phenomenon', '')}\n优先级: {meta.get('priority', '')}"
    )
    return prompt


def _clean(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_list(values) -> list[str] | None:
    if not isinstance(values, list):
        return None
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    return cleaned or None


# ────────────────────────── 持久化 ──────────────────────────


def _apply_payload(result: SddDiagnosisResult, payload: DiagnosisResultPayload) -> None:
    result.summary = _clean(payload.summary)
    result.root_cause = _clean(payload.root_cause)
    result.evidence_json = _clean_list(payload.evidence)
    result.fix_steps_json = _clean_list(payload.fix_steps)
    result.fix_code = _clean(payload.fix_code)
    result.confidence = payload.confidence
    result.code_context_json = [item.model_dump(exclude_none=True) for item in payload.code_context] or None
    result.similar_cases_json = [item.model_dump(exclude_none=True) for item in payload.similar_cases] or None
    result.call_chain_json = [item.model_dump(exclude_none=True) for item in payload.call_chain] or None


def _payload_dict(payload: DiagnosisResultPayload) -> dict:
    return payload.model_dump()


def _next_message_order_index(db: Session, task_id: str) -> int:
    """返回任务下一条消息应使用的 order_index（基于现有最大值 + 1）。"""
    messages = db.query(ChatMessage.metadata_json).filter(ChatMessage.task_id == task_id).all()
    max_order = 0
    for (metadata,) in messages:
        try:
            max_order = max(max_order, int((metadata or {}).get("order_index") or 0))
        except (TypeError, ValueError):
            continue
    return max_order + 1


def _sync_card_message(
    db: Session,
    *,
    task,
    result: SddDiagnosisResult,
    payload: DiagnosisResultPayload,
    actor_user_id: str,
) -> ChatMessage | None:
    """定位结果卡片消息：同一任务只保留一条，每次更新都移动到会话最后。"""
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
    from app.domains.search.capture import allocate_chat_seq

    metadata["order_index"] = allocate_chat_seq(db, task.id)
    if existing:
        existing.content = summary
        existing.metadata_json = metadata
        # 同时刷新落库时间（使用数据库服务器时间，与普通消息 created_at 同源），
        # 确保排序时卡片出现在最新消息之后
        existing.created_at = db.query(func.now()).scalar()
        message = existing
    else:
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
    message.sort_seq = metadata["order_index"]
    db.flush()
    result.source_chat_message_id = message.id
    return message


def _find_result(db: Session, task_id: str) -> SddDiagnosisResult | None:
    return db.query(SddDiagnosisResult).filter(SddDiagnosisResult.task_id == task_id).first()


def _enqueue_approved_case_update(db: Session, task, result: SddDiagnosisResult) -> None:
    """审批通过后，定位结果被修改时更新同一案例的 RAG 终态文档。"""
    if getattr(task, "task_type", None) != "DIAGNOSIS":
        return
    case = (
        db.query(SddCase)
        .filter(
            SddCase.source_task_id == task.id,
            SddCase.status == CaseStatus.APPROVED.value,
        )
        .first()
    )
    if case is None:
        return
    try:
        rag_outbox_service.enqueue_case_published(db, case, diagnosis_result=result)
    except Exception:
        logger.exception("Failed to enqueue RAG update for approved case task=%s", task.id)


def write_diagnosis_result(
    db: Session,
    *,
    task,
    payload: DiagnosisResultPayload,
    actor_user_id: str,
) -> SddDiagnosisResult | None:
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
    # 定位卡原地更新也产生新阅读版本（旧回执不能覆盖新内容）
    card = _sync_card_message(
        db,
        task=task,
        result=result,
        payload=payload,
        actor_user_id=actor_user_id,
    )
    from app.domains.task.services import reading_capture_service

    if card is not None:
        reading_capture_service.record_message_change(db, task_id=task.id, message=card)
    return result


def upsert_diagnosis_result_from_ai(
    db: Session, *, task, payload: DiagnosisResultPayload, actor_user_id: str
) -> SddDiagnosisResult | None:
    """Legacy committing wrapper around the transaction-owned projection writer."""
    result = write_diagnosis_result(db, task=task, payload=payload, actor_user_id=actor_user_id)
    if result is not None:
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
    # 用户编辑卡片同样刷新阅读版本（同事务）
    card = _sync_card_message(
        db,
        task=task,
        result=result,
        payload=data,
        actor_user_id=actor_user_id,
    )
    from app.domains.task.services import reading_capture_service

    if card is not None:
        reading_capture_service.record_message_change(db, task_id=task.id, message=card)
    db.commit()
    db.refresh(result)
    _enqueue_approved_case_update(db, task, result)
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
        "evidence": result.evidence_json if isinstance(result.evidence_json, list) else [],
        "fix_steps": result.fix_steps_json if isinstance(result.fix_steps_json, list) else [],
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


def _build_diagnosis_result_message_payload_sync(
    task_id: str,
    message_id: str,
) -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        task = db.query(SddTask).filter(SddTask.id == task_id).first()
        message = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
        if task is None or message is None:
            return None
        return _build_diagnosis_result_message_payload(db, task=task, message=message)
    finally:
        db.close()


def _build_diagnosis_result_message_payload(db: Session, *, task, message: ChatMessage) -> dict[str, Any]:
    """Build the WS payload while a short-lived DB session is owned by caller."""
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
    return WSChatPayload(
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


async def publish_diagnosis_result_message(*, task_id: str, message_id: str) -> None:
    """Build the card payload off-loop, then broadcast without holding ORM state."""
    payload = await run_db(_build_diagnosis_result_message_payload_sync, task_id, message_id)
    if payload:
        await ws_manager.send_message_to_room(task_id, WSMessage(type="chat_message", payload=payload))


# ──────────────────────── 一键总结问题案例 ────────────────────────


class DiagnosisSummaryError(ValueError):
    """一键总结问题案例的业务冲突（携带 HTTP 状态码，路由层统一映射）。"""

    def __init__(self, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


def prepare_diagnosis_summary_sync(db: Session, *, ws_id: str, task_id: str, actor_user_id: str) -> dict[str, Any]:
    """一键总结问题案例：守卫检查 + 幂等创建后台总结作业（单事务）。

    路由层负责权限校验与任务锁；这里完成任务类型守卫 → 提交互斥 →
    已采纳案例互斥 → 总结/会话作业互斥 → 作业创建。
    SubmissionError（提交受理中）原样上抛，由路由按 {code, message} 形状映射。
    """
    task = db.query(SddTask).filter(SddTask.id == task_id, SddTask.workspace_id == ws_id).first()
    if not task:
        raise DiagnosisSummaryError("Task not found", status_code=404)
    from app.domains.local_resource.client import ResourceError
    from app.domains.local_resource.service import require_operation

    try:
        require_operation(db, task, actor_user_id)
    except ResourceError as exc:
        raise DiagnosisSummaryError(str(exc), status_code=exc.status_code) from exc
    if getattr(task, "task_type", None) != "DIAGNOSIS":
        raise DiagnosisSummaryError("Only diagnosis tasks support diagnosis results", status_code=403)
    from app.domains.task.services.chat_submission_service import assert_no_preparing_submission

    assert_no_preparing_submission(db, task_id)
    existing_case = (
        db.query(SddCase)
        .filter(
            SddCase.workspace_id == ws_id,
            SddCase.source_task_id == task.id,
        )
        .first()
    )
    diagnosis_result = getattr(task, "diagnosis_result", None)
    if existing_case is not None or (diagnosis_result is not None and diagnosis_result.status == "CONFIRMED"):
        raise DiagnosisSummaryError("Case already adopted, diagnosis summarization is not allowed", status_code=409)

    active_summary = find_active_summary_job(db, task.id)
    if active_summary is not None:
        return {
            "job_id": active_summary.id,
            "status": serialize_job(active_summary).get("status"),
            "task_id": task.id,
            "created": False,
        }
    if find_active_chat_job(db, task.id) is not None:
        raise DiagnosisSummaryError("会话进行中，请等待完成或停止后再一键总结问题案例", status_code=409)
    job = create_diagnosis_summary_job(
        db,
        workspace_id=ws_id,
        task_id=task.id,
        creator_id=actor_user_id,
    )
    return {
        "job_id": job.id,
        "status": "PENDING",
        "task_id": task.id,
        "created": True,
    }
