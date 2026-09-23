import asyncio
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.dependencies import get_db, get_current_user
from app.domains.diagnosis_playbook import promotion, router
from app.domains.diagnosis_playbook.models import PlaybookSpec, CasePlaybookLink
from app.domains.diagnosis_playbook.contracts import PlaybookError
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.case_center.models.case import SddCase
from tests.diagnosis_playbook.test_business_flow import seed_case


def result(ids):
    return promotion.PromotionResult(playbooks=[dict(title='支付空指针排查', source_case_ids=ids,
        symptoms=['支付回调返回空对象导致空指针异常', '支付链路间歇性失败'], summary='检查调用链空返回传播',
        steps=['核对回调请求与调用链', '比较多个可证伪假说', '复现与回归'])])


def test_list_batch_endpoint_is_durable_idempotent_and_enqueues_cli(db, monkeypatch):
    user, workspace, _, first = seed_case(db)
    second = SddCase(workspace_id=workspace.id, creator_id=user.id, title='第二案例', status='APPROVED')
    db.add(second); db.commit()
    from app.domains.ai.services.jobs import publishing
    enqueue = AsyncMock()
    monkeypatch.setattr(publishing, 'enqueue_asset_thread_job', enqueue)
    app = FastAPI(); app.include_router(router.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    url = f'/workspaces/{workspace.id}/cases/playbook-promotions'
    body = {'case_ids': [first.id, second.id], 'idempotency_key': 'one'}
    response = client.post(url, json=body)
    assert response.status_code == 202, response.text
    identity = response.json()['job_id']
    enqueue.assert_awaited_once_with(identity)
    assert client.post(url, json=body).json()['job_id'] == identity
    assert client.get(url).json()['items'][0]['case_ids'] == sorted(body['case_ids'])
    assert not db.query(PlaybookSpec).count()
    assert client.post(url, json={**body, 'case_ids': ['other-workspace-case']}).status_code == 404
    from app.domains.ai.services.jobs import store
    from types import SimpleNamespace
    monkeypatch.setattr(store, 'SessionLocal', lambda: SimpleNamespace(query=db.query, close=lambda: None))
    assert f'PLAYBOOK_PROMOTION:{workspace.id}' in store.list_pending_queue_keys_sync()


def test_ai_output_waits_for_confirmation_and_publishes_only_abstract_methodology(db, monkeypatch):
    user, workspace, _, case = seed_case(db)
    job = promotion.create(db, workspace.id, [case.id], user.id, 'one'); db.commit()
    from app.domains.workspace_asset.services.requirements.preview import runner
    def finalize_state(db, job, **kw):
        job.status = kw['status']; job.result_json = kw['result']
    monkeypatch.setattr(runner, 'update_preview_job_state', finalize_state)
    promotion.finalize(db, job.id, result([case.id]), None, None, None)
    db.commit()
    assert db.query(PlaybookSpec).count() == 0
    assert db.query(CasePlaybookLink).count() == 0
    assert job.result_json['review_state'] == 'PENDING'
    promotion.confirm_draft(db, job, job.result_json['draft_revision'], result([case.id]), user.id)
    db.commit()
    spec = db.query(PlaybookSpec).one().spec_json['spec']
    assert spec['match']['symptoms'] == result([case.id]).playbooks[0].symptoms
    assert spec['context'] == {'summary': result([case.id]).playbooks[0].summary}
    assert 'sourceCaseRefs' not in spec['metadata']
    assert db.query(CasePlaybookLink).one().revision_json['ai_job_id'] == job.id
    assert job.status == AiJobStatus.SUCCESS


def test_missing_sources_and_stale_attempt_cannot_publish(db):
    user, workspace, _, case = seed_case(db)
    job = promotion.create(db, workspace.id, [case.id], user.id, 'one'); db.commit()
    with pytest.raises(PlaybookError, match='PROMOTION_INVALID_SOURCES'):
        promotion.finalize(db, job.id, result(['not-selected']), None, None, None)
    db.rollback()
    from app.domains.ai.services.ai_job_convergence_service import AttemptFencedError
    with pytest.raises(AttemptFencedError):
        promotion.finalize(db, job.id, result([case.id]), 'old-token', 'old-worker', None)
    assert not db.query(PlaybookSpec).count()


def test_runner_calls_workspace_cli_with_snapshot_and_records_model_output(db, monkeypatch, tmp_path):
    import json
    from app.config import settings
    from app.core import offload
    from app.agents import selection
    from app.domains.ai.services.jobs import provider_turn, publishing
    from app.domains.workspace_asset.services.requirements.preview import runner
    user, workspace, _, case = seed_case(db)
    job = promotion.create(db, workspace.id, [case.id], user.id, 'runner'); db.commit()
    case.title = '晋升后的修改不应进入已提交快照'; db.commit()
    monkeypatch.setattr(settings, 'SEARCH_SQLITE_PATH', str(tmp_path / 'search.sqlite3'))
    monkeypatch.setattr(selection, 'resolve_workspace_backend', lambda *args: 'test-backend')
    async def transaction(fn):
        try:
            value = fn(db); db.commit(); return value
        except Exception:
            db.rollback(); raise
    monkeypatch.setattr(offload, 'run_db_txn', transaction)
    def update(db, job, **values):
        job.progress = values['progress']
        if 'status' in values:
            job.status = values['status']; job.result_json = values['result']
    monkeypatch.setattr(runner, 'update_preview_job_state', update)
    cli = AsyncMock(return_value={'text': json.dumps(result([case.id]).model_dump(), ensure_ascii=False)})
    monkeypatch.setattr(provider_turn, 'run_cli_single_turn', cli)
    published = []
    async def publish(identity):
        db.expire_all()
        current = db.query(SddAiJob).filter_by(id=identity).one()
        published.append((current.status, current.progress, db.query(PlaybookSpec).count()))
    monkeypatch.setattr(publishing, 'publish_job_state', publish)
    assert asyncio.run(promotion.run(job.id)) is True
    assert cli.call_args.kwargs['backend_name'] == 'test-backend'
    assert cli.call_args.kwargs['permission_mode'] == 'read-only'
    assert '晋升后的修改' not in cli.call_args.kwargs['prompt']
    assert 'checkout' in cli.call_args.kwargs['prompt']
    assert db.query(PlaybookSpec).count() == 0
    assert job.result_json['review_state'] == 'PENDING'
    assert len(published) == 2
    assert published[0][1:] == (15, 0)
    assert published[-1] == (AiJobStatus.SUCCESS, 100, 0)
