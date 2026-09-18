from datetime import datetime, timezone
from typing import Literal
import httpx
import logging
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from app.config import settings
from app.dependencies import get_current_user, require_admin
from app.core.offload import run_db_txn
from app.core.logging import audit_log
from app.domains.search.service import SearchService, configuration
from app.domains.search.es import create_client
from app.domains.search.models import SearchEmbeddingProfile, SearchIndexTarget
from app.domains.search.worker import dto
from app.domains.search.embedding import embed, encrypt_key, validate_endpoint, EmbeddingError
from app.domains.search.projection import digest
from app.domains.search import sessions

router = APIRouter(tags=["Search"])


class SearchAccessFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) == 5:
            client, method, path, version, status = record.args
            if isinstance(path, str) and (path.startswith("/api/search") or "/messages/" in path and "/context" in path):
                record.args = (client, method, path.split("?", 1)[0], version, status)
        return True


async def start(app):
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, SearchAccessFilter) for f in access.filters):
        access.addFilter(SearchAccessFilter())
    app.state.search_es = create_client()
    app.state.search_http = httpx.AsyncClient(follow_redirects=False)
    app.state.search_service = SearchService(app.state.search_es, app.state.search_http)
    from app.domains.search.runtime import SearchRuntime
    if not hasattr(app.state, "search_runtime"):
        app.state.search_runtime = SearchRuntime()
    app.state.search_runtime.start()


async def stop(app):
    if hasattr(app.state, "search_runtime"):
        await app.state.search_runtime.stop()
    if hasattr(app.state, "search_es"):
        await app.state.search_es.close()
        await app.state.search_http.aclose()


@router.get("/search/capabilities")
async def capabilities(request: Request, user=Depends(get_current_user)):
    if not settings.SEARCH_ENABLED:
        return dict(enabled=False, ready=False, hybrid_available=False)
    target, profile = await run_db_txn(configuration)
    ready = False
    if target:
        try:
            ready = bool(await request.app.state.search_es.indices.exists(index=target["physical_index"]))
        except Exception:
            pass
    reason = "embedding_not_configured" if not profile else "semantic_index_not_ready" if not target["verified"] else None
    hybrid = ready and reason is None
    return dict(enabled=True, ready=ready, types=["task", "message"], min_query_length=2, max_query_length=200,
        max_limit=50, history_context_enabled=True, indexing_state="ready" if target and target["verified"] else "partial",
        default_retrieval="hybrid", available_retrievals=["lexical", "hybrid"] if hybrid else ["lexical"],
        hybrid_available=hybrid, hybrid_unavailable_reason=reason, semantic_indexing_state=target["semantic_indexing_state"] if target else "building",
        result_window_size=200, max_display_results=100, fusion="python_rrf")


@router.get("/search")
async def search(request: Request, q: str = Query(min_length=2, max_length=200),
        retrieval: Literal["hybrid", "lexical"] = "hybrid", type: Literal["all", "task", "message"] = "all",
        workspace_id: str | None = None, task_id: str | None = None, role: Literal["user", "assistant"] | None = None,
        date_from: datetime | None = Query(None, alias="from"), date_to: datetime | None = Query(None, alias="to"),
        limit: int = Query(20, ge=1, le=50), cursor: str | None = Query(None, max_length=4096), user=Depends(get_current_user)):
    q = q.strip()
    # ES treats dates without an offset as UTC; compare the same instants here.
    date_from = date_from.replace(tzinfo=timezone.utc) if date_from and date_from.tzinfo is None else date_from
    date_to = date_to.replace(tzinfo=timezone.utc) if date_to and date_to.tzinfo is None else date_to
    if len(q) < 2 or (date_from and date_to and date_from >= date_to):
        raise HTTPException(422, "SEARCH_INVALID_QUERY")
    params = dict(q=q, retrieval=retrieval, type=type, workspace_id=workspace_id, task_id=task_id, role=role,
        limit=limit, cursor=cursor, **{"from": date_from.isoformat() if date_from else None, "to": date_to.isoformat() if date_to else None})
    work = asyncio.create_task(request.app.state.search_service.search(str(user.id), params))
    async def disconnect_monitor():
        while not work.done():
            if await request.is_disconnected():
                work.cancel()
                return
            await asyncio.sleep(0.05)
    monitor = asyncio.create_task(disconnect_monitor())
    try:
        return await work
    finally:
        monitor.cancel()
        await asyncio.gather(monitor, return_exceptions=True)


