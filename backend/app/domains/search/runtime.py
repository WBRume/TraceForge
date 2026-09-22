"""Backend-owned search consumers; durable jobs remain in MySQL across restarts."""
import asyncio
import logging

from app.config import settings
from app.domains.search.worker import run

logger = logging.getLogger(__name__)


class SearchRuntime:
    def __init__(self):
        self.stop_event = asyncio.Event()
        self.tasks: list[asyncio.Task] = []

    def start(self):
        if self.tasks or not settings.SEARCH_ENABLED or not settings.SEARCH_WORKERS_ENABLED:
            return
        self.stop_event.clear()
        from .sqlite_index import local_only
        kinds = ('search',) if local_only() else ('search', 'embedding')
        self.tasks = [asyncio.create_task(self._supervise(kind), name=f"search-{kind}-worker") for kind in kinds]
        self.tasks.append(asyncio.create_task(self._bootstrap(), name="search-sqlite-backfill"))
        logger.info("Search and embedding workers started inside backend")

    async def _bootstrap(self):
        from .sqlite_index import bootstrap
        while not self.stop_event.is_set():
            try:
                await bootstrap(self.stop_event)
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Local search backfill retry after %s", type(exc).__name__)
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=5)
                except TimeoutError:
                    pass

    async def _supervise(self, kind):
        while not self.stop_event.is_set():
            try:
                await run(kind, stop_event=self.stop_event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Driver exception text may contain connection credentials.
                logger.warning("Search worker %s restarting after %s", kind, type(exc).__name__)
            if not self.stop_event.is_set():
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=5)
                except TimeoutError:
                    pass

    async def stop(self, grace_seconds=15):
        self.stop_event.set()
        if not self.tasks:
            return
        try:
            _, pending = await asyncio.wait(self.tasks, timeout=grace_seconds)
            for task in pending:
                task.cancel()
            # Cancelled in-flight jobs are recovered by the durable lease expiry.
            await asyncio.gather(*self.tasks, return_exceptions=True)
        finally:
            self.tasks = []
        logger.info("Search workers stopped")
