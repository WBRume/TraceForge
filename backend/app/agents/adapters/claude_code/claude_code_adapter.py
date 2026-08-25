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
from app.agents.activity_watchdog import AgentActivityWatchdog
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

    async def probe(self) -> str:
        cli_path = self._bridge._cli_path
        resolved = shutil.which(cli_path) or cli_path
        if not shutil.which(cli_path) and not os.path.isfile(cli_path):
            raise AgentError(f"Claude Code CLI not found: {cli_path!r}")
        return f"Claude Code CLI is available: {resolved}"

    async def run(self, request: AgentRunRequest, on_event: AgentEventSink) -> AgentRunResult:
        self._validate_request(request)
        self._cancelled = False
        self._last_result_payload = {}

        program = self._bridge
        program._task_id = str(request.metadata.get("task_id") or request.env.get("TASK_ID") or "")
        program._workspace_id = str(request.metadata.get("workspace_id") or request.env.get("WORKSPACE_ID") or "")
        program._job_id = str(request.metadata.get("ai_job_id") or request.env.get("AI_JOB_ID") or "")

        watchdog = AgentActivityWatchdog(
            startup_timeout_seconds=request.startup_timeout_seconds,
            idle_timeout_seconds=request.idle_timeout_seconds,
            hard_timeout_seconds=request.timeout_seconds,
        )

        async def _tracked_event(agent_event) -> None:
            watchdog.mark(agent_event.type)
            await on_event(agent_event)

        async def _raw_callback(event: dict[str, Any]) -> None:
            await self._handle_raw_event(event, _tracked_event)

        try:
            await program.start_session(
                prompt=request.prompt,
                project_path=request.project_path,
                event_callback=_raw_callback,
                session_id=request.session_id,
                env_overrides=request.env or None,
                fork_session=bool(request.provider_options.get("fork_session")),
                permission_mode=request.permission_mode,
            )
            try:
                await watchdog.wait(program.wait())
            except AgentTimeoutError:
                await program.cancel()
                raise
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
        """把 baseline 会话 stage 到目标目录的 project store，返回原会话 id。

        claude 的会话查找按 cwd 的 project store 隔离（跨目录 --resume 会报
        "No conversation found"），因此在目标目录 fork 前必须让 baseline 快照
        在目标 store 可见。这里做一次性 staging（硬链接优先，失败回退复制，
        幂等），之后每个线程在目标目录用 `--resume <sid> --fork-session`
        生成各自的新会话 id，原快照文件不会被任何线程续写。
        """
        source_store = _claude_project_store_dir(source_dir)
        target_store = _claude_project_store_dir(target_dir)
        target_file = os.path.join(target_store, f"{session_id}.jsonl")
        if os.path.isfile(target_file):
            return session_id

        source_file = _locate_session_file(source_store, session_id)
        if source_file is None:
            raise SessionForkError(
                f"Claude session snapshot not found for fork: session={session_id}, store={source_store}"
            )

        os.makedirs(target_store, exist_ok=True)
        try:
            os.link(source_file, target_file)
        except OSError:
            # 跨卷/文件系统不支持硬链接时回退为复制（单文件，一次性）
            shutil.copy2(source_file, target_file)
        return session_id

    async def start_session(
        self,
        prompt: str,
        project_path: str,
        event_callback,
        session_id: str | None = None,
        env_overrides: dict[str, str] | None = None,
        fork_session: bool = False,
        permission_mode: str = "default",
    ) -> str:
        return await self._bridge.start_session(
            prompt=prompt,
            project_path=project_path,
            event_callback=event_callback,
            session_id=session_id,
            env_overrides=env_overrides,
            fork_session=fork_session,
            permission_mode=permission_mode,
        )

    async def wait(self) -> None:
        await self._bridge.wait()

    @property
    def session_id(self) -> str | None:
        return self._bridge.session_id

    @property
    def process(self):
        return self._bridge.process
