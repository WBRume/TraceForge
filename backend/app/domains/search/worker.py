"""Run as --kind search or --kind embedding; no AI runtime is started."""
import argparse
import asyncio
from datetime import datetime, timedelta
from uuid import uuid4
import random
import json

import httpx
from sqlalchemy import or_, and_, select
from app.core.offload import run_db_txn
from app.domains.search.models import SearchOutbox, SearchDocumentState, SearchIndexTarget, SearchEmbeddingProfile, SearchEmbeddingJob
from app.domains.search.capture import mark_connection
from app.domains.search.projection import build_search_projection, build_embedding_chunks, embedding_text, digest
from app.domains.search.embedding import embed, EmbeddingError
from app.domains.search.es import create_client, bulk_write


def dto(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def claim(db, model):
    now = datetime.utcnow()
    row = db.query(model).filter(or_(and_(model.status == "pending", model.available_at <= now),
        and_(model.status == "leased", model.lease_until < now))).order_by(model.available_at, model.id).with_for_update(skip_locked=True).first()
    if row is None:
        return None
    row.status, row.lease_token, row.lease_until = "leased", str(uuid4()), now + timedelta(seconds=300)
    row.attempts += 1
    db.flush()
    return dto(row)


def owns(db, model, job):
    return db.query(model).filter(model.id == job["id"], model.status == "leased",
        model.lease_token == job["lease_token"], model.lease_until > datetime.utcnow()).with_for_update().first()


def finish(db, model, job, status="done", error=None):
    row = owns(db, model, job)
    if row is None:
        return False
    row.status, row.last_error_code = status, error
    row.lease_token, row.lease_until = None, None
    if status in ("done", "dead", "obsolete"):
        row.finished_at = datetime.utcnow()
    else:
        row.available_at = datetime.utcnow() + timedelta(seconds=min(120, 2 ** min(row.attempts, 7)) + random.random())
    return True


def current_document(db, key):
    from app.domains.task.models.chat import ChatMessage
    from app.domains.task.models.task import SddTask
    from app.domains.auth.models.user import Workspace
    kind, source_id = key.split(":", 1)
    model = ChatMessage if kind == "message" else SddTask
    # Existing source row lock serializes first state creation with ordinary source writes.
    if kind == "message":
        parent = db.query(ChatMessage.task_id).filter(ChatMessage.id == source_id).first()
        if parent:
            db.query(SddTask.id).filter(SddTask.id == parent[0]).with_for_update().first()
    source = db.query(model).filter(model.id == source_id).with_for_update().first()
    if source is not None:
        if db.query(Workspace.id).filter(Workspace.id == source.workspace_id).first() is None:
            source = None
        elif kind == "message" and db.query(SddTask.id).filter(SddTask.id == source.task_id).first() is None:
            source = None
    state = db.query(SearchDocumentState).filter(SearchDocumentState.entity_key == key).with_for_update().first()
    if source is not None:
        mark_connection(db.connection(), source, kind)
        if state:
            db.refresh(state)
        else:
            state = db.get(SearchDocumentState, key)
    elif state and not state.deleted:
        state.source_version += 1
        state.deleted, state.projection_hash, state.updated_at = True, None, datetime.utcnow()
        db.add(SearchOutbox(entity_key=key, source_version=state.source_version, task_id=state.task_id,
            workspace_id=state.workspace_id, event_kind="entity_changed"))
        db.flush()
    if state is None:
        return None
    if state.deleted or source is None:
        return dict(entity_key=key, kind=kind, task_id=state.task_id, workspace_id=state.workspace_id,
            source_version=state.source_version, schema_version=1, deleted=True)
    doc = build_search_projection(source, kind)
    if doc is None:
        return None
    doc.update(source_version=state.source_version, semantic_ready=False)
    return doc


def read_work(db, job):
    if owns(db, SearchOutbox, job) is None:
        return None
    if job["event_kind"] != "entity_changed":
        q = db.query(SearchDocumentState.entity_key)
        q = q.filter(SearchDocumentState.task_id == job["task_id"]) if job["task_id"] else q.filter(SearchDocumentState.workspace_id == job["workspace_id"])
        keys = [r[0] for r in q.filter(SearchDocumentState.entity_key > (job["scan_cursor"] or "")).order_by(SearchDocumentState.entity_key).limit(100)]
    else:
        keys = [job["entity_key"]]
    docs = [doc for key in keys if (doc := current_document(db, key)) is not None]
    targets = [dto(t) for t in db.query(SearchIndexTarget).filter(SearchIndexTarget.status.in_(["active", "building", "standby"]))]
    profiles = {p.id: dto(p) for p in db.query(SearchEmbeddingProfile).filter(SearchEmbeddingProfile.id.in_([t["embedding_profile_id"] for t in targets if t["embedding_profile_id"]]))}
    return docs, targets, profiles, keys


def prepare_document(doc, target, profile):
    doc = dict(doc)
    if not doc["deleted"] and profile:
        doc["embedding_profile_id"] = profile["id"]
        doc["embedding_input_hash"] = digest([doc["projection_hash"], profile["fingerprint"]])
    return doc


def confirm_body(db, job, documents, targets, profiles, keys):
    row = owns(db, SearchOutbox, job)
    if row is None:
        return
    # A target created while ES requests were in flight must receive this event too.
    current_targets = {t[0] for t in db.query(SearchIndexTarget.target_id).filter(SearchIndexTarget.status.in_(["active", "building", "standby"]))}
    if current_targets != {t["target_id"] for t in targets}:
        finish(db, SearchOutbox, job, "pending")
        return
    for target in targets:
        profile = profiles.get(target["embedding_profile_id"])
        if not profile:
            continue
        for doc in documents:
            if doc["deleted"]:
                continue
            existing = db.query(SearchEmbeddingJob.id).filter_by(target_id=target["target_id"], entity_key=doc["entity_key"], source_version=doc["source_version"], profile_id=profile["id"]).first()
            if existing is None:
                # Outbox row lease serializes this event; unique identity is the final backstop.
                from sqlalchemy.dialects.mysql import insert as mysql_insert
                from sqlalchemy.dialects.sqlite import insert as sqlite_insert
                values = dict(id=str(uuid4()), target_id=target["target_id"], profile_id=profile["id"], entity_key=doc["entity_key"], source_version=doc["source_version"], projection_hash=doc["projection_hash"], input_hash=digest([doc["projection_hash"], profile["fingerprint"]]))
                table = SearchEmbeddingJob.__table__
                if db.bind.dialect.name == "mysql":
                    statement = mysql_insert(table).values(**values).on_duplicate_key_update(id=table.c.id)
                else:
                    statement = sqlite_insert(table).values(**values).on_conflict_do_nothing()
                db.execute(statement)
    if job["event_kind"] != "entity_changed" and keys:
        row.scan_cursor = keys[-1]
        finish(db, SearchOutbox, job, "pending")
        row.available_at = datetime.utcnow()
    else:
        finish(db, SearchOutbox, job)


async def process_body(client, job):
    work = await run_db_txn(lambda db: read_work(db, job))
    if work is None:
        return
    docs, targets, profiles, keys = work
    if not targets:
        await run_db_txn(lambda db: finish(db, SearchOutbox, job, "pending", "SEARCH_NO_TARGET"))
        return
    for target in targets:
        batch, size = [], 0
        async def publish(batch):
            result = await bulk_write(client, target["physical_index"], batch)
            failures = [code for code in result.values() if code]
            if failures:
                raise RuntimeError(failures[0])
        for raw in docs:
            doc = prepare_document(raw, target, profiles.get(target["embedding_profile_id"]))
            length = len(json.dumps(doc, ensure_ascii=False).encode()) + 256
            if batch and (size + length > 2 * 1024 * 1024 or len(batch) >= 200):
                await publish(batch)
                batch, size = [], 0
            batch.append(doc)
            size += length
        if batch:
            await publish(batch)
    await run_db_txn(lambda db: confirm_body(db, job, docs, targets, profiles, keys))


def embedding_snapshot(db, job):
    if owns(db, SearchEmbeddingJob, job) is None:
        return None
    target = db.get(SearchIndexTarget, job["target_id"])
    profile = db.get(SearchEmbeddingProfile, job["profile_id"])
    doc = current_document(db, job["entity_key"])
    if not target or target.status == "retired" or target.embedding_profile_id != job["profile_id"] or not profile or not doc or doc["deleted"] or doc["source_version"] != job["source_version"] or doc.get("projection_hash") != job["projection_hash"] or digest([doc["projection_hash"], profile.fingerprint]) != job["input_hash"]:
        finish(db, SearchEmbeddingJob, job, "obsolete")
        return None
    if profile.last_error_code == "EMBEDDING_AUTH_FAILED":
        finish(db, SearchEmbeddingJob, job, "pending", profile.last_error_code)
        return None
    return doc, dto(target), dto(profile)


async def process_embedding(client, http, job):
    snapshot = await run_db_txn(lambda db: embedding_snapshot(db, job))
    if snapshot is None:
        return
    doc, target, profile = snapshot
    chunks = build_embedding_chunks(embedding_text(doc), profile["chunk_chars"], profile["chunk_overlap"])
    vectors = []
    for start in range(0, len(chunks), 16):
        from app.domains.search.budget import reserve
        await reserve(profile["id"])
        vectors.extend(await embed(http, profile, [c["text"] for c in chunks[start:start + 16]]))
    if await run_db_txn(lambda db: embedding_snapshot(db, job)) is None:
        return
    doc = prepare_document(doc, target, profile)
    doc["semantic_ready"] = True
    doc["semantic_passages"] = [{k: v for k, v in c.items() if k != "text"} | {"vector": vector} for c, vector in zip(chunks, vectors, strict=True)]
    result = await bulk_write(client, target["physical_index"], [doc])
    if result[doc["entity_key"]]:
        raise RuntimeError(result[doc["entity_key"]])
    await run_db_txn(lambda db: finish(db, SearchEmbeddingJob, job))


async def run(kind, once=False, stop_event=None):
    from app.config import settings
    from app.domains.search.registry import load_models
    load_models()
    # Load the application's model registry without starting its runtime.
    from app.domains.task.services import task_service  # noqa: F401
    model = SearchEmbeddingJob if kind == "embedding" else SearchOutbox
    async with create_client() as client, httpx.AsyncClient(follow_redirects=False) as http:
        while stop_event is None or not stop_event.is_set():
            if kind == "search":
                def advance_backfill(db):
                    from app.domains.search.models import SearchBackfillRun
                    from app.domains.search.cli import backfill_batch
                    pending = db.query(SearchBackfillRun.id).filter(SearchBackfillRun.status == "pending").order_by(SearchBackfillRun.created_at).with_for_update(skip_locked=True).first()
                    if pending:
                        backfill_batch(db, pending[0], 50)
                await run_db_txn(advance_backfill)
            job = await run_db_txn(lambda db: claim(db, model))
            if job:
                try:
                    if kind == "embedding":
                        await process_embedding(client, http, job)
                    else:
                        await process_body(client, job)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    code = exc.code if isinstance(exc, EmbeddingError) else str(exc) if isinstance(exc, (ValueError, RuntimeError)) and str(exc).startswith(("SEARCH_", "EMBEDDING_")) else "SEARCH_TRANSPORT_FAILED"
                    def fail(db):
                        if code == "EMBEDDING_AUTH_FAILED":
                            profile = db.get(SearchEmbeddingProfile, job["profile_id"])
                            if profile:
                                profile.last_error_code = code
                        permanent = isinstance(exc, (ValueError, EmbeddingError)) and not getattr(exc, "retryable", False)
                        finish(db, model, job, "dead" if permanent or job["attempts"] >= 8 else "pending", code)
                    await run_db_txn(fail)
            if once:
                return bool(job)
            if not job:
                if stop_event is None:
                    await asyncio.sleep(settings.SEARCH_WORKER_POLL_SECONDS)
                else:
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=max(0.1, settings.SEARCH_WORKER_POLL_SECONDS))
                    except TimeoutError:
                        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=["search", "embedding"], required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.kind, args.once))
