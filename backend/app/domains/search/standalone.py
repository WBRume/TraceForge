"""Standalone consumers observe the same DB settings and rebuild connections on change."""

import asyncio
import logging

from sqlalchemy.exc import SQLAlchemyError

from app.core.feature_settings import feature_settings
from app.core.offload import run_db_txn
from app.domains.search import sqlite_index
from app.domains.search.worker import run
from app.domains.system_config.services.feature_config_service import environment_snapshot, fingerprint, read
from app.domains.system_config.services.feature_runtime import load_runtime

logger = logging.getLogger(__name__)
_generation = ""


async def load():
    global _generation
    try:
        overrides, _ = await run_db_txn(load_runtime)
        values = await run_db_txn(lambda db: read(db, "search")[0])
        published = environment_snapshot(overrides)
        published.update(
            SEARCH_EMBEDDING_ENDPOINT=values["embedding_endpoint"],
            SEARCH_EMBEDDING_MODEL=values["embedding_model"],
            SEARCH_EMBEDDING_API_KEY=values["embedding_api_key"],
        )
        feature_settings.replace(published)
        _generation = fingerprint(overrides.get("search", {}))
    except SQLAlchemyError:
        logger.warning("Feature store unavailable; retaining last effective worker configuration")
    return _generation


async def main(kind, once=False):
    while True:
        generation = await load()
        enabled = feature_settings.SEARCH_ENABLED and (kind != "embedding" or not sqlite_index.local_only())
        if not enabled:
            if once:
                return False
            await asyncio.sleep(2)
            continue
        if kind == "search":
            await sqlite_index.bootstrap(asyncio.Event())
        stop = asyncio.Event()
        consumer = asyncio.create_task(run(kind, once=once, stop_event=stop))
        try:
            while not consumer.done():
                await asyncio.wait({consumer}, timeout=2)
                if not consumer.done() and await load() != generation:
                    break
            if consumer.done():
                outcome = await consumer
                if once:
                    return outcome
        finally:
            stop.set()
            try:
                await asyncio.wait_for(asyncio.shield(consumer), timeout=5)
            except TimeoutError:
                consumer.cancel()
                await asyncio.gather(consumer, return_exceptions=True)
        if once:
            return False
        await asyncio.sleep(1)
