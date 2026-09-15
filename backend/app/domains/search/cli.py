"""Search maintenance commands. No command resets source data or starts a license trial."""
import argparse
import asyncio
from datetime import datetime, timedelta
import json
import re
from uuid import uuid4

import httpx
from sqlalchemy import and_, or_, func
from app.config import settings
from app.core.offload import run_db_txn
from app.domains.search.models import SearchIndexTarget, SearchEmbeddingProfile, SearchBackfillRun, SearchDocumentState, SearchOutbox, SearchEmbeddingJob
from app.domains.search.worker import dto, current_document
from app.domains.search.es import create_client, index_mapping, search_body, scope_filters
from app.domains.search.embedding import embed, encrypt_key
from app.domains.search.projection import digest


def get_target(db, name):
    target = db.query(SearchIndexTarget).filter(SearchIndexTarget.physical_index == name).first()
    if not target:
        raise ValueError("SEARCH_TARGET_NOT_FOUND")
    return dto(target)


async def configure(http):
    """Bootstrap the specified supplier from local environment, encrypted at rest."""
    data = dict(endpoint="https://api.siliconflow.cn/v1/embeddings", model_id="BAAI/bge-m3",
        encrypted_api_key=encrypt_key(settings.SEARCH_EMBEDDING_API_KEY), dimension=1024,
        chunk_chars=1600, chunk_overlap=160, query_prefix="", document_prefix="")
    await embed(http, data, ["数据库连接池耗尽", "连接没有释放"])
    data["fingerprint"] = digest([data[k] for k in ("endpoint", "model_id", "dimension", "chunk_chars", "chunk_overlap", "query_prefix", "document_prefix")])
    def save(db):
        existing = db.query(SearchEmbeddingProfile).filter(SearchEmbeddingProfile.fingerprint == data["fingerprint"]).first()
        if existing:
            return {"profile_id": existing.id, "dimension": existing.dimension}
        p = SearchEmbeddingProfile(**data, status="tested")
        db.add(p)
        db.flush()
        return {"profile_id": p.id, "dimension": p.dimension}
    return await run_db_txn(save)


async def create_index(es, name, profile_id=None):
    if not re.fullmatch(r"traceforge-search-[a-z0-9-]{1,90}", name):
        raise ValueError("SEARCH_INVALID_INDEX_NAME")
    def read(db):
        existing = db.query(SearchIndexTarget).filter(SearchIndexTarget.physical_index == name).first()
        if existing:
            if existing.embedding_profile_id != profile_id:
                raise ValueError("SEARCH_TARGET_PROFILE_MISMATCH")
            return dto(existing), None
        p = db.get(SearchEmbeddingProfile, profile_id) if profile_id else None
        if profile_id and (not p or not p.dimension or not p.fingerprint or p.status == "draft"):
            raise ValueError("EMBEDDING_PROFILE_NOT_TESTED")
        return None, dto(p) if p else None
    existing, profile = await run_db_txn(read)
    if existing:
        return {"target_id": existing["target_id"], "existing": True}
    dimension = profile["dimension"] if profile else None
    await es.indices.create(index=name, body=index_mapping(dimension))
    def save(db):
        t = SearchIndexTarget(physical_index=name, embedding_profile_id=profile_id, dimension=dimension)
        db.add(t)
        db.flush()
        return {"target_id": t.target_id, "physical_index": name}
    return await run_db_txn(save)


