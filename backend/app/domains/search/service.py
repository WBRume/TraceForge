"""Authorized search: candidate metadata first, current bodies only for returned hits."""
import asyncio
import time
import html
import json
from fastapi import HTTPException
from sqlalchemy.orm import load_only
from app.config import settings
from app.core.offload import run_db_txn
from app.domains.auth.models.user import Workspace, WorkspaceMember
from app.domains.task.models.task import SddTask
from app.domains.task.models.chat import ChatMessage
from app.domains.search.models import SearchDocumentState, SearchIndexTarget, SearchEmbeddingProfile, SearchEmbeddingJob, SearchOutbox
from app.domains.search.projection import digest, build_search_projection, embedding_text
from app.domains.search.embedding import embed, EmbeddingError
from app.domains.search.es import search_body, scope_filters
from app.domains.search.rrf import hybrid_search, checked_hits
from app.domains.search.worker import dto
from app.domains.search import sessions


def authorized_scope(db, user_id, workspace_id=None, task_id=None):
    ids = [r[0] for r in db.query(WorkspaceMember.workspace_id).join(Workspace, Workspace.id == WorkspaceMember.workspace_id).filter(WorkspaceMember.user_id == user_id)]
    if workspace_id:
        if workspace_id not in ids:
            raise HTTPException(403, "No access to this workspace")
        ids = [workspace_id]
    if task_id:
        task = db.query(SddTask.workspace_id).filter(SddTask.id == task_id, SddTask.workspace_id.in_(ids)).first()
        if not task:
            raise HTTPException(404, "Task not found")
        ids = [task[0]]
    return sorted(ids)


def configuration(db):
    target = db.query(SearchIndexTarget).filter(SearchIndexTarget.status == "active").first()
    if not target:
        return None, None
    profile = db.get(SearchEmbeddingProfile, target.embedding_profile_id) if target.embedding_profile_id else None
    data = dto(target)
    pending = db.query(SearchEmbeddingJob.id).filter(SearchEmbeddingJob.target_id == target.target_id,
        SearchEmbeddingJob.status.notin_(["done", "obsolete"])).first() is not None
    pending = pending or db.query(SearchOutbox.id).filter(SearchOutbox.status != "done").first() is not None
    data["semantic_indexing_state"] = "ready" if target.verified and not pending else "partial"
    return data, dto(profile) if profile else None


def snippet(text, query, offset=0):
    pos = text.lower().find(query.lower())
    start = max(0, pos - 60) if pos >= 0 else max(0, min(offset, len(text)))
    part = text[start:start + 240]
    if pos < 0:
        return [{"text": part, "match": False}], "semantic" if offset else "plain"
    relative = pos - start
    return [{"text": part[:relative], "match": False}, {"text": part[relative:relative + len(query)], "match": True}, {"text": part[relative + len(query):], "match": False}], "keyword"


def highlight_segments(fragment):
    """Decode only text; never return provider HTML for browser interpretation."""
    segments, matched, buffer, remaining = [], False, [], 240
    for char in html.unescape(fragment):
        if char in ("\ue000", "\ue001"):
            if buffer:
                segments.append({"text": "".join(buffer), "match": matched})
                buffer = []
            matched = char == "\ue000"
        elif remaining:
            buffer.append(char)
            remaining -= 1
        else:
            break
    if buffer:
        segments.append({"text": "".join(buffer), "match": matched})
    return segments


def hydrate(db, user, candidates, offset, limit, query, scope):
    allowed = set(authorized_scope(db, user)) & set(scope)
    remaining = candidates[offset:]
    keys = [c["entity_key"] for c in remaining]
    states = {s.entity_key: s for s in db.query(SearchDocumentState).filter(SearchDocumentState.entity_key.in_(keys))}
    task_ids = list({c["task_id"] for c in remaining})
    tasks = {t.id: t for t in db.query(SddTask).options(load_only(SddTask.id, SddTask.name, SddTask.workspace_id)).filter(SddTask.id.in_(task_ids), SddTask.workspace_id.in_(allowed))}
    workspaces = {w.id: w.name for w in db.query(Workspace).options(load_only(Workspace.id, Workspace.name)).filter(Workspace.id.in_(allowed))}
    message_ids = [c.get("message_id") for c in remaining if c["kind"] == "message"]
    messages = {m.id: m for m in db.query(ChatMessage).options(load_only(ChatMessage.id, ChatMessage.task_id, ChatMessage.workspace_id)).filter(ChatMessage.id.in_(message_ids), ChatMessage.workspace_id.in_(allowed))}
    selected = []
    consumed = offset
    for candidate in remaining:
        consumed += 1
        state = states.get(candidate["entity_key"])
        task = tasks.get(candidate["task_id"])
        if not state or state.deleted or not task or state.workspace_id not in allowed or state.workspace_id != task.workspace_id or state.source_version != candidate.get("source_version") or state.projection_hash != candidate.get("projection_hash"):
            continue
        if candidate["kind"] == "message":
            msg = messages.get(candidate.get("message_id"))
            if not msg or msg.task_id != task.id or msg.workspace_id != task.workspace_id:
                continue
        selected.append(candidate)
        if len(selected) >= limit:
            break
    # Bounded full projection loading only for the final selected page.
    selected_messages = {m.id: m for m in db.query(ChatMessage).filter(ChatMessage.id.in_([c.get("message_id") for c in selected if c["kind"] == "message"])).populate_existing()}
    selected_tasks = {t.id: t for t in db.query(SddTask).filter(SddTask.id.in_([c["task_id"] for c in selected if c["kind"] == "task"])).populate_existing()}
    items = []
    for c in selected:
        source = selected_messages.get(c.get("message_id")) if c["kind"] == "message" else selected_tasks.get(c["task_id"])
        projection = build_search_projection(source, c["kind"]) if source else None
        if not projection or projection["projection_hash"] != c["projection_hash"]:
            continue
        task = tasks[c["task_id"]]
        segments, basis = snippet(embedding_text(projection), query, c.get("start_char", 0))
        if basis == "plain" and "start_char" in c:
            basis = "semantic"
        if c.get("highlight"):
            segments, basis = highlight_segments(c["highlight"]), "keyword"
        items.append(dict(kind=c["kind"], entity_key=c["entity_key"], workspace_id=task.workspace_id,
            workspace_name=workspaces[task.workspace_id], task_id=task.id, task_name=task.name,
            message_id=c.get("message_id"), role=projection.get("role"), message_type=projection.get("message_type"),
            created_at=projection["created_at"], snippet=segments, snippet_basis=basis,
            target={"route_name": "taskChat", "params": {"wsId": task.workspace_id, "taskId": task.id},
                "query": {"messageId": c["message_id"]} if c.get("message_id") else {}}))
    return items, consumed


