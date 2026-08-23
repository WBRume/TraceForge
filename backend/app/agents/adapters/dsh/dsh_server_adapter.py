"""DSH Web Host Agent backend（Server 模式）。

以 `dsh web --no-open --host 127.0.0.1 --port N` 启动的 DSH Web Host 暴露了
完整的 HTTP + WebSocket API（loopback 免认证），TraceForge 直接驱动：

- `POST /api/<method>`：JSON 信封 RPC（session.list / session.create / session.prompt /
  session.history / session.fork / session.cancel）
- `GET(ws) /api/events.mux`：全会话事件下行流（assistant chunk / tool call / usage）
- 冷会话在 prompt 时自动 `ctx.agents.resume`，天然支持跨进程多轮续会话

与 headless CLI 模式相比：支持 resume、工具事件、token usage 与多轮。
会话 fork 复用文件级实现（session_files），因为原生 session.fork 继承源会话
cwd，而评审线程需要落在自己的工作目录。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Optional

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
from app.agents.errors import AgentError, SessionForkError
from app.agents.events import AgentEvent


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
        chunk = str(data.get("text") or data.get("chunk") or "")
        if not chunk:
            return None
        return AgentEvent(
            type="text_delta",
            payload={"text": chunk, "provider": "dsh"},
            provider="dsh",
            raw=raw_event,
        )
    if etype == "tool/call":
        return AgentEvent(
            type="tool_use",
            payload={
                "tool": str(data.get("name") or data.get("tool") or ""),
                "input": data.get("arguments") or data.get("input") or {},
                "provider": "dsh",
            },
            provider="dsh",
            raw=raw_event,
        )
    if etype == "tool/result":
        return AgentEvent(
            type="tool_result",
            payload={
                "tool": str(data.get("name") or data.get("tool") or ""),
                "output": data.get("result") or data.get("output") or {},
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

    def __init__(self, server_url: str = "http://127.0.0.1:3097") -> None:
        self.server_url = server_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._running = False
        self._session_id: Optional[str] = None
        self._pending_asks: dict[str, str] = {}

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=None))
        return self._client

    async def _rpc(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        """调用 web host 的 /api/<method> 信封 RPC。

        业务错误也是 HTTP 200（result.ok=false），这里统一转成 AgentError。
        """
        client = await self._ensure_client()
        response = await client.post(
            f"{self.server_url}/api/{method}",
            json={
                "type": "client-request",
                "rpcId": f"tf-{uuid.uuid4().hex[:12]}",
                "method": method,
                "payload": payload,
            },
        )
        if response.status_code != 200:
            raise AgentError(
                f"DSH server RPC {method} failed: HTTP {response.status_code} {response.text[:300]}"
            )
        envelope = response.json()
        result = envelope.get("result") if isinstance(envelope, dict) else None
        if not isinstance(result, dict):
            raise AgentError(f"DSH server RPC {method} returned malformed envelope: {str(envelope)[:200]}")
        if not result.get("ok"):
            error = result.get("error") or {}
            raise AgentError(
                f"DSH server RPC {method} failed: {error.get('code', 'unknown')} {error.get('message', '')}"
            )
        value = result.get("value")
        return value if isinstance(value, dict) else {}

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

    def _ws_url(self) -> str:
        return f"{self.server_url.replace('http://', 'ws://', 1)}/api/events.mux"

    async def _consume_events(
        self,
        session_id: str,
        on_event: AgentEventSink,
    ) -> dict[str, Any]:
        """消费 events.mux 下行流直到该会话 turn/end，返回收尾信息。

        下行帧信封：{type:"server-request", rpcId, method:<frame.type>, payload:<frame>}；
        会话事件帧 method=session/event，payload 含 sessionId 与原生 SessionEvent。
        """
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
        async with websockets.connect(self._ws_url(), max_size=64 * 1024 * 1024) as ws:
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
                    if etype == "turn/end":
                        reason = event.get("data", {}).get("reason", {})
                        kind = str(reason.get("kind") or "completed") if isinstance(reason, dict) else "completed"
                        outcome["finish_reason"] = {
                            "completed": "completed",
                            "aborted": "aborted",
                            "error": "error",
                            "max-tokens": "max-tokens",
                        }.get(kind, kind)
                        return _finalize()
                elif method in ("approval/requested", "question/requested"):
                    self._pending_asks[rpc_id] = method
                    prompt = str(payload.get("prompt") or payload.get("message") or payload.get("title") or "DSH request")
                    await on_event(AgentEvent(
                        type="ask_user",
                        payload={
                            "ask_user_id": rpc_id,
                            "prompt": prompt,
                            "kind": "approval" if method.startswith("approval") else "question",
                            "options": payload.get("options") or [],
                        },
                        provider="dsh",
                    ))
                elif method == "stream/error":
                    outcome["finish_reason"] = "error"
                    outcome["text"] = str(payload.get("message") or "stream error")
                    return _finalize()
        return _finalize()

    async def run(self, request: AgentRunRequest, on_event: AgentEventSink) -> AgentRunResult:
        await self._ensure_client()
        self._running = True
        self._pending_asks.clear()
        started_at = time.monotonic()
        session_id = str(request.session_id or "").strip()
        try:
            if not session_id:
                session_id = await self._create_session(request)
            self._session_id = session_id

            await on_event(AgentEvent(
                type="session_started",
                payload={
                    "provider_session_id": session_id,
                    "provider": "dsh",
                    "model": request.model,
                    "directory": request.project_path,
                },
                provider="dsh",
            ))

            # 先开事件流再发 prompt，避免错过早期事件；prompt 失败时立刻终止等待
            consume_task = asyncio.create_task(self._consume_events(session_id, on_event))
            prompt_task = asyncio.create_task(self._rpc("session.prompt", {
                "sessionId": session_id,
                "mode": "queue",
                "content": [{"type": "text", "text": request.prompt}],
            }))

            def _abort_on_prompt_failure(task: asyncio.Task) -> None:
                if not task.cancelled() and task.exception() is not None:
                    consume_task.cancel()

            prompt_task.add_done_callback(_abort_on_prompt_failure)
            try:
                consumed = await asyncio.wait_for(
                    consume_task, timeout=request.timeout_seconds or 300.0
                )
            except asyncio.TimeoutError as exc:
                prompt_task.cancel()
                await self.cancel(session_id=session_id)
                raise AgentError(
                    f"DSH server turn timed out after {request.timeout_seconds}s"
                ) from exc
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
            await on_event(AgentEvent(
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
        client = await self._ensure_client()
        kind = self._pending_asks.pop(ask_user_id)
        if kind.startswith("approval"):
            outcome = "deny" if str(response).lower() in ("deny", "reject", "no", "拒绝") else "approve"
        else:
            outcome = str(response)
        reply = await client.post(
            f"{self.server_url}/api/respond",
            json={
                "type": "client-response",
                "rpcId": ask_user_id,
                "result": {"ok": True, "value": {"outcome": outcome}},
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
        session_files.fork_session_log(
            dsh_sessions_root(),
            session_id,
            new_session_id=new_id,
            target_cwd=str(target_dir or ""),
        )
        return new_id
