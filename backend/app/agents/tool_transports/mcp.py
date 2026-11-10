"""Private MCP 2026-07-28 HTTP endpoint; each request owns its metadata."""

import asyncio
import hmac
import json
import secrets
import socket
import uuid
from contextlib import asynccontextmanager, nullcontext

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from mcp.types import CallToolResult, DiscoverResult, ListToolsResult, Tool
from pydantic import ValidationError

from app.agents.tools import AgentToolContext
from app.protocols.schema import validate_schema

from .protocol import MCP_VERSION, CallParams, ListParams, ProtocolError, RpcRequest, logical_call_id, validate_request

SERVER_META = {"io.modelcontextprotocol/serverInfo": {"name": "traceforge-domain", "version": "2"}}


def tool_result(schema: dict, data, is_error: bool) -> CallToolResult:
    validate_schema(schema, data)
    if isinstance(data, dict) and (data.get("kind") == "error") != is_error:
        raise RuntimeError("Tool error flag does not match structured result")
    return CallToolResult(
        resultType="complete",
        isError=is_error,
        structuredContent=data,
        content=[{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
        _meta=SERVER_META,
    )


def error_response(error: ProtocolError, response_id):
    data = {"jsonrpc": "2.0", "error": {"code": error.code, "message": str(error)}}
    if response_id is not None:
        data["id"] = response_id
    if error.data is not None:
        data["error"]["data"] = error.data
    return JSONResponse(
        data, status_code=400 if error.code != -32603 else 500, headers={"Cache-Control": "private, no-store"}
    )


async def read_body(request: Request) -> bytearray:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 2_000_000:
            raise HTTPException(413, "Tool input too large")
    return body


async def handle_request(request: Request, invoke):
    if request.headers.get("origin"):
        raise HTTPException(403, "Browser origins are not permitted")
    body = await read_body(request)
    response_id = None
    try:
        raw = json.loads(body)
        if isinstance(raw, dict) and type(raw.get("id")) in (str, int):
            response_id = raw["id"]
        message = RpcRequest.model_validate(raw)
        validate_request(message, request.headers)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return error_response(ProtocolError(-32700, "Invalid JSON"), response_id)
    except ValidationError:
        return error_response(ProtocolError(-32600, "Invalid request envelope or metadata"), response_id)
    except ProtocolError as exc:
        return error_response(exc, response_id)
    return await respond(message, invoke)


async def respond(message: RpcRequest, invoke):
    from app.core.logging import get_logger

    logger = get_logger(__name__, category="agent")
    try:
        result = await invoke(message)
        value = (
            result.model_dump(mode="json", by_alias=True, exclude_none=True)
            if result
            else {"resultType": "complete", "_meta": SERVER_META}
        )
        if isinstance(result, CallToolResult):
            value["structuredContent"] = result.structured_content
        logger.info(
            "MCP {} method={} tool={} result_type={} tool_error={}",
            MCP_VERSION,
            message.method,
            message.params.get("name", ""),
            value["resultType"],
            value.get("isError"),
        )
        return JSONResponse(
            {"jsonrpc": "2.0", "id": message.id, "result": value}, headers={"Cache-Control": "private, no-store"}
        )
    except HTTPException:
        raise
    except ValidationError:
        return error_response(ProtocolError(-32602, "Invalid request parameters"), message.id)
    except ProtocolError as exc:
        return error_response(exc, message.id)
    except Exception as exc:
        diagnostic_id = uuid.uuid4().hex
        logger.error("MCP contract failure {} {} {}", diagnostic_id, message.method, type(exc).__name__)
        return error_response(
            ProtocolError(-32603, "Tool contract or execution failure", {"diagnosticId": diagnostic_id}), message.id
        )


async def dispatch(tools: AgentToolContext, message: RpcRequest):
    ensure_active = getattr(tools, "ensure_active", None)
    if ensure_active and message.method != "tools/call":
        ensure_active()
    if message.method in {"server/discover", "tools/list", "ping"}:
        ListParams.model_validate(message.params)
    if message.method == "server/discover":
        return DiscoverResult(supportedVersions=[MCP_VERSION], capabilities={"tools": {}}, _meta=SERVER_META)
    if message.method == "tools/list":
        return ListToolsResult(
            tools=[
                Tool(
                    name=tool.name,
                    description=tool.description,
                    inputSchema=tool.input_schema,
                    outputSchema=tool.output_schema,
                )
                for tool in tools.definitions
            ],
            cacheScope="private",
            ttlMs=0,
            _meta=SERVER_META,
        )
    if message.method == "ping":
        return None
    if message.method != "tools/call":
        raise ProtocolError(-32601, "Method not supported")
    params = CallParams.model_validate(message.params)
    definition = next((tool for tool in tools.definitions if tool.name == params.name), None)
    if definition is None:
        raise ProtocolError(-32602, "Unknown tool")
    # Transport IDs pair responses only; logical IDs belong to this run.
    logical_id = logical_call_id(params.meta)
    reply = await tools.invoke(params.name, params.arguments, logical_id)
    return tool_result(definition.output_schema, reply.data, reply.is_error)


def create_app(tools: AgentToolContext, token: str) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/mcp")
    async def rpc(request: Request):
        if not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + token):
            raise HTTPException(401, "Invalid invocation credential")
        return await handle_request(request, lambda message: dispatch(tools, message))

    return app


class ToolServer(uvicorn.Server):
    def capture_signals(self):
        return nullcontext()


@asynccontextmanager
async def serve_tools(tools: AgentToolContext):
    token = secrets.token_urlsafe(32)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    app = create_app(tools, token)
    server = ToolServer(uvicorn.Config(app, log_config=None, access_log=False, lifespan="off"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError("Tool listener failed to start")
                await asyncio.sleep(0.01)
        yield {"type": "http", "url": f"http://127.0.0.1:{port}/mcp", "headers": {"Authorization": "Bearer " + token}}
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=5)
        finally:
            sock.close()
