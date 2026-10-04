"""Run the complete HTTP application with process-local acceptance thresholds.

The stop file asks uvicorn to run its normal graceful shutdown / app lifespan.
MySQL, Redis, auth, HTTP routes, dispatchers and finalizers are the real ones.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path


async def serve(root: Path, hard_seconds: int):
    os.environ.update(
        AGENT_MAX_RUNTIME_HOURS=str(hard_seconds / 3600),
        AGENT_IDLE_TIMEOUT_MINUTES="0.1",
        OPENCODE_RECONCILE_INTERVAL_SECONDS="1",
        AI_JOB_HEARTBEAT_SECONDS="1",
        AI_JOB_LEASE_SECONDS="5",
        AI_JOB_REAPER_INTERVAL_SECONDS="1",
        LOG_DIR=str(root / "logs"),
        AI_SESSION_LOG_DIR=str(root / "ai-logs"),
    )
    import httpx
    import uvicorn
    from app.main import app
    from app.agents.adapters import register_all
    from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
    from app.agents.registry import AGENT_BACKENDS
    from tests.live_opencode.transport import LiveTransport, record

    log = root / f"http-{os.getpid()}.jsonl"

    class ObservedAdapter(OpenCodeAdapter):
        async def _ensure_client(self):
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    auth=self._auth, timeout=30, trust_env=False,
                    transport=LiveTransport(root, log),
                )
            return self._client

    register_all()
    AGENT_BACKENDS["opencode"] = ObservedAdapter
    # Uvicorn INFO WebSocket access logs include the token query parameter.
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="warning"))

    async def watch_stop():
        while not (root / f"stop-{os.getpid()}").exists():
            await asyncio.sleep(0.1)
        record(log, "graceful_shutdown_requested", pid=os.getpid())
        server.should_exit = True

    watcher = asyncio.create_task(watch_stop())
    try:
        record(log, "http_service_start", pid=os.getpid(), hard_seconds=hard_seconds)
        await server.serve()
        record(log, "http_service_stopped", pid=os.getpid())
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--hard-seconds", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(serve(args.root.resolve(), args.hard_seconds))
