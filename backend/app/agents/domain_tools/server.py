"""Private, short-lived Streamable HTTP MCP endpoint on an ephemeral loopback port."""

import asyncio
import hmac
import secrets
import socket
from contextlib import asynccontextmanager, nullcontext
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .runtime import DomainToolRun


class RpcRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    jsonrpc: Literal["2.0"]
    id: str | int | None = None
    method: str
    params: dict = Field(default_factory=dict)


def create_app(run: DomainToolRun, token: str) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/mcp")
    async def rpc(request: Request):
        if request.headers.get("origin"):
            raise HTTPException(403, "Browser origins are not permitted")
        if not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + token):
            raise HTTPException(401, "Invalid invocation credential")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 2_000_000:
                raise HTTPException(413, "Tool input too large")
        try:
            message = RpcRequest.model_validate_json(body)
        except ValueError:
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
        if message.id is None:
            return Response(status_code=202)
        if message.method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "traceforge-domain", "version": "1"},
            }
        elif message.method == "ping":
            result = {}
        elif message.method == "tools/list":
            from .workspace import READ_TOOL

            result = {"tools": [READ_TOOL, run.tool.schema()]}
        elif message.method == "tools/call":
            result = await run.invoke(
                message.params.get("name", ""), message.params.get("arguments", {}), str(message.id)
            )
        else:
            return {"jsonrpc": "2.0", "id": message.id, "error": {"code": -32601, "message": "Method not found"}}
        return {"jsonrpc": "2.0", "id": message.id, "result": result}

    return app


class ToolServer(uvicorn.Server):
    def capture_signals(self):
        # The application owns signals, not a per-invocation listener.
        return nullcontext()


@asynccontextmanager
async def serve_tools(run: DomainToolRun):
    token = secrets.token_urlsafe(32)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = ToolServer(uvicorn.Config(create_app(run, token), log_config=None, access_log=False, lifespan="off"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError("Domain tool listener failed to start")
                await asyncio.sleep(0.01)
        yield {"type": "http", "url": f"http://127.0.0.1:{port}/mcp", "headers": {"Authorization": "Bearer " + token}}
    finally:
        run.close()
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=5)
        finally:
            sock.close()
