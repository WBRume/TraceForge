"""Bounded, equal-weight Python reciprocal rank fusion.

Each leg contributes 1 / (60 + one-based rank). Scores from different engines
are never normalized or compared. At most 400 parent entities enter fusion.
"""

import asyncio

from app.domains.search.es import search_body
from app.domains.search.storage import partitioned, physical_indices


def fuse_rankings(lexical, semantic, *, rank_constant=60, window=200):
    if rank_constant < 1 or not 1 <= window <= 200:
        raise ValueError("SEARCH_INVALID_RRF_WINDOW")
    scores, hits, best_ranks = {}, {}, {}
    for results in (lexical, semantic):
        seen = set()
        for rank, hit in enumerate(results[:window], 1):
            identity = hit["_id"]
            if identity in seen:
                continue
            seen.add(identity)
            scores[identity] = scores.get(identity, 0.0) + 1.0 / (rank_constant + rank)
            best_ranks[identity] = min(best_ranks.get(identity, rank), rank)
            if identity not in hits:
                hits[identity] = dict(hit)
            if hit.get("inner_hits"):
                hits[identity]["inner_hits"] = hit["inner_hits"]
    ranking = sorted(scores, key=lambda identity: (-scores[identity], best_ranks[identity], identity))[:window]
    return [hits[identity] for identity in ranking]


def checked_hits(result):
    if result.get("timed_out") or result.get("_shards", {}).get("failed", 0):
        raise RuntimeError("SEARCH_INCOMPLETE")
    return result["hits"]["hits"]


async def hybrid_search(es, index, query, filters, vector, profile_id):
    # One short PIT for both legs avoids mixing source versions during fusion.
    # The final ranking is then stored in Redis; the PIT is not a pagination session.
    pit = await es.open_point_in_time(index=index, keep_alive="30s")
    pit_id = pit["id"]
    try:
        bodies = [search_body(query, filters), search_body(query, filters, vector, profile_id)]
        for body in bodies:
            body["pit"] = {"id": pit_id, "keep_alive": "30s"}
        async with asyncio.TaskGroup() as group:
            lexical = group.create_task(es.search(body=bodies[0]))
            semantic = group.create_task(es.search(body=bodies[1]))
        return fuse_rankings(checked_hits(lexical.result()), checked_hits(semantic.result()))
    finally:
        # Cleanup must neither hide a retrieval failure nor swallow cancellation.
        try:
            await es.close_point_in_time(id=pit_id)
        except Exception:
            pass


async def search_target(es, target, query, filters, *, kind="all", vector=None, profile_id=None):
    if not partitioned(target):
        if vector is not None:
            return await hybrid_search(es, target["physical_index"], query, filters, vector, profile_id)
        return checked_hits(await es.search(index=target["physical_index"], body=search_body(query, filters)))

    indices = physical_indices(target, kind)
    pit = await es.open_point_in_time(index=indices, keep_alive="30s")
    try:
        bodies = [search_body(query, [*filters, {"term": {"_index": index}}], highlight=False) for index in indices]
        if vector is not None:
            bodies.append(search_body(query, filters, vector, profile_id, highlight=False))
        for body in bodies:
            body["pit"] = {"id": pit["id"], "keep_alive": "30s"}
        async with asyncio.TaskGroup() as group:
            calls = [group.create_task(es.search(body=body)) for body in bodies]
        rankings = [checked_hits(call.result()) for call in calls]
        lexical = fuse_rankings(rankings[0], rankings[1]) if len(indices) == 2 else rankings[0]
        return fuse_rankings(lexical, rankings[-1]) if vector is not None else lexical
    finally:
        try:
            await es.close_point_in_time(id=pit["id"])
        except Exception:
            pass
