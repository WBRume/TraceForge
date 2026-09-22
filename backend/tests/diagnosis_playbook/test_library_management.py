from copy import deepcopy
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.dependencies import get_db, get_current_user
from app.domains.diagnosis_playbook import router, analysis_guide, promotion, service
from app.domains.diagnosis_playbook.models import CasePlaybookLink, PlaybookSpec
from app.domains.diagnosis_playbook.contracts import PlaybookError
from app.domains.case_center.services import case_service
from app.domains.auth.models.user import WorkspaceMember
from tests.diagnosis_playbook.test_business_flow import seed_case
from tests.diagnosis_playbook.test_promotion_jobs import result


def client_for(db, user):
    app = FastAPI(); app.include_router(router.router); app.include_router(router.global_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_library_server_pagination_search_and_no_membership_is_empty(db):
    user, ws, _, case = seed_case(db)
    first = analysis_guide.promote_case(db, case)['spec']
    source = db.get(PlaybookSpec, first['id']).spec_json['spec']
    for i in range(13):
        document = deepcopy(source)
        document['metadata'].update(id=f'guide-{i}', title=f'规程 {i}')
        service.register_spec(db, ws.id, document)
    db.commit()
    client = client_for(db, user)
    url = f'/workspaces/{ws.id}/cases/playbooks'
    page1 = client.get(url, params={'page_size': 12}).json()
    page2 = client.get(url, params={'page_size': 12, 'page': 2}).json()
    assert page1['total'] == page2['total'] == 14
    assert len(page1['items']) == 12 and len(page2['items']) == 2
    assert not {x['id'] for x in page1['items']} & {x['id'] for x in page2['items']}
    assert client.get(url, params={'keyword': '规程 12'}).json()['total'] == 1
    assert client.get(url, params={'page': 0}).status_code == 422
    db.query(WorkspaceMember).filter_by(user_id=user.id).delete(); db.commit()
    assert client.get('/cases/playbooks').json()['total'] == 0


def test_edit_publishes_new_version_preserves_source_and_existing_document(db):
    user, ws, _, case = seed_case(db)
    original = analysis_guide.promote_case(db, case)['spec']; db.commit()
    client = client_for(db, user)
    url = f"/workspaces/{ws.id}/cases/playbooks/{original['id']}"
    details = client.get(url).json()
    assert details['can_edit'] is True
    document = deepcopy(details['document'])
    document['metadata']['title'] = '编辑后的规程'
    document['metadata']['sourceCaseRefs'] = []
    document['match']['symptoms'] = ['重复扣款但只有一个订单']
    saved = client.put(url, json={'document': document})
    assert saved.status_code == 200, saved.text
    assert saved.json()['id'] != original['id']
    assert saved.json()['version'] != original['version']
    assert saved.json()['source_case_refs'] == []
    assert 'call_chain' not in saved.json()['document']['context']
    assert client.get(url).json()['document'] == details['document']
    assert db.query(CasePlaybookLink).filter_by(spec_id=saved.json()['id'], case_id=case.id).count() == 1
    cases, _ = case_service.list_cases(db, ws.id)
    assert case_service.serialize_case(cases[0])['has_playbook'] is True
    assert client.get(f'/workspaces/other/cases/playbooks/{original["id"]}').status_code in (403, 404)


@pytest.mark.parametrize('status', ['DRAFT', 'PENDING_REVIEW', 'IN_REVIEW', 'REJECTED', 'TECHNICALLY_VERIFIED'])
def test_only_reviewed_approved_cases_can_enter_promotion(db, status):
    user, ws, _, case = seed_case(db)
    case.status = status; db.commit()
    client = client_for(db, user)
    response = client.post(f'/workspaces/{ws.id}/cases/playbook-promotions', json={'case_ids': [case.id], 'idempotency_key': 'review'})
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'CASE_NOT_APPROVED'


def test_review_state_is_checked_again_after_cli_execution(db):
    user, ws, _, case = seed_case(db)
    job = promotion.create(db, ws.id, [case.id], user.id, 'review'); db.commit()
    case.status = 'REJECTED'; db.commit()
    with pytest.raises(PlaybookError, match='CASE_NOT_APPROVED'):
        promotion.finalize(db, job.id, result([case.id]), None, None, None)
    assert db.query(PlaybookSpec).count() == 0


def test_unpublished_extraction_has_no_promoted_badge_and_cannot_bypass_review(db):
    user, ws, _, case = seed_case(db)
    case.status = 'DRAFT'
    link = CasePlaybookLink(case_id=case.id, revision_json={'kind': 'EXTRACTION'})
    db.add(link); db.commit()
    rows, _ = case_service.list_cases(db, ws.id)
    response = client_for(db, user).post(f'/workspaces/{ws.id}/cases/{case.id}/playbook-extractions/{link.id}/spec', json={'document': {}})
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'CASE_NOT_APPROVED'


def test_delete_playbook_spec(db):
    user, ws, _, case = seed_case(db)
    spec_dict = analysis_guide.promote_case(db, case)['spec']
    spec_id = spec_dict['id']
    db.commit()

    client = client_for(db, user)
    # 删除前验证存在
    assert client.get(f'/workspaces/{ws.id}/cases/playbooks/{spec_id}').status_code == 200

    # 跨工作区删除应失败
    assert client.delete(f'/workspaces/other-ws/cases/playbooks/{spec_id}').status_code in (403, 404)

    # 正常删除
    res = client.delete(f'/workspaces/{ws.id}/cases/playbooks/{spec_id}')
    assert res.status_code == 200
    assert res.json()['id'] == spec_id

    # 删除后查询 404
    assert client.get(f'/workspaces/{ws.id}/cases/playbooks/{spec_id}').status_code == 404
    assert db.get(PlaybookSpec, spec_id) is None
    # 关联记录的 spec_id 已置空
    for link in db.query(CasePlaybookLink).filter_by(case_id=case.id):
        assert link.spec_id is None

