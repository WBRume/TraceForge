"""
RAG 适配层集成测试。

覆盖：
- 审批通过后终态案例入队
- 审批通过后定位结果修改覆盖更新同一 doc_key
- 审批前定位结果修改不入队
- 标准文档构建内容完整
"""

import os
import sys

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.dirname(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

from app.domains.rag import models as rag_models  # noqa: E402,F401
from app.domains.rag.schemas import RagOutboxStatus  # noqa: E402
from app.domains.rag.services import outbox_service  # noqa: E402
from app.domains.case_center.models.case import (  # noqa: E402
    CasePriority,
    CaseStatus,
    SddCase,
)
from app.domains.task.models.diagnosis import (  # noqa: E402
    DiagnosisResultStatus,
    SddDiagnosisResult,
)
from app.domains.task.models.task import TaskType  # noqa: E402
from app.domains.task.schemas.diagnosis import DiagnosisResultPayload  # noqa: E402
from app.domains.task.services import diagnosis_result_service  # noqa: E402
from test_workspace_asset_boundary import _build_db, _seed_workspace, _session  # noqa: E402


def _seed_diagnosis_task(db, workspace_id="ws-rag", task_id="task-rag"):
    user, workspace, task = _seed_workspace(db, workspace_id=workspace_id, task_id=task_id)
    task.task_type = TaskType.DIAGNOSIS.value
    task.name = "接口偶发超时定位"
    db.commit()
    return user, workspace, task


def _seed_approved_case(db, task):
    case = SddCase(
        id="case-rag-1",
        workspace_id=task.workspace_id,
        creator_id=task.creator_id,
        source_task_id=task.id,
        title=task.name,
        problem_description="生产环境接口偶发超时",
        root_cause="连接池耗尽",
        solution="扩容连接池并增加熔断",
        analysis_process="压测复现，查看日志",
        category="PUBLIC",
        priority=CasePriority.P1.value,
        status=CaseStatus.APPROVED.value,
        review_round=1,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def test_approve_case_enqueues_rag_outbox():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db)
            case = _seed_approved_case(db, task)

            row = outbox_service.enqueue_case_published(db, case)
            assert row is not None
            assert row.doc_key == f"case:{case.id}"
            assert row.status == RagOutboxStatus.PENDING.value
            payload = row.payload_json
            assert payload["source_type"] == "case"
            assert payload["source_id"] == case.id
            assert payload["version"] == 1
            assert "连接池耗尽" in payload["content"]
            assert payload["metadata"]["category"] == "PUBLIC"
            assert payload["metadata"]["review_round"] == 1

            # 同一案例重复 enqueue 应覆盖版本，不新增行
            row2 = outbox_service.enqueue_case_published(db, case)
            assert row2.id == row.id
            assert row2.payload_json["version"] == 2
    finally:
        engine.dispose()


def test_diagnosis_result_update_after_approval_enqueues_update():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db)
            case = _seed_approved_case(db, task)

            # 先产生初始终态文档
            outbox_service.enqueue_case_published(db, case)

            result = diagnosis_result_service.upsert_diagnosis_result_from_user(
                db,
                task=task,
                data=DiagnosisResultPayload(
                    summary="更新后的结论",
                    root_cause="连接池大小配置过小",
                ),
                actor_user_id=user.id,
            )
            assert result.status == DiagnosisResultStatus.DRAFT.value

            rows = (
                db.query(rag_models.SddRagOutbox)
                .filter(rag_models.SddRagOutbox.doc_key == f"case:{case.id}")
                .all()
            )
            assert len(rows) == 1
            row = rows[0]
            assert row.payload_json["version"] == 2
            assert "连接池大小配置过小" in row.payload_json["content"]
    finally:
        engine.dispose()


def test_diagnosis_result_update_before_approval_does_not_enqueue():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db)
            # 只建 DRAFT 案例，不建 APPROVED 案例
            case = SddCase(
                id="case-rag-draft",
                workspace_id=task.workspace_id,
                creator_id=task.creator_id,
                source_task_id=task.id,
                title=task.name,
                category="PUBLIC",
                priority=CasePriority.P2.value,
                status=CaseStatus.DRAFT.value,
                review_round=1,
            )
            db.add(case)
            db.commit()

            diagnosis_result_service.upsert_diagnosis_result_from_user(
                db,
                task=task,
                data=DiagnosisResultPayload(root_cause="未审批，不应推送"),
                actor_user_id=user.id,
            )

            count = db.query(rag_models.SddRagOutbox).count()
            assert count == 0
    finally:
        engine.dispose()


def test_mock_provider_upserts_document():
    from app.domains.rag.providers.mock_provider import MockRagProvider
    from app.domains.rag.schemas import RagDocument

    provider = MockRagProvider()
    doc = RagDocument(
        doc_id="rag:case:test",
        source_id="test",
        workspace_id="ws",
        title="T",
        content="C",
    )
    assert provider.upsert(doc) is True
    assert provider.upserted["rag:case:test"].content == "C"
    assert provider.delete("case:test") is True
    assert provider.deleted_keys == ["knowledge:case:test"]