def backfill_batch(db, run_id, batch_size):
    from app.domains.task.models.task import SddTask
    from app.domains.task.models.chat import ChatMessage
    run = db.query(SearchBackfillRun).filter(SearchBackfillRun.id == run_id).with_for_update().one()
    if run.status == "done":
        return dto(run)
    model = SddTask if run.stage == "task" else ChatMessage
    query = db.query(model).filter(model.created_at <= run.boundary)
    if run.cursor:
        stamp, identity = datetime.fromisoformat(run.cursor[0]), run.cursor[1]
        query = query.filter(or_(model.created_at > stamp, and_(model.created_at == stamp, model.id > identity)))
    rows = query.order_by(model.created_at, model.id).limit(batch_size).with_for_update().all()
    for source in rows:
        doc = current_document(db, f"{run.stage}:{source.id}")
        if run.stage == "message" and source.sort_seq is None:
            metadata = source.metadata_json if isinstance(source.metadata_json, dict) else {}
            try:
                source.sort_seq = int(metadata.get("order_index") or 0)
            except (ValueError, TypeError):
                source.sort_seq = 0
        if doc:
            db.flush()
            event = db.query(SearchOutbox).filter_by(event_kind="entity_changed", entity_key=doc["entity_key"], source_version=doc["source_version"]).with_for_update().first()
            if event and event.status != "leased":
                event.status, event.available_at, event.attempts = "pending", datetime.utcnow(), 0
            elif event is None:
                db.add(SearchOutbox(event_kind="entity_changed", entity_key=doc["entity_key"], source_version=doc["source_version"], task_id=doc["task_id"], workspace_id=doc["workspace_id"]))
        run.cursor = [source.created_at.isoformat(), source.id]
        run.processed += 1
    if len(rows) < batch_size:
        if run.stage == "task":
            run.stage, run.cursor = "message", None
        else:
            run.status, run.finished_at = "done", datetime.utcnow()
    db.flush()
    return dto(run)


async def backfill(name=None, run_id=None, batch_size=100):
    if not run_id:
        def create(db):
            target = get_target(db, name)
            old = db.query(SearchBackfillRun).filter(SearchBackfillRun.target_id == target["target_id"], SearchBackfillRun.status != "done").first()
            if old:
                return old.id
            # Legacy created_at uses the DB clock; use the same clock for its scan boundary.
            run = SearchBackfillRun(target_id=target["target_id"], boundary=db.query(func.now()).scalar())
            db.add(run)
            db.flush()
            return run.id
        run_id = await run_db_txn(create)
    while True:
        result = await run_db_txn(lambda db: backfill_batch(db, run_id, batch_size))
        if result["status"] == "done":
            return {k: result[k] for k in ("id", "status", "processed", "failed")}
        await asyncio.sleep(0.05)


async def verify(es, name):
    target = await run_db_txn(lambda db: get_target(db, name))
    cursor, checked, missing, semantic_missing = "", 0, 0, 0
    while True:
        def read(db):
            rows = db.query(SearchDocumentState.entity_key).filter(SearchDocumentState.entity_key > cursor).order_by(SearchDocumentState.entity_key).limit(100).all()
            return [d for (key,) in rows if (d := current_document(db, key)) is not None]
        docs = await run_db_txn(read)
        if not docs:
            break
        found = await es.mget(index=name, ids=[d["entity_key"] for d in docs], source_excludes=["semantic_passages.vector"])
        for expected, result in zip(docs, found["docs"], strict=True):
            checked += 1
            actual = result.get("_source", {})
            valid = result.get("found") and all(actual.get(k) == expected.get(k) for k in ("entity_key", "source_version", "projection_hash", "deleted"))
            missing += int(not valid)
            if expected["deleted"]:
                missing += int(any(k in actual for k in ("content_text", "title", "symbols", "semantic_passages")))
            elif target["embedding_profile_id"]:
                semantic_missing += int(not actual.get("semantic_ready") or actual.get("embedding_profile_id") != target["embedding_profile_id"])
        cursor = docs[-1]["entity_key"]
    def save(db):
        pending = db.query(SearchOutbox.id).filter(SearchOutbox.status != "done").first() is not None
        jobs = db.query(SearchEmbeddingJob.id).filter(SearchEmbeddingJob.target_id == target["target_id"], SearchEmbeddingJob.status.notin_(["done", "obsolete"])).first() is not None
        completed = db.query(SearchBackfillRun.id).filter_by(target_id=target["target_id"], status="done").first() is not None
        valid = not (missing or semantic_missing or pending or jobs) and completed
        db.get(SearchIndexTarget, target["target_id"]).verified = valid
        return dict(checked=checked, missing=missing, semantic_missing=semantic_missing, outbox_pending=pending, embedding_pending=jobs, backfill_completed=completed, verified=valid)
    return await run_db_txn(save)


