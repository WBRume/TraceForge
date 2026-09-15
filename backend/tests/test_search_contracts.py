import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
import time

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from tests.test_task_chat_history_ordering import db_session, _seed_task
from app.config import settings
from app.domains.auth.models.user import WorkspaceMember
from app.domains.task.models.chat import ChatMessage
from app.domains.task.services import task_service
from app.domains.search.models import SearchDocumentState, SearchOutbox, SearchEmbeddingJob
from app.domains.search.projection import build_search_projection, build_embedding_chunks, es_version
from app.domains.search.es import search_body, scope_filters, bulk_write
from app.domains.search.embedding import validate_vectors, EmbeddingError, embed, encrypt_key
from app.domains.search.service import hydrate
from app.domains.search.context import window
from app.domains.search.worker import claim, finish, current_document
from app.domains.search.sessions import sign, unsign


def message(kind="text", **kw):
    fields = dict(id="m", task_id="t", workspace_id="w", creator_id="u", role="assistant", content="连接池 run_db_txn camelCase C:/src/app.py\n尾部😀", message_type=kind, metadata_json={}, session_generation=0, created_at=datetime(2026, 1, 1))
    return SimpleNamespace(**(fields | kw))


@pytest.mark.parametrize("kind", ["thinking", "init_reason", "file_upload", "progress_card", "hitl_select"])
def test_hidden_metadata_is_not_indexed(kind):
    assert build_search_projection(message(kind), "message") is None


def test_projection_keeps_tail_symbols_and_excludes_card_secrets():
    doc = build_search_projection(message(), "message")
    assert "尾部😀" in doc["content_text"]
    assert "run_db_txn" in doc["symbols"]
    card = build_search_projection(message("diagnosis_result", metadata_json={"summary": "摘要", "api_key": "secret"}), "message")
    assert card["content_text"] == "摘要"
    assert "secret" not in str(card)


def test_chunks_cover_every_character_with_correct_offsets():
    content = ("中文😀代码" * 950) + "尾部特有"
    chunks = build_embedding_chunks(content)
    reconstructed = chunks[0]["text"] + "".join(c["text"][160:] for c in chunks[1:])
    assert reconstructed == content
    assert chunks[-1]["end_char"] == len(content)
    assert all(c["text"] == content[c["start_char"]:c["end_char"]] for c in chunks)


@pytest.mark.parametrize("vector", [[0, 0], [1, float("nan")], [1, float("inf")], [True, 1], [1], "bad"])
def test_invalid_vectors_are_never_published(vector):
    with pytest.raises(EmbeddingError):
        validate_vectors({"data": [{"index": 0, "embedding": vector}]}, 1, 2)


def test_provider_index_reordering_and_duplicates():
    assert validate_vectors({"data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}]}, 2, 2) == [[1, 0], [0, 1]]
    with pytest.raises(EmbeddingError):
        validate_vectors({"data": [{"index": 0, "embedding": [1, 0]}] * 2}, 2, 2)


def test_exact_supplier_contract(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setattr(settings, "SEARCH_CONFIG_ENCRYPTION_KEY", Fernet.generate_key().decode())
    profile = dict(endpoint="https://api.siliconflow.cn/v1/embeddings", model_id="BAAI/bge-m3", dimension=1024, encrypted_api_key=encrypt_key("test-only"))
    def respond(request):
        import json
        assert json.loads(request.content) == {"model": "BAAI/bge-m3", "input": ["测试"], "encoding_format": "float"}
        assert request.headers["Authorization"] == "Bearer test-only"
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0] * 1024}]})
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            assert len((await embed(client, profile, ["测试"]))[0]) == 1024
    asyncio.run(check())


def test_rrf_has_equal_acl_filters_and_no_sort_or_requery_cursor():
    filters = scope_filters(["workspace-a"], role="assistant", task_id="task-a", date_from="2026-01-01")
    body = search_body("连接池", filters, [1, 0], "profile-a")
    bm25 = search_body("连接池", filters)
    assert bm25["query"]["bool"]["filter"] == filters
    assert body["knn"]["filter"][:len(filters)] == filters
    assert "retriever" not in body
    assert not {"sort", "search_after", "scroll"} & body.keys()
    assert scope_filters([])[1] == {"terms": {"workspace_id": []}}


