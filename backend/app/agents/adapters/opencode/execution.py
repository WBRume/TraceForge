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
from collections import Counter

import httpx

from app.agents.adapters.opencode.event_mapper import map_opencode_event, opencode_event_session_id, text_segment_fields
from app.agents.contract import AgentInputImage
from app.agents.errors import (
    AgentError,
    AgentExecutionDetached,
    AgentPromptRejectedError,
    AgentSteeringClosedError,
    AgentSteeringRejectedError,
    AgentTimeoutError,
)
from app.agents.events import AgentEvent
from app.agents.tool_activity import mcp_tool_fields, wire_event_time
from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__, category="ai_session")
STEERING_PREFIX = "msg_tf_steer_"


class StreamDisconnected(Exception):
    pass


def message_key(session_id: str, message_id: str, text: str, occurrence: int = 0) -> str:
    # Keep the first occurrence compatible with messages persisted by older workers.
    identity = f"{session_id}\0{message_id}\0{text}"
    if occurrence:
        identity += f"\0{occurrence}"
    return hashlib.sha256(identity.encode()).hexdigest()


def turn_messages(messages: list[dict], prompt_id: str) -> list[dict]:
    boundary = next((i for i, row in enumerate(messages) if row.get("id") == prompt_id), None)
    if boundary is None:
        return []
    result = []
    for row in messages[boundary + 1 :]:
        if row.get("type") == "user" and not str(row.get("id") or "").startswith(STEERING_PREFIX):
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


