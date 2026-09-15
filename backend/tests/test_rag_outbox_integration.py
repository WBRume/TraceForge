"""
案例同步队列（批次）集成测试。

覆盖：
- 审批通过后入队 -> 追加到当前 RUNNING 队列（无则自动新建）
- 内容未变化重复 enqueue 不新建队列
- 打包下载本身不改变状态；保存成功后确认 -> CONSUMED 终态 + 案例 EXPORTED，再次确认幂等
- 单案例下载本身不改变状态；保存成功后确认 -> 案例 EXPORTED 但队列仍 RUNNING
- 队列终态后新审批案例 -> 自动创建新 RUNNING 队列
- 审批后定位结果更新 -> 新版本移入当前 RUNNING 队列
- 审批前定位结果更新不入队
- 队列/案例查询按工作区访问范围过滤
- 运维队列来源不再包含 rag
"""

import io
import os
import sys
import zipfile

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.dirname(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

from app.domains.rag import models as rag_models  # noqa: E402
from app.domains.rag.models import SddRagSyncQueue  # noqa: E402
from app.domains.rag.schemas import RagOutboxStatus, RagQueueStatus  # noqa: E402
from app.domains.rag.services import document_builder, outbox_service  # noqa: E402
from app.domains.auth.models.user import (  # noqa: E402
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)
from app.domains.case_center.models.case import (  # noqa: E402
    CasePriority,
    CaseStatus,
    SddCase,
)
from app.domains.task.models.diagnosis import (  # noqa: E402
    DiagnosisResultStatus,
)
from app.domains.task.models.task import SddTask, TaskStatus, TaskType  # noqa: E402
from app.domains.task.schemas.diagnosis import DiagnosisResultPayload  # noqa: E402
from app.domains.task.services import diagnosis_result_service  # noqa: E402
from test_workspace_asset_boundary import _build_db, _seed_workspace, _session  # noqa: E402


def _seed_diagnosis_task(db, workspace_id="ws-rag", task_id="task-rag"):
    user, workspace, task = _seed_workspace(db, workspace_id=workspace_id, task_id=task_id)
    task.task_type = TaskType.DIAGNOSIS.value
    task.name = "接口偶发超时定位"
    db.commit()
    return user, workspace, task


def _seed_approved_case(db, task, case_id="case-rag-1"):
    case = SddCase(
        id=case_id,
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


def _queues(db):
    return (
        db.query(SddRagSyncQueue)
        .order_by(SddRagSyncQueue.created_at.asc())
        .all()
    )


def test_approve_case_enqueues_into_workspace_running_queue():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db)
            case = _seed_approved_case(db, task)

            row = outbox_service.enqueue_case_published(db, case)
            assert row is not None
            assert row.doc_key == f"case:{case.id}"
            assert row.status == RagOutboxStatus.QUEUED.value
            assert row.queue_id is not None
            assert row.workspace_id == workspace.id

            queues = _queues(db)
            assert len(queues) == 1
            queue = queues[0]
            assert queue.status == RagQueueStatus.RUNNING.value
            assert queue.workspace_id == workspace.id
            assert queue.id == row.queue_id
            assert queue.name.startswith("RAG-")

            payload = row.payload_json
            assert payload["source_type"] == "case"
            assert payload["source_id"] == case.id
            assert payload["version"] == 1
            assert "连接池耗尽" in payload["content"]
            assert payload["metadata"]["category"] == "PUBLIC"
            assert payload["metadata"]["review_round"] == 1

            # 同一案例内容未变化时重复 enqueue 不应新建队列/重置
            row2 = outbox_service.enqueue_case_published(db, case)
            assert row2.id == row.id
            assert row2.queue_id == queue.id
            assert row2.payload_json["version"] == 1
            assert len(_queues(db)) == 1
    finally:
        engine.dispose()


def test_queue_export_does_not_mark_until_confirmed():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db)
            case = _seed_approved_case(db, task)
            row = outbox_service.enqueue_case_published(db, case)
            queue = _queues(db)[0]

            # 打包下载本身不改变状态（“点击下载时不应标记”）
            content = outbox_service.export_queue_zip(db, queue)
            assert content.startswith(b"PK")
            db.refresh(queue)
            db.refresh(row)
            assert queue.status == RagQueueStatus.RUNNING.value
            assert queue.consumed_at is None
            assert row.status == RagOutboxStatus.QUEUED.value
            assert row.exported_at is None

            # 保存成功后确认 -> 首次确认锁定 CONSUMED 终态 + 全部案例 EXPORTED
            outbox_service.mark_queue_exported(db, queue)
            db.refresh(queue)
            db.refresh(row)
            assert queue.status == RagQueueStatus.CONSUMED.value
            assert queue.consumed_at is not None
            assert row.status == RagOutboxStatus.EXPORTED.value
            assert row.exported_at is not None

            # 终态后再次下载 + 再次确认：幂等，状态不变（重试设计）
            content2 = outbox_service.export_queue_zip(db, queue)
            assert content2.startswith(b"PK")
            outbox_service.mark_queue_exported(db, queue)
            db.refresh(queue)
            db.refresh(row)
            assert queue.status == RagQueueStatus.CONSUMED.value
            assert row.status == RagOutboxStatus.EXPORTED.value

            with zipfile.ZipFile(io.BytesIO(content2)) as zf:
                names = zf.namelist()
                assert len(names) == 1
                md = zf.read(names[0]).decode("utf-8")
                assert md.startswith("---")
                assert "# " in md
    finally:
        engine.dispose()


