"""Provision dynamic search settings through the existing immutable index lifecycle."""

from datetime import datetime

from app.core.offload import run_db_txn
from app.domains.search.embedding import embed, encrypt_key
from app.domains.search.models import SearchBackfillRun, SearchEmbeddingJob, SearchEmbeddingProfile, SearchIndexTarget
from app.domains.search.projection import digest
from app.domains.search.worker import dto


def bind_existing_targets(db, url):
    db.query(SearchIndexTarget).filter(SearchIndexTarget.connection_fingerprint.is_(None)).update(
        {"connection_fingerprint": digest(url)}
    )


async def prepare_search(app, values):
    from app.domains.search.es import index_mapping

    if not values["enabled"] or values["backend"] == "sqlite" or not values["es_url"]:
        return None
    key = values["embedding_api_key"]
    profile_id = None
    if key:
        profile = {
            "endpoint": values["embedding_endpoint"],
            "model_id": values["embedding_model"],
            "encrypted_api_key": encrypt_key(key),
        }
        vectors = await embed(app.state.search_http, profile, ["TraceForge 服务连接测试"], runtime_credentials=False)
        profile["dimension"] = len(vectors[0])
        profile["fingerprint"] = digest(
            [profile["endpoint"], profile["model_id"], profile["dimension"], 1600, 160, "", ""]
        )

        def publish(db):
            current = (
                db.query(SearchEmbeddingProfile)
                .join(SearchIndexTarget, SearchIndexTarget.embedding_profile_id == SearchEmbeddingProfile.id)
                .filter(
                    SearchIndexTarget.status == "active",
                    SearchEmbeddingProfile.endpoint == profile["endpoint"],
                    SearchEmbeddingProfile.model_id == profile["model_id"],
                    SearchEmbeddingProfile.dimension == profile["dimension"],
                )
                .first()
            )
            if not current:
                current = db.query(SearchEmbeddingProfile).filter_by(fingerprint=profile["fingerprint"]).first()
            if current:
                current.last_error_code = None
                current.revision += 1
                db.query(SearchEmbeddingJob).filter_by(profile_id=current.id, status="dead").update(
                    {"status": "pending", "attempts": 0, "available_at": datetime.utcnow()}
                )
            else:
                current = SearchEmbeddingProfile(**profile, status="tested")
                db.add(current)
                db.flush()
            return dto(current)

        profile = await run_db_txn(publish)
        profile_id = profile["id"]
    else:
        profile = None
    # Include the server binding: an index on another cluster is a different target.
    identity = digest([values["es_url"], profile["fingerprint"] if profile else "lexical"])
    name = "traceforge-search-runtime-" + identity[:32]
    exists = bool(await app.state.search_es.indices.exists(index=name))
    if not exists:
        await app.state.search_es.indices.create(
            index=name, body=index_mapping(profile["dimension"] if profile else None)
        )

    def enqueue(db):
        target = db.query(SearchIndexTarget).filter_by(physical_index=name).first()
        if not target:
            target = SearchIndexTarget(
                physical_index=name,
                connection_fingerprint=digest(values["es_url"]),
                embedding_profile_id=profile_id,
                dimension=profile["dimension"] if profile else None,
            )
            db.add(target)
            db.flush()
        if not exists:
            target.verified = False
            target.status = "building"
            db.query(SearchEmbeddingJob).filter_by(target_id=target.target_id).update(
                {"status": "pending", "attempts": 0, "available_at": datetime.utcnow()}
            )
        backfill = db.query(SearchBackfillRun).filter_by(target_id=target.target_id).first()
        if not backfill:
            db.add(SearchBackfillRun(target_id=target.target_id, boundary=datetime.utcnow()))
        elif not exists:
            backfill.stage, backfill.cursor, backfill.status = "task", None, "pending"
            backfill.boundary = datetime.utcnow()
        db.query(SearchEmbeddingJob).filter_by(target_id=target.target_id, status="obsolete").update(
            {"status": "pending", "attempts": 0, "available_at": datetime.utcnow()}
        )
        return name

    return await run_db_txn(enqueue)


async def activate_when_ready(app, name):
    from app.domains.search.cli import activate, verify

    def readiness(db):
        target = db.query(SearchIndexTarget).filter_by(physical_index=name).first()
        if not target or target.status == "active":
            return False
        backfill = db.query(SearchBackfillRun).filter_by(target_id=target.target_id, status="done").first()
        return bool(backfill)

    if await run_db_txn(readiness):
        result = await verify(app.state.search_es, name)
        if result["verified"]:
            await activate(app.state.search_es, name)
