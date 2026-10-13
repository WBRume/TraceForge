from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.config import settings
from app.domains.auth.models.user import Workspace, WorkspaceMember
from app.domains.search import service, sessions, sqlite_index
from app.domains.search.worker import current_document
from app.domains.task.models.task import SddTask

from .test_search_contracts import _seed_task
from .test_search_contracts import db_session as db_session


@pytest.mark.asyncio
async def test_workspace_filter_limits_candidates_and_rejects_unauthorized_scope(db_session, monkeypatch):
    db = db_session
    first = _seed_task(db)
    first.name = "连接池工作区一"
    second_ws = Workspace(id="ws-2", name="Second", owner_id=first.creator_id)
    second = SddTask(
        id="task-2", workspace_id=second_ws.id, creator_id=first.creator_id, name="连接池工作区二", status="CODING"
    )
    db.add_all(
        [
            second_ws,
            second,
            *[
                WorkspaceMember(workspace_id=ws, user_id=first.creator_id, role="OWNER")
                for ws in (first.workspace_id, second_ws.id)
            ],
        ]
    )
    db.commit()
    sqlite_index.write([current_document(db, f"task:{t.id}") for t in (first, second)])
    db.commit()

    async def transaction(fn):
        return fn(db)

    async def save(user, binding, candidates, metadata):
        return "sid", {"candidates": candidates, "metadata": metadata}

    monkeypatch.setattr(service, "run_db_txn", transaction)
    monkeypatch.setattr(settings, "SEARCH_BACKEND", "sqlite")
    monkeypatch.setattr(settings, "SEARCH_ENABLED", True)
    monkeypatch.setattr(sessions, "create", save)
    monkeypatch.setattr(sessions, "cursor", lambda *args: "cursor")
    search = service.SearchService(None, None)
    params = {"q": "连接池", "retrieval": "lexical", "type": "all", "limit": 20}
    all_results = await search.search(first.creator_id, params)
    assert {r["entity_key"] for r in all_results["items"]} == {"task:task-1", "task:task-2"}
    scoped = await search.search(first.creator_id, params | {"workspace_id": "ws-2"})
    assert [r["entity_key"] for r in scoped["items"]] == ["task:task-2"]
    with pytest.raises(HTTPException) as error:
        await search.search(first.creator_id, params | {"workspace_id": "forbidden"})
    assert error.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("has_target", [False, True])
async def test_no_es_and_es_outage_use_bm25_with_source_acl(db_session, monkeypatch, has_target):
    db = db_session
    task = _seed_task(db)
    task.name = "连接池耗尽"
    db.add(WorkspaceMember(workspace_id=task.workspace_id, user_id=task.creator_id, role="OWNER"))
    db.commit()
    document = current_document(db, f"task:{task.id}")
    db.commit()
    sqlite_index.write([document])

    async def transaction(fn):
        return fn(db)

    monkeypatch.setattr(service, "run_db_txn", transaction)
    monkeypatch.setattr(settings, "SEARCH_BACKEND", "auto")
    monkeypatch.setattr(settings, "SEARCH_ENABLED", True)
    target = {
        "target_id": "es",
        "physical_index": "search",
        "embedding_profile_id": None,
        "verified": True,
        "semantic_indexing_state": "ready",
    }
    monkeypatch.setattr(service, "configuration", lambda db: (target if has_target else None, None))

    async def save(user, binding, candidates, metadata):
        assert all("content_text" not in item for item in candidates)
        return "sid", {"candidates": candidates, "metadata": metadata}

    monkeypatch.setattr(sessions, "create", save)
    monkeypatch.setattr(sessions, "cursor", lambda *args: "cursor")
    es = SimpleNamespace(search=AsyncMock(side_effect=OSError("unreachable")))
    response = await service.SearchService(es, None).search(
        task.creator_id, {"q": "连接池", "retrieval": "hybrid", "type": "all", "limit": 20}
    )
    assert response["executed_retrieval"] == "lexical"
    assert "sqlite_bm25" in response["degraded_reason"]
    assert response["items"][0]["task_name"] == "连接池耗尽"
    assert response["semantic_indexing_state"] == "unavailable"
    assert es.search.await_count == int(has_target)


@pytest.mark.asyncio
async def test_embedding_worker_does_not_call_model_when_es_is_absent(monkeypatch):
    from app.domains.search import worker

    monkeypatch.setattr(settings, "SEARCH_BACKEND", "auto")
    monkeypatch.setattr(settings, "SEARCH_ES_URL", "http://example.invalid:9200")
    monkeypatch.setattr(
        worker, "run_db_txn", AsyncMock(return_value=({"kind": "case"}, {"physical_index": "missing"}, {}))
    )
    embedding = AsyncMock()
    monkeypatch.setattr(worker, "embed", embedding)
    es = SimpleNamespace(indices=SimpleNamespace(exists=AsyncMock(return_value=False)))
    with pytest.raises(RuntimeError, match="SEARCH_TRANSPORT_FAILED"):
        await worker.process_embedding(es, None, {})
    embedding.assert_not_awaited()