def test_single_case_export_does_not_mark_until_confirmed():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db)
            case = _seed_approved_case(db, task)
            row = outbox_service.enqueue_case_published(db, case)
            queue = _queues(db)[0]

            # 单案例下载本身不改变状态
            content = outbox_service.build_single_case_markdown(db, row)
            assert content.startswith("---")
            db.refresh(queue)
            db.refresh(row)
            assert queue.status == RagQueueStatus.RUNNING.value
            assert row.status == RagOutboxStatus.QUEUED.value

            # 保存成功后确认 -> 标记 EXPORTED，但队列仍 RUNNING
            outbox_service.mark_case_exported(db, row)
            db.refresh(queue)
            db.refresh(row)
            assert queue.status == RagQueueStatus.RUNNING.value
            assert row.status == RagOutboxStatus.EXPORTED.value
            assert row.exported_at is not None
    finally:
        engine.dispose()


def test_queue_consumed_then_new_approval_creates_new_running_queue():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db)
            case = _seed_approved_case(db, task, case_id="case-rag-batch-1")
            outbox_service.enqueue_case_published(db, case)
            first_queue = _queues(db)[0]
            outbox_service.export_queue_zip(db, first_queue)
            outbox_service.mark_queue_exported(db, first_queue)
            db.refresh(first_queue)
            assert first_queue.status == RagQueueStatus.CONSUMED.value

            # 新审批案例：无 RUNNING 队列 -> 自动新建
            case2 = _seed_approved_case(db, task, case_id="case-rag-batch-2")
            row2 = outbox_service.enqueue_case_published(db, case2)
            queues = _queues(db)
            assert len(queues) == 2
            second_queue = queues[1]
            assert second_queue.status == RagQueueStatus.RUNNING.value
            assert second_queue.id != first_queue.id
            assert row2.queue_id == second_queue.id

            # 同名案例更新内容时进入当前 RUNNING 队列（即使是已有行）
            case2.root_cause = "更新后的根因"
            db.add(case2)
            db.commit()
            row2b = outbox_service.enqueue_case_published(db, case2)
            assert row2b.id == row2.id
            assert row2b.queue_id == second_queue.id
            assert row2b.payload_json["version"] == 2
    finally:
        engine.dispose()


def test_diagnosis_result_update_after_approval_enqueues_update():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db)
            case = _seed_approved_case(db, task)

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
            assert row.status == RagOutboxStatus.QUEUED.value
            # 同一 doc_key 更新后仍留在当前 RUNNING 队列
            assert row.queue_id == _queues(db)[0].id
    finally:
        engine.dispose()


def test_diagnosis_result_update_before_approval_does_not_enqueue():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db)
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
            assert len(_queues(db)) == 0
    finally:
        engine.dispose()


