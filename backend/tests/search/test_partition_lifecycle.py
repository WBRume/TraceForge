from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.domains.case_center.models.case import SddCase
from app.domains.search import cli, router, sqlite_index, worker
from app.domains.search.models import (
    SearchBackfillRun,
    SearchEmbeddingJob,
    SearchEmbeddingProfile,
    SearchIndexTarget,
    SearchOutbox,
)

from .test_search_contracts import _seed_task
from .test_search_contracts import db_session as db_session


@pytest.mark.asyncio
async def test_explicit_es_without_a_target_keeps_outbox_pending(db_session, monkeypatch):
    db = db_session
    _seed_task(db)
    monkeypatch.setattr(settings, "SEARCH_BACKEND", "elasticsearch")

    async def transaction(fn):
        result = fn(db)
        db.commit()
        return result

    monkeypatch.setattr(worker, "run_db_txn", transaction)
    job = await transaction(lambda db: worker.claim(db, SearchOutbox))
    await worker.process_body(None, job)
    event = db.get(SearchOutbox, job["id"])
    assert event.status == "pending"
    assert event.last_error_code == "SEARCH_NO_TARGET"
    assert not any(sqlite_index.index_path(corpus).exists() for corpus in ("history", "knowledge"))


@pytest.mark.asyncio
async def test_worker_verification_activation_and_capabilities_share_partition_identity(db_session, monkeypatch):
    db = db_session
    task = _seed_task(db)
    case = SddCase(
        id="case-1", workspace_id=task.workspace_id, creator_id=task.creator_id, title="连接池案例", status="APPROVED"
    )
    profile = SearchEmbeddingProfile(
        id="p", endpoint="https://example.invalid", model_id="test", dimension=3, fingerprint="space", status="tested"
    )
    db.add_all([case, profile])
    db.commit()
    monkeypatch.setattr(settings, "SEARCH_BACKEND", "elasticsearch")
    monkeypatch.setattr(settings, "SEARCH_ENABLED", True)

    async def transaction(fn):
        value = fn(db)
        db.commit()
        return value

    for module in (cli, worker, router):
        monkeypatch.setattr(module, "run_db_txn", transaction)

    indices, documents = set(), {}

    async def exists(*, index):
        return index in indices

    async def create(*, index, body):
        indices.add(index)

    async def bulk(*, operations):
        for action, doc in zip(operations[::2], operations[1::2], strict=True):
            documents[(action["index"]["_index"], doc["entity_key"])] = {
                k: v for k, v in doc.items() if k not in {"title", "content_text", "symbols"}
            }
        return {"items": [{"index": {"status": 201}} for _ in operations[::2]]}

    async def mget(*, docs, **kwargs):
        return {"docs": [{"found": True, "_source": documents[(d["_index"], d["_id"])]} for d in docs]}

    es = SimpleNamespace(
        indices=SimpleNamespace(
            exists=AsyncMock(side_effect=exists),
            create=AsyncMock(side_effect=create),
            get_alias=AsyncMock(return_value={"old-index": {}}),
            update_aliases=AsyncMock(),
        ),
        bulk=AsyncMock(side_effect=bulk),
        mget=AsyncMock(side_effect=mget),
    )
    name = "traceforge-search-lifecycle"
    result = await cli.create_index(es, name, profile.id)
    target = db.get(SearchIndexTarget, result["target_id"])
    assert target.schema_version == 2
    assert indices == {f"{name}-history", f"{name}-knowledge"}
    while job := await transaction(lambda db: worker.claim(db, SearchOutbox)):
        await worker.process_body(es, job)
    assert {j.entity_key for j in db.query(SearchEmbeddingJob)} == {"case:case-1"}
    assert not any(sqlite_index.index_path(corpus).exists() for corpus in ("history", "knowledge"))
    assert (f"{name}-history", f"task:{task.id}") in documents
    assert (f"{name}-knowledge", "case:case-1") in documents

    # Verification waits for asset vectors but does not require vectors for history.
    db.add(SearchBackfillRun(target_id=target.target_id, status="done"))
    db.commit()
    assert not (await cli.verify(es, name))["verified"]
    documents[(f"{name}-knowledge", "case:case-1")].update(semantic_ready=True, embedding_profile_id=profile.id)
    db.query(SearchEmbeddingJob).update({"status": "done"})
    db.commit()
    indices.remove(f"{name}-history")
    assert not (await cli.verify(es, name))["verified"]
    indices.add(f"{name}-history")
    assert (await cli.verify(es, name))["verified"]
    await cli.activate(es, name)
    actions = es.indices.update_aliases.call_args.kwargs["actions"]
    assert {a["add"]["index"] for a in actions if "add" in a} == indices
    assert actions[0]["remove"]["index"] == "old-index"
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(search_es=es)))
    capabilities = await router.capabilities(request, SimpleNamespace(id=task.creator_id))
    assert capabilities["ready"] and capabilities["hybrid_available"]
    assert capabilities["semantic_types"] == ["case", "playbook"]
