"""Fault injection around real HTTP connections; never synthesize provider data."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import httpx


def record(log_path: Path, kind: str, **values) -> None:
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": time.time(), "kind": kind, **values}, ensure_ascii=False) + "\n")


class LiveTransport(httpx.AsyncBaseTransport):
    def __init__(self, root: Path, log: Path, *, mute_session_events: bool = False):
        self.root, self.log = root, log
        self.mute = mute_session_events
        self.inner = httpx.AsyncHTTPTransport(retries=0)
        self.last_cut = ""

    async def handle_async_request(self, request):
        path = request.url.path
        details = {}
        if path.endswith("/prompt") and request.method == "POST":
            details["prompt_id"] = json.loads(request.content).get("id")
        record(self.log, "http", method=request.method, path=path, **details)
        response = await self.inner.handle_async_request(request)
        if path == "/api/event":
            record(self.log, "sse_open", status=response.status_code)
            response.stream = FaultStream(response.stream, self)
        return response

    async def aclose(self):
        await self.inner.aclose()


class FaultStream(httpx.AsyncByteStream):
    def __init__(self, upstream, owner):
        self.upstream, self.owner = upstream, owner

    async def wait_cut(self):
        while True:
            flag = self.owner.root / "cut-sse"
            if flag.exists():
                token = flag.read_text(encoding="utf-8")
                if token and token != self.owner.last_cut:
                    self.owner.last_cut = token
                    return token
            await asyncio.sleep(0.1)

    async def __aiter__(self):
        iterator = self.upstream.__aiter__()
        cut = asyncio.create_task(self.wait_cut())
        pending = None
        buffer = b""
        try:
            while True:
                pending = asyncio.create_task(anext(iterator))
                done, _ = await asyncio.wait({pending, cut}, return_when=asyncio.FIRST_COMPLETED)
                if cut in done:
                    record(self.owner.log, "sse_cut", token=cut.result())
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                    return  # Closing this upstream stream closes its actual HTTP connection.
                try:
                    chunk = pending.result()
                except StopAsyncIteration:
                    return
                if not self.owner.mute:
                    yield chunk
                    continue
                buffer += chunk
                while b"\n\n" in buffer:
                    frame, buffer = buffer.split(b"\n\n", 1)
                    kind = ""
                    for line in frame.splitlines():
                        if line.startswith(b"data:"):
                            data = json.loads(line[5:])
                            if isinstance(data, str):
                                data = json.loads(data)
                            kind = data.get("type", "")
                    if kind.startswith("server.") or not kind:
                        yield frame + b"\n\n"
                    else:
                        record(self.owner.log, "sse_drop", event_type=kind)
        finally:
            cut.cancel()
            if pending and not pending.done():
                pending.cancel()
            await asyncio.gather(cut, *([pending] if pending else []), return_exceptions=True)
            await self.upstream.aclose()

    async def aclose(self):
        await self.upstream.aclose()
