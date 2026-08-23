"""OpenCode Agent backend（Server 模式）。

Spike 结论：`opencode run --format json` 在 Windows 当前环境因 shell 探测失败，
`opencode serve` 可稳定提供 SSE/HTTP API，因此 OpenCode 采用 **server 模式**接入。

连接方式：
- `POST /api/session` 创建会话（或复用 `request.session_id`）
- 先打开 `GET /api/session/{id}/event` SSE 流，再 `POST /api/session/{id}/prompt`
- 从 SSE 事件解析统一 AgentEvent，直到 `step.ended.finish=stop/cancelled/error`
- 最后用 `GET /api/session/{id}/message` 取最终消息/用量兜底
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Optional

import httpx

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
from app.agents.adapters.opencode.event_mapper import map_opencode_event


class OpenCodeAdapter(AgentBackend):
    name = "opencode"
    capabilities = AgentCapabilities(
        supports_resume=True,
        supports_streaming_text=True,
        supports_tool_events=True,
        supports_fork=True,
        hitl_modes=["turn_based", "long_connection"],
        supports_usage=True,
        skill_layouts=["opencode"],
        preferred_mode="server",
    )

    def __init__(self, server_url: str = "http://127.0.0.1:4097") -> None:
        self.server_url = server_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._running = False
        self._run_id: Optional[str] = None
        self._session_id: Optional[str] = None
        self._interrupted = False

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=None))
        return self._client

    def _session_url(self, session_id: str, path: str = "") -> str:
        return f"{self.server_url}/api/session/{session_id}{path}"

    async def _create_session(self, request: AgentRunRequest) -> str:
        client = await self._ensure_client()
        body: dict[str, Any] = {}
        if request.project_path:
            body["location"] = {"directory": request.project_path}
        if request.model:
            body["model"] = {"id": request.model, "providerID": "opencode"}
        response = await client.post(f"{self.server_url}/api/session", json=body)
        if response.status_code != 200:
            raise AgentError(
                f"OpenCode create session failed: HTTP {response.status_code} {response.text[:300]}"
            )
        data = response.json().get("data")
        session_id = data.get("id") if isinstance(data, dict) else None
        if not session_id:
            raise AgentError("OpenCode create session returned no session id")
        return session_id

    async def _send_prompt(self, session_id: str, request: AgentRunRequest) -> None:
        client = await self._ensure_client()
        body: dict[str, Any] = {
            "prompt": {"text": request.prompt},
            "delivery": "steer",
        }
        if request.session_id:
            # 已有会话略过 resume 标志，直接追加消息
            body["resume"] = True
        response = await client.post(
            self._session_url(session_id, "/prompt"),
            json=body,
        )
        if response.status_code != 200:
            raise AgentError(
                f"OpenCode prompt failed: HTTP {response.status_code} {response.text[:300]}"
            )

    async def _fetch_final_message(self, session_id: str) -> dict[str, Any]:
        client = await self._ensure_client()
        response = await client.get(
            self._session_url(session_id, "/message"),
            params={"limit": 20},
        )
        if response.status_code != 200:
            return {}
        messages = response.json().get("data") or []
        for message in reversed(messages):
            if not isinstance(message, dict) or message.get("type") != "assistant":
                continue
            content = message.get("content") or []
            text = "".join(
                str(block.get("text") or "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ).strip()
            return {
                "text": text,
                "finish": message.get("finish"),
                "cost": message.get("cost"),
                "tokens": message.get("tokens") or {},
            }
        return {}

    def _to_token_usage(self, tokens: Optional[dict[str, Any]]) -> Optional[TokenUsage]:
        if not isinstance(tokens, dict):
            return None
        cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
        input_tokens = tokens.get("input")
        output_tokens = tokens.get("output")
        reasoning = tokens.get("reasoning")
        cache_read = cache.get("read")
        cache_write = cache.get("write")
        if input_tokens is None and output_tokens is None:
            return None
        known = [v for v in (input_tokens, output_tokens, reasoning, cache_read, cache_write) if v is not None]
        return TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_write,
            total_tokens=sum(known) if known else None,
            raw=tokens,
        )

    @staticmethod
    def _normalize_finish_reason(finish: Optional[str]) -> Optional[str]:
        if not finish:
            return None
        return {
            "stop": "completed",
            "max_tokens": "max-tokens",
            "max-tokens": "max-tokens",
            "cancelled": "aborted",
            "aborted": "aborted",
            "error": "error",
        }.get(finish, finish)

    async def _consume_sse(
        self,
        session_id: str,
        request: AgentRunRequest,
        on_event: AgentEventSink,
    ) -> dict[str, Any]:
        """打开 SSE 流、发送 prompt、消费事件，返回最终状态。"""
        client = await self._ensure_client()
        result_payload: dict[str, Any] = {}

        # 先发送 prompt，再订阅 SSE；实测 OpenCode 会把刚发生的事件从当前游标开始补发。
        await self._send_prompt(session_id, request)

        async with client.stream(
            "GET",
            self._session_url(session_id, "/event"),
        ) as response:
            if response.status_code != 200:
                raise AgentError(
                    f"OpenCode event stream failed: HTTP {response.status_code} {response.text[:300]}"
                )

            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw_text = line[5:].strip()
                if not raw_text:
                    continue
                try:
                    raw_event = json.loads(raw_text)
                except json.JSONDecodeError:
                    continue
                for unified in map_opencode_event(raw_event):
                    if unified.type == "result":
                        # 不在 SSE 中重复发 result；由 run() 在拿到最终 message 后补发
                        # 带完整文本的 result。
                        result_payload = {
                            "finish_reason": unified.payload.get("finish_reason") or "completed",
                            "success": True,
                        }
                        return result_payload
                    await on_event(unified)
                    if unified.type == "error":
                        result_payload = {
                            "finish_reason": unified.payload.get("finish_reason") or "error",
                            "success": False,
                        }
                        return result_payload
        return result_payload

    async def run(self, request: AgentRunRequest, on_event: AgentEventSink) -> AgentRunResult:
        await self._ensure_client()
        self._running = True
        self._run_id = request.run_id
        self._interrupted = False
        started_at = time.monotonic()
        session_id = request.session_id or ""
        try:
            if request.session_id:
                session_id = request.session_id
            else:
                session_id = await self._create_session(request)
            self._session_id = session_id

            await on_event(AgentEvent(
                type="session_started",
                payload={
                    "provider_session_id": session_id,
                    "provider": "opencode",
                    "model": request.model,
                    "directory": request.project_path,
                },
                provider="opencode",
            ))

            timeout = request.timeout_seconds or 300.0
            try:
                consumed = await asyncio.wait_for(
                    self._consume_sse(session_id, request, on_event),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                await self.interrupt(session_id=session_id)
                final = await self._fetch_final_message(session_id)
                return AgentRunResult(
                    run_id=request.run_id,
                    session_id=session_id,
                    success=False,
                    finish_reason="timeout",
                    result_text=final.get("text", ""),
                    usage=self._to_token_usage(final.get("tokens")),
                    cost_usd=final.get("cost"),
                    duration_ms=int((time.monotonic() - started_at) * 1000),
                    return_code=None,
                    raw_trace=f"timeout after {timeout:.0f}s",
                )

            finish_reason = consumed.get("finish_reason")
            success = bool(consumed.get("success"))
            final = await self._fetch_final_message(session_id)
            if not finish_reason:
                finish_reason = self._normalize_finish_reason(final.get("finish")) or ("completed" if success else "error")
            if self._interrupted:
                finish_reason = "interrupted"

            await on_event(AgentEvent(
                type="result",
                payload={
                    "success": success,
                    "result": final.get("text", ""),
                    "finish_reason": finish_reason,
                    "session_id": session_id,
                    "usage": (self._to_token_usage(final.get("tokens")) or {}).__dict__ if self._to_token_usage(final.get("tokens")) else {},
                    "cost_usd": final.get("cost"),
                },
                provider="opencode",
            ))

            return AgentRunResult(
                run_id=request.run_id,
                session_id=session_id,
                success=success,
                finish_reason=finish_reason,
                result_text=final.get("text", ""),
                usage=self._to_token_usage(final.get("tokens")),
                cost_usd=final.get("cost"),
                duration_ms=int((time.monotonic() - started_at) * 1000),
                return_code=None,
                raw_trace=json.dumps(consumed, ensure_ascii=False, default=str),
            )
        except Exception as exc:
            if isinstance(exc, AgentError):
                raise
            raise AgentError(f"OpenCode run failed: {exc}") from exc
        finally:
            self._running = False
            self._run_id = None

    async def interrupt(self, run_id: str | None = None, *, session_id: str | None = None) -> None:
        sid = session_id or self._session_id
        if not sid or self._client is None:
            return
        try:
            await self._client.post(self._session_url(sid, "/interrupt"))
        except Exception:
            pass
        self._interrupted = True

    async def cancel(self, run_id: str | None = None) -> None:
        sid = self._session_id
        if sid and self._client is not None:
            try:
                await self._client.post(self._session_url(sid, "/abort"))
            except Exception:
                try:
                    await self._client.post(f"{self.server_url}/session/{sid}/abort")
                except Exception:
                    pass
        self._interrupted = True
        self._running = False

    def is_running(self, run_id: str | None = None) -> bool:
        return self._running

    async def close(self) -> None:
        self._running = False
        self._run_id = None
        self._session_id = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def respond_to_ask_user(self, ask_user_id: str, response: str) -> None:
        sid = self._session_id
        if not sid or not ask_user_id:
            raise AgentError("OpenCode HITL reply requires active session and ask_user_id")
        client = await self._ensure_client()
        if ask_user_id.startswith("per") or ask_user_id.startswith("permission"):
            reply = "once" if response.lower() != "reject" else "reject"
            url = self._session_url(sid, f"/permission/{ask_user_id}/reply")
            body = {"reply": reply}
        else:
            url = self._session_url(sid, f"/question/{ask_user_id}/reply")
            body = {"answers": [[response]]}
        result = await client.post(url, json=body)
        if result.status_code != 200:
            raise AgentError(
                f"OpenCode HITL reply failed: HTTP {result.status_code} {result.text[:300]}"
            )

    # ── 会话 fork（baseline → 评审线程）────────────────────────
    async def _fork_create(self, client: httpx.AsyncClient, session_id: str) -> str:
        """调用 fork API，返回新会话 id。v1 路由优先，v2 路由回退。"""
        responses = (
            # v1（v1.18.21+ 已发布）: POST /session/{id}/fork, 可选 body {messageID}
            ("post", f"{self.server_url}/session/{session_id}/fork", None),
            # v2: POST /api/session/{id}/fork, body boundary=through 表示复制全部历史
            ("post", f"{self.server_url}/api/session/{session_id}/fork", {
                "boundary": {"type": "through"},
            }),
        )
        last_error = ""
        for _method, url, body in responses:
            response = await client.post(url, json=body)
            if response.status_code == 200:
                data = response.json()
                payload = data.get("data") if isinstance(data, dict) else None
                if not isinstance(payload, dict):
                    payload = data if isinstance(data, dict) else {}
                new_id = str(payload.get("id") or "").strip()
                if new_id:
                    return new_id
                last_error = f"fork response missing session id: {str(data)[:200]}"
                continue
            last_error = f"HTTP {response.status_code} {response.text[:200]}"
        raise SessionForkError(f"OpenCode session fork failed for {session_id}: {last_error}")

    async def _fork_move(
        self,
        client: httpx.AsyncClient,
        session_id: str,
        target_dir: str,
    ) -> None:
        """把 fork 出的会话挪到线程工作目录（决定工具执行 cwd）。"""
        abs_dir = os.path.abspath(target_dir)
        moves = (
            # v1: experimental control-plane
            ("post", f"{self.server_url}/experimental/control-plane/move-session", {
                "sessionID": session_id,
                "destination": {"directory": abs_dir},
            }),
            # v2
            ("post", f"{self.server_url}/api/session/{session_id}/move", {
                "directory": abs_dir,
            }),
        )
        last_error = ""
        for _method, url, body in moves:
            response = await client.post(url, json=body)
            if response.status_code == 200:
                return
            last_error = f"HTTP {response.status_code} {response.text[:200]}"
        raise SessionForkError(
            f"OpenCode forked session {session_id} could not be moved to {abs_dir}: {last_error}"
        )

    async def delete_session(self, session_id: str) -> bool:
        """尽力删除会话（fork 演练清理用）；不支持时返回 False。"""
        client = await self._ensure_client()
        for url in (
            f"{self.server_url}/session/{session_id}",
            f"{self.server_url}/api/session/{session_id}",
        ):
            try:
                response = await client.delete(url)
            except Exception:
                continue
            if response.status_code in (200, 204):
                return True
        return False

    async def fork_session(
        self,
        session_id: str,
        *,
        source_dir: str,
        target_dir: str,
    ) -> str:
        """fork baseline 会话：复制完整历史（含工具调用）为独立新会话并挪到线程目录。

        原会话在服务端保持只读；每个评审线程 fork 出自己的会话 id，
        互不串上下文，且无需重读需求文档。
        """
        client = await self._ensure_client()
        new_id = await self._fork_create(client, session_id)
        try:
            # baseline 已直接在任务目录执行时，fork 出的新会话目录与源一致，
            # 无需再 move；仅当源/目标目录不同才迁移。
            if os.path.abspath(source_dir or "") != os.path.abspath(target_dir or ""):
                await self._fork_move(client, new_id, target_dir)
        except SessionForkError:
            # move 失败时清理 fork 产物，避免遗留孤儿会话
            await self.delete_session(new_id)
            raise
        return new_id