def _seed_second_workspace(db, user, ws_id="ws-rag-b", task_id="task-rag-b", name="Workspace B"):
    """第二个工作区复用同一用户（多工作区成员），避免 user email 唯一冲突。"""
    ws_b = Workspace(
        id=ws_id, name=name, owner_id=user.id, project_path="G:/repo"
    )
    member_b = WorkspaceMember(
        id=f"member-{ws_id}",
        workspace_id=ws_b.id,
        user_id=user.id,
        role=WorkspaceRole.OWNER,
        permissions_json="[]",
        is_expert=True,
    )
    task_b = SddTask(
        id=task_id,
        workspace_id=ws_b.id,
        creator_id=user.id,
        name="Implement checkout B",
        description="Task process boundary",
        project_path="G:/repo",
        status=TaskStatus.PLANNING,
    )
    db.add_all([ws_b, member_b, task_b])
    db.commit()
    task_b.task_type = TaskType.DIAGNOSIS.value
    task_b.name = "接口偶发超时定位 B"
    db.commit()
    return ws_b, task_b


def test_queues_are_isolated_by_workspace():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, ws_a, task_a = _seed_diagnosis_task(
                db, workspace_id="ws-rag-a", task_id="task-rag-a"
            )
            ws_b, task_b = _seed_second_workspace(db, user)

            case_a = _seed_approved_case(db, task_a, case_id="case-rag-ws-a")
            case_b = _seed_approved_case(db, task_b, case_id="case-rag-ws-b")
            row_a = outbox_service.enqueue_case_published(db, case_a)
            row_b = outbox_service.enqueue_case_published(db, case_b)

            queues = {q.workspace_id: q for q in _queues(db)}
            assert set(queues.keys()) == {"ws-rag-a", "ws-rag-b"}
            queue_a = queues["ws-rag-a"]
            queue_b = queues["ws-rag-b"]
            assert queue_a.id != queue_b.id
            assert row_a.queue_id == queue_a.id
            assert row_b.queue_id == queue_b.id
            assert queue_a.name != queue_b.name

            # 各自独立消费：消费 A 不影响 B
            outbox_service.export_queue_zip(db, queue_a)
            outbox_service.mark_queue_exported(db, queue_a)
            db.refresh(queue_a)
            db.refresh(queue_b)
            db.refresh(row_a)
            db.refresh(row_b)
            assert queue_a.status == RagQueueStatus.CONSUMED.value
            assert row_a.status == RagOutboxStatus.EXPORTED.value
            assert queue_b.status == RagQueueStatus.RUNNING.value
            assert row_b.status == RagOutboxStatus.QUEUED.value

            # B 未消费：新审批案例仍进 B 的 RUNNING 队列
            case_b2 = _seed_approved_case(db, task_b, case_id="case-rag-ws-b2")
            row_b2 = outbox_service.enqueue_case_published(db, case_b2)
            assert row_b2.queue_id == queue_b.id

            # A 已消费：新审批案例进入 A 的新 RUNNING 队列
            case_a2 = _seed_approved_case(db, task_a, case_id="case-rag-ws-a2")
            row_a2 = outbox_service.enqueue_case_published(db, case_a2)
            queue_a_new = (
                db.query(SddRagSyncQueue)
                .filter(
                    SddRagSyncQueue.id == row_a2.queue_id,
                    SddRagSyncQueue.workspace_id == "ws-rag-a",
                )
                .first()
            )
            assert queue_a_new is not None
            assert queue_a_new.status == RagQueueStatus.RUNNING.value
            assert queue_a_new.id != queue_a.id
    finally:
        engine.dispose()


