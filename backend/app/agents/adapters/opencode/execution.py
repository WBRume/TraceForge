"""Observe one durable OpenCode inbox item across transport/worker restarts.

SSE is volatile. Terminal evidence must belong to our input, never just the
session. Native question cancellation may omit idle but leaves an aborted tool.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import random
import time
import uuid

import httpx

from app.agents.adapters.opencode.event_mapper import map_opencode_event, opencode_event_session_id
from app.agents.errors import AgentExecutionDetached, AgentTimeoutError
from app.agents.events import AgentEvent
from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__, category="ai_session")


class StreamDisconnected(Exception):
    pass


def message_key(session_id: str, message_id: str, text: str) -> str:
    return hashlib.sha256(f"{session_id}\0{message_id}\0{text}".encode()).hexdigest()


def turn_messages(messages: list[dict], prompt_id: str) -> list[dict]:
    boundary = next((i for i, row in enumerate(messages) if row.get("id") == prompt_id), None)
    if boundary is None:
        return []
    result = []
    for row in messages[boundary + 1 :]:
        if row.get("type") == "user":
            break
        result.append(row)
        if row.get("type") == "idle":
            break
    return result


def aborted_tool_turn(messages: list[dict]) -> bool:
    """Recognize a completed interruption within the owned input's message slice."""
    if not messages:
        return False
    last = messages[-1]
    if (
        last.get("type") != "assistant"
        or last.get("finish") != "error"
        or not (last.get("time") or {}).get("completed")
    ):
        return False
    return any(
        part.get("type") == "tool"
        and (part.get("state") or {}).get("status") == "error"
        and isinstance((part.get("state") or {}).get("error"), dict)
        and part["state"]["error"].get("type") == "aborted"
        for part in last.get("content", [])
    )