async def withdraw_owned_prompt(adapter, client, session_id: str, checkpoint: dict) -> bool:
    """Withdraw pending input, or require proof before a session-level interrupt."""
    prompt_id = checkpoint.get("prompt_id")
    if not prompt_id or checkpoint.get("session_id") != session_id:
        raise AgentError(
            "OpenCode stop checkpoint belongs to a different session", failure_code="REMOTE_STOP_UNCONFIRMED"
        )
    phase = checkpoint.get("phase")
    if phase == "stopping":
        phase = checkpoint.get("phase_before_stop")
    if phase in {"prepared", "rejected"}:
        return True
    admitted = phase == "submitted"
    if not admitted:
        response = await client.get(adapter._session_url(session_id, "/inbox"))
        adapter._check_response(response, "list pending input")
        admitted = any(row.get("id") == prompt_id for row in response.json()["data"])

    await adapter._cancel_inbox_input(client, session_id, prompt_id)
    # Cancellation of an already delivered input is a provider no-op. Checking
    # history after DELETE distinguishes that case from a withdrawn queued input.
    messages = await adapter.list_messages(session_id)
    inputs = [
        row.get("id")
        for row in messages
        if row.get("type") == "user" and not str(row.get("id") or "").startswith(STEERING_PREFIX)
    ]
    if prompt_id in inputs:
        if any(
            row.get("type") == "idle" and row.get("outcome") in {"succeeded", "failed", "interrupted"}
            for row in turn_messages(messages, prompt_id)
        ):
            return True
        if inputs[-1] == prompt_id:
            return False
    elif admitted:
        return True
    raise AgentError("OpenCode could not confirm the stopped input", failure_code="REMOTE_STOP_UNCONFIRMED")


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
        self._text_occurrences: Counter[tuple[str, str]] = Counter()
        self._text_keys: dict[str, str] = {}
        self.delivered: set[str] = set()
        self.last_check = time.monotonic()
        self.interval = min(settings.OPENCODE_RECONCILE_INTERVAL_SECONDS, request.idle_timeout_seconds / 3)
        self.watchdog = adapter._watchdog
        self.prompt_delivered = False
        self.steering_open = False
        self._steering_lock = asyncio.Lock()
        self._pending_steers: set[str] = set()
        self._delivered_steers: set[str] = set()

    async def steer(self, message_id: str, content: str, *, images: tuple[AgentInputImage, ...] = ()) -> None:
        async with self._steering_lock:
            if not self.steering_open:
                raise AgentSteeringClosedError("OpenCode is outside the active prompt")
            active = await self.get_data(self.adapter.server_url + "/api/session/active")
            if not self.steering_open or self.session_id not in active or self.adapter._interrupted:
                raise AgentSteeringClosedError("OpenCode is outside the active prompt")
            provider_id = STEERING_PREFIX + message_id
            if provider_id not in self._delivered_steers:
                self._pending_steers.add(provider_id)
            client = await self.adapter._ensure_client()
            response = await client.post(
                self.adapter._session_url(self.session_id, "/prompt"),
                json={
                    **self.adapter._prompt_payload(content, images),
                    "id": provider_id,
                    "delivery": "steer",
                    "resume": False,
                },
                timeout=5,
            )
            if images and response.status_code in {400, 413, 415, 422}:
                self._pending_steers.discard(provider_id)
                raise AgentSteeringRejectedError(f"OpenCode 拒绝了图片输入（HTTP {response.status_code}）")
            self.adapter._check_response(response, "steer")
            if response.json().get("data", {}).get("id") != provider_id:
                raise AgentExecutionDetached("OpenCode steering acceptance could not be confirmed")

    async def _observe_user_input(self, provider_id: str) -> None:
        if provider_id == self.checkpoint["prompt_id"]:
            self.prompt_delivered = True
            self.steering_open = True
        elif (
            self.prompt_delivered
            and provider_id.startswith(STEERING_PREFIX)
            and provider_id not in self._delivered_steers
        ):
            if self.request.on_steering_delivered:
                await self.request.on_steering_delivered(provider_id.removeprefix(STEERING_PREFIX))
            self.adapter._message_ids.add(provider_id)
            self._delivered_steers.add(provider_id)
            self._pending_steers.discard(provider_id)

    async def _close_steering(self) -> None:
        self.steering_open = False
        async with self._steering_lock:
            if not self._pending_steers:
                return
            try:
                await self.adapter._remove_pending_steers(self.session_id, self._pending_steers)
            except (httpx.HTTPError, OSError):
                # Inputs use resume=false. The next primary prompt also clears
                # leftover steering before it wakes the provider.
                logger.warning("Could not clear pending OpenCode steering for session {}", self.session_id)

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
            return None
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
                return None
        self.checkpoint["phase"] = "submitting"
        await self.save()  # Intent + stable input ID must commit before POST.
        try:
            await self.adapter._send_prompt(self.session_id, self.request)
        except AgentPromptRejectedError as exc:
            self.checkpoint.update(phase="rejected", rejection_message=str(exc))
            await self.save()
            return self.rejected_result()
        self.checkpoint["phase"] = "submitted"
        await self.save()
        return None

    def rejected_result(self) -> dict:
        return {
            "success": False,
            "finish_reason": "input_rejected",
            "input_rejection": self.checkpoint["rejection_message"],
        }

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
            if row.get("type") == "user":
                await self._observe_user_input(str(row.get("id") or ""))
                continue
            if row.get("type") != "assistant" or row.get("agent") in {"title", "summary"}:
                continue
            mid = str(row.get("id") or "")
            self.adapter._message_ids.add(mid)
            # Only completed assistant messages contain stable text. An active
            # partially projected response must not become a permanent bubble.
            completed = bool((row.get("time") or {}).get("completed"))
            text_occurrences: Counter[str] = Counter()
            for part in row.get("content", []):
                kind = part.get("type")
                if kind == "text" and completed and part.get("text"):
                    text = str(part["text"]).strip()
                    await self.emit(
                        AgentEvent(
                            type="text",
                            payload={"text": text, **text_segment_fields(mid, part.get("textID") or part.get("id"))},
                            provider="opencode",
                        ),
                        message_key(self.session_id, mid, text, text_occurrences[text]),
                    )
                    text_occurrences[text] += 1
                elif kind == "tool":
                    tid = str(part.get("callID") or part.get("id") or "")
                    name = part.get("tool") or part.get("name")
                    state = part.get("state") or {}
                    if not tid or not isinstance(name, str) or not name or state.get("status") == "streaming":
                        continue
                    timing = part.get("time")
                    if not isinstance(timing, dict):
                        timing = {}
                    mcp = mcp_tool_fields(part.get("mcpServer") or part.get("mcp_server"))
                    await self.emit(
                        AgentEvent(
                            type="tool_use",
                            provider="opencode",
                            time=wire_event_time(timing.get("ran") or timing.get("created")),
                            payload={
                                "tool_use_id": tid,
                                "tool_name": name,
                                "tool_input": state.get("input", {}),
                                **mcp,
                            },
                        ),
                        f"tool_use:{tid}",
                    )
                    if state.get("status") in {"completed", "error"}:
                        await self.emit(
                            AgentEvent(
                                type="tool_result",
                                provider="opencode",
                                time=wire_event_time(timing.get("completed")),
                                payload={
                                    "tool_use_id": tid,
                                    "tool_name": name,
                                    "output": self.adapter._tool_state_output_text(state),
                                    "is_error": state.get("status") == "error",
                                    "structured_content": state.get("structured"),
                                    "content": state.get("content") or [],
                                    "provider_replay": True,
                                    **mcp,
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
        if self.checkpoint["phase"] == "rejected":
            return self.rejected_result()
        messages = await self.adapter.list_messages(self.session_id)
        current = turn_messages(messages, self.checkpoint["prompt_id"])
        if any(row.get("id") == self.checkpoint["prompt_id"] for row in messages):
            self.prompt_delivered = True
            self.steering_open = not any(row.get("type") == "idle" for row in current)
        await self.restore_messages(current)
        terminal = next((row for row in current if row.get("type") == "idle"), None)
        if self.prompt_delivered:
            await self.restore_asks(terminal=bool(terminal))
        self.last_check = time.monotonic()
        if terminal and terminal.get("outcome") in {"succeeded", "failed", "interrupted"}:
            await self._close_steering()
            outcome = terminal["outcome"]
            return {
                "success": outcome == "succeeded",
                "finish_reason": {"succeeded": "completed", "failed": "error"}.get(outcome, outcome),
            }
        active = await self.get_data(self.adapter.server_url + "/api/session/active")
        inbox = await self.get_data(self.adapter._session_url(self.session_id, "/inbox"))
        if (
            self.session_id not in active
            and not any(not str(row.get("id") or "").startswith(STEERING_PREFIX) for row in inbox)
            and aborted_tool_turn(current)
        ):
            await self._close_steering()
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

    def _live_text_key(self, message_id: str, payload: dict) -> str:
        text = payload["text"]
        segment = payload.get("segment_id")
        if segment and segment in self._text_keys:
            return self._text_keys[segment]
        count_key = (message_id, text)
        key = message_key(self.session_id, message_id, text, self._text_occurrences[count_key])
        if segment:
            self._text_occurrences[count_key] += 1
            self._text_keys[segment] = key
        return key

    async def handle_event(self, event):
        kind = event.get("type")
        if kind == "server.connected":
            rejected = await self.ensure_submitted()
            return rejected or (await self.reconcile() if self.restoring else None)
        if self.checkpoint["phase"] != "submitted" or opencode_event_session_id(event) != self.session_id:
            return None
        data = event.get("data") or {}
        if kind in {"session.execution.succeeded", "session.execution.failed", "session.execution.interrupted"}:
            # A prior execution can finish while our input is still queued.
            # Session ID alone never establishes ownership of this terminal.
            return await self.reconcile()
        if kind == "session.inbox.delivered":
            await self._observe_user_input(str(data.get("inboxID") or ""))
            return None
        if not self.prompt_delivered:
            # An accepted inbox input can still be queued behind another run.
            return None
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
            if unified.type == "text" and (message_id := unified.payload.get("provider_message_id") or mid):
                key = self._live_text_key(message_id, unified.payload)
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
            except (httpx.HTTPError, OSError) as exc:
                if self.request.on_execution_checkpoint:
                    raise AgentExecutionDetached("OpenCode execution could not be observed") from exc
            if self.watchdog:
                self.watchdog.pause_idle()
            failures += 1
            await asyncio.sleep(min(30, 0.5 * 2 ** min(failures, 6)) * random.uniform(0.8, 1.2))