def test_list_queues_and_cases_respect_workspace_scope():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, ws_a, task_a = _seed_diagnosis_task(
                db, workspace_id="ws-rag-a", task_id="task-rag-a"
            )
            ws_b, task_b = _seed_second_workspace(db, user)

            case_a = _seed_approved_case(db, task_a, case_id="case-rag-ws-a")
            case_b = _seed_approved_case(db, task_b, case_id="case-rag-ws-b")
            outbox_service.enqueue_case_published(db, case_a)
            outbox_service.enqueue_case_published(db, case_b)
            queue_a = (
                db.query(SddRagSyncQueue)
                .filter(SddRagSyncQueue.workspace_id == "ws-rag-a")
                .first()
            )
            queue_b = (
                db.query(SddRagSyncQueue)
                .filter(SddRagSyncQueue.workspace_id == "ws-rag-b")
                .first()
            )

            # 管理员（workspace_ids=None）：全部队列可见
            queues_admin, total_admin = outbox_service.list_queues(db, workspace_ids=None)
            assert total_admin == 2
            assert {q.id for q in queues_admin} == {queue_a.id, queue_b.id}

            # 仅 ws-a 用户：只见 ws-a 的队列，案例清单只含 ws-a
            queues_a, total_a = outbox_service.list_queues(
                db, workspace_ids=["ws-rag-a"]
            )
            assert total_a == 1
            assert queues_a[0].id == queue_a.id
            cases_a, _ = outbox_service.list_queue_cases(
                db, queue_id=queue_a.id, workspace_ids=["ws-rag-a"]
            )
            assert {r.case_id for r in cases_a} == {"case-rag-ws-a"}

            # 无关工作区用户：不可见
            queues_empty, total_empty = outbox_service.list_queues(
                db, workspace_ids=["ws-unknown"]
            )
            assert total_empty == 0
            assert queues_empty == []

            # get_queue 权限校验（按队列归属）
            assert (
                outbox_service.get_queue(db, queue_id=queue_a.id, workspace_ids=None)
                is not None
            )
            assert (
                outbox_service.get_queue(
                    db, queue_id=queue_a.id, workspace_ids=["ws-rag-a"]
                )
                is not None
            )
            assert (
                outbox_service.get_queue(
                    db, queue_id=queue_a.id, workspace_ids=["ws-rag-b"]
                )
                is None
            )
            assert (
                outbox_service.get_queue(
                    db, queue_id=queue_a.id, workspace_ids=["ws-unknown"]
                )
                is None
            )
            # 未归属（legacy）队列对普通用户不可见，管理员可见
            assert (
                outbox_service.get_queue(
                    db, queue_id=queue_b.id, workspace_ids=["ws-unknown"]
                )
                is None
            )
    finally:
        engine.dispose()


def test_build_case_document_problem_description_uses_task_phenomenon():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(
                db, workspace_id="ws-rag-phenomenon", task_id="task-rag-phenomenon"
            )
            task.task_meta_json = {"phenomenon": "接口偶发超时", "priority": "P1"}
            case = _seed_approved_case(db, task)
            case.problem_description = "旧背景\n\n接口偶发超时"
            db.commit()
            db.refresh(case)

            doc = document_builder.build_case_document(case)
            assert "接口偶发超时" in doc.content
            assert "旧背景" not in doc.content
    finally:
        engine.dispose()


def test_build_zip_bytes_bundles_markdown_documents():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(
                db, workspace_id="ws-rag-zip", task_id="task-rag-zip"
            )
            case = _seed_approved_case(db, task)
            row = outbox_service.enqueue_case_published(db, case)

            content = outbox_service.build_zip_bytes([row])
            assert content.startswith(b"PK")
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                names = zf.namelist()
                assert len(names) == 1
                md = zf.read(names[0]).decode("utf-8")
                assert md.startswith("---")
                assert "# " in md
    finally:
        engine.dispose()


def test_ops_queue_sources_no_longer_include_rag():
    from app.domains.ai.services import queue_service

    assert "rag" not in queue_service.QUEUE_SOURCES
    assert queue_service.QUEUE_SOURCES == {
        "provision",
        "api_mock",
        "bootstrap",
        "skill_analysis",
    }


def test_content_disposition_ascii_filename_keeps_plain_header():
    from app.domains.rag.routers.outbox import _content_disposition

    header = _content_disposition("RAG-228f39dc-001.zip", "rag-queue.zip")
    assert header == 'attachment; filename="RAG-228f39dc-001.zip"'
    # Starlette 会用 latin-1 编码响应头，纯 ASCII 名必须可直接编码
    header.encode("latin-1")


def test_content_disposition_non_ascii_filename_uses_rfc5987_filename_star():
    from urllib.parse import unquote

    from app.domains.rag.routers.outbox import _content_disposition

    filename = "案例一：接口偶发超时.md"
    header = _content_disposition(filename, "case.md")

    # 整体头仍须 latin-1 可编码（修复 500 UnicodeEncodeError 的核心断言）
    header.encode("latin-1")

    assert header.startswith('attachment; filename="case.md"; filename*=UTF-8\'\'')
    encoded = header.split("UTF-8''", 1)[1]
    assert "%" in encoded
    # percent 解码后可还原原始中文文件名
    assert unquote(encoded) == filename