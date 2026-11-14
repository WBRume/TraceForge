"""Maintain and query the PostgreSQL search projection."""

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import cast, delete, func, literal_column, or_, select, text
from sqlalchemy.dialects.postgresql import insert

from app.core.feature_settings import feature_settings as settings
from app.domains.search.embedding import decrypt_key, encrypt_key
from app.domains.search.embedding_protocols import EmbeddingError, profile_fingerprint
from app.domains.search.models import (
    SearchBackfillRun,
    SearchDocumentState,
    SearchEmbeddingJob,
    SearchEmbeddingProfile,
    SearchOutbox,
)
from app.domains.search.postgres_schema import EMBEDDING_DIMENSION, documents, passages
from app.domains.search.relevance import minimum_semantic_similarity
from app.domains.search.rrf import fuse_rankings
from app.domains.search.storage import SCHEMA_VERSION

TARGET_ID = "postgresql"
_FTS_CONFIG = literal_column("'public.jiebacfg'::regconfig")
_HIT_FIELDS = ("entity_key", "kind", "source_version", "projection_hash", "workspace_id", "task_id", "message_id")
_MAX_CONTENT_CHARS = 80_000


def es_enabled(url=None, backend=None):
    backend = settings.SEARCH_BACKEND if backend is None else backend
    url = settings.SEARCH_ES_URL if url is None else url
    return backend == "elasticsearch" or backend == "auto" and bool(url.strip())


def embedding_settings():
    data = {
        "endpoint": settings.SEARCH_EMBEDDING_ENDPOINT.rstrip("/"),
        "model_id": settings.SEARCH_EMBEDDING_MODEL,
        "protocol": settings.SEARCH_EMBEDDING_PROTOCOL,
        "dimension": EMBEDDING_DIMENSION,
    }
    fingerprint = profile_fingerprint(data)
    return data | {"fingerprint": fingerprint, "id": str(uuid5(NAMESPACE_URL, f"traceforge:postgres:{fingerprint}"))}


def ensure_backfill(db):
    """Register a restartable backfill when the lexical index or vector space is new."""
    key = settings.SEARCH_EMBEDDING_API_KEY.strip()
    data = embedding_settings() if key else None
    if data:
        profile = db.query(SearchEmbeddingProfile).filter_by(id=data["id"]).with_for_update().first()
        if not profile:
            statement = insert(SearchEmbeddingProfile).values(
                **data, encrypted_api_key=encrypt_key(key), status="tested"
            )
            db.execute(statement.on_conflict_do_nothing(index_elements=["id"]))
        else:
            try:
                current_key = decrypt_key(profile.encrypted_api_key)
            except EmbeddingError:
                current_key = ""
            if key != current_key:
                profile.encrypted_api_key = encrypt_key(key)
                profile.last_error_code = None
                db.query(SearchEmbeddingJob).filter_by(
                    target_id=TARGET_ID, profile_id=profile.id, status="dead"
                ).update({"status": "pending", "attempts": 0, "available_at": datetime.utcnow()})
    backfill_id = data["id"] if data else str(uuid5(NAMESPACE_URL, "traceforge:postgres:lexical"))
    backfill = db.query(SearchBackfillRun).filter_by(id=backfill_id).with_for_update().first()
    if backfill and data and backfill.status == "done":
        job = SearchEmbeddingJob
        c = documents.c
        missing = db.execute(
            select(c.entity_key)
            .where(
                ~c.deleted,
                ~select(job.id)
                .where(
                    job.target_id == TARGET_ID,
                    job.profile_id == backfill_id,
                    job.entity_key == c.entity_key,
                    job.source_version == c.source_version,
                    job.status != "obsolete",
                )
                .exists(),
            )
            .limit(1)
        ).scalar_one_or_none()
        if missing:
            backfill.stage, backfill.cursor, backfill.status = "task", None, "pending"
            backfill.boundary, backfill.finished_at = datetime.utcnow(), None
            db.query(job).filter_by(target_id=TARGET_ID, profile_id=backfill_id, status="obsolete").delete()
    if backfill:
        return
    statement = insert(SearchBackfillRun).values(id=backfill_id, target_id=TARGET_ID)
    db.execute(statement.on_conflict_do_nothing(index_elements=["id"]))


def active_profile(db):
    if not settings.SEARCH_EMBEDDING_API_KEY.strip():
        return None
    return db.get(SearchEmbeddingProfile, embedding_settings()["id"])


