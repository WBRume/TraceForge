"""
问题定位任务 + 案例中心 集成测试
覆盖：任务类型创建/过滤、定位结果、一键转案例、案例生命周期状态机、检索与权限。
"""

import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
TEST_ROOT = os.path.abspath(os.path.dirname(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

from app.domains.auth.models.user import (  # noqa: E402
    User,
    WorkspaceMember,
    WorkspaceRole,
)
from app.domains.task.models.task import SddTask, TaskType  # noqa: E402
from app.domains.task.routers import task as task_router  # noqa: E402
from app.domains.case_center.routers import case as case_center_router  # noqa: E402
from test_workspace_asset_boundary import _build_db, _seed_workspace, _session  # noqa: E402


def _build_app(SessionLocal, user):
    def _override_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(task_router.router, prefix="/api")
    app.include_router(case_center_router.router, prefix="/api")
    app.dependency_overrides[task_router.get_db] = _override_db
    app.dependency_overrides[task_router.get_current_user] = lambda: user
    app.dependency_overrides[case_center_router.get_db] = _override_db
    app.dependency_overrides[case_center_router.get_current_user] = lambda: user
    return app


def _seed_diagnosis_task(db, workspace_id="ws-diag", task_id="task-diag"):
    user, workspace, task = _seed_workspace(db, workspace_id=workspace_id, task_id=task_id)
    task.task_type = TaskType.DIAGNOSIS.value
    task.task_meta_json = {"phenomenon": "接口偶发超时", "priority": "P1"}
    db.commit()
    return user, workspace, task


def test_create_diagnosis_task_via_service_and_filter():
    from app.domains.task.services.task_service import create_task_record_for_provision, list_tasks

    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, _ = _seed_workspace(db, workspace_id="ws-filter")
            dev_task = create_task_record_for_provision(
                db,
                user,
                workspace.id,
                name="Dev task",
                task_type="DEVELOPMENT",
            )
            diag_task = create_task_record_for_provision(
                db,
                user,
                workspace.id,
                name="Diag task",
                task_type="DIAGNOSIS",
                phenomenon="页面白屏",
                priority="p0",
            )
            assert diag_task.task_type == "DIAGNOSIS"
            assert diag_task.task_meta_json == {"phenomenon": "页面白屏", "priority": "P0"}
            assert dev_task.task_meta_json is None

            all_items, total = list_tasks(db, workspace.id)
            assert total == 3  # 种子任务 + 研发态 + 问题定位
            diag_items, diag_total = list_tasks(db, workspace.id, task_type="DIAGNOSIS")
            assert diag_total == 1
            assert diag_items[0].id == diag_task.id
    finally:
        engine.dispose()


def test_diagnosis_result_upsert_and_validation():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db)
        client = TestClient(_build_app(SessionLocal, user))
        ws_id, task_id = workspace.id, task.id

        # 未创建时 404
        resp = client.get(f"/api/workspaces/{ws_id}/tasks/{task_id}/diagnosis-result")
        assert resp.status_code == 404, resp.text

        # upsert
        resp = client.put(
            f"/api/workspaces/{ws_id}/tasks/{task_id}/diagnosis-result",
            json={
                "root_cause": "连接池耗尽",
                "evidence_chain": "1. 日志显示获取连接超时\n2. 压测复现",
                "fix_suggestion": "扩容连接池并增加熔断",
                "confidence": 85,
            },
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["root_cause"] == "连接池耗尽"
        assert payload["confidence"] == 85
        assert payload["status"] == "DRAFT"

        # 置信度越界
        resp = client.put(
            f"/api/workspaces/{ws_id}/tasks/{task_id}/diagnosis-result",
            json={"confidence": 150},
        )
        assert resp.status_code == 422

        # 研发态任务不允许
        with _session(SessionLocal) as db:
            dev = SddTask(
                id="task-dev-1",
                workspace_id=ws_id,
                creator_id=user.id,
                task_type="DEVELOPMENT",
                name="Dev",
                project_path="G:/repo",
            )
            db.add(dev)
            db.commit()
        resp = client.put(
            f"/api/workspaces/{ws_id}/tasks/task-dev-1/diagnosis-result",
            json={"root_cause": "x"},
        )
        assert resp.status_code == 403, resp.text
    finally:
        engine.dispose()


def test_case_lifecycle_full_flow():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db)
            # 先保存定位结果
            from app.domains.task.models.diagnosis import SddDiagnosisResult

            db.add(
                SddDiagnosisResult(
                    task_id=task.id,
                    workspace_id=workspace.id,
                    created_by_id=user.id,
                    root_cause="空指针异常",
                    evidence_chain="堆栈证据",
                    fix_suggestion="判空处理",
                    confidence=90,
                )
            )
            db.commit()
            task_id, ws_id = task.id, workspace.id
        client = TestClient(_build_app(SessionLocal, user))

        # 一键转案例（生成草稿）
        resp = client.post(
            f"/api/workspaces/{ws_id}/tasks/{task_id}/case-draft",
            json={"category": "PRODUCT", "priority": "P1", "site_name": "华东局点"},
        )
        assert resp.status_code == 201, resp.text
        case = resp.json()
        case_id = case["id"]
        assert case["status"] == "DRAFT"
        assert case["source_task_id"] == task_id
        assert case["category"] == "PRODUCT"
        assert case["priority"] == "P1"
        assert case["site_name"] == "华东局点"
        assert case["problem_description"] and "接口偶发超时" in case["problem_description"]
        assert case["root_cause"] == "空指针异常"
        assert case["solution"] == "判空处理"
        assert case["review_records"] == []

        # 重复转案例 → 409
        resp = client.post(f"/api/workspaces/{ws_id}/tasks/{task_id}/case-draft", json={})
        assert resp.status_code == 409, resp.text

        # 定位结果被标记为已确认
        resp = client.get(f"/api/workspaces/{ws_id}/tasks/{task_id}/diagnosis-result")
        assert resp.json()["status"] == "CONFIRMED"

        # 草稿 → 待评审
        resp = client.post(f"/api/workspaces/{ws_id}/cases/{case_id}/submit")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "PENDING_REVIEW"

        # 专家接单 → 评审中
        resp = client.post(f"/api/workspaces/{ws_id}/cases/{case_id}/start-review")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "IN_REVIEW"

        # 通过入库（附意见）
        resp = client.post(
            f"/api/workspaces/{ws_id}/cases/{case_id}/review",
            json={"conclusion": "approve", "comment": "根因清晰，同意入库"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "APPROVED"
        records = resp.json()["review_records"]
        assert [r["action"] for r in records] == ["START", "APPROVE"]
        assert records[-1]["comment"] == "根因清晰，同意入库"
        assert records[-1]["reviewer_name"] == user.display_name

        # 已入库案例不可再编辑
        resp = client.put(f"/api/workspaces/{ws_id}/cases/{case_id}", json={"title": "x"})
        assert resp.status_code == 409, resp.text

        # 驳回打回 → 重新提交
        resp = client.post(
            f"/api/workspaces/{ws_id}/cases/{case_id}/review",
            json={"conclusion": "approve", "comment": "x"},
        )
        assert resp.status_code == 409  # 非评审中状态不可裁决
        resp = client.post(f"/api/workspaces/{ws_id}/cases/{case_id}/resubmit")
        assert resp.status_code == 409  # APPROVED 不可重提
    finally:
        engine.dispose()


def test_case_reject_and_resubmit_round():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db)
            ws_id, task_id = workspace.id, task.id
        client = TestClient(_build_app(SessionLocal, user))

        resp = client.post(f"/api/workspaces/{ws_id}/tasks/{task_id}/case-draft", json={})
        case_id = resp.json()["id"]
        client.post(f"/api/workspaces/{ws_id}/cases/{case_id}/submit")
        client.post(f"/api/workspaces/{ws_id}/cases/{case_id}/start-review")

        # 驳回打回
        resp = client.post(
            f"/api/workspaces/{ws_id}/cases/{case_id}/review",
            json={"conclusion": "reject", "comment": "证据链不完整，补充日志"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "REJECTED"
        assert resp.json()["rejected_comment"] == "证据链不完整，补充日志"

        # 驳回后可编辑并重新提交
        resp = client.put(
            f"/api/workspaces/{ws_id}/cases/{case_id}",
            json={"analysis_process": "补充了完整证据链"},
        )
        assert resp.status_code == 200, resp.text

        resp = client.post(f"/api/workspaces/{ws_id}/cases/{case_id}/resubmit")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "PENDING_REVIEW"
        assert resp.json()["review_round"] == 2
    finally:
        engine.dispose()


def test_case_search_and_filters():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db, workspace_id="ws-search", task_id="task-search")
            ws_id = workspace.id
        client = TestClient(_build_app(SessionLocal, user))

        cases = []
        for idx, (title, category, priority, root_cause) in enumerate(
            [
                ("连接池耗尽排查", "PRODUCT", "P0", "连接池配置过小"),
                ("白屏问题定位", "SITE", "P1", "前端资源加载失败"),
                ("临时记录", "TEMPORARY", "P3", "连接池问题记录待整理"),
            ]
        ):
            resp = client.post(
                f"/api/workspaces/{ws_id}/cases",
                json={
                    "title": title,
                    "problem_description": f"问题描述 {idx}",
                    "category": category,
                    "priority": priority,
                    "root_cause": root_cause,
                },
            )
            assert resp.status_code == 201, resp.text
            cases.append(resp.json()["id"])

        # 关键词检索（命中 title / root_cause）
        resp = client.get(f"/api/workspaces/{ws_id}/cases", params={"keyword": "连接池"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

        # 分类过滤
        resp = client.get(f"/api/workspaces/{ws_id}/cases", params={"category": "SITE"})
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["id"] == cases[1]

        # 状态过滤
        client.post(f"/api/workspaces/{ws_id}/cases/{cases[0]}/submit")
        resp = client.get(f"/api/workspaces/{ws_id}/cases", params={"status": "PENDING_REVIEW"})
        assert resp.json()["total"] == 1

        # 组合过滤
        resp = client.get(
            f"/api/workspaces/{ws_id}/cases",
            params={"keyword": "白屏", "priority": "P1", "category": "SITE"},
        )
        assert resp.json()["total"] == 1

        # 删除草稿
        resp = client.delete(f"/api/workspaces/{ws_id}/cases/{cases[2]}")
        assert resp.status_code == 200
        resp = client.get(f"/api/workspaces/{ws_id}/cases", params={"category": "TEMPORARY"})
        assert resp.json()["total"] == 0
    finally:
        engine.dispose()


def test_case_review_requires_expert():
    engine, SessionLocal = _build_db()
    try:
        with _session(SessionLocal) as db:
            user, workspace, task = _seed_diagnosis_task(db, workspace_id="ws-expert", task_id="task-expert")
            ws_id = workspace.id
            # 普通成员（非专家）
            dev_member = WorkspaceMember(
                id="member-dev",
                workspace_id=workspace.id,
                user_id="user-dev",
                role=WorkspaceRole.DEVELOPER,
                permissions_json="[]",
                is_expert=False,
            )
            dev_user = User(id="user-dev", email="dev@example.com", hashed_password="x", display_name="Dev")
            db.add_all([dev_user, dev_member])
            db.commit()
        client = TestClient(_build_app(SessionLocal, user))

        resp = client.post(f"/api/workspaces/{ws_id}/tasks/{task.id}/case-draft", json={})
        case_id = resp.json()["id"]
        client.post(f"/api/workspaces/{ws_id}/cases/{case_id}/submit")

        # 普通成员不能接单评审
        dev_client = TestClient(_build_app(SessionLocal, dev_user))
        resp = dev_client.post(f"/api/workspaces/{ws_id}/cases/{case_id}/start-review")
        assert resp.status_code == 403, resp.text

        # 专家可接单
        resp = client.post(f"/api/workspaces/{ws_id}/cases/{case_id}/start-review")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "IN_REVIEW"
    finally:
        engine.dispose()
