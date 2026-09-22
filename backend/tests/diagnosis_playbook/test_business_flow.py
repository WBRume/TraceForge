from copy import deepcopy
from contextlib import contextmanager
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.dependencies import get_current_user, get_db
from app.domains.case_center.models.case import SddCase
from app.domains.diagnosis_playbook import router, analysis_guide, service
from app.domains.diagnosis_playbook.models import CasePlaybookLink, PlaybookSpec, PlaybookRun
from app.domains.diagnosis_playbook.contracts import PlaybookError
from app.domains.task.models.task import SddTask
from app.domains.task.routers.task import crud
from app.engine.session import turn_setup
from tests.workspace_asset.test_workspace_asset_boundary import _seed_workspace


def seed_case(db):
    user, workspace, task = _seed_workspace(db)
    case = SddCase(workspace_id=workspace.id, creator_id=user.id, title="支付回调 NullPointerException",
        status="APPROVED", problem_description="checkout 调用支付接口报错",
        root_cause="payment 返回空对象", analysis_process="沿请求链排查空返回",
        solution="对支付结果增加空值处理",
        diagnosis_detail_json={"call_chain": [
            {"file": "checkout.py", "function": "checkout", "line": 12, "description": "调用 payment"},
            {"file": "payment.py", "function": "pay", "line": 34, "description": "返回空对象"}],
            "evidence_chain": "日志 request-id 关联到空返回"})
    db.add(case)
    db.commit()
    return user, workspace, task, case