def configuration(db):
    profile = active_profile(db)
    backfill_done = db.query(SearchBackfillRun.id).filter_by(target_id=TARGET_ID, status="done").first() is not None
    # ES delivery may still have pending jobs after PostgreSQL has applied a version.
    c = documents.c
    state = SearchDocumentState.__table__.c
    lexical_pending = not backfill_done
    if backfill_done and db.query(SearchOutbox.id).filter(SearchOutbox.status != "done").first():
        lexical_pending = (
            db.execute(
                select(state.entity_key)
                .select_from(SearchDocumentState.__table__.outerjoin(documents, state.entity_key == c.entity_key))
                .where(or_(c.entity_key.is_(None), c.source_version != state.source_version))
                .limit(1)
            ).first()
            is not None
        )
    pending = False
    if profile:
        pending = (
            db.query(SearchBackfillRun.id).filter_by(id=profile.id, status="done").first() is None
            or db.query(SearchEmbeddingJob.id)
            .filter(
                SearchEmbeddingJob.target_id == TARGET_ID,
                SearchEmbeddingJob.profile_id == profile.id,
                SearchEmbeddingJob.status.notin_(["done", "obsolete"]),
            )
            .first()
            is not None
        )
    semantic_ready = bool(profile and profile.last_error_code is None)
    target = {
        "target_id": TARGET_ID,
        "schema_version": SCHEMA_VERSION,
        "verified": not lexical_pending,
        "embedding_profile_id": profile.id if semantic_ready else None,
        "semantic_indexing_state": (
            "unavailable" if not semantic_ready else "partial" if pending or lexical_pending else "ready"
        ),
    }
    profile_data = (
        {column.name: getattr(profile, column.name) for column in profile.__table__.columns} if semantic_ready else None
    )
    return target, profile_data


def _utc_naive(stamp):
    value = datetime.fromisoformat(stamp) if isinstance(stamp, str) else stamp
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value and value.tzinfo else value


def write(db, projections):
    """Write monotonic projections and remove superseded vectors in the same transaction."""
    for doc in projections:
        values = {field: doc.get(field) for field in (*_HIT_FIELDS, "role", "deleted")}
        values.update(
            created_at=_utc_naive(doc.get("created_at")),
            title=doc.get("title", "").replace("\x00", ""),
            content=doc.get("content_text", "")[:_MAX_CONTENT_CHARS].replace("\x00", ""),
        )
        statement = insert(documents).values(**values)
        updated = db.execute(
            statement.on_conflict_do_update(
                index_elements=[documents.c.entity_key],
                set_=values,
                where=documents.c.source_version < statement.excluded.source_version,
            ).returning(documents.c.entity_key)
        ).scalar_one_or_none()
        if updated:
            db.execute(delete(passages).where(passages.c.entity_key == updated))


def write_passages(db, doc, profile, chunks, vectors):
    """Publish only against the exact document version that was embedded."""
    c = documents.c
    current = db.execute(
        select(c.entity_key)
        .where(
            c.entity_key == doc["entity_key"],
            c.source_version == doc["source_version"],
            ~c.deleted,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if not current:
        return False
    statement = insert(passages).values(
        [
            {
                "entity_key": current,
                "profile_id": profile["id"],
                "chunk_no": chunk["chunk_no"],
                "start_char": chunk["start_char"],
                "embedding": vector,
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
    )
    db.execute(statement.on_conflict_do_nothing())
    return True


def search(
    db, query, scope, *, kind="all", task_id=None, role=None, date_from=None, date_to=None, vector=None, profile_id=None
):
    """Rank authorized lexical matches and fuse with nearest distinct passages."""
    if not scope:
        return []
    db.execute(text("SET LOCAL statement_timeout = '850ms'"))
    c = documents.c
    fields = [c[field] for field in _HIT_FIELDS]
    filters = [~c.deleted, c.workspace_id.in_(scope)]
    if kind != "all":
        filters.append(c.kind == kind)
    if task_id:
        filters.append(c.task_id == task_id)
    if role:
        filters.append(or_(c.kind == "task", c.role == role))
    if date_from:
        filters.append(c.created_at >= _utc_naive(date_from))
    if date_to:
        filters.append(c.created_at < _utc_naive(date_to))

    terms = func.plainto_tsquery(_FTS_CONFIG, query.replace("\x00", ""))
    rank = func.ts_rank_cd(c.terms, terms)
    lexical = [
        {"_id": row.entity_key, "_source": dict(row)}
        for row in db.execute(
            select(*fields).where(*filters, c.terms.bool_op("@@")(terms)).order_by(rank.desc(), c.entity_key).limit(200)
        ).mappings()
    ]
    if vector is None:
        return lexical

    semantic = _semantic_hits(db, fields, filters, vector, profile_id, minimum_semantic_similarity(query))
    return fuse_rankings(lexical, semantic)


def _semantic_hits(db, fields, filters, vector, profile_id, minimum_similarity):
    db.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
    c = documents.c
    p = passages.c
    distance = p.embedding.cosine_distance(cast(vector, p.embedding.type)).label("distance")
    # Keep the distance filter outside the bounded HNSW scan.
    candidates = (
        select(*fields, p.start_char, distance)
        .select_from(passages.join(documents, p.entity_key == c.entity_key))
        .where(*filters, p.profile_id == profile_id)
        .order_by(distance)
        .limit(2000)
        .cte("nearest_passages")
        .prefix_with("MATERIALIZED")
    )
    nearest = db.execute(
        select(*(candidates.c[name] for name in _HIT_FIELDS), candidates.c.start_char)
        .where(candidates.c.distance <= 1 - minimum_similarity)
        .order_by(candidates.c.distance, candidates.c.entity_key, candidates.c.start_char)
    ).mappings()
    semantic = {}
    for row in nearest:
        source = dict(row)
        offset = source.pop("start_char")
        semantic.setdefault(
            row.entity_key,
            {
                "_id": row.entity_key,
                "_source": source,
                "inner_hits": {
                    "passages": {"hits": {"hits": [{"fields": {"semantic_passages.start_char": [offset]}}]}}
                },
            },
        )
        if len(semantic) == 200:
            break
    return list(semantic.values())
