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
from app.agents.activity_watchdog import AgentActivityWatchdog
from app.agents.errors import AgentError, AgentTimeoutError, SessionForkError
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

    async def probe(self) -> str:
        client = await self._ensure_client()
        try:
            response = await client.get(self.server_url + "/")
        except Exception as exc:
            raise AgentError(f"OpenCode server unreachable: {exc}") from exc
        return f"OpenCode server is reachable at {self.server_url} (HTTP {response.status_code})"

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
        # 使用 prompt_async：该接口立即返回 204，避免同步 prompt 接口
        # 一直持有 HTTP 连接直到 agent 回合结束，导致 SSE 事件虽然已产生
        # 却迟迟不被消费，前端长时间“只看到运行、没有数据”。
        body: dict[str, Any] = {
            "parts": [{"type": "text", "text": request.prompt}],
        }
        if request.model:
            body["model"] = {"providerID": "opencode", "modelID": request.model}
        if str(request.permission_mode or "").strip().lower() in {"read-only", "readonly", "plan"}:
            # OpenCode's built-in plan agent disables write-oriented execution.
            body["agent"] = "plan"
        params: dict[str, str] = {}
        if request.project_path:
            # 明确告诉 OpenCode 本次 prompt 所在的工作目录，确保每个任务
            # 都读取自己任务目录下的文件，而不是服务启动时的目录。
            params["directory"] = request.project_path
        response = await client.post(
            f"{self.server_url}/session/{session_id}/prompt_async",
            params=params,
            json=body,
        )
        if response.status_code not in (200, 204):
            raise AgentError(
                f"OpenCode prompt failed: HTTP {response.status_code} {response.text[:300]}"
            )

    async def _fetch_final_message(self, session_id: str) -> dict[str, Any]:
        client = await self._ensure_client()
        # 优先使用 v1 /session/{id}/message：实测 v2 /api/session/{id}/message
        # 对 prompt_async 创建的会话可能返回空 data，导致最终文本/内容丢失。
        response = await client.get(
            f"{self.server_url}/session/{session_id}/message",
        )
        if response.status_code == 200:
            parsed = self._parse_v1_messages(response.json())
            if parsed:
                return parsed

        # 回退 v2（旧版本/未来版本可能使用 v2 结构）
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
                "content": content,
            }
        return {}

    @staticmethod
    def _parse_v1_messages(data: Any) -> Optional[dict[str, Any]]:
        """解析 OpenCode v1 /session/{id}/message 返回的消息列表。"""
        if not isinstance(data, list):
            return None
        for item in reversed(data):
            if not isinstance(item, dict):
                continue
            info = item.get("info") if isinstance(item.get("info"), dict) else {}
            if info.get("role") != "assistant":
                continue
            parts = item.get("parts") if isinstance(item.get("parts"), list) else []
            content: list[dict[str, Any]] = []
            text_parts: list[str] = []
            for part in parts:
                if not isinstance(part, dict):
                    continue
                part_type = part.get("type")
                if part_type == "text":
                    text = OpenCodeAdapter._text(part.get("text"))
                    if text:
                        text_parts.append(text)
                        content.append({"type": "text", "text": text})
                elif part_type == "reasoning":
                    text = OpenCodeAdapter._text(part.get("text"))
                    if text:
                        content.append({"type": "reasoning", "text": text})
                elif part_type == "tool":
                    state = part.get("state") if isinstance(part.get("state"), dict) else {}
                    content.append({
                        "type": "tool",
                        "id": OpenCodeAdapter._text(part.get("callID") or part.get("id")),
                        "name": OpenCodeAdapter._text(part.get("tool") or part.get("name")),
                        "state": state,
                    })
            return {
                "text": "\n".join(text_parts).strip(),
                "finish": info.get("finish"),
                "cost": info.get("cost"),
                "tokens": info.get("tokens") or {},
                "content": content,
            }
        return None

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

    @staticmethod
    def _text(value: Any) -> str:
        return str(value or "").strip()

    async def _emit_missing_final_events(
        self,
        final: dict[str, Any],
        seen_types: set[str],
        on_event: AgentEventSink,
    ) -> None:
        """SSE 流缺失/断连时，从最终 assistant message 补齐 thinking/tool/usage。

        OpenCode 的最终 message 包含 reasoning 文本、tool state（input/content/
        structured/result/error）与 tokens；这些足够重建统一事件，避免 UI 拿到
        只有最终文本、没有中间过程的情况。
        """
        content = final.get("content") or []
        if not isinstance(content, list):
            return

        if "thinking" not in seen_types:
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "reasoning":
                    continue
                text = self._text(block.get("text"))
                if text:
                    await on_event(AgentEvent(
                        type="thinking",
                        payload={"text": text},
                        provider="opencode",
                        raw=block,
                    ))

        if "tool_use" not in seen_types:
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool":
                    continue
                state = block.get("state") if isinstance(block.get("state"), dict) else {}
                await on_event(AgentEvent(
                    type="tool_use",
                    payload={
                        "tool_use_id": self._text(block.get("id")),
                        "tool_name": self._text(block.get("name") or block.get("tool")) or "unknown",
                        "tool_input": state.get("input", {}),
                    },
                    provider="opencode",
                    raw=block,
                ))

        if "tool_result" not in seen_types:
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool":
                    continue
                state = block.get("state") if isinstance(block.get("state"), dict) else {}
                status = self._text(state.get("status"))
                if status not in ("completed", "error"):
                    continue
                output = self._tool_state_output_text(state)
                if status == "error" and state.get("error") is not None:
                    error_text = state.get("error")
                    if isinstance(error_text, dict):
                        error_text = error_text.get("message") or error_text.get("name") or str(error_text)
                    output = f"{output}\n{self._text(error_text)}".strip()
                await on_event(AgentEvent(
                    type="tool_result",
                    payload={
                        "tool_use_id": self._text(block.get("id")),
                        "output": output,
                        "is_error": status == "error",
                    },
                    provider="opencode",
                    raw=block,
                ))

        if "usage" not in seen_types:
            usage = self._to_token_usage(final.get("tokens"))
            if usage is not None:
                payload = {k: v for k, v in usage.__dict__.items() if k != "raw"}
                await on_event(AgentEvent(
                    type="usage",
                    payload=payload,
                    provider="opencode",
                    raw=final.get("tokens") or {},
                ))

    @staticmethod
    def _tool_state_output_text(state: dict[str, Any]) -> str:
        """从 OpenCode tool state 中提取可读输出。"""
        parts: list[str] = []
        structured = state.get("structured")
        if isinstance(structured, dict):
            entries = structured.get("entries")
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict):
                        path = OpenCodeAdapter._text(entry.get("path"))
                        if path:
                            parts.append(path)
            else:
                try:
                    parts.append(json.dumps(structured, ensure_ascii=False, default=str)[:4000])
                except Exception:
                    parts.append(str(structured))
        content = state.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        parts.append(OpenCodeAdapter._text(text))
        result = state.get("result")
        if result is not None:
            try:
                parts.append(json.dumps(result, ensure_ascii=False, default=str)[:4000])
            except Exception:
                parts.append(str(result))
        joined = "\n".join(p for p in parts if p)
        if joined:
            return joined
        try:
            return json.dumps(state, ensure_ascii=False, default=str)[:4000]
        except Exception:
            return str(state)

    async def _consume_sse(
        self,
        session_id: str,
        request: AgentRunRequest,
        on_event: AgentEventSink,
    ) -> tuple[dict[str, Any], set[str]]:
        """订阅 /global/event 持久流，再发送 prompt_async，消费事件。

        注意：
        - 使用 `/global/event` 而不是 `/api/event`。`/api/event` 在回放当前
          快照后会关闭连接，无法收到后续 assistant 实时事件；`/global/event`
          是持久 SSE 流，会持续推送 `message.updated`、`message.part.updated`、
          `session.updated` 等事件。
        - 使用 `prompt_async` 发送消息，避免同步 prompt 接口持有连接直到回合
          结束，导致事件虽然已产生却迟迟不被消费。
        - 全局流包含所有会话事件，因此按 `sessionID` 过滤。
        """
        client = await self._ensure_client()
        result_payload: dict[str, Any] = {}
        seen_types: set[str] = set()
        message_roles: dict[str, str] = {}
        message_agents: dict[str, str] = {}
        known_model: Optional[str] = None

        async with client.stream(
            "GET",
            f"{self.server_url}/global/event",
        ) as response:
            if response.status_code != 200:
                raise AgentError(
                    f"OpenCode event stream failed: HTTP {response.status_code} {response.text[:300]}"
                )

            # 使用 /global/event 持久流：/api/event 只回放当前快照后会关闭，
            # 无法收到后续 assistant 实时事件；/global/event 会持续推送。
            # 流已就绪后再发送 prompt_async，期间产生的 SSE 事件由 httpx 缓冲。
            await self._send_prompt(session_id, request)

            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw_text = line[5:].strip()
                if not raw_text:
                    continue
                try:
                    raw_frame = json.loads(raw_text)
                except json.JSONDecodeError:
                    continue
                # /global/event 外层是 { directory, project, payload }，
                # payload 才是真正的 OpenCode 事件；sync 只是重复投递，跳过。
                raw_event = raw_frame.get("payload") if isinstance(raw_frame.get("payload"), dict) else raw_frame
                if not isinstance(raw_event, dict) or raw_event.get("type") == "sync":
                    continue
                # 全局事件流包含所有会话事件，只处理当前会话的数据。
                event_payload = raw_event.get("data") if isinstance(raw_event.get("data"), dict) else (
                    raw_event.get("properties") if isinstance(raw_event.get("properties"), dict) else {}
                )
                if self._text(event_payload.get("sessionID")) != session_id:
                    continue
                raw_type = self._text(raw_event.get("type"))
                if raw_type == "session.updated":
                    info = event_payload.get("info") if isinstance(event_payload.get("info"), dict) else {}
                    model_ref = info.get("model") if isinstance(info.get("model"), dict) else {}
                    model_name = self._text(
                        model_ref.get("id") or model_ref.get("modelID") or info.get("modelID")
                    )
                    if model_name and model_name != known_model:
                        known_model = model_name
                        await on_event(AgentEvent(
                            type="session_started",
                            payload={
                                "provider_session_id": session_id,
                                "provider": "opencode",
                                "model": model_name,
                                "directory": request.project_path,
                            },
                            provider="opencode",
                        ))
                if raw_type == "message.updated":
                    info = event_payload.get("info") if isinstance(event_payload.get("info"), dict) else {}
                    mid = self._text(info.get("id"))
                    role = self._text(info.get("role"))
                    agent = self._text(info.get("agent"))
                    if mid and role:
                        message_roles[mid] = role
                    if mid and agent:
                        message_agents[mid] = agent
                    # 标题/摘要等内部消息不是真正的用户回复，忽略其终态，
                    # 避免在 build agent 真正完成前误判回合结束。
                    if agent in ("title", "summary"):
                        continue
                # message.part.* 不携带 role/agent，需要根据 message.updated 记录的
                # 消息角色与 agent 过滤用户消息和内部标题/摘要消息。
                msg_id = ""
                if raw_type == "message.part.updated":
                    part = event_payload.get("part") if isinstance(event_payload.get("part"), dict) else {}
                    msg_id = self._text(part.get("messageID"))
                elif raw_type == "message.part.delta":
                    msg_id = self._text(event_payload.get("messageID"))
                if msg_id and message_roles.get(msg_id) == "user":
                    continue
                if msg_id and message_agents.get(msg_id) in ("title", "summary"):
                    continue
                for unified in map_opencode_event(raw_event):
                    seen_types.add(unified.type)
                    if unified.type == "result":
                        # 不在 SSE 中重复发 result；由 run() 在拿到最终 message 后补发
                        # 带完整文本的 result。
                        result_payload = {
                            "finish_reason": unified.payload.get("finish_reason") or "completed",
                            "success": True,
                        }
                        return result_payload, seen_types
                    await on_event(unified)
                    if unified.type == "error":
                        result_payload = {
                            "finish_reason": unified.payload.get("finish_reason") or "error",
                            "success": False,
                        }
                        return result_payload, seen_types
        return result_payload, seen_types

    async def run(self, request: AgentRunRequest, on_event: AgentEventSink) -> AgentRunResult:
        await self._ensure_client()
        self._running = True
        self._run_id = request.run_id
        self._interrupted = False
        started_at = time.monotonic()
        watchdog = AgentActivityWatchdog(
            startup_timeout_seconds=request.startup_timeout_seconds,
            idle_timeout_seconds=request.idle_timeout_seconds,
            hard_timeout_seconds=request.timeout_seconds,
        )

        async def _tracked_event(event: AgentEvent) -> None:
            watchdog.mark(event.type)
            await on_event(event)
        session_id = request.session_id or ""
        try:
            if request.session_id:
                session_id = request.session_id
            else:
                session_id = await self._create_session(request)
            self._session_id = session_id

            await _tracked_event(AgentEvent(
                type="session_started",
                payload={
                    "provider_session_id": session_id,
                    "provider": "opencode",
                    "model": request.model,
                    "directory": request.project_path,
                },
                provider="opencode",
            ))

            consume_task = asyncio.create_task(
                self._consume_sse(session_id, request, _tracked_event)
            )
            try:
                consumed, seen_types = await watchdog.wait(consume_task)
            except AgentTimeoutError:
                await self.interrupt(session_id=session_id)
                consume_task.cancel()
                await asyncio.gather(consume_task, return_exceptions=True)
                final = await self._fetch_final_message(session_id)
                await self._emit_missing_final_events(
                    final, set(), _tracked_event,
                )
                raise

            finish_reason = consumed.get("finish_reason")
            success = bool(consumed.get("success"))
            final = await self._fetch_final_message(session_id)
            await self._emit_missing_final_events(
                final, seen_types, _tracked_event,
            )
            if not finish_reason:
                finish_reason = self._normalize_finish_reason(final.get("finish")) or ("completed" if success else "error")
            if self._interrupted:
                finish_reason = "interrupted"

            await _tracked_event(AgentEvent(
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
