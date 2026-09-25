"""OpenCode 2.x server adapter using /api routes and native session events.

Subscribe before enqueuing a prompt. A step ending is not a turn ending;
only session.execution.* terminal events settle an execution.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Optional

import httpx
from app.agents.http_transport import agent_ssl_context

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
    def get_runtime_control(self):
        from app.agents.runtime_control import runtime_control_for
        return runtime_control_for(self)

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
        # 服务端执行：不创建本地受监管子进程，必须显式声明（doc 6.3）。
        execution_kind="REMOTE_SESSION",
    )

    def __init__(self, server_url: str = "http://127.0.0.1:4097", *, username: str = "opencode", password: str = "") -> None:
        self.server_url = server_url.rstrip("/")
        self._auth = (username, password) if password else None
        self._client: Optional[httpx.AsyncClient] = None
        self._running = False
        self._run_id: Optional[str] = None
        self._session_id: Optional[str] = None
        self._interrupted = False
        self._message_ids: set[str] = set()
        self._user_message_id: Optional[str] = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                trust_env=False, verify=agent_ssl_context(),
                auth=self._auth,
            )
        return self._client

    def _session_url(self, session_id: str, path: str = "") -> str:
        return f"{self.server_url}/api/session/{session_id}{path}"

    @staticmethod
    def _is_json_response(response: httpx.Response) -> bool:
        headers = getattr(response, "headers", None)
        if headers is None:
            # Keep lightweight test doubles and older adapter transports
            # compatible; real httpx responses always expose headers.
            return response.status_code == 200
        content_type = str(headers.get("content-type") or "").lower()
        return response.status_code == 204 or "json" in content_type

    async def probe(self) -> str:
        client = await self._ensure_client()
        try:
            response = await client.get(self.server_url + "/api/info")
            if response.status_code != 200 or not self._is_json_response(response) or not str(response.json().get("version", "")).startswith("2."):
                raise AgentError("OpenCode v2 /api/info response is invalid; OpenCode 2.x is required")
        except Exception as exc:
            raise AgentError(f"OpenCode server unreachable: {exc}") from exc
        return f"OpenCode server is reachable at {self.server_url} (HTTP {response.status_code})"

    async def _create_session(self, request: AgentRunRequest) -> str:
        client = await self._ensure_client()
        body: dict[str, Any] = {}
        if request.project_path:
            body["location"] = {"directory": request.project_path}
        if request.model:
            body["model"] = self._model_ref(request.model)
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
        prompt_text = request.prompt
        normalized_mode = str(request.permission_mode or "").strip().lower()
        if normalized_mode in {"read-only", "readonly"}:
            # 只读运行：不再切换到 plan agent——plan agent 的“调研→计划”行为
            # 会把结论写进计划消息而非直接输出，破坏「仅输出 JSON 总结」契约。
            # 改为注入只读约束前缀（与 dsh adapter 的做法一致）。
            prompt_text = (
                "[只读会话约束] 只能分析、读取和总结；禁止创建、修改、删除文件，"
                "禁止执行会改变项目或外部系统状态的命令。\n\n"
                + prompt_text
            )
        policy = request.provider_options.get("execution_policy")
        if policy is not None and policy.get("enforcement") != "ADVISORY_GUARD":
            if request.provider_options.get("dedicated_backend_host") is not True:
                raise AgentError("SOP_DEDICATED_BACKEND_HOST_REQUIRED")
        if request.model:
            response = await client.post(self._session_url(session_id, "/model"), json={"model": self._model_ref(request.model)})
            self._check_response(response, "switch model")
        if normalized_mode == "plan":
            response = await client.post(self._session_url(session_id, "/agent"), json={"agent": "plan"})
            self._check_response(response, "switch agent")
        if policy is not None and policy.get("enforcement") != "ADVISORY_GUARD":
            # Runtime MCP credentials remain restricted to a dedicated host.
            location = {"location[directory]": request.project_path} if request.project_path else {}
            configured = await client.put(f"{self.server_url}/api/experimental/mcp/traceforge_playbook", params=location, json={
                "config": {"type": "remote", "url": policy["mcp_config"]["url"],
                           "headers": policy["mcp_config"]["headers"], "oauth": False, "codemode": False},
            })
            self._check_response(configured, "configure MCP")
            listed = await client.get(f"{self.server_url}/api/mcp", params=location)
            self._check_response(listed, "MCP status")
            if not any(item.get("name") == "traceforge_playbook" and item.get("status", {}).get("status") == "connected"
                       for item in listed.json().get("data", [])):
                raise AgentError("SOP_MCP_NOT_CONNECTED")
            allowed = ["read_source", "propose_hypotheses", "propose_experiment"]
            if policy["tier"] == "WORKSPACE_WRITE":
                allowed.append("propose_patch")
            permissions = [{"action": "*", "resource": "*", "effect": "deny"}]
            permissions.extend({"action": f"traceforge_playbook_{tool}", "resource": "*", "effect": "allow"} for tool in allowed)
            configured = await client.patch(self._session_url(session_id), json={"permissions": permissions})
            self._check_response(configured, "session permissions")
        response = await client.post(self._session_url(session_id, "/prompt"), json={"text": prompt_text})
        self._check_response(response, "prompt")
        data = response.json().get("data", {})
        if not isinstance(data, dict) or not data.get("id"):
            raise AgentError("OpenCode prompt returned no inbox message id")
        self._user_message_id = str(data["id"])
        self._message_ids.add(self._user_message_id)

    @staticmethod
    def _model_ref(model: str) -> dict[str, str]:
        provider, separator, name = model.partition("/")
        return {"providerID": provider if separator else "opencode", "id": name if separator else model}

    @classmethod
    def _check_response(cls, response: httpx.Response, operation: str) -> None:
        if response.status_code == 204 or (response.status_code == 200 and cls._is_json_response(response)):
            return
        raise AgentError(f"OpenCode {operation} failed: HTTP {response.status_code} {response.text[:300]}")

    async def _fetch_final_message(self, session_id: str) -> dict[str, Any]:
        messages = await self.list_messages(session_id)
        # Do not return an earlier turn when the current prompt produced no answer.
        if self._user_message_id:
            boundary = next((i for i, item in enumerate(messages) if item.get("id") == self._user_message_id), None)
            if boundary is None:
                return {}
            messages = messages[boundary + 1:]
        assistants = [item for item in messages if item.get("type") == "assistant" and item.get("agent") not in {"title", "summary"}]
        if not assistants:
            return {}
        last = assistants[-1]
        content = [part for item in assistants for part in item.get("content", []) if isinstance(part, dict)]
        return {**last, "text": "\n".join(str(part.get("text", "")) for part in last.get("content", []) if part.get("type") == "text"), "content": content}

    async def revert_message(self, session_id: str, message_id: str, part_id: str | None = None) -> bool:
        if part_id:
            raise AgentError("OpenCode v2 revert requires a whole-message boundary")
        client = await self._ensure_client()
        response = await client.post(self._session_url(session_id, "/revert/stage"), json={"messageID": message_id, "files": False})
        self._check_response(response, "stage revert")
        response = await client.post(self._session_url(session_id, "/revert/commit"))
        self._check_response(response, "commit revert")
        return True

    async def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        client = await self._ensure_client()
        messages: list[dict[str, Any]] = []
        params: dict[str, Any] = {"limit": 200, "order": "asc"}
        cursors: set[str] = set()
        while True:
            response = await client.get(self._session_url(session_id, "/message"), params=params)
            self._check_response(response, "list messages")
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("data"), list) or not isinstance(data.get("cursor"), dict):
                raise AgentError("OpenCode v2 message listing returned an invalid page")
            messages.extend(item for item in data["data"] if isinstance(item, dict))
            cursor = data["cursor"].get("next")
            if not cursor:
                return messages
            if cursor in cursors:
                raise AgentError("OpenCode message pagination repeated a cursor")
            cursors.add(cursor)
            params = {"limit": 200, "cursor": cursor}

    async def wait_until_idle(self, session_id: str, timeout_seconds: float = 30.0) -> None:
        client = await self._ensure_client()
        deadline = time.monotonic() + max(0.1, timeout_seconds)
        while time.monotonic() < deadline:
            response = await client.get(f"{self.server_url}/api/session/active")
            self._check_response(response, "active sessions")
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
                raise AgentError("OpenCode active sessions response is invalid")
            if session_id not in payload["data"]:
                return
            await asyncio.sleep(0.1)
        raise AgentError("OpenCode session did not become idle before undo")

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
            "length": "max-tokens",
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
        self, session_id: str, request: AgentRunRequest, on_event: AgentEventSink,
    ) -> tuple[dict[str, Any], set[str]]:
        """Open the v2 live stream before submitting the prompt to its inbox."""
        client = await self._ensure_client()
        seen_types: set[str] = set()
        sent = False
        finish_reason = "completed"
        async with client.stream("GET", f"{self.server_url}/api/event", timeout=httpx.Timeout(30.0, read=None)) as response:
            if response.status_code != 200:
                raise AgentError(f"OpenCode event stream failed: HTTP {response.status_code}")
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[5:].strip())
                    if isinstance(event, str):
                        event = json.loads(event)
                except (ValueError, TypeError):
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("type") == "server.connected" and not sent:
                    await self._send_prompt(session_id, request)
                    sent = True
                    continue
                data = event.get("data")
                if not sent or not isinstance(data, dict) or data.get("sessionID") != session_id:
                    continue
                kind = event.get("type")
                if kind in {"session.execution.succeeded", "session.execution.failed", "session.execution.interrupted"}:
                    success = kind == "session.execution.succeeded"
                    if kind == "session.execution.failed":
                        await on_event(AgentEvent(type="error", payload={"success": False, "finish_reason": "error", "result": str(data.get("error") or "OpenCode execution failed")}, provider="opencode", raw=event))
                    return {"success": success, "finish_reason": finish_reason if success else ("interrupted" if kind.endswith("interrupted") else "error")}, seen_types
                message_id = data.get("assistantMessageID") or data.get("messageID")
                if message_id:
                    self._message_ids.add(str(message_id))
                if kind in {"session.model.switched", "session.step.started"}:
                    model = data.get("model") or {}
                    if model.get("id"):
                        await on_event(AgentEvent(type="model", payload={"model": model["id"], "provider_session_id": session_id}, provider="opencode"))
                for unified in map_opencode_event(event):
                    seen_types.add(unified.type)
                    if unified.type == "result":
                        finish_reason = unified.payload.get("finish_reason") or finish_reason
                        continue
                    await on_event(unified)
                    if unified.type == "error":
                        finish_reason = "error"
        raise AgentError("OpenCode v2 event stream closed before the turn completed")

    async def run(self, request: AgentRunRequest, on_event: AgentEventSink) -> AgentRunResult:
        await self._ensure_client()
        self._running = True
        self._run_id = request.run_id
        self._interrupted = False
        self._message_ids = set()
        self._user_message_id = None
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
                stop = await self.interrupt(session_id=session_id)
                from app.agents.contract import record_attempt_remote_stop

                record_attempt_remote_stop(stop)
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
                metadata={
                    "provider_message_ids": sorted(self._message_ids),
                    "provider_user_message_id": self._user_message_id,
                    "provider_assistant_message_id": final.get("id"),
                },
            )
        except Exception as exc:
            if isinstance(exc, AgentError):
                raise
            raise AgentError(f"OpenCode run failed: {exc}") from exc
        finally:
            self._running = False
            self._run_id = None

    async def _abort_session(self, sid: str) -> "AgentStopResult":
        """Interrupt the v2 worker and verify quiescence before acknowledging stop."""
        from app.agents.contract import EXECUTION_KIND_REMOTE_SESSION, AgentStopResult

        if self._client is None:
            return AgentStopResult(
                execution_kind=EXECUTION_KIND_REMOTE_SESSION,
                stop_acknowledged=False,
                failure_code="REMOTE_STOP_UNCONFIRMED",
                error_message="OpenCode client is closed; abort not sent",
            )
        try:
            response = await self._client.post(self._session_url(sid, "/interrupt"), params={"resume": "false"})
        except Exception as exc:
            return AgentStopResult(
                execution_kind=EXECUTION_KIND_REMOTE_SESSION,
                stop_acknowledged=False,
                failure_code="OPENCODE_ABORT_NETWORK_ERROR",
                error_message=str(exc) or type(exc).__name__,
            )
        if response.status_code == 200 and self._is_json_response(response):
            payload = response.json()
            if isinstance(payload, dict) and isinstance(payload.get("interrupted"), bool):
                try:
                    await self.wait_until_idle(sid)
                except (AgentError, httpx.HTTPError, ValueError) as exc:
                    return AgentStopResult(execution_kind=EXECUTION_KIND_REMOTE_SESSION, stop_acknowledged=False,
                                           failure_code="REMOTE_STOP_UNCONFIRMED", error_message=str(exc))
                return AgentStopResult(execution_kind=EXECUTION_KIND_REMOTE_SESSION, stop_acknowledged=True)
        return AgentStopResult(
            execution_kind=EXECUTION_KIND_REMOTE_SESSION,
            stop_acknowledged=False,
            failure_code="OPENCODE_ABORT_REJECTED",
            error_message=f"OpenCode abort returned HTTP {response.status_code}",
        )

    async def interrupt(
        self, run_id: str | None = None, *, session_id: str | None = None
    ) -> "AgentStopResult":
        from app.agents.contract import EXECUTION_KIND_REMOTE_SESSION, AgentStopResult

        sid = session_id or self._session_id
        if not sid:
            return AgentStopResult(
                execution_kind=EXECUTION_KIND_REMOTE_SESSION,
                stop_acknowledged=False,
                failure_code="REMOTE_STOP_UNCONFIRMED",
                error_message="no active OpenCode session to abort",
            )
        self._interrupted = True
        return await self._abort_session(sid)

    async def cancel(self, run_id: str | None = None) -> "AgentStopResult":
        from app.agents.contract import EXECUTION_KIND_REMOTE_SESSION, AgentStopResult

        sid = self._session_id
        self._interrupted = True
        self._running = False
        if not sid:
            return AgentStopResult(
                execution_kind=EXECUTION_KIND_REMOTE_SESSION,
                stop_acknowledged=False,
                failure_code="REMOTE_STOP_UNCONFIRMED",
                error_message="no active OpenCode session to abort",
            )
        return await self._abort_session(sid)

    async def cancel_persisted_session(self, session_id: str) -> "AgentStopResult":
        """Reaper durable stop：目标必须是显式传入的持久化 session id。

        禁止回退到 ``self._session_id``（reaper 每次新建 adapter，内存
        session 必然为空；doc 修复方案 §9.3 的 P1-3 修复）。
        """
        from app.agents.contract import EXECUTION_KIND_REMOTE_SESSION, AgentStopResult

        sid = str(session_id or "").strip()
        self._running = False
        if not sid:
            return AgentStopResult(
                execution_kind=EXECUTION_KIND_REMOTE_SESSION,
                stop_acknowledged=False,
                failure_code="REMOTE_STOP_LOCATOR_MISSING",
                error_message="persisted OpenCode session id is required",
            )
        return await self._abort_session(sid)

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
            body = {"decision": reply}
        elif ask_user_id.startswith("frm_"):
            detail = await client.get(self._session_url(sid, f"/form/{ask_user_id}"))
            self._check_response(detail, "get form")
            fields = detail.json().get("data", {}).get("fields", [])
            try:
                answer = json.loads(response)
            except ValueError:
                answer = None
            if not isinstance(answer, dict):
                if len(fields) != 1 or fields[0].get("type") != "string":
                    raise AgentError("OpenCode form requires a JSON object keyed by its field names")
                answer = {fields[0]["key"]: response}
            url = self._session_url(sid, f"/form/{ask_user_id}/reply")
            body = {"answer": answer}
        else:
            raise AgentError("OpenCode v2 requires a permission or form request id")
        result = await client.post(url, json=body)
        self._check_response(result, "HITL reply")

    # ── 会话 fork（baseline → 评审线程）────────────────────────
    async def _fork_create(self, client: httpx.AsyncClient, session_id: str) -> str:
        response = await client.post(self._session_url(session_id, "/fork"), json={})
        try:
            self._check_response(response, "fork")
        except AgentError as exc:
            raise SessionForkError(str(exc)) from exc
        new_id = response.json().get("data", {}).get("id")
        if not new_id:
            raise SessionForkError("OpenCode fork returned no session id")
        return str(new_id)

    async def _fork_move(self, client: httpx.AsyncClient, session_id: str, target_dir: str) -> None:
        response = await client.post(self._session_url(session_id, "/move"), json={"directory": target_dir})
        try:
            self._check_response(response, "move")
        except AgentError as exc:
            raise SessionForkError(str(exc)) from exc

    async def delete_session(self, session_id: str) -> bool:
        client = await self._ensure_client()
        response = await client.delete(self._session_url(session_id))
        self._check_response(response, "delete session")
        return True

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
            if (source_dir or "").replace("\\", "/").rstrip("/") != (target_dir or "").replace("\\", "/").rstrip("/"):
                await self._fork_move(client, new_id, target_dir)
        except SessionForkError:
            # move 失败时清理 fork 产物，避免遗留孤儿会话
            await self.delete_session(new_id)
            raise
        return new_id
