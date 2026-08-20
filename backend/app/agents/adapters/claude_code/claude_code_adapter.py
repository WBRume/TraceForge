"""Claude Code CLI Agent backend。

实现统一 AgentBackend，内部复用现有 SubprocessCliBridge 的进程管理能力，
将 Claude NDJSON 流通过 event_mapper 转换为统一 AgentEvent。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from app.agents.contract import (
    AgentBackend,
    AgentCapabilities,
    AgentEventSink,
    AgentRunRequest,
    AgentRunResult,
    TokenUsage,
)
from app.agents.adapters.claude_code.event_mapper import map_claude_event
from app.agents.errors import AgentCancelledError, AgentError, AgentTimeoutError
from app.engine.claude_bridge import SubprocessCliBridge


class ClaudeCodeAdapter(AgentBackend):
    name = "claude-code"
    capabilities = AgentCapabilities(
        supports_resume=True,
        supports_streaming_text=False,
        supports_tool_events=True,
        hitl_modes=["turn_based"],
        supports_usage=True,
        skill_layouts=["claude-skills"],
        preferred_mode="subprocess",
    )

    def __init__(self, cli_path: Optional[str] = None) -> None:
        self._bridge = SubprocessCliBridge(cli_path=cli_path)
        self._last_result_payload: Dict[str, Any] = {}
        self._cancelled = False

    async def _handle_raw_event(self, event: dict[str, Any], on_event: AgentEventSink) -> None:
        for agent_event in map_claude_event(event):
            if agent_event.type == "result" or agent_event.type == "error":
                self._last_result_payload = dict(agent_event.payload)
            if agent_event.type == "session_started":
                sid = agent_event.payload.get("provider_session_id")
                if sid:
                    self._last_result_payload.setdefault("session_id", sid)
            await on_event(agent_event)

    async def run(self, request: AgentRunRequest, on_event: AgentEventSink) -> AgentRunResult:
        self._validate_request(request)
        self._cancelled = False
        self._last_result_payload = {}

        program = self._bridge
        program._task_id = str(request.metadata.get("task_id") or request.env.get("TASK_ID") or "")
        program._workspace_id = str(request.metadata.get("workspace_id") or request.env.get("WORKSPACE_ID") or "")
        program._job_id = str(request.metadata.get("ai_job_id") or request.env.get("AI_JOB_ID") or "")

        async def _raw_callback(event: dict[str, Any]) -> None:
            await self._handle_raw_event(event, on_event)

        try:
            await program.start_session(
                prompt=request.prompt,
                project_path=request.project_path,
                event_callback=_raw_callback,
                session_id=request.session_id,
                env_overrides=request.env or None,
            )
            try:
                await asyncio.wait_for(program.wait(), timeout=max(1.0, request.timeout_seconds))
            except asyncio.TimeoutError as exc:
                await program.cancel()
                raise AgentTimeoutError(f"Claude Code session timed out after {request.timeout_seconds}s") from exc
        except AgentError:
            raise
        except Exception as exc:
            if self._cancelled:
                raise AgentCancelledError("Claude Code session cancelled") from exc
            raise AgentError(f"Claude Code session failed: {exc}") from exc

        payload = self._last_result_payload or {}
        success = bool(payload.get("success", True))
        finish_reason = payload.get("finish_reason") or ("error" if not success else "completed")
        usage_raw = payload.get("usage") or {}
        usage = TokenUsage(
            input_tokens=usage_raw.get("input_tokens"),
            output_tokens=usage_raw.get("output_tokens"),
            cache_read_tokens=usage_raw.get("cache_read_tokens"),
            cache_creation_tokens=usage_raw.get("cache_creation_tokens"),
            total_tokens=usage_raw.get("total_tokens"),
            raw=usage_raw,
        ) if usage_raw else None

        return AgentRunResult(
            run_id=request.run_id,
            session_id=payload.get("session_id") or program.session_id or request.session_id or "",
            success=bool(success),
            result_text=str(payload.get("result") or ""),
            finish_reason=finish_reason,
            usage=usage,
            cost_usd=payload.get("cost_usd"),
            duration_ms=payload.get("duration_ms"),
            return_code=getattr(program.process, "returncode", None),
            raw_trace=getattr(program, "_session_trace_path", None),
        )

    async def interrupt(self, run_id: str | None = None) -> None:
        self._cancelled = True
        await self._bridge.interrupt()

    async def cancel(self, run_id: str | None = None) -> None:
        self._cancelled = True
        await self._bridge.cancel()

    def is_running(self, run_id: str | None = None) -> bool:
        return self._bridge.is_running()

    async def close(self) -> None:
        if self._bridge.is_running():
            await self._bridge.cancel()
        self._bridge._session_trace_path = None
        self._last_result_payload = {}

    # ── 旧 CliBridgeBase 兼容入口 ──────────────────────────────
    async def start_session(
        self,
        prompt: str,
        project_path: str,
        event_callback,
        session_id: str | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> str:
        return await self._bridge.start_session(
            prompt=prompt,
            project_path=project_path,
            event_callback=event_callback,
            session_id=session_id,
            env_overrides=env_overrides,
        )

    async def wait(self) -> None:
        await self._bridge.wait()

    @property
    def session_id(self) -> str | None:
        return self._bridge.session_id

    @property
    def process(self):
        return self._bridge.process