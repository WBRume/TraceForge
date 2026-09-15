"""Shared, separate query/document rate budgets; no unbounded local fallback."""
import asyncio
import time
from app.config import settings
from app.core.redis_client import get_redis_client
from app.domains.search.embedding import EmbeddingError

RESERVE = """
local used = tonumber(redis.call('GET', KEYS[1]) or '0')
if used >= tonumber(ARGV[1]) then return 0 end
redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], 2)
return 1
"""


async def reserve(profile_id, *, query=False):
    cap = settings.SEARCH_QUERY_RPS if query else settings.SEARCH_DOCUMENT_RPS
    lane = "query" if query else "document"
    for _ in range(20 if not query else 1):
        key = f"{settings.SEARCH_SESSION_NAMESPACE}:budget:{profile_id}:{lane}:{int(time.time())}"
        try:
            redis = await get_redis_client()
            accepted = await redis.eval(RESERVE, 1, key, cap)
        except Exception:
            raise EmbeddingError("EMBEDDING_BUDGET_UNAVAILABLE", True) from None
        if accepted:
            return
        if not query:
            await asyncio.sleep(0.1)
    raise EmbeddingError("EMBEDDING_BUDGET_EXCEEDED", True)