def test_transaction_rollback_removes_source_state_and_outbox(db_session):
    db = db_session
    task = _seed_task(db)
    msg = ChatMessage(id="rollback", task_id=task.id, workspace_id=task.workspace_id, creator_id=task.creator_id,
        role="assistant", message_type="text", content="回滚", sort_seq=0)
    db.add(msg)
    db.flush()
    assert db.get(SearchDocumentState, "message:rollback")
    db.rollback()
    assert db.get(ChatMessage, "rollback") is None
    assert db.get(SearchDocumentState, "message:rollback") is None
    assert db.query(SearchOutbox).filter_by(entity_key="message:rollback").count() == 0


def test_new_message_version_update_and_tombstone(db_session):
    db = db_session
    task = _seed_task(db)
    msg = task_service.save_chat_message(db, task.id, task.workspace_id, task.creator_id, "assistant", "第一版")
    state = db.get(SearchDocumentState, "message:" + msg.id)
    assert state.source_version == 1
    msg.content = "第二版"
    db.commit()
    db.refresh(state)
    assert state.source_version == 2
    db.delete(msg)
    db.commit()
    db.refresh(state)
    assert state.source_version == 3 and state.deleted and state.projection_hash is None
    assert es_version(2, 1) < es_version(3, 0) < es_version(3, 1)


def test_lease_fencing_rejects_old_owner(db_session):
    db = db_session
    _seed_task(db)
    job = claim(db, SearchOutbox)
    row = db.get(SearchOutbox, job["id"])
    row.lease_token = "replacement-owner"
    db.flush()
    assert finish(db, SearchOutbox, job) is False
    assert row.status == "leased"


