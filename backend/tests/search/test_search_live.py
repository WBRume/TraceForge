"""Opt-in synthetic integration checks against configured infrastructure.

SEARCH_LIVE_TESTS=1 creates and removes only a UUID-named test database/index.
The application database, indexes and aliases are never modified.
"""
import asyncio
import importlib.util
import os
from pathlib import Path
import time
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from tests.task.test_task_chat_history_ordering import _seed_task
from app.config import settings
from app.database import Base
from app.domains.search.es import create_client, index_mapping, bulk_write, search_body, scope_filters
from app.domains.search.embedding import encrypt_key, embed
from app.domains.search.models import SearchDocumentState, SearchOutbox, SearchIndexTarget, SearchEmbeddingProfile, SearchEmbeddingJob
from app.domains.search.worker import claim, process_body, process_embedding, current_document
from app.domains.search.projection import digest
from app.domains.search import sessions
from app.domains.search.rrf import hybrid_search
from app.domains.task.services import task_service
from app.core.redis_client import close_redis_client

pytestmark = pytest.mark.skipif(os.getenv("SEARCH_LIVE_TESTS") != "1", reason="opt-in real infrastructure")


@pytest.fixture()
def mysql_db(monkeypatch):
    import app.database as database
    name = "traceforge_search_test_" + uuid4().hex[:12]
    original = create_engine(settings.DATABASE_URL)
    assert name.startswith("traceforge_search_test_")
    with original.begin() as conn:
        conn.execute(text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
    engine = create_engine(original.url.set(database=name), pool_size=4, max_overflow=0)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(database, "SessionLocal", factory)
    try:
        Base.metadata.create_all(engine)
        yield engine, factory
    finally:
        engine.dispose()
        with original.begin() as conn:
            conn.execute(text(f"DROP DATABASE `{name}`"))
        original.dispose()


def test_mysql_incremental_migration_roundtrip(mysql_db):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    engine, factory = mysql_db
    path = Path(__file__).parents[2] / "alembic/versions/d5f60718293a_global_search.py"
    spec = importlib.util.spec_from_file_location("search_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.downgrade()
            migration.upgrade()
            migration.downgrade()
            migration.upgrade()
        assert connection.execute(text("SHOW COLUMNS FROM chat_messages LIKE 'sort_seq'")).first()


def test_mysql_es_embedding_pipeline_and_tombstone(mysql_db, monkeypatch):
    engine, factory = mysql_db
    name = "traceforge-search-test-" + uuid4().hex[:12]
    profile_id = str(uuid4())
    monkeypatch.setattr(settings, "SEARCH_ENABLED", True)
    monkeypatch.setattr(settings, "SEARCH_SESSION_NAMESPACE", "traceforge:search:test:" + uuid4().hex)
    profile = dict(id=profile_id, endpoint="https://api.siliconflow.cn/v1/embeddings", model_id="BAAI/bge-m3",
        encrypted_api_key=encrypt_key(settings.SEARCH_EMBEDDING_API_KEY), dimension=1024,
        chunk_chars=1600, chunk_overlap=160, query_prefix="", document_prefix="", fingerprint="synthetic-test")
    with factory() as db:
        task = _seed_task(db)
        db.add(SearchEmbeddingProfile(**profile, status="tested"))
        target = SearchIndexTarget(physical_index=name, embedding_profile_id=profile_id, dimension=1024)
        db.add(target)
        from app.domains.auth.models.user import WorkspaceMember
        db.add(WorkspaceMember(workspace_id=task.workspace_id, user_id=task.creator_id, role="OWNER"))
        db.commit()
        msg = task_service.save_chat_message(db, task.id, task.workspace_id, task.creator_id, "assistant", "连接池耗尽：run_db_txn 未释放连接，导致请求排队。")
        message_id = msg.id
    def tx(fn):
        with factory() as db:
            result = fn(db)
            db.commit()
            return result
    async def check():
        async with create_client() as es, httpx.AsyncClient(follow_redirects=False) as http:
            await es.indices.create(index=name, body=index_mapping(1024))
            try:
                for _ in range(12):
                    job = tx(lambda db: claim(db, SearchOutbox))
                    if not job:
                        break
                    await process_body(es, job)
                indexed = await es.get(index=name, id="message:" + message_id)
                assert indexed["_source"]["semantic_ready"] is False
                for _ in range(12):
                    job = tx(lambda db: claim(db, SearchEmbeddingJob))
                    if not job:
                        break
                    await process_embedding(es, http, job)
                indexed = await es.get(index=name, id="message:" + message_id)
                assert indexed["_source"]["semantic_ready"] is True
                old_document = indexed["_source"]
                await es.indices.refresh(index=name)
                result = await es.search(index=name, body=search_body("run_db_txn", scope_filters(["ws-1"])))
                assert any(h["_id"] == "message:" + message_id for h in result["hits"]["hits"])
                paraphrase = "资源未归还为何让业务阻塞？"
                vector = (await embed(http, profile, [paraphrase]))[0]
                lexical = await es.search(index=name, body=search_body(paraphrase, scope_filters(["ws-1"])))
                assert not any(h["_id"] == "message:" + message_id for h in lexical["hits"]["hits"])
                fused = await hybrid_search(es, name, paraphrase, scope_filters(["ws-1"]), vector, profile_id)
                assert any(h["_id"] == "message:" + message_id for h in fused)
                with factory() as db:
                    row = db.query(SearchIndexTarget).filter_by(physical_index=name).one()
                    row.status, row.verified = "active", True
                    db.commit()
                from app.domains.search.service import SearchService
                from unittest.mock import patch, AsyncMock
                service = SearchService(es, http)
                params = dict(q="连接池", retrieval="hybrid", type="all", limit=1)
                first = await service.search("user-1", params)
                assert first["executed_retrieval"] == "hybrid"
                assert first["next_cursor"]
                with patch.object(es, "search", new=AsyncMock(side_effect=AssertionError("pagination repeated ES"))), patch("app.domains.search.service.embed", new=AsyncMock(side_effect=AssertionError("pagination repeated embedding"))):
                    second = await service.search("user-1", params | {"cursor": first["next_cursor"]})
                assert len(second["items"]) == 1
                assert second["items"][0]["entity_key"] != first["items"][0]["entity_key"]
                await sessions.close("user-1", first["session_cursor"])
                with factory() as db:
                    from app.domains.task.models.chat import ChatMessage
                    db.delete(db.get(ChatMessage, message_id)); db.commit()
                job = tx(lambda db: claim(db, SearchOutbox))
                await process_body(es, job)
                result = await es.get(index=name, id="message:" + message_id)
                assert result["_source"]["deleted"]
                assert not {"content_text", "title", "semantic_passages"} & result["_source"].keys()
                assert (await bulk_write(es, name, [old_document]))["message:" + message_id] is None
                assert (await es.get(index=name, id="message:" + message_id))["_source"]["deleted"]
            finally:
                await es.indices.delete(index=name)
                await close_redis_client()
    asyncio.run(check())


def test_real_redis_snapshot_quota_isolation_expiry(monkeypatch):
    monkeypatch.setattr(settings, "SEARCH_SESSION_NAMESPACE", "traceforge:search:test:" + uuid4().hex)
    async def check():
        tokens = []
        try:
            for _ in range(4):
                sid, snapshot = await sessions.create("test-user", "binding", [{"entity_key": "test"}], {})
                tokens.append(sessions.cursor("test-user", sid, snapshot, 0, 0))
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as error:
                await sessions.read("test-user", tokens[0], "binding")
            assert error.value.status_code == 410
            assert (await sessions.read("test-user", tokens[-1], "binding"))[1]["candidates"] == [{"entity_key": "test"}]
            with pytest.raises(HTTPException):
                await sessions.read("other-user", tokens[-1], "binding")
        finally:
            for token in tokens:
                await sessions.close("test-user", token)
            await close_redis_client()
    asyncio.run(check())


def test_real_python_rrf_on_basic_license():
    name = "traceforge-search-test-" + uuid4().hex[:12]
    async def check():
        async with create_client() as es:
            await es.indices.create(index=name, body=index_mapping(3))
            try:
                await es.index(index=name, id="task:synthetic", document=dict(entity_key="task:synthetic", kind="task", task_id="synthetic", workspace_id="synthetic", deleted=False, title="测试", semantic_ready=True, embedding_profile_id="test", semantic_passages=[dict(chunk_no=0, start_char=0, end_char=2, vector=[1., 0., 0.])]), refresh=True)
                fused = await hybrid_search(es, name, "测试", scope_filters(["synthetic"]), [1., 0., 0.], "test")
                assert [hit["_id"] for hit in fused] == ["task:synthetic"]
            finally:
                await es.indices.delete(index=name)
    asyncio.run(check())
