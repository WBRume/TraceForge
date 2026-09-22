from copy import deepcopy
import pytest
from app.domains.diagnosis_playbook import promotion, analysis_guide, guide_session
from app.domains.diagnosis_playbook.models import PlaybookSpec, CasePlaybookLink
from app.domains.diagnosis_playbook.contracts import PlaybookError
from app.domains.case_center.models.case import SddCase
from app.domains.workspace_asset.services.requirements.preview import runner
from tests.diagnosis_playbook.test_business_flow import seed_case
from tests.diagnosis_playbook.test_library_management import client_for
from tests.diagnosis_playbook.test_promotion_jobs import result


def generated(db, monkeypatch):
    user, ws, task, first = seed_case(db)
    rest = [SddCase(workspace_id=ws.id, creator_id=user.id, title=f'案例{i}', status='APPROVED') for i in range(2)]
    db.add_all(rest); db.commit()
    ids = [first.id, *[c.id for c in rest]]
    job = promotion.create(db, ws.id, ids, user.id, 'initial'); db.commit()
    def update(db, current, **values):
        current.status = values.get('status', current.status)
        current.progress = values.get('progress', current.progress)
        current.result_json = values.get('result', current.result_json)
    monkeypatch.setattr(runner, 'update_preview_job_state', update)
    draft = promotion.PromotionResult(playbooks=[result(ids[:2]).playbooks[0], result(ids[2:]).playbooks[0]], grouping_reason='两组适用条件不同')
    promotion.finalize(db, job.id, draft, None, None, None); db.commit()
    return user, ws, task, job, draft


def test_two_plus_one_is_only_a_draft_until_explicit_confirmation(db, monkeypatch):
    user, ws, _, job, draft = generated(db, monkeypatch)
    client = client_for(db, user)
    assert db.query(PlaybookSpec).count() == db.query(CasePlaybookLink).count() == 0
    assert client.get('/cases/playbook-promotions/active').json()['items'][0]['result']['review_state'] == 'PENDING'
    assert client.get(f'/workspaces/{ws.id}/cases/playbooks').json()['total'] == 0
    url = f'/workspaces/{ws.id}/cases/playbook-promotions/{job.id}/confirm'
    body = {'draft_revision': job.result_json['draft_revision'], 'draft': draft.model_dump()}
    body['draft']['playbooks'][0]['summary'] = '人工确认的共同定位方法'
    first = client.post(url, json=body)
    assert first.status_code == 200, first.text
    assert first.json()['result']['review_state'] == 'CONFIRMED'
    assert db.query(PlaybookSpec).count() == 2 and db.query(CasePlaybookLink).count() == 3
    assert client.post(url, json=body).json()['result']['spec_ids'] == first.json()['result']['spec_ids']
    body['draft']['playbooks'][0]['title'] = '并发修改'
    assert client.post(url, json=body).status_code == 409
    for spec in db.query(PlaybookSpec):
        assert set(spec.spec_json['spec']['context']) == {'summary'}
        assert 'sourceCaseRefs' not in spec.spec_json['spec']['metadata']


def test_regenerate_forces_one_abstract_method_and_still_requires_review(db, monkeypatch, tmp_path):
    user, ws, _, job, draft = generated(db, monkeypatch)
    revision = job.result_json['draft_revision']
    replacement = promotion.regenerate(db, job, revision, 'merge', user.id); db.commit()
    assert replacement.id != job.id and replacement.context_json['merge_all'] is True
    assert promotion.regenerate(db, job, revision, 'merge', user.id).id == replacement.id
    from app.config import settings
    from app.agents import selection
    monkeypatch.setattr(settings, 'SEARCH_SQLITE_PATH', str(tmp_path / 'index.sqlite3'))
    monkeypatch.setattr(selection, 'resolve_workspace_backend', lambda *args: 'test')
    assert '必须只输出一个规程' in promotion.prepare(db, replacement.id, None, None)['prompt']
    with pytest.raises(PlaybookError, match='PROMOTION_MERGE_REQUIRED'):
        promotion.finalize(db, replacement.id, draft, None, None, None)
    merged = result(job.context_json['case_ids'])
    promotion.finalize(db, replacement.id, merged, None, None, None); db.commit()
    assert db.query(PlaybookSpec).count() == 0
    with pytest.raises(PlaybookError, match='PROMOTION_DRAFT_CHANGED'):
        promotion.confirm_draft(db, job, revision, draft, user.id)
    promotion.confirm_draft(db, replacement, replacement.result_json['draft_revision'], merged, user.id); db.commit()
    assert db.query(PlaybookSpec).count() == 1


def test_discard_and_review_state_change_cannot_publish(db, monkeypatch):
    user, ws, _, job, draft = generated(db, monkeypatch)
    revision = job.result_json['draft_revision']
    case = db.get(SddCase, job.context_json['case_ids'][0]); case.status = 'REJECTED'; db.commit()
    with pytest.raises(PlaybookError, match='CASE_NOT_APPROVED'):
        promotion.confirm_draft(db, job, revision, draft, user.id)
    promotion.discard_draft(job, revision); db.commit()
    assert client_for(db, user).get('/cases/playbook-promotions/active').json()['items'] == []
    assert db.query(PlaybookSpec).count() == 0


def test_legacy_provenance_is_not_injected_into_diagnosis_prompt(db):
    _, _, task, _ = seed_case(db)
    task.task_meta_json = {'diagnosis_playbook_guide': {'title': '方法', 'steps': [],
        'source_case_refs': ['private-case'], 'context': {'summary': '对比持久化边界',
        'call_chain': ['private-call-chain'], 'source_cases': ['private-case-snapshot']}}}
    suffix = analysis_guide.prompt_suffix(task)
    snapshot = guide_session.snapshot(task)['guide']
    assert 'private-' not in suffix
    assert snapshot['context'] == {'summary': '对比持久化边界'}
    assert 'source_case_refs' not in snapshot