class SearchService:
    def __init__(self, es, http):
        self.es, self.http = es, http
        self.inflight = 0

    async def search(self, user, params):
        if not settings.SEARCH_ENABLED:
            raise HTTPException(503, "SEARCH_DISABLED")
        if self.inflight >= 8:
            raise HTTPException(429, "SEARCH_BUSY")
        self.inflight += 1
        try:
            async with asyncio.timeout(2):
                return await self._search(user, params)
        except TimeoutError:
            raise HTTPException(504, "SEARCH_TIMEOUT") from None
        finally:
            self.inflight -= 1

    async def _search(self, user, params):
        started = time.monotonic()
        def read_config(db):
            return authorized_scope(db, user, params.get("workspace_id"), params.get("task_id")), configuration(db)
        scope, (target, profile) = await run_db_txn(read_config)
        if not scope:
            return dict(items=[], next_cursor=None, session_cursor="", has_more=False, requested_retrieval=params["retrieval"],
                executed_retrieval=params["retrieval"], degraded_reason=None, indexing_state="ready", semantic_indexing_state="ready",
                result_window_exhausted=False, incomplete=False, took_ms=round((time.monotonic() - started) * 1000))
        if not target:
            raise HTTPException(503, "SEARCH_NOT_READY")
        binding = digest([user, scope, target["target_id"], target["embedding_profile_id"], {k: v for k, v in params.items() if k != "cursor"}])
        if params.get("cursor"):
            sid, snapshot, offset, shown = await sessions.read(user, params["cursor"], binding)
        else:
            mode, degraded = params["retrieval"], None
            vector = None
            if mode == "hybrid":
                if not profile or not target["verified"]:
                    raise HTTPException(409, "SEARCH_SEMANTIC_NOT_READY")
                try:
                    from app.domains.search.budget import reserve
                    await reserve(profile["id"], query=True)
                    vector = (await embed(self.http, profile, [params["q"]], query=True))[0]
                except EmbeddingError as exc:
                    mode, degraded = "lexical", exc.code.lower()
            candidates = []
            if scope:
                filters = scope_filters(scope, kind=params["type"], task_id=params.get("task_id"), role=params.get("role"), date_from=params.get("from"), date_to=params.get("to"))
                try:
                    if vector is not None:
                        hits = await hybrid_search(self.es, target["physical_index"], params["q"], filters, vector, target["embedding_profile_id"])
                    else:
                        hits = checked_hits(await self.es.search(index=target["physical_index"], body=search_body(params["q"], filters)))
                except Exception:
                    raise HTTPException(503, "SEARCH_UNAVAILABLE") from None
                for hit in hits:
                    candidate = dict(hit["_source"])
                    highlights = hit.get("highlight", {})
                    fragments = highlights.get("content_text") or highlights.get("title")
                    if fragments:
                        candidate["highlight"] = fragments[0][:2048]
                    inner = next(iter(hit.get("inner_hits", {}).values()), {}).get("hits", {}).get("hits", [])
                    if inner:
                        candidate["start_char"] = inner[0].get("fields", {}).get("semantic_passages.start_char", [0])[0]
                    candidates.append(candidate)
            metadata = dict(requested_retrieval=params["retrieval"], executed_retrieval=mode, degraded_reason=degraded,
                indexing_state="ready" if target["verified"] else "partial", semantic_indexing_state=target["semantic_indexing_state"])
            sid, snapshot = await sessions.create(user, binding, candidates, metadata)
            offset = shown = 0
        items, consumed = await run_db_txn(lambda db: hydrate(db, user, snapshot["candidates"], offset, min(params["limit"], 100 - shown), params["q"], scope))
        while len(json.dumps(items, ensure_ascii=False).encode()) > 56 * 1024:
            dropped = items.pop()
            consumed = min(consumed, next(i for i, c in enumerate(snapshot["candidates"]) if c["entity_key"] == dropped["entity_key"]))
        shown += len(items)
        has_more = consumed < len(snapshot["candidates"]) and shown < 100
        token = sessions.cursor(user, sid, snapshot, consumed, shown)
        from app.core.logging import get_logger
        get_logger(__name__, category="search").info("Search completed retrieval={} returned={} scanned={} duration_ms={}",
            snapshot["metadata"]["executed_retrieval"], len(items), consumed - offset, round((time.monotonic() - started) * 1000))
        return dict(items=items, next_cursor=token if has_more else None, session_cursor=token, has_more=has_more,
            **snapshot["metadata"], result_window_exhausted=shown >= 100 or (not has_more and len(snapshot["candidates"]) == 200),
            incomplete=False, took_ms=round((time.monotonic() - started) * 1000))