class CloseSession(BaseModel):
    cursor: str = Field(max_length=4096)


@router.post("/search/sessions/close")
async def close_session(body: CloseSession, user=Depends(get_current_user)):
    await sessions.close(str(user.id), body.cursor)
    return {"closed": True}


@router.get("/workspaces/{ws_id}/tasks/{task_id}/messages/context")
async def more_context(ws_id: str, task_id: str, cursor: str = Query(max_length=4096),
        direction: Literal["before", "after"] = "before", limit: int = Query(30, ge=1, le=50), user=Depends(get_current_user)):
    from app.domains.search.context import window
    return await run_db_txn(lambda db: window(db, str(user.id), ws_id, task_id, cursor=cursor, direction=direction, limit=limit))


@router.get("/workspaces/{ws_id}/tasks/{task_id}/messages/{message_id}/context")
async def message_context(ws_id: str, task_id: str, message_id: str,
        before: int = Query(15, ge=0, le=50), after: int = Query(15, ge=0, le=50), user=Depends(get_current_user)):
    from app.domains.search.context import window
    return await run_db_txn(lambda db: window(db, str(user.id), ws_id, task_id, message_id=message_id, before=before, after=after))


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    id: str | None = None
    revision: int = Field(0, ge=0)
    endpoint: str = Field(max_length=500)
    model_id: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(None, max_length=4096)
    clear_api_key: bool = False


def public_profile(profile):
    return {k: getattr(profile, k) for k in ("id", "revision", "status", "endpoint", "model_id", "dimension", "last_error_code")} | {"has_api_key": bool(profile.encrypted_api_key)}


@router.get("/admin/search/embedding")
async def profiles(user=Depends(require_admin)):
    return await run_db_txn(lambda db: {"profiles": [public_profile(p) for p in db.query(SearchEmbeddingProfile).order_by(SearchEmbeddingProfile.created_at.desc())],
        "targets": [{k: getattr(t, k) for k in ("target_id", "physical_index", "status", "embedding_profile_id", "verified")} for t in db.query(SearchIndexTarget)]})


def save_profile(db, body):
    try:
        endpoint = validate_endpoint(body.endpoint)
        encrypted = encrypt_key(body.api_key) if body.api_key is not None else None
    except EmbeddingError as exc:
        raise HTTPException(422, exc.code) from None
    if body.clear_api_key and body.api_key is not None:
        raise HTTPException(422, "EMBEDDING_KEY_CONFLICT")
    profile = db.query(SearchEmbeddingProfile).filter(SearchEmbeddingProfile.id == body.id).with_for_update().first() if body.id else None
    if body.id and (not profile or profile.revision != body.revision):
        raise HTTPException(409, "SEARCH_CONFIG_REVISION_CONFLICT")
    bound = profile and db.query(SearchIndexTarget.target_id).filter(SearchIndexTarget.embedding_profile_id == profile.id).first()
    changed_space = profile and (profile.endpoint != endpoint or profile.model_id != body.model_id)
    if bound and changed_space:
        old_key = profile.encrypted_api_key
        profile = SearchEmbeddingProfile(endpoint=endpoint, model_id=body.model_id, encrypted_api_key=old_key)
        db.add(profile)
    elif not profile:
        profile = SearchEmbeddingProfile(endpoint=endpoint, model_id=body.model_id)
        db.add(profile)
    else:
        profile.revision += 1
        if changed_space:
            profile.status, profile.dimension, profile.fingerprint = "draft", None, None
    profile.endpoint, profile.model_id = endpoint, body.model_id
    if body.clear_api_key:
        profile.encrypted_api_key = None
    elif encrypted is not None:
        profile.encrypted_api_key = encrypted
        profile.last_error_code = None
        from app.domains.search.models import SearchEmbeddingJob
        db.query(SearchEmbeddingJob).filter(SearchEmbeddingJob.profile_id == profile.id,
            SearchEmbeddingJob.status == "dead", SearchEmbeddingJob.last_error_code == "EMBEDDING_AUTH_FAILED").update(
                dict(status="pending", attempts=0, available_at=datetime.utcnow()))
    db.flush()
    return public_profile(profile)


