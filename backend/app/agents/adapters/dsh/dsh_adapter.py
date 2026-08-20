"""DSH（DeepSeek Harness）Agent backend。

Spike 结论：
- Windows 当前无法通过 pip 安装官方 Python SDK 的带 runtime 版本
  （deepseek-harness-runtime-bin 只有 linux/macos 平台 wheel）。
- TraceForge 避免依赖 DSH 源码仓库，因此默认走 **CLI subprocess 模式**
  （`dsh --profile headless`），只要求系统 PATH 中存在 `dsh`。
- 若未来在 Linux/macOS 部署或拿到 Windows runtime wheel，可切回
  `deepseek_harness` SDK 模式（SDK 事件映射见 event_mapper.py）。
"""

from __future__ import annotations

import asyncio
import locale
import os
import shutil
from pathlib import Path
from typing import Any, Optional

from app.agents.contract import (
    AgentBackend,
    AgentCapabilities,
    AgentEventSink,
    AgentRunRequest,
    AgentRunResult,
)
from app.agents.errors import AgentError
from app.agents.events import AgentEvent


def _decode_text(raw: bytes) -> str:
    """优先 UTF-8，失败时退回系统本地编码（Windows 下通常是 cp936/GBK）。"""
    for encoding in ("utf-8", locale.getpreferredencoding(False) or "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


class DSHAdapter(AgentBackend):
    name = "dsh"
    capabilities = AgentCapabilities(
        supports_resume=False,  # headless 单轮 CLI 不恢复会话；SDK 模式可支持
        supports_streaming_text=False,  # CLI 只拿最终 stdout；SDK 模式可支持流式
        supports_tool_events=False,  # CLI 默认不暴露工具事件；SDK 模式可支持
        hitl_modes=[],
        supports_usage=False,  # CLI 不返回 usage；SDK 模式可支持
        skill_layouts=["dsh"],
        preferred_mode="subprocess",
    )

    def __init__(
        self,
        provider: str = "deepseek-official",
        model: str = "deepseek-v4-flash",
        runtime_bin: Optional[str] = None,
        launch_args_override: Optional[tuple[str, ...]] = None,
        dsh_cli: str = "dsh",
    ) -> None:
        self.provider = provider
        self.model = model
        self.runtime_bin = runtime_bin
        self.launch_args_override = launch_args_override
        self.dsh_cli = dsh_cli
        self._running = False
        self._run_id: Optional[str] = None

    async def run(self, request: AgentRunRequest, on_event: AgentEventSink) -> AgentRunResult:
        cli_path = shutil.which(self.dsh_cli) or self.dsh_cli
        if not shutil.which(self.dsh_cli) and not Path(self.dsh_cli).exists():
            raise AgentError(
                f"DSH CLI not found: {self.dsh_cli!r}; install DSH or set dsh_cli"
            )

        cwd: str | None = None
        if request.project_path:
            project_path = Path(request.project_path).expanduser().resolve()
            if project_path.is_dir():
                cwd = str(project_path)

        session_id = request.session_id or f"dsh-cli-{request.run_id or 'run'}"
        env = os.environ.copy()
        env.update(request.env or {})
        if request.model:
            env.setdefault("DSH_MODEL", request.model)
        if request.provider_options.get("base_url"):
            env.setdefault("DEEPSEEK_BASE_URL", str(request.provider_options["base_url"]))
        if request.provider_options.get("api_key"):
            env.setdefault("DEEPSEEK_API_KEY", str(request.provider_options["api_key"]))

        command = [cli_path, "--profile", "headless", request.prompt]

        self._running = True
        self._run_id = request.run_id
        started_at = asyncio.get_running_loop().time()
        raw_lines: list[str] = []
        stderr_parts: list[str] = []
        try:
            await on_event(AgentEvent(
                type="session_started",
                payload={"provider_session_id": session_id, "provider": "dsh", "model": request.model or self.model},
                provider="dsh",
            ))

            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=cwd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = _decode_text(line).rstrip("\r\n")
                if text:
                    raw_lines.append(text)

            stderr = _decode_text(await proc.stderr.read())
            if stderr:
                stderr_parts.append(stderr)
            return_code = await proc.wait()

            if return_code != 0:
                detail = "\n".join(stderr_parts).strip() or "unknown error"
                await on_event(AgentEvent(
                    type="error",
                    payload={"result": detail, "provider": "dsh", "session_id": session_id, "return_code": return_code},
                    provider="dsh",
                ))
                return AgentRunResult(
                    run_id=request.run_id,
                    session_id=session_id,
                    success=False,
                    finish_reason="error",
                    result_text="",
                    duration_ms=int((asyncio.get_running_loop().time() - started_at) * 1000),
                    return_code=return_code,
                    raw_trace="\n".join(raw_lines + stderr_parts),
                )

            final_text = "\n".join(raw_lines).strip()
            if final_text:
                await on_event(AgentEvent(
                    type="text",
                    payload={"text": final_text, "provider": "dsh", "session_id": session_id},
                    provider="dsh",
                ))

            await on_event(AgentEvent(
                type="result",
                payload={
                    "result": final_text,
                    "finish_reason": "completed",
                    "provider": "dsh",
                    "session_id": session_id,
                },
                provider="dsh",
            ))

            return AgentRunResult(
                run_id=request.run_id,
                session_id=session_id,
                success=True,
                finish_reason="completed",
                result_text=final_text,
                duration_ms=int((asyncio.get_running_loop().time() - started_at) * 1000),
                return_code=0,
                raw_trace="\n".join(raw_lines + stderr_parts),
            )
        except FileNotFoundError as exc:
            raise AgentError(f"DSH CLI failed to spawn: {exc}") from exc
        finally:
            self._running = False
            self._run_id = None

    async def interrupt(self, run_id: str | None = None) -> None:
        # headless 单轮 CLI 无法优雅保留；取消由 cancel() 负责。
        self._running = False

    async def cancel(self, run_id: str | None = None) -> None:
        self._running = False

    def is_running(self, run_id: str | None = None) -> bool:
        return self._running

    async def close(self) -> None:
        self._running = False
        self._run_id = None