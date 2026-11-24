"""DSH Web Host Agent backend（Server 模式）。

以 `dsh web --no-open --host 127.0.0.1 --port N` 启动的 DSH Web Host 暴露了
完整的 HTTP + WebSocket API。TraceForge 通过可选的 launch token/cookie 建立
同一浏览器认证会话后直接驱动：

- `POST /api/<method>`：JSON 信封 RPC（session.list / session.create / session.prompt /
  session.history / session.fork / session.cancel）
- `GET(ws) /api/events.mux`：全会话事件下行流（assistant chunk / tool call / usage）
- 冷会话在 prompt 时自动 `ctx.agents.resume`，天然支持跨进程多轮续会话

Web Host server 模式是 dsh 在 TraceForge 中的唯一接入方式（headless CLI 已移除），
支持 resume、工具事件、token usage、流式文本与多轮。
会话 fork 复用文件级实现（session_files），因为原生 session.fork 继承源会话
cwd，而评审线程需要落在自己的工作目录。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Any
from urllib.parse import quote

import httpx
import websockets

from app.agents.activity_watchdog import AgentActivityWatchdog
from app.agents.adapters.dsh.event_mapper import map_dsh_tool_result
from app.agents.adapters.dsh.text_events import DshTextEvents
from app.agents.contract import (
    AgentBackend,
    AgentCapabilities,
    AgentEventSink,
    AgentInputImage,
    AgentRunRequest,
    AgentRunResult,
    AgentStopResult,
    TokenUsage,
)
from app.agents.errors import (
    AgentError,
    AgentInteractionDeliveryUncertain,
    AgentSteeringClosedError,
    AgentSteeringRejectedError,
    AgentTimeoutError,
    SessionForkError,
)
from app.agents.events import AgentEvent
from app.agents.http_transport import agent_ssl_context
from app.agents.tool_activity import mcp_tool_fields, wire_event_time
from app.config import settings
from app.core.logging import get_logger

STEERING_REQUEST_PREFIX = "tf-steer-"
logger = get_logger(__name__, category="ai_session")


def _format_dsh_model(provider: Any, model: Any) -> str | None:
    """Build the canonical provider/model label from a DSH model selection."""
    provider_name = str(provider or "").strip()
    model_name = str(model or "").strip()
    if not model_name:
        return None
    return f"{provider_name}/{model_name}" if provider_name else model_name


def _map_assistant_message(raw_event: dict[str, Any], data: dict[str, Any]) -> AgentEvent | None:
    # web host 事件形状：data.message.{role,content[,usage]}（部分流式事件平铺在 data 上）
    msg = data.get("message") if isinstance(data.get("message"), dict) else data
    source = msg.get("source") if isinstance(msg.get("source"), dict) else {}
    model = _format_dsh_model(source.get("provider"), source.get("model")) if source.get("kind") == "model" else None
    blocks = msg.get("content") if isinstance(msg.get("content"), list) else []
    text = "\n".join(
        str(block.get("text") or "") for block in blocks if isinstance(block, dict) and block.get("type") == "text"
    ).strip()
    usage_raw = (
        msg.get("usage")
        if isinstance(msg.get("usage"), dict)
        else (data.get("usage") if isinstance(data.get("usage"), dict) else None)
    )
    usage: TokenUsage | None = None
    if usage_raw:
        usage = TokenUsage(
            input_tokens=usage_raw.get("inputTokens"),
            output_tokens=usage_raw.get("outputTokens"),
            cache_read_tokens=usage_raw.get("cacheReadTokens"),
            cache_creation_tokens=usage_raw.get("cacheWriteTokens"),
            total_tokens=None,
            raw=usage_raw,
        )
    if text:
        payload: dict[str, Any] = {
            "text": text,
            "usage": usage.__dict__ if usage else {},
            "provider": "dsh",
        }
        if model:
            payload["model"] = model
        return AgentEvent(
            type="text",
            payload=payload,
            provider="dsh",
            raw=raw_event,
        )
    if usage is not None:
        return AgentEvent(
            type="usage",
            payload={
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_read_tokens": usage.cache_read_tokens,
                "cache_creation_tokens": usage.cache_creation_tokens,
                "thinking_tokens": usage.raw.get("reasoningTokens"),
                "total_tokens": usage.raw.get("totalTokens"),
                "raw_usage": usage.raw,
                "provider": "dsh",
            },
            provider="dsh",
            raw=raw_event,
        )
    if model:
        return AgentEvent(
            type="model",
            payload={"model": model, "provider": "dsh", "source": "assistant/message"},
            provider="dsh",
            raw=raw_event,
        )
    return None


def map_dsh_event(raw_event: dict[str, Any]) -> AgentEvent | None:
    """DSH SessionEvent（web host 原生事件）→ 统一 AgentEvent。"""
    etype = str(raw_event.get("type") or "")
    data = raw_event.get("data") if isinstance(raw_event.get("data"), dict) else {}

    if etype == "request/header":
        # DSH records the effective model selected for this request before the
        # model response is produced.  TraceForge observes this event; it does
        # not query or configure the model itself.
        header = data.get("header") if isinstance(data.get("header"), dict) else {}
        config = header.get("config") if isinstance(header.get("config"), dict) else {}
        model = _format_dsh_model(config.get("provider"), config.get("model"))
        if not model:
            return None
        return AgentEvent(
            type="model",
            payload={"model": model, "provider": "dsh", "source": "request/header"},
            provider="dsh",
            raw=raw_event,
        )

    if etype == "assistant/message":
        return _map_assistant_message(raw_event, data)
    if etype in ("assistant/chunk",):
        raw_chunk = data.get("chunk")
        if isinstance(raw_chunk, dict):
            chunk_type = str(raw_chunk.get("type") or "").strip().lower()
            chunk_text = str(raw_chunk.get("text") or "")
            if chunk_type == "reasoning-delta" and chunk_text:
                return AgentEvent(
                    type="thinking",
                    payload={"text": chunk_text, "delta": chunk_text, "provider": "dsh"},
                    provider="dsh",
                    raw=raw_event,
                )
            if chunk_type == "text-delta" and chunk_text:
                return AgentEvent(
                    type="text_delta",
                    payload={"text": chunk_text, "delta": chunk_text, "provider": "dsh"},
                    provider="dsh",
                    raw=raw_event,
                )
            if chunk_type == "usage":
                usage_raw = raw_chunk.get("usage") if isinstance(raw_chunk.get("usage"), dict) else {}
                return AgentEvent(
                    type="usage",
                    payload={
                        "input_tokens": usage_raw.get("inputTokens"),
                        "output_tokens": usage_raw.get("outputTokens"),
                        "cache_read_tokens": usage_raw.get("cacheReadTokens"),
                        "cache_creation_tokens": usage_raw.get("cacheWriteTokens"),
                        "raw_usage": usage_raw,
                        "provider": "dsh",
                    },
                    provider="dsh",
                    raw=raw_event,
                )
            # block-start/block-end/finish are control frames.  Complete text
            # and termination are delivered by assistant/message + turn/end.
            return None
        chunk = str(data.get("text") or raw_chunk or "")
        if not chunk:
            return None
        return AgentEvent(
            type="text_delta",
            payload={"text": chunk, "delta": chunk, "provider": "dsh"},
            provider="dsh",
            raw=raw_event,
        )
    if etype == "tool/call":
        tool_name = str(data.get("name") or data.get("tool") or "")
        tool_input = data.get("arguments") or data.get("input") or {}
        tool_use_id = str(data.get("callId") or data.get("id") or "")
        if not tool_use_id or not tool_name:
            return None
        return AgentEvent(
            type="tool_use",
            payload={
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_use_id": tool_use_id,
                "provider": "dsh",
                **mcp_tool_fields(data.get("mcpServer") or data.get("mcp_server")),
            },
            provider="dsh",
            raw=raw_event,
            time=wire_event_time(raw_event.get("timestamp") or raw_event.get("time")),
        )
    if etype == "tool/result":
        return map_dsh_tool_result(raw_event, data)
    return None


class DshServerAdapter(AgentBackend):
    def get_runtime_control(self):
        from app.agents.runtime_control import runtime_control_for

        return runtime_control_for(self)

    name = "dsh"
    capabilities = AgentCapabilities(
        supports_resume=True,  # web host prompt 隐式 resume 冷会话
        supports_streaming_text=True,
        supports_tool_events=True,
        supports_tool_binding=False,
        supports_fork=True,  # 文件级 fork（session_files）
        supports_steering=True,
        supports_image_input=True,
        hitl_modes=["turn_based", "long_connection"],
        supports_usage=True,
        skill_layouts=["dsh"],
        preferred_mode="server",
        # 服务端执行：不创建本地受监管子进程，必须显式声明（doc 6.3）。
        execution_kind="REMOTE_SESSION",
    )

    def __init__(
        self,
        server_url: str = "http://127.0.0.1:3080",
        *,
        browser_token: str | None = None,
        browser_cookie: str | None = None,
        runtime_credentials: bool = False,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self._browser_token = browser_token
        self._browser_cookie = browser_cookie
        self._client: httpx.AsyncClient | None = None
        self._runtime_credentials = runtime_credentials
        self._retired_clients: list[httpx.AsyncClient] = []
        self._running = False
        self._session_id: str | None = None
        self._pending_asks: dict[str, dict[str, Any]] = {}
        self._gateway_protocol: bool | None = None
        self._prompt_request_id: str | None = None
        self._steering_open = False
        self._on_steering_delivered = None
        self._steering_lock = asyncio.Lock()
        self._pending_steering: set[str] = set()

    async def _ensure_client(self) -> httpx.AsyncClient:
        from app.core.feature_settings import feature_settings

        if self._runtime_credentials and self.server_url == feature_settings.DSH_SERVER_URL.rstrip("/"):
            credentials = (feature_settings.DSH_BROWSER_TOKEN, feature_settings.DSH_BROWSER_COOKIE)
            if credentials != (self._browser_token, self._browser_cookie):
                self._browser_token, self._browser_cookie = credentials
                if self._client is not None:
                    self._retired_clients.append(self._client)
                    self._client = None
        if self._client is None or self._client.is_closed:
            headers: dict[str, str] = {}
            cookie = (
                self._browser_cookie
                if self._browser_cookie is not None
                else str(os.environ.get("DSH_BROWSER_COOKIE") or settings.DSH_BROWSER_COOKIE or "").strip()
            )
            if cookie:
                headers["Cookie"] = cookie
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, read=None),
                headers=headers,
                follow_redirects=self._browser_token is None,
                trust_env=False,
                verify=agent_ssl_context(),
            )
            token = (
                self._browser_token
                if self._browser_token is not None
                else str(os.environ.get("DSH_BROWSER_TOKEN") or settings.DSH_BROWSER_TOKEN or "").strip()
            )
            if token and not cookie:
                response = await self._client.get(f"{self.server_url}/?token={quote(token, safe='')}")
                if response.status_code >= 400:
                    await self._client.aclose()
                    self._client = None
                    raise AgentError(f"DSH browser token exchange failed: HTTP {response.status_code}")
        return self._client

    async def _rpc(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        """调用 DSH Web Host RPC，兼容新旧路由及信封格式。

        新版 gateway 使用 ``/api/session/list`` 这类斜线路由，并把业务
        参数包装在 ``payload.args.request``（list 是 ``_request``）中；
        较早的 web host 使用 ``/api/session.list``，参数直接放在 payload。
        """
        client = await self._ensure_client()
        attempts: list[tuple[str, str, dict[str, Any], bool]] = []
        if self._gateway_protocol is not False:
            gateway_method = method.replace(".", "/")
            parameter_name = "_request" if method == "session.list" else "request"
            args = {} if method == "session.modelCatalog" else {parameter_name: payload}
            attempts.append(
                (
                    f"{self.server_url}/api/{gateway_method}",
                    gateway_method,
                    {"args": args},
                    True,
                )
            )
        if self._gateway_protocol is not True:
            attempts.append(
                (
                    f"{self.server_url}/api/{method}",
                    method,
                    payload,
                    False,
                )
            )

        last_response: httpx.Response | None = None
        for url, wire_method, wire_payload, is_gateway in attempts:
            response = await client.post(
                url,
                json={
                    "type": "client-request",
                    "rpcId": f"tf-{uuid.uuid4().hex[:12]}",
                    "method": wire_method,
                    "payload": wire_payload,
                },
            )
            last_response = response
            if response.status_code == 404 and len(attempts) > 1:
                continue
            if response.status_code != 200:
                raise AgentError(f"DSH server RPC {method} failed: HTTP {response.status_code}")
            envelope = response.json()
            result = envelope.get("result") if isinstance(envelope, dict) else None
            if not isinstance(result, dict):
                raise AgentError(f"DSH server RPC {method} returned malformed envelope")
            if not result.get("ok"):
                error = result.get("error") or {}
                code = str(error.get("code") or "unknown")
                raise AgentError(
                    f"DSH server RPC {method} failed: {code} {error.get('message', '')}",
                    failure_code=code if code == "session/attachment-invalid" else None,
                )
            self._gateway_protocol = is_gateway
            value = result.get("value")
            return value if isinstance(value, dict) else {}
        status = last_response.status_code if last_response is not None else "unknown"
        raise AgentError(f"DSH server RPC {method} failed: HTTP {status}")

    async def probe(self) -> str:
        await self._rpc("session.list", {})
        return f"DSH JSON-RPC server is reachable at {self.server_url}"

    async def native_session(self, session_id: str) -> dict | None:
        result = await self._rpc("session.list", {})
        items = result.get("items")
        if not isinstance(items, list) or any(not isinstance(row, dict) or not row.get("sessionId") for row in items):
            raise AgentError("DSH returned an invalid session list")
        session = next((row for row in items if row["sessionId"] == session_id), None)
        if session is None:
            return None
        if session.get("formatStatus") == "migration-required":
            return {"directory": session.get("cwd"), "readable": False}
        if self._gateway_protocol:
            page = await self._rpc(
                "session.events",
                {
                    "address": {"kind": "session", "sessionId": session_id},
                    "maxMessages": 1,
                },
            )
            if not isinstance(page.get("records"), list):
                raise AgentError("DSH did not return readable session history")
        return {"directory": session.get("cwd"), "created": session.get("createdAt")}

    async def session_running(self, session_id: str) -> bool:
        state = await self._rpc("session.state", {"sessionId": session_id})
        if not isinstance(state.get("running"), bool) or "queue" not in state:
            raise AgentError("DSH returned an invalid session state")
        return state["running"] or bool(state["queue"])

    async def execution_result(self, session_id: str, request_id: str) -> tuple[str, str] | None:
        page = await self._rpc(
            "session.events",
            {
                "address": {"kind": "session", "sessionId": session_id},
                "maxMessages": 50,
            },
        )
        owned = False
        text = []
        for record in page.get("records", []):
            event = record.get("event") or {}
            data = event.get("data") or {}
            if event.get("type") == "turn/start":
                owned = False
                text.clear()
            elif event.get("type") == "user/message" and (data.get("source") or {}).get("rpcId") == request_id:
                owned = True
            elif owned and event.get("type") == "assistant/message":
                text.extend(
                    part["text"]
                    for part in (data.get("message") or {}).get("content", [])
                    if part.get("type") == "text" and isinstance(part.get("text"), str)
                )
            elif owned and event.get("type") == "turn/end":
                return (data.get("reason") or {}).get("kind", "error"), "\n".join(text)
        return None

    async def model_catalog(self, *, project_path: str = "", session_id: str | None = None) -> dict:
        from app.agents.model_selection import model_option

        data = await self._rpc("session.modelCatalog", {})
        default = data.get("default") or {}
        options = [
            model_option(
                f"{group['id']}/{model['id']}",
                f"{model.get('name') or model['id']} · {group.get('name') or group['id']}",
            )
            for group in data.get("groups", [])
            for model in group.get("models", [])
        ]
        return {"options": options, "default_model": _format_dsh_model(default.get("provider"), default.get("model"))}

    async def _create_session(self, request: AgentRunRequest) -> str:
        payload = await self._rpc(
            "session.create",
            {"cwd": request.project_path or "."},
        )
        session_id = str(payload.get("sessionId") or "").strip()
        if not session_id:
            raise AgentError("DSH session.create returned no sessionId")
        return session_id

    async def _ensure_event_protocol(self) -> None:
        """Detect the DSH transport protocol without querying model state."""
        if self._gateway_protocol is None:
            try:
                await self._rpc("session.list", {})
            except AgentError:
                # Preserve the existing fallback for older hosts that do not
                # expose the discovery route.  This probe is only transport
                # negotiation; model information comes from DSH events.
                pass

    def _ws_url(self) -> str:
        path = "remote.mux" if self._gateway_protocol is True else "events.mux"
        return f"{self.server_url.replace('http://', 'ws://', 1)}/api/{path}"

    def _ws_headers(self) -> dict[str, str]:
        if self._client is None:
            return {}
        cookies = self._client.cookies
        values = [f"{key}={value}" for key, value in cookies.items()]
        return {"Cookie": "; ".join(values)} if values else {}

    async def _handle_interaction_request(self, method, payload, rpc_id, session_id, read_only, on_event):
        if method == "approval/requested":
            approval_id = str(payload.get("approvalId") or "")
            if read_only:
                await self._respond(
                    rpc_id,
                    {
                        "sessionId": session_id,
                        "approvalId": approval_id,
                        "outcome": "rejected",
                    },
                )
                return
            self._pending_asks[rpc_id] = {
                "kind": method,
                "session_id": session_id,
                "approval_id": approval_id,
            }
            prompt = str(payload.get("reason") or f"Allow DSH tool {payload.get('toolName') or 'unknown'}?")
            options = ["allowed-once", "rejected"]
        else:
            questions = payload.get("questions") if isinstance(payload.get("questions"), list) else []
            self._pending_asks[rpc_id] = {
                "kind": method,
                "session_id": session_id,
                "questions": questions,
            }
            first = questions[0] if questions and isinstance(questions[0], dict) else {}
            prompt = str(first.get("question") or first.get("prompt") or "DSH question")
            options = [
                str(item.get("label") or "")
                for item in (first.get("options") or [])
                if isinstance(item, dict) and str(item.get("label") or "")
            ]
        await on_event(
            AgentEvent(
                type="ask_user",
                payload={
                    "ask_user_id": rpc_id,
                    "prompt": prompt,
                    "question": prompt,
                    "kind": "approval" if method.startswith("approval") else "question",
                    "options": options,
                },
                provider="dsh",
            )
        )

    async def _emit_message_reasoning(self, event, on_event):
        # 若 DSH 只在完整 assistant/message 中给出 reasoning（未逐字
        # 推 reasoning-delta），这里补发一次完整 thinking。
        raw_data = event.get("data") if isinstance(event.get("data"), dict) else {}
        raw_msg = raw_data.get("message") if isinstance(raw_data.get("message"), dict) else raw_data
        blocks = raw_msg.get("content") if isinstance(raw_msg.get("content"), list) else []
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "reasoning":
                continue
            reasoning = str(block.get("text") or block.get("content") or "").strip()
            if reasoning:
                await on_event(
                    AgentEvent(
                        type="thinking",
                        payload={"text": reasoning, "provider": "dsh"},
                        provider="dsh",
                    )
                )

    async def _publish_session_event(self, event: dict, text_events: DshTextEvents, on_event: AgentEventSink) -> None:
        if event.get("type") == "turn/end":
            await self._close_steering()
        elif event.get("type") == "user/message":
            data = event.get("data") or {}
            request_id = str((data.get("source") or {}).get("rpcId") or "")
            if request_id and request_id == self._prompt_request_id:
                self._steering_open = True
            elif self._steering_open and request_id.startswith(STEERING_REQUEST_PREFIX) and self._on_steering_delivered:
                await self._on_steering_delivered(request_id.removeprefix(STEERING_REQUEST_PREFIX))
                self._pending_steering.discard(request_id)
        for unified in text_events.project(event, map_dsh_event(event)):
            await on_event(unified)

    @staticmethod
    async def _finalize_turn(event: dict, text_events: DshTextEvents, on_event: AgentEventSink) -> dict:
        reason = event.get("data", {}).get("reason")
        reason = reason if isinstance(reason, dict) else {}
        kind = str(reason.get("kind") or "completed")
        for unified in text_events.finish():
            await on_event(unified)
        body = "\n".join(text_events.completed)
        if kind == "error" and not body:
            error = reason.get("error")
            body = str(error.get("message") or "") if isinstance(error, dict) else ""
            body = body or "DSH stream error"
        return {"finish_reason": kind, "text": body, "usage_raw": None}

    async def _consume_events(
        self,
        session_id: str,
        on_event: AgentEventSink,
        *,
        read_only: bool = False,
        ready: asyncio.Event | None = None,
    ) -> dict[str, Any]:
        """消费 events.mux 下行流直到该会话 turn/end，返回收尾信息。

        下行帧信封：{type:"server-request", rpcId, method:<frame.type>, payload:<frame>}；
        会话事件帧 method=session/event，payload 含 sessionId 与原生 SessionEvent。
        """
        if self._gateway_protocol is True:
            return await self._consume_gateway_events(session_id, on_event, ready=ready)

        text_events = DshTextEvents()

        async with websockets.connect(
            self._ws_url(),
            additional_headers=self._ws_headers(),
            max_size=64 * 1024 * 1024,
        ) as ws:
            async for raw in ws:
                try:
                    frame = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(frame, dict) or frame.get("type") != "server-request":
                    continue
                method = str(frame.get("method") or "")
                payload = frame.get("payload") if isinstance(frame.get("payload"), dict) else {}
                rpc_id = str(frame.get("rpcId") or "")

                if method == "session/event":
                    if str(payload.get("sessionId") or "") != session_id:
                        continue
                    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
                    await self._publish_session_event(event, text_events, on_event)
                    etype = str(event.get("type") or "")
                    if etype == "assistant/message":
                        await self._emit_message_reasoning(event, on_event)
                    if etype == "turn/end":
                        return await self._finalize_turn(event, text_events, on_event)
                elif method in ("approval/requested", "question/requested"):
                    await self._handle_interaction_request(method, payload, rpc_id, session_id, read_only, on_event)
                elif method == "stream/error":
                    return {"finish_reason": "error", "text": str(payload.get("message") or "stream error")}
        return {"finish_reason": None, "text": "\n".join(text_events.completed)}

    async def _consume_gateway_events(
        self,
        session_id: str,
        on_event: AgentEventSink,
        *,
        ready: asyncio.Event | None = None,
    ) -> dict[str, Any]:
        """Consume the current DSH gateway ``session/follow`` stream.

        The current Web Host no longer exposes the legacy ``events.mux`` RPC
        stream.  Its gateway multiplexes logical streams over ``remote.mux``;
        the session follow stream starts with a snapshot and then emits event
        records.  The snapshot is deliberately ignored here because the prompt
        admission runs concurrently and only post-open events belong to this
        turn.
        """
        text_events = DshTextEvents()
        stream_id = f"tf-{uuid.uuid4().hex}"

        async with websockets.connect(
            self._ws_url(),
            additional_headers=self._ws_headers(),
            max_size=64 * 1024 * 1024,
        ) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "open",
                        "streamId": stream_id,
                        "endpoint": "session/follow",
                        "payload": {
                            "args": {
                                "request": {
                                    "address": {"kind": "session", "sessionId": session_id},
                                    "maxMessages": 50,
                                    "assistantStream": True,
                                },
                            },
                        },
                    }
                )
            )
            async for raw in ws:
                try:
                    frame = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(frame, dict) or frame.get("streamId") != stream_id:
                    continue
                frame_type = str(frame.get("type") or "")
                if frame_type == "error":
                    error = frame.get("error") if isinstance(frame.get("error"), dict) else {}
                    raise AgentError(
                        f"DSH session follow failed: {error.get('code', 'unknown')} {error.get('message', '')}"
                    )
                if frame_type == "end":
                    raise AgentError("DSH session stream ended before a terminal turn event")
                if frame_type != "item":
                    continue
                value = frame.get("value") if isinstance(frame.get("value"), dict) else {}
                if value.get("type") == "snapshot":
                    if ready is not None:
                        ready.set()
                    continue
                if value.get("type") == "assistant-stream":
                    event = text_events.live_event(value.get("frame") or {})
                else:
                    event = value.get("event") if value.get("type") == "event" else value
                if not isinstance(event, dict):
                    continue
                await self._publish_session_event(event, text_events, on_event)
                if event.get("type") == "turn/end":
                    return await self._finalize_turn(event, text_events, on_event)
        raise AgentError("DSH session stream disconnected before a terminal turn event")

    async def _emit_run_result(self, consumed, session_id, request, started_at, _tracked_event):
        finish_reason = consumed.get("finish_reason") or "completed"
        final_text = str(consumed.get("text") or "")
        success = finish_reason not in ("error", "aborted", "interrupted", "blocked")
        await _tracked_event(
            AgentEvent(
                type="result",
                payload={
                    "success": success,
                    "result": final_text,
                    "finish_reason": finish_reason,
                    "session_id": session_id,
                },
                provider="dsh",
            )
        )
        return AgentRunResult(
            run_id=request.run_id,
            session_id=session_id,
            success=success,
            finish_reason=finish_reason,
            result_text=final_text,
            duration_ms=int((time.monotonic() - started_at) * 1000),
            return_code=0 if success else 1,
            raw_trace=json.dumps(consumed, ensure_ascii=False, default=str),
        )

    async def _send_prompt(self, session_id, prompt_text, images: tuple[AgentInputImage, ...] = ()):
        from app.domains.ai.services.jobs.agent_dispatch import record_dsh_prompt

        request_id = f"tf-{uuid.uuid4().hex}"
        await record_dsh_prompt(session_id, request_id)
        self._prompt_request_id = request_id
        return await self._submit_prompt(session_id, request_id, prompt_text, mode="queue", images=images)

    async def _submit_prompt(
        self, session_id, request_id, prompt_text, *, mode, images: tuple[AgentInputImage, ...] = ()
    ):
        content = [{"type": "text", "text": prompt_text}] if prompt_text or not images else []
        content.extend(
            {"type": "image", "mediaType": image.media_type, "data": image.base64_data(), "name": image.filename}
            for image in images
        )
        return await self._rpc(
            "session.prompt",
            {
                "requestId": request_id,
                "sessionId": session_id,
                "mode": mode,
                "content": content,
            },
        )

    async def steer(self, message_id: str, content: str, *, images: tuple[AgentInputImage, ...] = ()) -> None:
        async with self._steering_lock:
            session_id = self._session_id
            if not self.accepts_steering() or not session_id:
                raise AgentSteeringClosedError("DSH is outside the active prompt")
            state = await self._rpc("session.state", {"sessionId": session_id})
            if not self.accepts_steering() or state.get("running") is not True:
                raise AgentSteeringClosedError("DSH is outside the active prompt")
            request_id = STEERING_REQUEST_PREFIX + message_id
            self._pending_steering.add(request_id)
            try:
                receipt = await self._submit_prompt(session_id, request_id, content, mode="steer", images=images)
            except AgentError as exc:
                if images and exc.failure_code == "session/attachment-invalid":
                    self._pending_steering.discard(request_id)
                    raise AgentSteeringRejectedError(str(exc)) from exc
                raise
            if receipt.get("accepted") is not True:
                raise AgentError("DSH steering acceptance could not be confirmed")

    def accepts_steering(self) -> bool:
        return self._running and self._steering_open and self._session_id is not None

    async def _close_steering(self) -> None:
        self._steering_open = False
        async with self._steering_lock:
            if not self._pending_steering or not self._session_id:
                return
            session_id = self._session_id
            try:
                async with asyncio.timeout(5):
                    await self._clear_late_steering(session_id)
            except (AgentError, httpx.HTTPError, TimeoutError, OSError) as exc:
                logger.warning(
                    "Could not clear pending DSH steering: session={}, error={}", session_id, type(exc).__name__
                )

    async def _clear_late_steering(self, session_id: str) -> None:
        """Clean up outstanding input if the native turn ended during admission."""
        state = await self._rpc("session.state", {"sessionId": session_id})
        for item in state.get("queue") or []:
            if item.get("rpcId") in self._pending_steering:
                await self._rpc(
                    "session.updateQueue",
                    {
                        "sessionId": session_id,
                        "itemId": item["id"],
                        "action": {"kind": "remove"},
                    },
                )
        if state.get("running"):
            page = await self._rpc(
                "session.events",
                {
                    "address": {"kind": "session", "sessionId": session_id},
                    "maxMessages": 50,
                },
            )
            # A steer on an idle DSH session can wake a native turn. Only stop
            # it if the first input of the still-open turn is our late request.
            first_request = None
            for record in reversed(page.get("records", [])):
                event = record.get("event") or {}
                if event.get("type") == "turn/end":
                    break
                if event.get("type") == "turn/start":
                    if first_request in self._pending_steering:
                        await self._stop_session(session_id)
                    break
                if event.get("type") == "user/message":
                    source = (event.get("data") or {}).get("source") or {}
                    if source.get("kind") != "runtime-context":
                        first_request = source.get("rpcId")

    async def _run_stream_turn(
        self, session_id: str, request: AgentRunRequest, watchdog: AgentActivityWatchdog, on_event: AgentEventSink
    ) -> dict:
        # Open the gateway subscription before admitting the prompt.
        read_only = str(request.permission_mode or "").strip().lower() in {"read-only", "readonly", "plan"}
        ready = asyncio.Event() if self._gateway_protocol is True else None
        consume_task = asyncio.create_task(self._consume_events(session_id, on_event, read_only=read_only, ready=ready))
        prompt = request.prompt
        if read_only:
            prompt = (
                "[只读会话约束] 只能分析、读取和总结；禁止创建、修改、删除文件，"
                "禁止执行会改变项目或外部系统状态的命令。\n\n" + prompt
            )

        async def send_when_ready() -> None:
            if ready is not None:
                await ready.wait()
            await self._send_prompt(session_id, prompt, request.images)

        def abort_on_prompt_failure(task: asyncio.Task) -> None:
            if not task.cancelled() and task.exception() is not None:
                consume_task.cancel()

        prompt_task = asyncio.create_task(send_when_ready())
        prompt_task.add_done_callback(abort_on_prompt_failure)
        try:
            result = await watchdog.wait(consume_task)
            await prompt_task
            return result
        except AgentTimeoutError:
            prompt_task.cancel()
            consume_task.cancel()
            from app.agents.contract import record_attempt_remote_stop

            record_attempt_remote_stop(await self.cancel(session_id=session_id))
            await asyncio.gather(prompt_task, consume_task, return_exceptions=True)
            raise
        except asyncio.CancelledError as exc:
            prompt_task.cancel()
            try:
                await prompt_task
            except AgentError as prompt_error:
                raise prompt_error from exc
            raise
        except Exception:
            prompt_task.cancel()
            await asyncio.gather(prompt_task, return_exceptions=True)
            raise

    async def run(self, request: AgentRunRequest, on_event: AgentEventSink) -> AgentRunResult:
        await self._ensure_client()
        self._running = True
        self._pending_asks.clear()
        self._prompt_request_id = None
        self._steering_open = False
        self._on_steering_delivered = request.on_steering_delivered
        self._pending_steering.clear()
        started_at = time.monotonic()
        watchdog = AgentActivityWatchdog(
            startup_timeout_seconds=request.startup_timeout_seconds,
            idle_timeout_seconds=request.idle_timeout_seconds,
            hard_timeout_seconds=request.timeout_seconds,
        )

        async def _tracked_event(event: AgentEvent) -> None:
            watchdog.mark(event.type)
            await on_event(event)

        session_id = str(request.session_id or "").strip()
        try:
            if not session_id:
                session_id = await self._create_session(request)
            self._session_id = session_id

            if request.model:
                provider, separator, model = request.model.partition("/")
                if not separator or not provider or not model:
                    raise AgentError("DSH model must be provider/model")
                await self._rpc("session.selectModel", {"sessionId": session_id, "provider": provider, "model": model})

            await self._ensure_event_protocol()
            policy = request.provider_options.get("execution_policy")
            if policy is not None and policy.get("enforcement") != "ADVISORY_GUARD":
                from app.agents.playbook_guard import apply_dsh_policy

                await apply_dsh_policy(request, session_id)

            await _tracked_event(
                AgentEvent(
                    type="session_started",
                    payload={
                        "provider_session_id": session_id,
                        "provider": "dsh",
                        "directory": request.project_path,
                    },
                    provider="dsh",
                )
            )

            consumed = await self._run_stream_turn(session_id, request, watchdog, _tracked_event)
            return await self._emit_run_result(consumed, session_id, request, started_at, _tracked_event)

        except AgentError:
            raise
        except Exception as exc:
            raise AgentError(f"DSH server run failed: {exc}") from exc
        finally:
            self._running = False
            self._steering_open = False
            self._on_steering_delivered = None

    async def interrupt(self, run_id: str | None = None) -> AgentStopResult:
        """Remote interrupt: only a successful ``session.cancel`` RPC response
        counts as acknowledged; errors/timeouts/disconnects are
        returned as structured failures, never swallowed."""
        return await self._stop_session(self._session_id)

    async def cancel(self, run_id: str | None = None, *, session_id: str | None = None) -> AgentStopResult:
        self._running = False
        return await self._stop_session(session_id or self._session_id)

    async def _stop_session(self, sid: str | None) -> AgentStopResult:
        from app.agents.contract import EXECUTION_KIND_REMOTE_SESSION, AgentStopResult
        from app.domains.ai.services.jobs.agent_dispatch import verify_bound_stop

        if sid == self._session_id:
            self._steering_open = False
        if not sid:
            return AgentStopResult(
                execution_kind=EXECUTION_KIND_REMOTE_SESSION,
                stop_acknowledged=False,
                failure_code="REMOTE_STOP_UNCONFIRMED",
                error_message="no active DSH session to cancel",
            )
        try:
            async with asyncio.timeout(15):
                await verify_bound_stop(self, sid)
                await self._rpc("session.cancel", {"sessionId": sid})
                if getattr(self, "_dispatch_identity", None):
                    while await self.session_running(sid):
                        await asyncio.sleep(0.5)
        except Exception as exc:
            if isinstance(exc, asyncio.CancelledError):
                raise
            return AgentStopResult(
                execution_kind=EXECUTION_KIND_REMOTE_SESSION,
                stop_acknowledged=False,
                failure_code=getattr(exc, "failure_code", None) or "DSH_CANCEL_RPC_FAILED",
                error_message=str(exc) or type(exc).__name__,
            )
        return AgentStopResult(
            execution_kind=EXECUTION_KIND_REMOTE_SESSION,
            stop_acknowledged=True,
        )

    async def cancel_persisted_session(self, session_id: str) -> AgentStopResult:
        """Reaper durable stop：目标必须是显式传入的持久化 session id。

        禁止回退到 ``self._session_id``（reaper 每次新建 adapter，内存
        session 必然为空；P1-3 修复）。
        """
        from app.agents.contract import EXECUTION_KIND_REMOTE_SESSION, AgentStopResult

        sid = str(session_id or "").strip()
        if not sid:
            return AgentStopResult(
                execution_kind=EXECUTION_KIND_REMOTE_SESSION,
                stop_acknowledged=False,
                failure_code="REMOTE_STOP_LOCATOR_MISSING",
                error_message="persisted DSH session id is required",
            )
        return await self._stop_session(sid)

    async def unload_session(self, session_id: str | None = None) -> None:
        """Dispose the DSH Web Host's in-memory Agent for a cold disk restore.

        ``session.cancel`` only stops the current turn.  The Web Host keeps the
        Agent and its folded context alive, so restoring ``session.jsonl`` on
        disk alone would still let the next prompt see reverted content.
        """
        sid = session_id or self._session_id
        if not sid:
            return
        try:
            await self._rpc("session.unload", {"sessionId": sid})
        except AgentError as exc:
            raise AgentError(f"DSH session unload failed: {exc}") from exc
        self._running = False
        if self._session_id == sid:
            self._session_id = None

    def is_running(self, run_id: str | None = None) -> bool:
        return self._running

    async def close(self) -> None:
        self._running = False
        self._session_id = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        for client in self._retired_clients:
            await client.aclose()
        self._retired_clients.clear()

    async def respond_to_ask_user(self, ask_user_id: str, response: str) -> None:
        if not ask_user_id or ask_user_id not in self._pending_asks:
            raise AgentError("DSH HITL reply requires a pending approval/question rpcId")
        pending = self._pending_asks[ask_user_id]
        kind = str(pending.get("kind") or "")
        if kind.startswith("approval"):
            outcome = (
                "rejected" if str(response).lower() in ("deny", "reject", "rejected", "no", "拒绝") else "allowed-once"
            )
            value = {
                "sessionId": pending.get("session_id") or self._session_id,
                "approvalId": pending.get("approval_id"),
                "outcome": outcome,
            }
        else:
            answer_text = str(response)
            answers = []
            for question in pending.get("questions") or []:
                if not isinstance(question, dict):
                    continue
                labels = {
                    str(item.get("label") or "") for item in (question.get("options") or []) if isinstance(item, dict)
                }
                answers.append(
                    {
                        "id": str(question.get("id") or ""),
                        "selected": [answer_text] if answer_text in labels else [],
                        **({} if answer_text in labels else {"custom": answer_text}),
                    }
                )
            value = {
                "sessionId": pending.get("session_id") or self._session_id,
                "answer": {"answers": answers},
            }
        try:
            await self._respond(ask_user_id, value)
        except httpx.RequestError as exc:
            raise AgentInteractionDeliveryUncertain("DSH reply delivery could not be confirmed.") from exc
        self._pending_asks.pop(ask_user_id, None)

    async def _respond(self, rpc_id: str, value: dict[str, Any]) -> None:
        client = await self._ensure_client()
        reply = await client.post(
            f"{self.server_url}/api/respond",
            timeout=30.0,
            json={
                "type": "client-response",
                "rpcId": rpc_id,
                "result": {"ok": True, "value": value},
            },
        )
        if reply.status_code != 200:
            raise AgentError(f"DSH HITL reply failed: HTTP {reply.status_code} {reply.text[:300]}")

    async def fork_session(
        self,
        session_id: str,
        *,
        source_dir: str,
        target_dir: str,
    ) -> str:
        """文件级 fork：web host 持久化布局与 CLI 一致，复用 session_files。"""
        from app.agents.adapters.dsh import session_files
        from app.agents.adapters.dsh.dsh_adapter import dsh_sessions_root

        new_id = f"session-tf-fork-{uuid.uuid4().hex}"
        try:
            session_files.fork_session_log(
                dsh_sessions_root(),
                session_id,
                new_session_id=new_id,
                target_cwd=str(target_dir or ""),
            )
        except Exception as exc:
            raise SessionForkError(f"DSH session fork failed for {session_id}: {exc}") from exc
        return new_id