class ExecutionMonitor:
    def __init__(self, adapter, session_id, request, on_event):
        self.adapter, self.session_id = adapter, session_id
        self.request, self.on_event = request, on_event
        self.checkpoint = copy.deepcopy(request.execution_checkpoint or {})
        self.restoring = bool(self.checkpoint)
        self.checkpoint.setdefault("version", 1)
        self.checkpoint.setdefault("session_id", session_id)
        self.checkpoint.setdefault("prompt_id", "msg_" + uuid.uuid4().hex)
        self.checkpoint.setdefault("deadline", time.time() + request.timeout_seconds)
        self.checkpoint.setdefault("phase", "prepared")
        self.interactions = self.checkpoint.get("interactions", {})
        self.adapter._user_message_id = self.checkpoint["prompt_id"]
        self.adapter._execution_checkpoint = self.checkpoint
        self.seen_types: set[str] = set()
        self.delivered: set[str] = set()
        self.last_check = time.monotonic()
        self.interval = min(settings.OPENCODE_RECONCILE_INTERVAL_SECONDS, request.idle_timeout_seconds / 3)
        self.watchdog = adapter._watchdog

    async def save(self):
        if self.request.on_execution_checkpoint:
            try:
                await self.request.on_execution_checkpoint(copy.deepcopy(self.checkpoint))
            except AgentExecutionDetached:
                raise
            except Exception as exc:
                raise AgentExecutionDetached("Remote execution checkpoint could not be persisted") from exc

    async def get_data(self, path: str):
        client = await self.adapter._ensure_client()
        response = await client.get(path)
        response.raise_for_status()
        return response.json()["data"]

    async def ensure_submitted(self):
        phase = self.checkpoint["phase"]
        if phase == "submitted":
            return
        if time.time() >= self.checkpoint["deadline"]:
            raise AgentTimeoutError(
                "OpenCode execution deadline has expired", phase="hard", limit_seconds=self.request.timeout_seconds
            )
        if phase == "submitting":
            messages = await self.adapter.list_messages(self.session_id)
            inbox = await self.get_data(self.adapter._session_url(self.session_id, "/inbox"))
            if any(row.get("id") == self.checkpoint["prompt_id"] for row in [*messages, *inbox]):
                self.checkpoint["phase"] = "submitted"
                await self.save()
                return
        self.checkpoint["phase"] = "submitting"
        await self.save()  # Intent + stable input ID must commit before POST.
        await self.adapter._send_prompt(self.session_id, self.request)
        self.checkpoint["phase"] = "submitted"
        await self.save()

    async def emit(self, event: AgentEvent, key: str = ""):
        if key and key in self.delivered:
            return
        if event.type in {"ask_user", "ask_user_resolved"}:
            rid = str(event.payload.get("ask_user_id") or "")
            if not rid:
                return
            entry = self.interactions.setdefault(rid, {})
            self.checkpoint["interactions"] = self.interactions
            field = "request" if event.type == "ask_user" else "resolution"
            if field == "request" and entry.get("resolution"):
                return
            if field == "resolution" and entry.get("resolution"):
                event.payload = entry["resolution"]
            entry[field] = dict(event.payload)
            # Persist before publication so worker recovery can replay a lost callback.
            await self.save()
            if field == "resolution":
                self.adapter._complete_ask(rid)
        if event.type == "text" and key:
            event.payload["provider_event_key"] = key
        await self.on_event(event)
        self.seen_types.add(event.type)
        if key:
            self.delivered.add(key)

    async def restore_messages(self, messages: list[dict]):
        for row in messages:
            if row.get("type") != "assistant" or row.get("agent") in {"title", "summary"}:
                continue
            mid = str(row.get("id") or "")
            self.adapter._message_ids.add(mid)
            # Only completed assistant messages contain stable text. An active
            # partially projected response must not become a permanent bubble.
            completed = bool((row.get("time") or {}).get("completed"))
            for part in row.get("content", []):
                kind = part.get("type")
                if kind == "text" and completed and part.get("text"):
                    text = str(part["text"])
                    await self.emit(
                        AgentEvent(type="text", payload={"text": text}, provider="opencode"),
                        message_key(self.session_id, mid, text),
                    )
                elif kind == "tool":
                    tid = str(part.get("id") or "")
                    state = part.get("state") or {}
                    if state.get("status") == "streaming":
                        continue
                    await self.emit(
                        AgentEvent(
                            type="tool_use",
                            provider="opencode",
                            payload={
                                "tool_use_id": tid,
                                "tool_name": part.get("name", "unknown"),
                                "tool_input": state.get("input", {}),
                            },
                        ),
                        f"tool_use:{tid}",
                    )
                    if state.get("status") in {"completed", "error"}:
                        await self.emit(
                            AgentEvent(
                                type="tool_result",
                                provider="opencode",
                                payload={
                                    "tool_use_id": tid,
                                    "output": self.adapter._tool_state_output_text(state),
                                    "is_error": state.get("status") == "error",
                                    "provider_replay": True,
                                },
                            ),
                            f"tool_result:{tid}",
                        )

    async def restore_asks(self, *, terminal: bool = False):
        pending = set()
        for suffix, kind in () if terminal else (("form", "form.created"), ("permission", "permission.asked")):
            rows = await self.get_data(self.adapter._session_url(self.session_id, "/" + suffix))
            for row in rows:
                rid = str(row.get("id") or "")
                pending.add(rid)
                data = {"form": row} if suffix == "form" else {**row, "sessionID": self.session_id}
                for event in map_opencode_event({"type": kind, "data": data}):
                    await self.emit(event, f"ask:{rid}")
        for rid, entry in list(self.interactions.items()):
            if entry.get("resolution"):
                await self.emit(
                    AgentEvent(type="ask_user_resolved", payload=entry["resolution"], provider="opencode"),
                    f"resolved:{rid}",
                )
                continue
            if rid in pending:
                continue
            # Recreate the public question if the worker died before publishing it.
            if entry.get("request"):
                await self.emit(
                    AgentEvent(type="ask_user", payload=entry["request"], provider="opencode"), f"ask:{rid}"
                )
            resolution = await self.adapter.get_interaction_resolution(rid)
            if resolution:
                await self.emit(
                    AgentEvent(type="ask_user_resolved", payload=resolution, provider="opencode"), f"resolved:{rid}"
                )

    async def reconcile(self):
        if self.watchdog:
            self.watchdog.pause_idle()  # A status lookup in flight is not idle evidence.
        await self.save()  # Also fences observation and terminal finalization.
        messages = await self.adapter.list_messages(self.session_id)
        current = turn_messages(messages, self.checkpoint["prompt_id"])
        await self.restore_messages(current)
        terminal = next((row for row in current if row.get("type") == "idle"), None)
        await self.restore_asks(terminal=bool(terminal))
        self.last_check = time.monotonic()
        if terminal and terminal.get("outcome") in {"succeeded", "failed", "interrupted"}:
            outcome = terminal["outcome"]
            return {
                "success": outcome == "succeeded",
                "finish_reason": {"succeeded": "completed", "failed": "error"}.get(outcome, outcome),
            }
        active = await self.get_data(self.adapter.server_url + "/api/session/active")
        inbox = await self.get_data(self.adapter._session_url(self.session_id, "/inbox"))
        if self.session_id not in active and not inbox and aborted_tool_turn(current):
            return {"success": False, "finish_reason": "interrupted"}
        admitted = any(row.get("id") == self.checkpoint["prompt_id"] for row in [*messages, *inbox])
        if admitted and self.checkpoint["phase"] != "submitted":
            self.checkpoint["phase"] = "submitted"
            await self.save()
        if self.watchdog:
            if not self.adapter._pending_asks:
                # Do not reset a genuinely idle execution on every successful GET.
                self.watchdog.set_idle_paused(False)
            if admitted and self.session_id in active:
                self.watchdog.confirm_remote_liveness()
        return None

    async def pump(self, queue):
        try:
            client = await self.adapter._ensure_client()
            async with client.stream(
                "GET", self.adapter.server_url + "/api/event", timeout=httpx.Timeout(30, read=None)
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:].strip())
                        if isinstance(event, str):
                            event = json.loads(event)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(event, dict):
                        await queue.put(event)
            await queue.put(StreamDisconnected("OpenCode event stream closed"))
        except Exception as exc:
            await queue.put(exc)

    async def handle_event(self, event):
        kind = event.get("type")
        if kind == "server.connected":
            await self.ensure_submitted()
            if self.restoring:
                return await self.reconcile()
            return None
        if self.checkpoint["phase"] != "submitted" or opencode_event_session_id(event) != self.session_id:
            return None
        data = event.get("data") or {}
        if kind in {"session.execution.succeeded", "session.execution.failed", "session.execution.interrupted"}:
            # A prior execution can finish while our input is still queued.
            # Session ID alone never establishes ownership of this terminal.
            return await self.reconcile()
        mid = str(data.get("assistantMessageID") or data.get("messageID") or "")
        if mid:
            self.adapter._message_ids.add(mid)
        if kind in {"session.model.switched", "session.step.started"}:
            model = data.get("model") or {}
            if model.get("id"):
                name = f"{model['providerID']}/{model['id']}" if model.get("providerID") else model["id"]
                await self.emit(AgentEvent(type="model", payload={"model": name}, provider="opencode"))
        for unified in map_opencode_event(event):
            if unified.type == "result":
                continue  # A model step is not a terminal execution.
            key = ""
            if unified.type == "text" and mid:
                key = message_key(self.session_id, mid, unified.payload.get("text", ""))
            elif unified.type in {"tool_use", "tool_result"}:
                key = f"{unified.type}:{unified.payload.get('tool_use_id')}"
            elif unified.type == "ask_user":
                key = f"ask:{unified.payload.get('ask_user_id')}"
            elif unified.type == "ask_user_resolved":
                key = f"resolved:{unified.payload.get('ask_user_id')}"
            await self.emit(unified, key)
        return None

    async def _observe_next_result(self, queue):
        try:
            async with asyncio.timeout(max(0.01, self.interval)):
                event = await queue.get()
        except TimeoutError:
            event = None
        if isinstance(event, Exception):
            raise event
        result = await self.handle_event(event) if event else None
        if result:
            return result
        # Snapshot only on silence, reconnect, or a recovery request.
        if self.checkpoint["phase"] == "submitted" and time.monotonic() - self.last_check >= self.interval:
            if event is None or not self.watchdog or self.watchdog.quiet_seconds >= self.interval:
                result = await self.reconcile()
                if result:
                    return result
            else:
                self.last_check = time.monotonic()
        return None

    async def run(self):
        await self.save()
        failures = 0
        while True:
            connected_at = time.monotonic()
            queue = asyncio.Queue(maxsize=256)
            pump = asyncio.create_task(self.pump(queue))
            try:
                while True:
                    result = await self._observe_next_result(queue)
                    if result:
                        return result, self.seen_types

                    if time.monotonic() - connected_at >= 30:
                        failures = 0
            except (StreamDisconnected, httpx.HTTPError, OSError) as exc:
                if (
                    isinstance(exc, httpx.HTTPStatusError)
                    and exc.response.status_code < 500
                    and exc.response.status_code not in {408, 409, 429}
                ):
                    raise AgentExecutionDetached(
                        f"OpenCode observation requires attention: HTTP {exc.response.status_code}"
                    ) from exc
                self.restoring = True
                if self.watchdog:
                    self.watchdog.pause_idle()  # Transport loss is not evidence of agent inactivity.
                logger.warning(
                    "OpenCode observation reconnect: session={}, error={}", self.session_id, type(exc).__name__
                )
            finally:
                pump.cancel()
                await asyncio.gather(pump, return_exceptions=True)
            try:
                if self.checkpoint["phase"] == "submitted":
                    result = await self.reconcile()
                    if result:
                        return result, self.seen_types
            except (httpx.HTTPError, OSError):
                pass
            if self.watchdog:
                self.watchdog.pause_idle()
            failures += 1
            await asyncio.sleep(min(30, 0.5 * 2 ** min(failures, 6)) * random.uniform(0.8, 1.2))
