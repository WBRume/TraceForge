from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from .test_search_contracts import db_session, _seed_task
from app.config import settings
from app.domains.auth.models.user import WorkspaceMember
from app.domains.search import service, sqlite_index, sessions
from app.domains.search.worker import current_document


@pytest.mark.asyncio
@pytest.mark.parametrize('has_target', [False, True])
async def test_no_es_and_es_outage_use_bm25_with_source_acl(db_session, monkeypatch, has_target):
    db = db_session
    task = _seed_task(db)
    task.name = '连接池耗尽'
    db.add(WorkspaceMember(workspace_id=task.workspace_id, user_id=task.creator_id, role='OWNER'))
    db.commit()
    document = current_document(db, f'task:{task.id}'); db.commit()
    sqlite_index.write([document])
    async def transaction(fn):
        return fn(db)
    monkeypatch.setattr(service, 'run_db_txn', transaction)
    monkeypatch.setattr(settings, 'SEARCH_BACKEND', 'auto')
    monkeypatch.setattr(settings, 'SEARCH_ENABLED', True)
    target = dict(target_id='es', physical_index='search', embedding_profile_id=None, verified=True, semantic_indexing_state='ready')
    monkeypatch.setattr(service, 'configuration', lambda db: (target if has_target else None, None))
    async def save(user, binding, candidates, metadata):
        assert all('content_text' not in item for item in candidates)
        return 'sid', dict(candidates=candidates, metadata=metadata)
    monkeypatch.setattr(sessions, 'create', save)
    monkeypatch.setattr(sessions, 'cursor', lambda *args: 'cursor')
    es = SimpleNamespace(search=AsyncMock(side_effect=OSError('unreachable')))
    response = await service.SearchService(es, None).search(task.creator_id, dict(q='连接池', retrieval='hybrid', type='all', limit=20))
    assert response['executed_retrieval'] == 'lexical'
    assert 'sqlite_bm25' in response['degraded_reason']
    assert response['items'][0]['task_name'] == '连接池耗尽'
    assert response['semantic_indexing_state'] == 'unavailable'
    assert es.search.await_count == int(has_target)


@pytest.mark.asyncio
async def test_embedding_worker_does_not_call_model_when_es_is_absent(monkeypatch):
    from app.domains.search import worker
    monkeypatch.setattr(settings, 'SEARCH_BACKEND', 'auto')
    monkeypatch.setattr(settings, 'SEARCH_ES_URL', 'http://example.invalid:9200')
    monkeypatch.setattr(worker, 'run_db_txn', AsyncMock(return_value=({}, {'physical_index': 'missing'}, {})))
    embedding = AsyncMock()
    monkeypatch.setattr(worker, 'embed', embedding)
    es = SimpleNamespace(indices=SimpleNamespace(exists=AsyncMock(return_value=False)))
    with pytest.raises(RuntimeError, match='SEARCH_TRANSPORT_FAILED'):
        await worker.process_embedding(es, None, {})
    embedding.assert_not_awaited()
