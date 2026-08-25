"""Agent turn liveness watchdog shared by subprocess and server adapters."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable
from typing import TypeVar

from app.agents.errors import AgentTimeoutError


T = TypeVar("T")

# Provider keep-alives are intentionally excluded.  These events prove that the
# agent is making user-visible or model/tool progress, rather than merely that a
# socket is still connected.
MEANINGFUL_ACTIVITY_TYPES = frozenset(
    {
        "session_started",
        "thinking",
        "text",
        "text_delta",
        "tool_use",
        "tool_result",
        "ask_user",
        "usage",
        "context_compacted",
        "result",
        "error",
    }
)


class AgentActivityWatchdog:
    """Apply startup, inactivity and hard-runtime limits to one agent turn."""

    def __init__(
        self,
        *,
        startup_timeout_seconds: float,
        idle_timeout_seconds: float,
        hard_timeout_seconds: float,
    ) -> None:
        now = time.monotonic()
        self._started_at = now
        self._last_activity_at = now
        self._has_activity = False
        self.startup_timeout_seconds = max(0.01, float(startup_timeout_seconds))
        self.idle_timeout_seconds = max(0.01, float(idle_timeout_seconds))
        self.hard_timeout_seconds = max(0.01, float(hard_timeout_seconds))

    def mark(self, event_type: str) -> None:
        if str(event_type or "").strip().lower() not in MEANINGFUL_ACTIVITY_TYPES:
            return
        self._has_activity = True
        self._last_activity_at = time.monotonic()

    def _next_timeout(self) -> tuple[str, float, float]:
        now = time.monotonic()
        hard_remaining = self.hard_timeout_seconds - (now - self._started_at)
        if self._has_activity:
            phase = "idle"
            phase_limit = self.idle_timeout_seconds
            phase_remaining = phase_limit - (now - self._last_activity_at)
        else:
            phase = "startup"
            phase_limit = self.startup_timeout_seconds
            phase_remaining = phase_limit - (now - self._started_at)

        if hard_remaining <= phase_remaining:
            return "hard", self.hard_timeout_seconds, hard_remaining
        return phase, phase_limit, phase_remaining

    async def wait(self, awaitable: Awaitable[T]) -> T:
        task = awaitable if isinstance(awaitable, asyncio.Task) else asyncio.create_task(awaitable)
        while True:
            phase, limit, remaining = self._next_timeout()
            if remaining <= 0:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise AgentTimeoutError(self._message(phase, limit))
            done, _ = await asyncio.wait({task}, timeout=remaining)
            if task in done:
                return await task

    @staticmethod
    def _message(phase: str, limit: float) -> str:
        if phase == "startup":
            return f"Agent produced no activity during startup for {limit:g}s"
        if phase == "idle":
            return f"Agent produced no meaningful activity for {limit:g}s"
        return f"Agent exceeded the hard runtime limit of {limit:g}s"
