"""Playbook recall through the same lexical/vector index used by global search."""

import asyncio
from functools import partial

from fastapi import HTTPException

from app.core.feature_settings import feature_settings as settings
from app.core.offload import run_db_txn
from app.domains.search import sqlite_index
from app.domains.search.embedding import EmbeddingError, embed
from app.domains.search.es import scope_filters, search_body
from app.domains.search.models import SearchDocumentState
from app.domains.search.projection import build_search_projection
from app.domains.search.rrf import checked_hits, hybrid_search
from app.domains.search.service import configuration

from .models import PlaybookSpec
from .service import serialize_spec


def _browse_latest_playbooks(db, *, ws_id):
    rows = (
        db.query(PlaybookSpec)
        .filter_by(workspace_id=ws_id)
        .order_by(PlaybookSpec.created_at.desc(), PlaybookSpec.id.desc())
        .all()
    )
    seen, items = set(), []
    for row in rows:
        if row.spec_key not in seen:
            seen.add(row.spec_key)
            items.append({**serialize_spec(row), "reasons": [], "score": 0})
    return items


def _hydrate_playbook_hits(db, *, ws_id, hits):
    from sqlalchemy import and_, or_
    from sqlalchemy.orm import aliased

    newer = aliased(PlaybookSpec)
    superseded = (
        db.query(newer.id)
        .filter(
            newer.workspace_id == PlaybookSpec.workspace_id,
            newer.spec_key == PlaybookSpec.spec_key,
            or_(
                newer.created_at > PlaybookSpec.created_at,
                and_(newer.created_at == PlaybookSpec.created_at, newer.id > PlaybookSpec.id),
            ),
        )
        .exists()
    )
    ids = [h["_source"]["entity_key"].split(":", 1)[1] for h in hits]
    rows = {
        r.id: r
        for r in db.query(PlaybookSpec).filter(
            PlaybookSpec.workspace_id == ws_id, PlaybookSpec.id.in_(ids), ~superseded
        )
    }
    states = {
        s.entity_key: s
        for s in db.query(SearchDocumentState).filter(
            SearchDocumentState.entity_key.in_([h["_source"]["entity_key"] for h in hits])
        )
    }
    seen, items = set(), []
    for hit in hits:
        candidate = hit["_source"]
        row = rows.get(candidate["entity_key"].split(":", 1)[1])
        state = states.get(candidate["entity_key"])
        if (
            not row
            or row.spec_key in seen
            or not state
            or state.deleted
            or state.source_version != candidate.get("source_version")
            or state.projection_hash != candidate.get("projection_hash")
        ):
            continue
        if build_search_projection(row, "playbook")["projection_hash"] != state.projection_hash:
            continue
        seen.add(row.spec_key)
        items.append(
            {
                **serialize_spec(row),
                "reasons": [],
                "score": hit.get("_score", 0),
                "usage": "ANALYSIS_GUIDE",
                "requires_environment_probe": False,
            }
        )
    return items


async def recommend(es, http, ws_id, text, keyword=""):
    query = (keyword.strip() or text.strip())[:200]
    if not query:
        browse = partial(_browse_latest_playbooks, ws_id=ws_id)

        return await run_db_txn(browse), "browse"
    target, profile = await run_db_txn(configuration)
    if not target and settings.SEARCH_BACKEND == "elasticsearch":
        raise HTTPException(status_code=503, detail={"code": "SEARCH_UNAVAILABLE"})
    mode = "sqlite_bm25"
    hits = None
    if target and not sqlite_index.local_only():
        filters = scope_filters([ws_id], kind="playbook")
        try:
            vector = None
            if profile and target["verified"]:
                try:
                    from app.domains.search.budget import reserve

                    await reserve(profile["id"], query=True)
                    vector = (await embed(http, profile, [query], query=True))[0]
                except EmbeddingError:
                    pass
            if vector:
                hits = await hybrid_search(es, target["physical_index"], query, filters, vector, profile["id"])
                mode = "hybrid"
            else:
                hits = checked_hits(await es.search(index=target["physical_index"], body=search_body(query, filters)))
                mode = "bm25"
        except Exception as exc:
            if settings.SEARCH_BACKEND == "elasticsearch":
                raise HTTPException(status_code=503, detail={"code": "SEARCH_UNAVAILABLE"}) from exc
    if hits is None:
        hits = await asyncio.to_thread(sqlite_index.search, query, [ws_id], kind="playbook")

    hydrate = partial(_hydrate_playbook_hits, ws_id=ws_id, hits=hits)

    return await run_db_txn(hydrate), mode
