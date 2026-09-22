from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from app.config import settings
from app.domains.diagnosis_playbook import recommendation, analysis_guide
from app.domains.search.worker import current_document
from app.domains.search import budget
from tests.diagnosis_playbook.test_business_flow import seed_case


@pytest.mark.asyncio
@pytest.mark.parametrize('configured', [False, True])
async def test_explicit_es_mode_reports_unavailable_without_sqlite_fallback(monkeypatch, configured):
    monkeypatch.setattr(settings, 'SEARCH_BACKEND', 'elasticsearch')
    target = {'physical_index': 'search', 'verified': False} if configured else None
    monkeypatch.setattr(recommendation, 'run_db_txn', AsyncMock(return_value=(target, None)))
    es = SimpleNamespace(search=AsyncMock(side_effect=ConnectionError('offline')))
    with pytest.raises(HTTPException) as failure:
        await recommendation.recommend(es, None, 'workspace', '支付异常')
    assert failure.value.status_code == 503
    assert failure.value.detail['code'] == 'SEARCH_UNAVAILABLE'


@pytest.mark.asyncio
@pytest.mark.parametrize('semantic', [False, True])
async def test_recommendations_use_es_bm25_and_optional_vector_rrf(db, monkeypatch, semantic):
    _, workspace, _, case = seed_case(db)
    row = analysis_guide.promote_case(db, case)['spec']
    doc = current_document(db, f"playbook:{row['id']}"); db.commit()
    target = dict(physical_index='search', embedding_profile_id='profile', verified=True)
    monkeypatch.setattr(recommendation, 'configuration', lambda db: (target, {'id': 'profile'} if semantic else None))
    monkeypatch.setattr(settings, 'SEARCH_BACKEND', 'auto')
    monkeypatch.setattr(settings, 'SEARCH_ES_URL', 'http://example.invalid:9200')
    async def transaction(fn):
        return fn(db)
    monkeypatch.setattr(recommendation, 'run_db_txn', transaction)
    monkeypatch.setattr(budget, 'reserve', AsyncMock())
    embedding = AsyncMock(return_value=[[0.1, 0.2]])
    monkeypatch.setattr(recommendation, 'embed', embedding)
    es = SimpleNamespace(search=AsyncMock(return_value={'hits': {'hits': [{'_id': doc['entity_key'], '_source': doc, '_score': 2.0}]}}),
        open_point_in_time=AsyncMock(return_value={'id': 'pit'}), close_point_in_time=AsyncMock())
    items, mode = await recommendation.recommend(es, None, workspace.id, '支付空指针')
    assert items[0]['id'] == row['id']
    assert mode == ('hybrid' if semantic else 'bm25')
    assert es.search.await_count == (2 if semantic else 1)
    bodies = [call.kwargs['body'] for call in es.search.await_args_list]
    assert any('query' in body for body in bodies)
    assert any('knn' in body for body in bodies) == semantic
    if semantic:
        es.close_point_in_time.assert_awaited_once_with(id='pit')