@router.put("/admin/search/embedding")
async def update_profile(body: ProfileInput, user=Depends(require_admin)):
    result = await run_db_txn(lambda db: save_profile(db, body))
    audit_log(action="update_search_embedding", outcome="success", resource_type="search_profile", resource_id=result["id"], user_id=user.id,
        changed_fields=[k for k in body.model_fields_set if k not in ("id", "revision")])
    return result


@router.post("/admin/search/embedding/{profile_id}/test")
async def test_profile(profile_id: str, request: Request, user=Depends(require_admin)):
    def read(db):
        p = db.get(SearchEmbeddingProfile, profile_id)
        if not p:
            raise HTTPException(404, "Profile not found")
        return dto(p)
    profile = await run_db_txn(read)
    try:
        vectors = await embed(request.app.state.search_http, profile, ["数据库连接池耗尽", "连接未释放导致请求排队"])
    except EmbeddingError as exc:
        raise HTTPException(422, exc.code) from None
    dimension = len(vectors[0])
    if profile["model_id"] == "BAAI/bge-m3" and dimension != 1024:
        raise HTTPException(422, "EMBEDDING_INVALID_RESPONSE")
    def publish(db):
        current = db.query(SearchEmbeddingProfile).filter(SearchEmbeddingProfile.id == profile_id).with_for_update().one()
        if current.revision != profile["revision"]:
            raise HTTPException(409, "SEARCH_CONFIG_REVISION_CONFLICT")
        current.dimension, current.status, current.last_error_code = dimension, "tested", None
        current.fingerprint = digest([current.endpoint, current.model_id, dimension, current.chunk_chars, current.chunk_overlap, current.query_prefix, current.document_prefix])
        current.revision += 1
        return public_profile(current)
    return await run_db_txn(publish)


@router.post("/admin/search/embedding/{profile_id}/build")
async def build_profile(profile_id: str, request: Request, user=Depends(require_admin)):
    from app.domains.search.cli import create_index
    from app.domains.search.models import SearchBackfillRun
    # Stable name makes a repeated click idempotent for this immutable profile.
    name = "traceforge-search-v1-" + profile_id.replace("-", "")
    result = await create_index(request.app.state.search_es, name, profile_id)
    def enqueue(db):
        run = db.query(SearchBackfillRun).filter(SearchBackfillRun.target_id == result["target_id"]).first()
        if not run:
            from sqlalchemy import func
            run = SearchBackfillRun(target_id=result["target_id"], boundary=db.query(func.now()).scalar())
            db.add(run)
            db.flush()
        return {"run_id": run.id, "status": run.status}
    return await run_db_txn(enqueue)


@router.post("/admin/search/targets/{target_id}/{operation}")
async def target_operation(target_id: str, operation: Literal["verify", "activate"], request: Request, user=Depends(require_admin)):
    from app.domains.search.cli import verify, activate
    def read(db):
        target = db.get(SearchIndexTarget, target_id)
        if not target:
            raise HTTPException(404, "Target not found")
        return target.physical_index
    name = await run_db_txn(read)
    try:
        return await (verify(request.app.state.search_es, name) if operation == "verify" else activate(request.app.state.search_es, name))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