async def activate(es, name):
    token = str(uuid4())
    def claim_activation(db):
        rows = db.query(SearchIndexTarget).order_by(SearchIndexTarget.target_id).with_for_update().all()
        target = next((t for t in rows if t.physical_index == name), None)
        if not target or not target.verified:
            raise ValueError("SEARCH_VERIFY_REQUIRED")
        now = datetime.utcnow()
        for row in rows:
            if row.activation_phase in ("pending", "alias_applied"):
                if row.activation_until and row.activation_until > now:
                    raise ValueError("SEARCH_ACTIVATION_BUSY")
                if row.physical_index != name:
                    raise ValueError("SEARCH_RESUME_PREVIOUS_ACTIVATION")
        target.activation_phase, target.activation_token = "pending", token
        target.activation_until = now + timedelta(seconds=30)
        return dto(target)
    target = await run_db_txn(claim_activation)
    # API reads the physical target from DB; alias-only interruptions cannot mix vector spaces.
    from elasticsearch import NotFoundError
    try:
        aliases = await es.indices.get_alias(name=settings.SEARCH_READ_ALIAS)
    except NotFoundError:
        aliases = {}
    actions = [{"remove": {"index": old, "alias": settings.SEARCH_READ_ALIAS}} for old in aliases]
    actions.append({"add": {"index": name, "alias": settings.SEARCH_READ_ALIAS}})
    await es.indices.update_aliases(actions=actions)
    def alias_applied(db):
        current = db.query(SearchIndexTarget).filter_by(target_id=target["target_id"]).with_for_update().one()
        if current.activation_token != token or current.activation_until <= datetime.utcnow():
            raise ValueError("SEARCH_ACTIVATION_LEASE_LOST")
        current.activation_phase = "alias_applied"
    await run_db_txn(alias_applied)
    def publish(db):
        rows = db.query(SearchIndexTarget).order_by(SearchIndexTarget.target_id).with_for_update().all()
        current = next(t for t in rows if t.target_id == target["target_id"])
        if not current.verified or current.activation_token != token or current.activation_until <= datetime.utcnow():
            raise ValueError("SEARCH_ACTIVATION_LEASE_LOST")
        for t in rows:
            if t.status == "active":
                t.status = "standby"
        current.status = "active"
        current.activation_phase, current.activation_token, current.activation_until = "done", None, None
        return {"active": name, "fusion": "python_rrf"}
    return await run_db_txn(publish)


def status(db):
    def counts(model):
        return dict(db.query(model.status, func.count()).group_by(model.status).all())
    return dict(outbox=counts(SearchOutbox), embeddings=counts(SearchEmbeddingJob), backfills=counts(SearchBackfillRun),
        targets=[{k: getattr(t, k) for k in ("target_id", "physical_index", "status", "embedding_profile_id", "verified")} for t in db.query(SearchIndexTarget)])


async def main(args):
    from app.domains.search.registry import load_models
    load_models()
    from app.domains.task.services import task_service  # noqa: F401
    async with create_client() as es, httpx.AsyncClient(follow_redirects=False) as http:
        if args.command == "configure":
            result = await configure(http)
        elif args.command == "create-index":
            result = await create_index(es, args.target, args.embedding_profile)
        elif args.command in ("backfill", "resume"):
            result = await backfill(args.target, args.run_id, args.batch_size)
        elif args.command == "verify":
            result = await verify(es, args.target)
        elif args.command == "activate":
            result = await activate(es, args.target)
        elif args.command == "retry":
            def retry(db):
                for model in (SearchOutbox, SearchEmbeddingJob):
                    db.query(model).filter(model.status == "dead").update(dict(status="pending", attempts=0, available_at=datetime.utcnow()))
                return {"requeued": True}
            result = await run_db_txn(retry)
        else:
            result = await run_db_txn(status)
        print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["configure", "create-index", "backfill", "resume", "verify", "activate", "status", "retry"])
    parser.add_argument("--target")
    parser.add_argument("--embedding-profile")
    parser.add_argument("--run-id")
    parser.add_argument("--batch-size", type=int, choices=range(1, 201), default=100)
    args = parser.parse_args()
    if args.command in ("create-index", "backfill", "verify", "activate") and not args.target:
        parser.error("--target is required")
    if args.command == "resume" and not args.run_id:
        parser.error("--run-id is required")
    asyncio.run(main(args))
