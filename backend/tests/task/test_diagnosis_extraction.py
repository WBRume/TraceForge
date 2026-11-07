"""
问题定位结果：AI 会话反填提取与卡片消息测试

覆盖：工具契约严格校验、AI 反填 upsert、
卡片消息稳定更新、CONFIRMED 保护、非诊断任务跳过。
"""

import os
import sys

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

from app.domains.task.models.chat import ChatMessage, MessageRole, MessageType  # noqa: E402
from app.domains.task.models.diagnosis import SddDiagnosisResult  # noqa: E402
from app.domains.task.models.task import TaskType  # noqa: E402
from app.domains.task.schemas.diagnosis import DiagnosisResultPayload  # noqa: E402
from app.domains.task.services import diagnosis_result_service  # noqa: E402
from tests.workspace_asset.test_workspace_asset_boundary import _build_db, _seed_workspace, _session  # noqa: E402


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
            # 辅助文档目录指引：告知 agent 上传的日志/文档可能在 .sdd/diagnosis/ 下
            assert ".sdd/diagnosis" in suffix
            assert "辅助文档" in suffix
            assert "日志" in suffix
            # 任务性质与定位优先约束
            assert "问题定位任务" in suffix and "不是一次性全量修复" in suffix
            assert "禁止一次性全量修复" in suffix
            assert "现网问题请保持最小侵入" in suffix
            # 允许辅助定位的改码与测试用例
            assert "修改代码" in suffix and "测试用例" in suffix
            # 多轮 HITL 补充线索
            assert "多轮交互（HITL）" in suffix
            assert "索取新的问题线索" in suffix
            # 初始化提示词不再内嵌「每轮输出 JSON 定位结果」的约定（已收敛为「一键总结」生成）
            assert "```json" not in suffix
            assert '"confidence"' not in suffix
            assert '"call_chain"' not in suffix
            assert "每轮回复结束时" not in suffix
            assert "JSON" not in suffix
            assert "fix_suggestion" not in suffix
            assert "fix_code" not in suffix
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


def test_summary_prompt_requires_tool_and_preserves_readonly_fork_context():
    import pytest
    from pydantic import ValidationError

    from app.agents.domain_tools.contracts import DiagnosisSubmission

    engine, factory = _build_db()
    try:
        with _session(factory) as db:
            _, _, task = _seed_diagnosis_task(db)
            prompt = diagnosis_result_service.build_diagnosis_summary_prompt(task)
            assert "submit_diagnosis" in prompt
            assert "```json" not in prompt
            assert "接口偶发超时" in prompt
            valid = {
                "summary": "连接池耗尽",
                "root_cause": "池配置过小",
                "evidence_chain": "日志超时",
                "fix_suggestion": "扩容",
            }
            assert DiagnosisSubmission.model_validate(valid, strict=True).root_cause == "池配置过小"
            for invalid in ({**valid, "confidence": 150}, {**valid, "confidence": "85%"}, {"diagnosis": valid}, "正文"):
                with pytest.raises(ValidationError):
                    DiagnosisSubmission.model_validate(invalid, strict=True)
    finally:
        engine.dispose()


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


def test_upsert_from_user_persists_edits_to_result_and_card():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, _, task = _seed_diagnosis_task(db)
            diagnosis_result_service.upsert_diagnosis_result_from_ai(
                db,
                task=task,
                payload=DiagnosisResultPayload.model_validate(
                    {"summary": "AI 初稿", "root_cause": "AI 根因", "confidence": 60}
                ),
                actor_user_id=user.id,
            )

            edited = DiagnosisResultPayload.model_validate(
                {
                    "summary": "用户修正后的总结",
                    "root_cause": "用户修正根因",
                    "evidence_chain": "证据链已补充",
                    "fix_suggestion": "修复建议已补充",
                    "confidence": 88,
                    "code_context": [{"file_path": "src/pool.py", "start_line": 12}],
                    "similar_cases": [{"title": "用户补充案例"}],
                    "call_chain": [{"seq": 1, "module": "Gateway", "function": "handle"}],
                }
            )
            result = diagnosis_result_service.upsert_diagnosis_result_from_user(
                db,
                task=task,
                data=edited,
                actor_user_id=user.id,
            )
            assert result.summary == "用户修正后的总结"
            assert result.root_cause == "用户修正根因"
            assert result.evidence_chain == "证据链已补充"
            assert result.fix_suggestion == "修复建议已补充"
            assert result.confidence == 88
            assert result.code_context_json[0]["file_path"] == "src/pool.py"
            assert result.similar_cases_json[0]["title"] == "用户补充案例"
            assert result.call_chain_json[0]["module"] == "Gateway"

            message = db.query(ChatMessage).filter(ChatMessage.id == result.source_chat_message_id).first()
            assert message is not None
            assert message.metadata_json["summary"] == "用户修正后的总结"
            assert message.metadata_json["root_cause"] == "用户修正根因"
            assert message.metadata_json["confidence"] == 88
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
            assert db.query(SddDiagnosisResult).filter(SddDiagnosisResult.task_id == task.id).count() == 0
    finally:
        engine.dispose()