def test_promoted_spec_task_creation_and_agent_context(db, monkeypatch):
    user, workspace, _, case = seed_case(db)
    app = FastAPI()
    app.include_router(router.router)
    app.include_router(crud.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(crud.provision_job_service, "run_create_task_job", AsyncMock())
    client = TestClient(app)
    promoted = analysis_guide.promote_case(db, case)
    db.commit()
    spec_id = promoted['spec']['id']
    assert db.query(CasePlaybookLink).count() == 1
    assert case.status == 'APPROVED'
    # 诊断规程仅问题定位任务可选，研发态任务不允许绑定
    rejected = client.post(f"/workspaces/{workspace.id}/tasks", json={
        "name": "修复支付回调", "task_type": "DEVELOPMENT", "diagnosis_playbook_spec_id": spec_id})
    assert rejected.status_code == 400, rejected.text
    created = client.post(f"/workspaces/{workspace.id}/tasks", json={
        "name": "定位支付回调", "task_type": "DIAGNOSIS", "phenomenon": "checkout 支付异常",
        "diagnosis_playbook_spec_id": spec_id})
    assert created.status_code == 202, created.text
    task = db.get(SddTask, created.json()["task_id"])
    bound = task.task_meta_json["diagnosis_playbook_guide"]
    assert task.task_type == "DIAGNOSIS"
    assert "call_chain" not in bound["context"]
    assert "source_cases" not in bound["context"]
    assert any(step["id"] == "chain_1" and "checkout" in step["objective"] for step in bound["steps"])
    assert not db.query(PlaybookRun).count()  # no physical worker/environment required
    @contextmanager
    def session():
        yield db
    monkeypatch.setattr(turn_setup, "SessionLocal", session)
    prompt = turn_setup.playbook_context_sync(task.id)
    assert "checkout.py" in prompt and "payment.py" in prompt and "多个角度" in prompt
    frozen = deepcopy(bound)
    case.root_cause = "后续修订：连接池耗尽"
    db.commit()
    new_version = analysis_guide.promote_case(db, case)["spec"]["id"]
    assert new_version != spec_id
    db.refresh(task)
    assert task.task_meta_json["diagnosis_playbook_guide"] == frozen
    assert db.query(PlaybookSpec).count() == 2


def test_missing_or_cross_workspace_selection_cannot_create_task(db):
    user, workspace, _, case = seed_case(db)
    promoted = analysis_guide.promote_case(db, case)
    with pytest.raises(PlaybookError, match="PLAYBOOK_NOT_FOUND"):
        analysis_guide.task_binding(db, "another-workspace", promoted["spec"]["id"])
    before = db.query(SddTask).count()
    from app.domains.task.services.task_service import create_task_record_for_provision
    with pytest.raises(ValueError, match="requires a DIAGNOSIS task"):
        create_task_record_for_provision(db, user, workspace.id, "dev selection", diagnosis_playbook_spec_id=promoted["spec"]["id"])
    with pytest.raises(PlaybookError):
        create_task_record_for_provision(db, user, workspace.id, "invalid selection", task_type="DIAGNOSIS",
            phenomenon="checkout 支付异常", diagnosis_playbook_spec_id="missing")
    assert db.query(SddTask).count() == before


def test_analysis_guide_never_enters_physical_runner(db):
    user, _, task, case = seed_case(db)
    task.task_type = "DIAGNOSIS"
    promoted = analysis_guide.promote_case(db, case)
    with pytest.raises(PlaybookError, match="ANALYSIS_GUIDE_USE_TASK_CREATION"):
        service.attach(db, task, promoted["spec"]["id"], {}, "key", user.id, "no-fixture")


def test_recommendations_rank_matches_and_only_include_current_workspace(db):
    _, workspace, _, case = seed_case(db)
    result = analysis_guide.promote_case(db, case)
    case.title = "布局溢出"
    case.problem_description = "CSS overflow"
    case.root_cause = "宽度错误"
    case.diagnosis_detail_json = {}
    case.analysis_process = "检查布局"
    # A separate case, not a new version of the first.
    other = SddCase(workspace_id=workspace.id, creator_id=case.creator_id, title="布局溢出", problem_description="CSS overflow")
    db.add(other)
    db.flush()
    analysis_guide.promote_case(db, other)
    rows = analysis_guide.recommend(db, workspace.id, "NullPointerException")
    assert rows[0]["id"] == result["spec"]["id"] and rows[0]["score"] > rows[1]["score"]
    assert analysis_guide.recommend(db, "other-workspace", "NullPointerException") == []


@pytest.mark.asyncio
async def test_draft_recommendations_search_and_paginate_on_server(db, monkeypatch, tmp_path):
    from types import SimpleNamespace
    from app.config import settings
    from app.core import offload
    from app.domains.search import sqlite_index
    from app.domains.search.worker import current_document
    from app.domains.diagnosis_playbook import recommendation
    monkeypatch.setattr(settings, 'SEARCH_SQLITE_PATH', str(tmp_path / 'search.sqlite3'))
    monkeypatch.setattr(settings, 'SEARCH_BACKEND', 'sqlite')
    user, workspace, _, case = seed_case(db)
    promoted = analysis_guide.promote_case(db, case)
    for index in range(10):
        other = SddCase(workspace_id=workspace.id, creator_id=user.id, title=f"布局溢出 {index}", problem_description="CSS overflow")
        db.add(other); db.flush()
        analysis_guide.promote_case(db, other)
    docs = [current_document(db, f'playbook:{row.id}') for row in db.query(PlaybookSpec)]
    db.commit()
    sqlite_index.write(docs)
    async def transaction(fn):
        return fn(db)
    monkeypatch.setattr(offload, 'run_db_txn', transaction)
    monkeypatch.setattr(recommendation, 'run_db_txn', transaction)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(search_es=None, search_http=None)))
    first = await router.recommend_draft(workspace.id, router.RecommendationRequest(), request, user)
    second = await router.recommend_draft(workspace.id, router.RecommendationRequest(page=2), request, user)
    assert first['total'] == 11 and len(first['items']) == 8 and len(second['items']) == 3
    assert not {item['id'] for item in first['items']} & {item['id'] for item in second['items']}
    searched = await router.recommend_draft(workspace.id, router.RecommendationRequest(keyword='checkout'), request, user)
    assert searched['total'] == 1 and searched['items'][0]['id'] == promoted['spec']['id']
    assert searched['retrieval'] == 'sqlite_bm25'
    empty = await router.recommend_draft(workspace.id, router.RecommendationRequest(keyword='absentword'), request, user)
    assert empty['total'] == 0
