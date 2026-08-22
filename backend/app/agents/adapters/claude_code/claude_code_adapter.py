"""Claude Code CLI Agent backend。

实现统一 AgentBackend，内部复用现有 SubprocessCliBridge 的进程管理能力，
将 Claude NDJSON 流通过 event_mapper 转换为统一 AgentEvent。
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
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
from app.agents.errors import AgentCancelledError, AgentError, AgentTimeoutError, SessionForkError
from app.engine.claude_bridge import SubprocessCliBridge


def _claude_project_store_dir(project_path: str) -> str:
    """Claude Code 以 cwd 派生 project key 存放会话 jsonl。"""
    override = (
        str(os.environ.get("CLAUDE_HOME") or "").strip()
        or str(os.environ.get("CLAUDE_CONFIG_DIR") or "").strip()
    )
    home = os.path.abspath(override) if override else os.path.join(os.path.expanduser("~"), ".claude")
    project_abs = os.path.abspath(project_path or "")
    project_key = re.sub(r"[^A-Za-z0-9]", "-", project_abs)
    return os.path.join(home, "projects", project_key)


def _locate_session_file(store_dir: str, session_id: str) -> Optional[str]:
    sid = str(session_id or "").strip()
    if not sid or not os.path.isdir(store_dir):
        return None
    direct = os.path.join(store_dir, f"{sid}.jsonl")
    if os.path.isfile(direct):
        return direct
    for root, _, files in os.walk(store_dir):
        if f"{sid}.jsonl" in files:
            return os.path.join(root, f"{sid}.jsonl")
    return None


class ClaudeCodeAdapter(AgentBackend):
    name = "claude-code"
    capabilities = AgentCapabilities(
        supports_resume=True,
        supports_streaming_text=False,
        supports_tool_events=True,
        supports_fork=True,
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
    async def fork_session(
        self,
        session_id: str,
        *,
        source_dir: str,
        target_dir: str,
    ) -> str:
        """文件级 fork：把 baseline 会话 jsonl 复制到线程工作区的 project store。

        Claude 的会话以 cwd 派生 key 存储，复制单个 `{sid}.jsonl` 到目标 store
        后，线程在自己的目录里 resume 同一 id，写入只落在线程副本上，
        baseline 保持只读。找不到单文件时回退为整目录复制。
        """
        source_store = _claude_project_store_dir(source_dir)
        target_store = _claude_project_store_dir(target_dir)
        if os.path.isdir(target_store) and _locate_session_file(target_store, session_id):
            return session_id

        source_file = _locate_session_file(source_store, session_id)
        os.makedirs(os.path.dirname(target_store), exist_ok=True)
        if source_file:
            os.makedirs(target_store, exist_ok=True)
            shutil.copy2(source_file, os.path.join(target_store, f"{session_id}.jsonl"))
            return session_id

        # 回退：兼容旧版布局（快照嵌套/未按单文件存放）时复制整个 project store
        if os.path.isdir(source_store):
            if not os.path.isdir(target_store):
                shutil.copytree(source_store, target_store, dirs_exist_ok=False)
            return session_id

        raise SessionForkError(
            f"Claude session snapshot not found for fork: session={session_id}, store={source_store}"
        )

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