def test_acl_version_recheck_and_context(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SEARCH_CURSOR_SECRET", "test-only-signing-secret")
    db = db_session
    task = _seed_task(db)
    db.add(WorkspaceMember(workspace_id=task.workspace_id, user_id=task.creator_id, role="OWNER"))
    db.commit()
    messages = [task_service.save_chat_message(db, task.id, task.workspace_id, task.creator_id, "assistant", f"连接池 {i}") for i in range(7)]
    # SQLite CURRENT_TIMESTAMP omits fractions; explicit values match its bound DateTime representation.
    for msg in messages:
        msg.created_at = datetime(2026, 1, 1)
    db.commit()
    doc = current_document(db, "message:" + messages[3].id)
    rows, consumed = hydrate(db, task.creator_id, [doc], 0, 20, "连接池", [task.workspace_id])
    assert len(rows) == 1 and consumed == 1
    result = window(db, task.creator_id, task.workspace_id, task.id, message_id=messages[3].id, before=1, after=1)
    assert [m["id"] for m in result["messages"]] == [m.id for m in messages[2:5]]
    assert result["has_before"] and result["has_after"]
    with pytest.raises(HTTPException) as exc:
        window(db, "not-member", task.workspace_id, task.id, message_id=messages[3].id)
    assert exc.value.status_code == 403
    messages[3].content = "改动后内容"
    db.commit()
    assert hydrate(db, task.creator_id, [doc], 0, 20, "连接池", [task.workspace_id])[0] == []


def test_cursor_tampering_user_scope_expiration(monkeypatch):
    monkeypatch.setattr(settings, "SEARCH_CURSOR_SECRET", "test-only-signing-secret")
    token = sign(dict(purpose="search", user="u", expires=time.time() + 60))
    assert unsign(token, "search", "u")["user"] == "u"
    for raw, user in ((token + "x", "u"), (token, "other")):
        with pytest.raises(HTTPException):
            unsign(raw, "search", user)


def test_bulk_partial_failure_and_equal_version_identity():
    doc = dict(entity_key="message:m", source_version=2, projection_hash="a", deleted=False)
    client = SimpleNamespace(bulk=AsyncMock(return_value={"items": [{"index": {"status": 409}}]}),
        get=AsyncMock(return_value={"_version": 4, "_source": doc | {"projection_hash": "different"}}))
    assert asyncio.run(bulk_write(client, "test", [doc]))["message:m"] == "SEARCH_VERSION_IDENTITY_MISMATCH"
    client.bulk.return_value = {"items": [{"index": {"status": 200}}, {"index": {"status": 429}}]}
    result = asyncio.run(bulk_write(client, "test", [doc, doc | {"entity_key": "message:n"}]))
    assert result["message:m"] is None and result["message:n"] == "SEARCH_BULK_429"


def test_python_rrf_one_based_ranks_deduplication_and_ties():
    from app.domains.search.rrf import fuse_rankings
    hit = lambda key: {"_id": key, "_source": {"entity_key": key}}
    lexical = [hit("a"), hit("b"), hit("c")]
    semantic = [hit("b"), hit("d"), hit("a")]
    assert [h["_id"] for h in fuse_rankings(lexical, semantic)] == ["b", "a", "d", "c"]
    # Duplicate passage parents cannot contribute twice in a single leg.
    assert [h["_id"] for h in fuse_rankings([hit("b"), hit("b")], [hit("a")])] == ["a", "b"]
    assert len(fuse_rankings([hit(str(i)) for i in range(400)], [])) == 200


def test_profile_encryption_revision_rotation_and_space_change(db_session, monkeypatch):
    from cryptography.fernet import Fernet
    from app.domains.search.router import save_profile, ProfileInput
    from app.domains.search.models import SearchEmbeddingProfile, SearchIndexTarget
    monkeypatch.setattr(settings, "SEARCH_CONFIG_ENCRYPTION_KEY", Fernet.generate_key().decode())
    db = db_session
    body = dict(endpoint="https://api.siliconflow.cn/v1/embeddings", model_id="BAAI/bge-m3", api_key="test-secret")
    first = save_profile(db, ProfileInput(**body))
    db.commit()
    assert "test-secret" not in str(first) and "encrypted_api_key" not in first
    stored = db.get(SearchEmbeddingProfile, first["id"])
    assert stored.encrypted_api_key != "test-secret"
    stored.dimension, stored.fingerprint = 1024, "fixed-space"
    db.add(SearchIndexTarget(physical_index="traceforge-search-test", embedding_profile_id=stored.id, dimension=1024))
    db.commit()
    rotated = save_profile(db, ProfileInput(**(body | dict(id=stored.id, revision=stored.revision, api_key="rotated-secret"))))
    assert rotated["id"] == first["id"]
    assert stored.fingerprint == "fixed-space"
    with pytest.raises(HTTPException):
        save_profile(db, ProfileInput(**(body | dict(id=stored.id, revision=0))))
    replacement = save_profile(db, ProfileInput(**(body | dict(id=stored.id, revision=stored.revision, model_id="different-model"))))
    assert replacement["id"] != first["id"] and replacement["dimension"] is None


def test_admin_configuration_cannot_be_read_by_member():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.dependencies import get_current_user
    from app.domains.search.router import router
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="member", is_admin=False)
    with TestClient(app) as client:
        assert client.get("/api/admin/search/embedding").status_code == 403


def test_highlight_is_plain_text_and_bounded():
    from app.domains.search.service import highlight_segments
    segments = highlight_segments('&lt;script&gt;alert(1)&lt;/script&gt;\ue000命中\ue001' + '尾' * 300)
    assert sum(len(s["text"]) for s in segments) == 240
    assert any(s["match"] and s["text"] == "命中" for s in segments)
    assert segments[0]["text"].startswith("<script>")


def test_search_access_logs_strip_query_and_cursor():
    import logging
    from app.domains.search.router import SearchAccessFilter
    for path in ("/api/search?q=private&cursor=secret", "/api/workspaces/w/tasks/t/messages/m/context?cursor=secret"):
        record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "%s %s %s %s %s",
            ("client", "GET", path, "1.1", 200), None)
        assert SearchAccessFilter().filter(record)
        assert "?" not in record.args[2]


def test_search_date_filter_accepts_mixed_timezone_formats():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.dependencies import get_current_user
    from app.domains.search.router import router
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="member")
    search = AsyncMock(return_value={"items": []})
    app.state.search_service = SimpleNamespace(search=search)
    with TestClient(app) as client:
        assert client.get("/api/search", params={"q": "hello", "from": "2026-01-01", "to": "2026-01-02T00:00:00Z"}).status_code == 200
        assert client.get("/api/search", params={"q": "hello", "from": "2026-01-02", "to": "2026-01-01T00:00:00Z"}).status_code == 422
