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
from typing import Any, Optional
from urllib.parse import quote

import httpx
import websockets

from app.agents.contract import (
    AgentBackend,
    AgentCapabilities,
    AgentEventSink,
    AgentRunRequest,
    AgentRunResult,
    TokenUsage,
)
from app.agents.activity_watchdog import AgentActivityWatchdog
from app.agents.errors import AgentError, AgentTimeoutError, SessionForkError
from app.agents.events import AgentEvent
from app.config import settings


def map_dsh_event(raw_event: dict[str, Any]) -> Optional[AgentEvent]:
    """DSH SessionEvent（web host 原生事件）→ 统一 AgentEvent。"""
    etype = str(raw_event.get("type") or "")
    data = raw_event.get("data") if isinstance(raw_event.get("data"), dict) else {}

    if etype == "assistant/message":
        # web host 事件形状：data.message.{role,content[,usage]}（部分流式事件平铺在 data 上）
        msg = data.get("message") if isinstance(data.get("message"), dict) else data
        blocks = msg.get("content") if isinstance(msg.get("content"), list) else []
        text = "\n".join(
            str(block.get("text") or "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
        usage_raw = msg.get("usage") if isinstance(msg.get("usage"), dict) else (
            data.get("usage") if isinstance(data.get("usage"), dict) else None
        )
        usage: Optional[TokenUsage] = None
        if usage_raw:
            usage = TokenUsage(
                input_tokens=usage_raw.get("inputTokens"),
                output_tokens=usage_raw.get("outputTokens"),
                cache_read_tokens=usage_raw.get("cacheReadTokens"),
                cache_creation_tokens=usage_raw.get("cacheWriteTokens"),
                total_tokens=None,
                raw=usage_raw,
            )
        if text or usage:
            return AgentEvent(
                type="text" if text else "usage",
                payload={"text": text, "usage": usage.__dict__ if usage else {}, "provider": "dsh"},
                provider="dsh",
                raw=raw_event,
            )
        return None
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
                    payload={"text": chunk_text, "provider": "dsh"},
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
            payload={"text": chunk, "provider": "dsh"},
            provider="dsh",
            raw=raw_event,
        )
    if etype == "tool/call":
        tool_name = str(data.get("name") or data.get("tool") or "")
        tool_input = data.get("arguments") or data.get("input") or {}
        tool_use_id = str(data.get("callId") or data.get("id") or "")
        return AgentEvent(
            type="tool_use",
            payload={
                "tool": tool_name,
                "input": tool_input,
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_use_id": tool_use_id,
                "provider": "dsh",
            },
            provider="dsh",
            raw=raw_event,
        )
    if etype == "tool/result":
        tool_name = str(data.get("name") or data.get("tool") or "")
        tool_use_id = str(data.get("callId") or data.get("toolUseId") or data.get("id") or "")
        output = data.get("result") or data.get("output") or data.get("content") or ""
        return AgentEvent(
            type="tool_result",
            payload={
                "tool": tool_name,
                "tool_name": tool_name,
                "tool_use_id": tool_use_id,
                "output": output,
                "is_error": bool(data.get("isError") or data.get("is_error")),
                "provider": "dsh",
            },
            provider="dsh",
            raw=raw_event,
        )
    return None


class DshServerAdapter(AgentBackend):
    name = "dsh"
    capabilities = AgentCapabilities(
        supports_resume=True,  # web host prompt 隐式 resume 冷会话
        supports_streaming_text=True,
        supports_tool_events=True,
        supports_fork=True,  # 文件级 fork（session_files）
        hitl_modes=["turn_based", "long_connection"],
        supports_usage=True,
        skill_layouts=["dsh"],
        preferred_mode="server",
    )

    def __init__(self, server_url: str = "http://127.0.0.1:3080") -> None:
        self.server_url = server_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._running = False
        self._session_id: Optional[str] = None
        self._pending_asks: dict[str, dict[str, Any]] = {}
        self._gateway_protocol: Optional[bool] = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers: dict[str, str] = {}
            cookie = str(os.environ.get("DSH_BROWSER_COOKIE") or settings.DSH_BROWSER_COOKIE or "").strip()
            if cookie:
                headers["Cookie"] = cookie
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, read=None),
                headers=headers,
                follow_redirects=True,
                trust_env=False,
            )
            token = str(os.environ.get("DSH_BROWSER_TOKEN") or settings.DSH_BROWSER_TOKEN or "").strip()
            if token and not cookie:
                response = await self._client.get(
                    f"{self.server_url}/?token={quote(token, safe='')}"
                )
                if response.status_code >= 400:
                    await self._client.aclose()
                    self._client = None
                    raise AgentError(
                        f"DSH browser token exchange failed: HTTP {response.status_code}"
                    )
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
            attempts.append((
                f"{self.server_url}/api/{gateway_method}",
                gateway_method,
                {"args": {parameter_name: payload}},
                True,
            ))
        if self._gateway_protocol is not True:
            attempts.append((
                f"{self.server_url}/api/{method}",
                method,
                payload,
                False,
            ))

        last_response: Optional[httpx.Response] = None
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
                raise AgentError(
                    f"DSH server RPC {method} failed: HTTP {response.status_code}"
                )
            envelope = response.json()
            result = envelope.get("result") if isinstance(envelope, dict) else None
            if not isinstance(result, dict):
                raise AgentError(f"DSH server RPC {method} returned malformed envelope")
            if not result.get("ok"):
                error = result.get("error") or {}
                raise AgentError(
                    f"DSH server RPC {method} failed: {error.get('code', 'unknown')} {error.get('message', '')}"
                )
            self._gateway_protocol = is_gateway
            value = result.get("value")
            return value if isinstance(value, dict) else {}
        status = last_response.status_code if last_response is not None else "unknown"
        raise AgentError(f"DSH server RPC {method} failed: HTTP {status}")

    async def probe(self) -> str:
        await self._rpc("session.list", {})
        return f"DSH JSON-RPC server is reachable at {self.server_url}"

    async def _create_session(self, request: AgentRunRequest) -> str:
        payload = await self._rpc(
            "session.create",
            {"cwd": request.project_path or "."},
        )
        session_id = str(payload.get("sessionId") or "").strip()
        if not session_id:
            raise AgentError("DSH session.create returned no sessionId")
        return session_id

    async def _resolve_session_model(
        self,
        session_id: str,
        fallback: Optional[str] = None,
    ) -> Optional[str]:
        """从 web host 查询会话当前模型，避免启动状态显示 unknown。"""
        if fallback:
            return fallback
        # ``session.models`` is optional on the current gateway and returns
        # HTTP 404 even though the gateway itself is healthy.  A fresh adapter
        # must therefore discover the wire protocol from the stable
        # ``session.list`` route before attempting this best-effort lookup;
        # otherwise ``_gateway_protocol`` stays ``None`` and the event stream
        # is incorrectly downgraded to the legacy events.mux endpoint.
        if self._gateway_protocol is None:
            try:
                await self._rpc("session.list", {})
            except AgentError:
                # Keep model lookup best-effort.  A server that cannot answer
                # the probe will still be handled by the existing RPC errors.
                pass
        try:
            value = await self._rpc("session.models", {"sessionId": session_id})
            current = value.get("current") if isinstance(value, dict) else None
            if not isinstance(current, dict):
                return fallback
            provider = str(current.get("provider") or "").strip()
            model = str(current.get("model") or "").strip()
            if not model:
                return fallback
            return f"{provider}/{model}" if provider else model
        except Exception:
            return fallback

    def _ws_url(self) -> str:
        path = "remote.mux" if self._gateway_protocol is True else "events.mux"
        return f"{self.server_url.replace('http://', 'ws://', 1)}/api/{path}"

    def _ws_headers(self) -> dict[str, str]:
        if self._client is None:
            return {}
        cookies = self._client.cookies
        values = [f"{key}={value}" for key, value in cookies.items()]
        return {"Cookie": "; ".join(values)} if values else {}

    async def _consume_events(
        self,
        session_id: str,
        on_event: AgentEventSink,
        *,
        read_only: bool = False,
    ) -> dict[str, Any]:
        """消费 events.mux 下行流直到该会话 turn/end，返回收尾信息。

        下行帧信封：{type:"server-request", rpcId, method:<frame.type>, payload:<frame>}；
        会话事件帧 method=session/event，payload 含 sessionId 与原生 SessionEvent。
        """
        if self._gateway_protocol is True:
            return await self._consume_gateway_events(session_id, on_event)

        outcome: dict[str, Any] = {"finish_reason": None, "text": "", "usage_raw": None}
        text_parts: list[str] = []
        delta_parts: list[str] = []

        def _finalize() -> dict[str, Any]:
            # 最终文本优先取完整 assistant/message；缺失时回退拼接流式 delta
            body = "\n".join(part for part in text_parts if part).strip()
            if not body:
                body = "".join(delta_parts).strip()
            outcome["text"] = body
            return outcome
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
                    unified = map_dsh_event(event)
                    if unified:
                        if unified.type == "text" and unified.payload.get("text"):
                            text_parts.append(str(unified.payload["text"]))
                        elif unified.type == "text_delta" and unified.payload.get("text"):
                            delta_parts.append(str(unified.payload["text"]))
                        await on_event(unified)
                    etype = str(event.get("type") or "")
                    if etype == "assistant/message":
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
                                await on_event(AgentEvent(
                                    type="thinking",
                                    payload={"text": reasoning, "provider": "dsh"},
                                    provider="dsh",
                                ))
                    if etype == "turn/end":
                        reason = event.get("data", {}).get("reason", {})
                        kind = str(reason.get("kind") or "completed") if isinstance(reason, dict) else "completed"
                        outcome["finish_reason"] = {
                            "completed": "completed",
                            "aborted": "aborted",
                            "error": "error",
                            "max-tokens": "max-tokens",
                        }.get(kind, kind)
                        finalize_result = _finalize()
                        # 若流式过程中只收到 text-delta 而缺失完整 assistant/message，
                        # 把累积文本作为完整 text 事件补发，确保前端收到落库的 assistant 消息。
                        body = str(finalize_result.get("text") or "")
                        if body and not text_parts:
                            await on_event(AgentEvent(
                                type="text",
                                payload={"text": body, "provider": "dsh"},
                                provider="dsh",
                            ))
                        # DSH 模型/provider 出错时没有正文，把具体错误写到 result，
                        # 避免前端只看到空白的“Agent execution failed”。
                        if kind == "error" and not body:
                            error_info = reason.get("error") if isinstance(reason, dict) else None
                            if isinstance(error_info, dict):
                                finalize_result["text"] = str(error_info.get("message") or "DSH stream error")
                            else:
                                finalize_result["text"] = "DSH stream error"
                        return finalize_result
                elif method in ("approval/requested", "question/requested"):
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
                            continue
                        self._pending_asks[rpc_id] = {
                            "kind": method,
                            "session_id": session_id,
                            "approval_id": approval_id,
                        }
                        prompt = str(
                            payload.get("reason")
                            or f"Allow DSH tool {payload.get('toolName') or 'unknown'}?"
                        )
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
                    await on_event(AgentEvent(
                        type="ask_user",
                        payload={
                            "ask_user_id": rpc_id,
                            "prompt": prompt,
                            "question": prompt,
                            "kind": "approval" if method.startswith("approval") else "question",
                            "options": options,
                        },
                        provider="dsh",
                    ))
                elif method == "stream/error":
                    outcome["finish_reason"] = "error"
                    outcome["text"] = str(payload.get("message") or "stream error")
                    return _finalize()
        return _finalize()

    async def _consume_gateway_events(
        self,
        session_id: str,
        on_event: AgentEventSink,
    ) -> dict[str, Any]:
        """Consume the current DSH gateway ``session/follow`` stream.

        The current Web Host no longer exposes the legacy ``events.mux`` RPC
        stream.  Its gateway multiplexes logical streams over ``remote.mux``;
        the session follow stream starts with a snapshot and then emits event
        records.  The snapshot is deliberately ignored here because the prompt
        admission runs concurrently and only post-open events belong to this
        turn.
        """
        outcome: dict[str, Any] = {"finish_reason": None, "text": "", "usage_raw": None}
        text_parts: list[str] = []
        delta_parts: list[str] = []
        stream_id = f"tf-{uuid.uuid4().hex}"

        def _finalize() -> dict[str, Any]:
            body = "\n".join(part for part in text_parts if part).strip()
            if not body:
                body = "".join(delta_parts).strip()
            outcome["text"] = body
            return outcome

        async with websockets.connect(
            self._ws_url(),
            additional_headers=self._ws_headers(),
            max_size=64 * 1024 * 1024,
        ) as ws:
            await ws.send(json.dumps({
                "type": "open",
                "streamId": stream_id,
                "endpoint": "session/follow",
                "payload": {
                    "args": {
                        "request": {
                            "address": {"kind": "session", "sessionId": session_id},
                            "maxMessages": 50,
                        },
                    },
                },
            }))
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
                    return _finalize()
                if frame_type != "item":
                    continue
                value = frame.get("value") if isinstance(frame.get("value"), dict) else {}
                if value.get("type") == "snapshot":
                    continue
                event = value.get("event") if value.get("type") == "event" else value
                if not isinstance(event, dict):
                    continue
                unified = map_dsh_event(event)
                if unified:
                    if unified.type == "text" and unified.payload.get("text"):
                        text_parts.append(str(unified.payload["text"]))
                    elif unified.type == "text_delta" and unified.payload.get("text"):
                        delta_parts.append(str(unified.payload["text"]))
                    await on_event(unified)
                etype = str(event.get("type") or "")
                if etype == "turn/end":
                    reason = event.get("data", {}).get("reason", {})
                    kind = str(reason.get("kind") or "completed") if isinstance(reason, dict) else "completed"
                    outcome["finish_reason"] = {
                        "completed": "completed",
                        "aborted": "aborted",
                        "error": "error",
                        "max-tokens": "max-tokens",
                    }.get(kind, kind)
                    result = _finalize()
                    body = str(result.get("text") or "")
                    if body and not text_parts:
                        await on_event(AgentEvent(
                            type="text",
                            payload={"text": body, "provider": "dsh"},
                            provider="dsh",
                        ))
                    if kind == "error" and not body:
                        error_info = reason.get("error") if isinstance(reason, dict) else None
                        result["text"] = str(error_info.get("message") or "DSH stream error") if isinstance(error_info, dict) else "DSH stream error"
                    return result
        return _finalize()

    async def run(self, request: AgentRunRequest, on_event: AgentEventSink) -> AgentRunResult:
        await self._ensure_client()
        self._running = True
        self._pending_asks.clear()
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
            model = await self._resolve_session_model(session_id, request.model)

            await _tracked_event(AgentEvent(
                type="session_started",
                payload={
                    "provider_session_id": session_id,
                    "provider": "dsh",
                    "model": model,
                    "directory": request.project_path,
                },
                provider="dsh",
            ))

            # 先开事件流再发 prompt，避免错过早期事件；prompt 失败时立刻终止等待
            is_read_only = str(request.permission_mode or "").strip().lower() in {
                "read-only", "readonly", "plan",
            }
            consume_task = asyncio.create_task(
                self._consume_events(session_id, _tracked_event, read_only=is_read_only)
            )
            prompt_text = request.prompt
            if is_read_only:
                prompt_text = (
                    "[只读会话约束] 只能分析、读取和总结；禁止创建、修改、删除文件，"
                    "禁止执行会改变项目或外部系统状态的命令。\n\n"
                    + prompt_text
                )
            prompt_task = asyncio.create_task(self._rpc("session.prompt", {
                "requestId": f"tf-{uuid.uuid4().hex}",
                "sessionId": session_id,
                "mode": "queue",
                "content": [{"type": "text", "text": prompt_text}],
            }))

            def _abort_on_prompt_failure(task: asyncio.Task) -> None:
                if not task.cancelled() and task.exception() is not None:
                    consume_task.cancel()

            prompt_task.add_done_callback(_abort_on_prompt_failure)
            try:
                consumed = await watchdog.wait(consume_task)
            except AgentTimeoutError:
                prompt_task.cancel()
                consume_task.cancel()
                await self.cancel(session_id=session_id)
                await asyncio.gather(prompt_task, consume_task, return_exceptions=True)
                raise
            except asyncio.CancelledError as exc:
                prompt_task.cancel()
                # consume 被 prompt 失败回调取消：抛出 prompt 的真实错误
                try:
                    await prompt_task
                except AgentError as prompt_error:
                    raise prompt_error from exc
                raise
            await prompt_task

            finish_reason = consumed.get("finish_reason") or "completed"
            final_text = str(consumed.get("text") or "")
            success = finish_reason not in ("error", "aborted")
            await _tracked_event(AgentEvent(
                type="result",
                payload={
                    "success": success,
                    "result": final_text,
                    "finish_reason": finish_reason,
                    "session_id": session_id,
                },
                provider="dsh",
            ))
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
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError(f"DSH server run failed: {exc}") from exc
        finally:
            self._running = False

    async def interrupt(self, run_id: str | None = None) -> None:
        if self._session_id:
            try:
                await self._rpc("session.cancel", {"sessionId": self._session_id})
            except AgentError:
                pass

    async def cancel(self, run_id: str | None = None, *, session_id: str | None = None) -> None:
        sid = session_id or self._session_id
        if sid:
            try:
                await self._rpc("session.cancel", {"sessionId": sid})
            except AgentError:
                pass
        self._running = False

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

    async def respond_to_ask_user(self, ask_user_id: str, response: str) -> None:
        if not ask_user_id or ask_user_id not in self._pending_asks:
            raise AgentError("DSH HITL reply requires a pending approval/question rpcId")
        pending = self._pending_asks.pop(ask_user_id)
        kind = str(pending.get("kind") or "")
        if kind.startswith("approval"):
            outcome = (
                "rejected"
                if str(response).lower() in ("deny", "reject", "rejected", "no", "拒绝")
                else "allowed-once"
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
                    str(item.get("label") or "")
                    for item in (question.get("options") or [])
                    if isinstance(item, dict)
                }
                answers.append({
                    "id": str(question.get("id") or ""),
                    "selected": [answer_text] if answer_text in labels else [],
                    **({} if answer_text in labels else {"custom": answer_text}),
                })
            value = {
                "sessionId": pending.get("session_id") or self._session_id,
                "answer": {"answers": answers},
            }
        await self._respond(ask_user_id, value)

    async def _respond(self, rpc_id: str, value: dict[str, Any]) -> None:
        client = await self._ensure_client()
        reply = await client.post(
            f"{self.server_url}/api/respond",
            json={
                "type": "client-response",
                "rpcId": rpc_id,
                "result": {"ok": True, "value": value},
            },
        )
        if reply.status_code != 200:
            raise AgentError(
                f"DSH HITL reply failed: HTTP {reply.status_code} {reply.text[:300]}"
            )

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
