"""
问题定位结果：AI 会话反填提取与卡片消息测试

覆盖：prompt 契约、fenced JSON 提取、降级策略、AI 反填 upsert、
卡片消息稳定更新、CONFIRMED 保护、非诊断任务跳过。
"""

import os
import sys

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.dirname(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

from app.domains.task.models.chat import ChatMessage, MessageRole, MessageType  # noqa: E402
from app.domains.task.models.diagnosis import SddDiagnosisResult  # noqa: E402
from app.domains.task.models.task import TaskType  # noqa: E402
from app.domains.task.services import diagnosis_result_service  # noqa: E402
from app.domains.task.schemas.diagnosis import DiagnosisResultPayload  # noqa: E402
from test_workspace_asset_boundary import _build_db, _session, _seed_workspace  # noqa: E402


def _seed_diagnosis_task(db, workspace_id="ws-diag-x", task_id="task-diag-x"):
    user, workspace, task = _seed_workspace(db, workspace_id=workspace_id, task_id=task_id)
    task.task_type = TaskType.DIAGNOSIS.value
    task.task_meta_json = {"phenomenon": "接口偶发超时", "priority": "P1"}
    db.commit()
    return user, workspace, task


# ────────────────────────── Prompt 契约 ──────────────────────────


def test_prompt_suffix_declares_diagnosis_contract():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            _, _, task = _seed_diagnosis_task(db)
            suffix = diagnosis_result_service.build_diagnosis_prompt_suffix(task)

            assert "[问题定位任务]" in suffix
            assert "现象: 接口偶发超时" in suffix
            assert "优先级: P1" in suffix
            # 任务性质与定位优先约束
            assert "问题定位任务" in suffix and "不是一次性全量修复" in suffix
            assert "禁止一次性全量修复" in suffix
            assert "现网问题请保持最小侵入" in suffix
            # 允许辅助定位的改码与测试用例
            assert "修改代码" in suffix and "测试用例" in suffix
            # 多轮 HITL 补充线索
            assert "多轮交互（HITL）" in suffix
            assert "索取新的问题线索" in suffix
            # 结构化结果输出约定
            assert '```json' in suffix
            assert '"code_context"' in suffix and '"similar_cases"' in suffix and '"call_chain"' in suffix
            assert '"confidence"' in suffix
    finally:
        engine.dispose()


def test_prompt_suffix_empty_for_development_task():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_workspace(db, workspace_id="ws-dev-x", task_id="task-dev-x")
            task.task_type = TaskType.DEVELOPMENT.value
            db.commit()
            assert diagnosis_result_service.build_diagnosis_prompt_suffix(task) == ""
    finally:
        engine.dispose()


# ────────────────────────── JSON 提取 ──────────────────────────

_JSON_BLOCK = """{
  "summary": "连接池耗尽",
  "root_cause": "池配置过小",
  "evidence_chain": "日志超时",
  "fix_suggestion": "扩容",
  "fix_code": "maxActive=200",
  "code_context": [{"file_path": "src/pool.py", "start_line": 12}],
  "similar_cases": [{"title": "历史案例"}],
  "call_chain": [{"seq": 1, "function": "handle"}],
  "confidence": 88
}"""


def test_extract_valid_fenced_json():
    text = f"定位结论如下：\n```json\n{_JSON_BLOCK}\n```\n请补充线索。"
    payload = diagnosis_result_service.extract_payload_from_text(text)
    assert payload is not None
    assert payload.root_cause == "池配置过小"
    assert payload.confidence == 88
    assert payload.code_context[0].file_path == "src/pool.py"
    assert payload.similar_cases[0].title == "历史案例"
    assert payload.call_chain[0].function == "handle"


def test_extract_takes_last_block_and_ignores_bad_ones():
    bad_block = "```json\n{invalid json\n```"
    good_block = "```json\n" + _JSON_BLOCK + "\n```"
    text = f"先试一次：{bad_block}\n再来：{good_block}"
    payload = diagnosis_result_service.extract_payload_from_text(text)
    assert payload is not None
    assert payload.root_cause == "池配置过小"


def test_extract_unwraps_diagnosis_key():
    text = '```json\n{"diagnosis": ' + _JSON_BLOCK + "}\n```"
    payload = diagnosis_result_service.extract_payload_from_text(text)
    assert payload is not None
    assert payload.summary == "连接池耗尽"


def test_extract_confidence_out_of_range_falls_back_to_summary():
    block = _JSON_BLOCK.replace('"confidence": 88', '"confidence": 150')
    text = f"```json\n{block}\n```"
    payload = diagnosis_result_service.extract_payload_from_text(text)
    assert payload is not None
    assert payload.summary and payload.summary.startswith("```json")  # 降级为原文摘要
    assert payload.root_cause is None


def test_extract_fallback_summary_only_for_plain_text():
    text = "问题大概率是连接池配置过小导致的超时。"
    payload = diagnosis_result_service.extract_payload_from_text(text)
    assert payload is not None
    assert payload.summary == text
    assert payload.root_cause is None
    assert payload.confidence == 0


def test_extract_none_for_empty_text():
    assert diagnosis_result_service.extract_payload_from_text("   ") is None
    assert diagnosis_result_service.extract_payload_from_text("") is None


# ────────────────────────── AI 反填 upsert 与卡片消息 ──────────────────────────


def test_upsert_from_ai_creates_and_updates_single_card_message():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, _, task = _seed_diagnosis_task(db)
            payload = DiagnosisResultPayload.model_validate(
                {
                    "summary": "第一轮：疑似连接池",
                    "root_cause": "连接池偏小",
                    "confidence": 60,
                    "code_context": [{"file_path": "src/pool.py", "start_line": 12}],
                }
            )
            result = diagnosis_result_service.upsert_diagnosis_result_from_ai(
                db, task=task, payload=payload, actor_user_id=user.id
            )
            assert result is not None
            assert result.extracted_from_ai is True
            assert result.extracted_at is not None
            assert result.status == "DRAFT"
            first_message_id = result.source_chat_message_id
            assert first_message_id

            messages = (
                db.query(ChatMessage)
                .filter(
                    ChatMessage.task_id == task.id,
                    ChatMessage.message_type == MessageType.DIAGNOSIS_RESULT,
                )
                .all()
            )
            assert len(messages) == 1
            assert messages[0].role == MessageRole.ASSISTANT
            assert messages[0].content == "第一轮：疑似连接池"
            assert messages[0].metadata_json["confidence"] == 60

            # 第二轮：HITL 补充线索后原位更新同一卡片
            payload2 = DiagnosisResultPayload.model_validate(
                {"summary": "第二轮：确认连接池耗尽", "root_cause": "连接池耗尽", "confidence": 95}
            )
            result2 = diagnosis_result_service.upsert_diagnosis_result_from_ai(
                db, task=task, payload=payload2, actor_user_id=user.id
            )
            assert result2.source_chat_message_id == first_message_id
            messages = (
                db.query(ChatMessage)
                .filter(
                    ChatMessage.task_id == task.id,
                    ChatMessage.message_type == MessageType.DIAGNOSIS_RESULT,
                )
                .all()
            )
            assert len(messages) == 1
            assert messages[0].content == "第二轮：确认连接池耗尽"
            assert messages[0].metadata_json["confidence"] == 95
    finally:
        engine.dispose()


def test_upsert_from_ai_skips_confirmed_result():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, _, task = _seed_diagnosis_task(db)
            db.add(
                SddDiagnosisResult(
                    task_id=task.id,
                    workspace_id=task.workspace_id,
                    created_by_id=user.id,
                    root_cause="已确认根因",
                    status="CONFIRMED",
                )
            )
            db.commit()
            db.refresh(task)
            payload = DiagnosisResultPayload.model_validate({"summary": "AI 新结论"})
            result = diagnosis_result_service.upsert_diagnosis_result_from_ai(
                db, task=task, payload=payload, actor_user_id=user.id
            )
            assert result is None
            saved = db.query(SddDiagnosisResult).filter(SddDiagnosisResult.task_id == task.id).first()
            assert saved.root_cause == "已确认根因"
            assert saved.summary is None
    finally:
        engine.dispose()


def test_upsert_from_ai_skips_development_task():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, _, task = _seed_workspace(db, workspace_id="ws-dev2", task_id="task-dev2")
            task.task_type = TaskType.DEVELOPMENT.value
            db.commit()
            payload = DiagnosisResultPayload.model_validate({"summary": "不该出现"})
            result = diagnosis_result_service.upsert_diagnosis_result_from_ai(
                db, task=task, payload=payload, actor_user_id=user.id
            )
            assert result is None
            assert (
                db.query(SddDiagnosisResult).filter(SddDiagnosisResult.task_id == task.id).count() == 0
            )
    finally:
        engine.dispose()
