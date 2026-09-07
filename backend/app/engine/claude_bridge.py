"""
Claude CLI 桥接引擎
支持 Mock (降级) 和 Real (subprocess + stream-json) 两种模式
Real 模式通过 asyncio subprocess 启动 claudecode CLI，以 NDJSON 流式解析输出
"""

import json
import asyncio
import uuid
import os
import re
import shutil
import signal
import subprocess
import codecs
from abc import ABC, abstractmethod
from typing import Optional, Callable, Any, Dict

from app.config import settings
from app.core.logging import get_logger
from app.agents.process_supervisor import (
    ManagedAgentProcess,
    TerminationResult,
    process_supervisor,
)

logger = get_logger(__name__, category="ai_session")


# read-only（如「一键总结问题案例」）场景禁用的写/执行类工具。
# 保留 Read/Grep/Glob，允许模型核对上下文，但不允许任何副作用。
_READONLY_DENIED_TOOLS = (
    "Write",
    "Edit",
    "MultiEdit",
    "NotebookEdit",
    "Bash",
    "BashOutput",
    "KillShell",
    "Task",
    "TodoWrite",
    "ExitPlanMode",
    "WebFetch",
    "WebSearch",
)


def resolve_claude_permission_args(permission_mode: str) -> list[str]:
    """把语义化 permission_mode 解析为 Claude Code CLI 参数。

    - read-only：只读运行——不再映射为 plan 模式。plan 模式的系统提示词会
      驱动模型重新调研问题并把结果写进 ~/.claude/plans/*.md、调用
      ExitPlanMode 等待审批，破坏「仅输出 JSON 总结」的契约；这里改用
      default + --disallowedTools 只禁写/执行类工具。
    - plan：显式要求 Claude Code 计划模式时保持原行为。
    - 其他（default）：维持 bypassPermissions，与既有会话行为一致。
    """
    normalized = str(permission_mode or "").strip().lower()
    if normalized in {"read-only", "readonly"}:
        return [
            "--permission-mode", "default",
            "--disallowedTools", ",".join(_READONLY_DENIED_TOOLS),
        ]
    if normalized == "plan":
        return ["--permission-mode", "plan"]
    return ["--permission-mode", "bypassPermissions"]


class CliBridgeBase(ABC):
    """CLI 桥接抽象基类"""

    @abstractmethod
    async def start_session(
        self,
        prompt: str,
        project_path: str,
        event_callback: Callable[[dict], Any],
        session_id: Optional[str] = None,
        env_overrides: Optional[Dict[str, str]] = None,
        fork_session: bool = False,
        permission_mode: str = "default",
        on_process_started: Optional[Callable[[Any], Any]] = None,
    ) -> str:
        """
        启动 CLI 会话。
        - prompt: 用户的自然语言输入
        - project_path: 工作区目录
        - event_callback: 解析后的结构化事件回调 (async callable)
        - session_id: 可选，传入已有 session_id 则恢复会话 (--resume)
        返回: session_id
        """
        pass

    @abstractmethod
    async def cancel(self) -> Optional[TerminationResult]:
        """取消正在运行的 CLI 进程"""
        pass

    @abstractmethod
    async def interrupt(self) -> Optional[TerminationResult]:
        """临时中断正在运行的 CLI 进程，保留会话用于后续恢复"""
        pass

    @abstractmethod
    def is_running(self) -> bool:
        pass


class SubprocessCliBridge(CliBridgeBase):
    """
    真实 CLI 桥接：通过 asyncio subprocess 启动 claude CLI
    使用 --print --output-format stream-json --verbose 模式
    逐行解析 NDJSON 事件流 (system / assistant / result)
    """

    def __init__(self, cli_path: Optional[str] = None):
        self.process: Optional[asyncio.subprocess.Process] = None
        self._managed_process: Optional[ManagedAgentProcess] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._event_cb: Optional[Callable] = None
        self._session_id: Optional[str] = None
        self._running = False
        self.last_termination: Optional[TerminationResult] = None
        self._cli_path = (cli_path or settings.CLAUDE_CLI_PATH).strip() or settings.CLAUDE_CLI_PATH

    def _subprocess_kwargs(self) -> Dict[str, Any]:
        if os.name == "nt":
            return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        return {"start_new_session": True}

    def _command_args_for_target(self, target_path: str) -> list[str]:
        lower = str(target_path or "").lower()
        if lower.endswith((".js", ".mjs", ".cjs")):
            return ["node", target_path]
        return [target_path]

    def _expand_cmd_path_token(self, token: str, dp0: str) -> str:
        value = str(token or "").strip()
        dp0_with_sep = dp0 if dp0.endswith(("\\", "/")) else f"{dp0}{os.sep}"
        replacements = {
            "%~dp0": dp0_with_sep,
            "%dp0%\\": dp0_with_sep,
            "%dp0%/": dp0_with_sep,
            "%dp0%": dp0_with_sep,
        }
        for needle, replacement in replacements.items():
            value = re.sub(re.escape(needle), lambda _match: replacement, value, flags=re.I)
        return os.path.normpath(value)

    def _resolve_windows_cmd_shim_target(self, cmd_path: str) -> Optional[str]:
        dp0 = os.path.dirname(os.path.abspath(cmd_path))
        candidates = [
            os.path.join(dp0, "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe"),
            os.path.join(dp0, "node_modules", "@anthropic-ai", "claude-code", "cli.js"),
        ]
        try:
            with open(cmd_path, "r", encoding="utf-8", errors="replace") as fp:
                content = fp.read(8192)
        except Exception:
            content = ""

        for match in re.finditer(r'"([^"]+\.(?:exe|js|mjs|cjs))"', content, re.I):
            expanded = self._expand_cmd_path_token(match.group(1), dp0)
            lower = expanded.lower()
            if "node_modules" not in lower or lower.endswith("node.exe"):
                continue
            candidates.insert(0, expanded)

        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate
        return None

    def _resolve_cli_base_args(self) -> list[str]:
        cli_path = self._cli_path
        resolved_path = shutil.which(cli_path) or cli_path

        if os.name == "nt":
            lower = str(resolved_path or "").lower()
            if lower.endswith((".cmd", ".bat")):
                shim_target = self._resolve_windows_cmd_shim_target(resolved_path)
                if shim_target:
                    return self._command_args_for_target(shim_target)
            return self._command_args_for_target(resolved_path)

        return [resolved_path]

    async def start_session(
        self,
        prompt: str,
        project_path: str,
        event_callback: Callable[[dict], Any],
        session_id: Optional[str] = None,
        env_overrides: Optional[Dict[str, str]] = None,
        fork_session: bool = False,
        permission_mode: str = "default",
        on_process_started: Optional[Callable[[Any], Any]] = None,
    ) -> str:
        self._event_cb = event_callback
        self._running = True

        # 构建命令行参数。Windows 的 npm .cmd shim 会经由 cmd.exe 解析参数，
        # prompt 中的 "|" 等字符会被当作 shell 运算符；这里直接解析到真实入口。
        args = self._resolve_cli_base_args()

        cli_permission_args = resolve_claude_permission_args(permission_mode)
        args.extend([
            "-p",
            "--output-format", "stream-json",
            *cli_permission_args,
            "--verbose",
        ])

        # 恢复已有会话
        if session_id:
            args.extend(["--resume", session_id])
            if fork_session:
                # 原生 fork：在当前目录生成新会话 id 继承全部历史，原会话不被续写
                args.append("--fork-session")
            self._session_id = session_id
        else:
            # 新会话：生成 session_id
            self._session_id = str(uuid.uuid4())
            args.extend(["--session-id", self._session_id])

        # 追加 prompt
        args.append(prompt)

        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            if env_overrides:
                for key, value in env_overrides.items():
                    if key and value is not None:
                        env[str(key)] = str(value)

            self._managed_process = await process_supervisor.spawn(
                args,
                cwd=project_path,
                env=env,
                run_token=str(env.get("TRACEFORGE_RUN_TOKEN") or "") or None,
                worker_boot_id=str(env.get("WORKER_BOOT_ID") or "") or None,
                on_process_started=on_process_started,
            )
            self.process = self._managed_process.process

            # 启动异步读取循环
            self._reader_task = asyncio.create_task(self._read_loop())

            # 启动 stderr 读取
            self._stderr_task = asyncio.create_task(self._read_stderr())
            self._managed_process.add_reader_task(self._reader_task)
            self._managed_process.add_reader_task(self._stderr_task)

            return self._session_id

        except Exception as e:
            logger.exception(f"Failed to start Claude CLI: {e}")
            self._running = False
            raise

    async def _read_loop(self):
        """逐块读取 stdout 并解析 NDJSON 事件流"""
        buffer = ""
        # 增量 UTF-8 解码器：跨块保留未完成的多字节序列，
        # 避免 4096 字节块边界把一个中文字符切碎后被 errors="replace" 替换成 U+FFFD 乱码。
        utf8_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            while True:
                chunk = await self.process.stdout.read(4096)
                if not chunk:
                    break

                text = utf8_decoder.decode(chunk)
                buffer += text
                
                # 处理缓冲区内完整的所有行
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                        
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # 从 system.init 事件提取真实 session_id
                    if event.get("type") == "system" and event.get("subtype") == "init":
                        real_sid = event.get("session_id")
                        if real_sid:
                            self._session_id = real_sid

                    # 回调分发事件
                    if self._event_cb:
                        try:
                            result = self._event_cb(event)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as e:
                            logger.exception(f"Event callback error: {e}")
                            
        except Exception as e:
            if self._running:
                logger.exception(f"CLI stdout read error: {e}")
        finally:
            self._running = False

    async def _read_stderr(self):
        """读取 stderr 日志（按块读取防止无换行符阻塞）"""
        try:
            while True:
                chunk = await self.process.stderr.read(1024)
                if not chunk:
                    break
        except Exception as e:
            logger.exception(f"Stderr read error: {e}")

    async def wait(self):
        """等待 CLI 进程结束"""
        if self._managed_process:
            await self._managed_process.wait()
            process_supervisor.forget(self._managed_process)
        elif self.process:
            await self.process.wait()
        self._running = False

    async def _taskkill_tree(self) -> None:
        """兼容旧调用方的进程树终止入口。"""
        if not self.process or self.process.returncode is not None:
            return
        await process_supervisor.stop_persisted(
            pid=int(self.process.pid),
            process_started_at=None,
            reason="bridge_force_stop",
        )

    async def _wait_for_exit(self, timeout: float = 5.0) -> bool:
        if not self.process:
            return True
        try:
            await asyncio.wait_for(self.process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        return self.process.returncode is not None

    async def _force_stop_process(self, reason: str = "cancel") -> None:
        """保留旧的强制停止契约，并确保先处理进程树再等待根进程。"""
        if self._managed_process:
            self.last_termination = await asyncio.shield(
                self._managed_process.close(reason=reason)
            )
            process_supervisor.forget(self._managed_process)
            return

        if not self.process or self.process.returncode is not None:
            return

        await self._taskkill_tree()
        stopped = await self._wait_for_exit()
        if not stopped and self.process.returncode is None:
            self.process.terminate()
            await self._wait_for_exit(timeout=2.0)
            if self.process.returncode is None and hasattr(self.process, "kill"):
                self.process.kill()
                await self._wait_for_exit(timeout=2.0)

    async def cancel(self) -> Optional[TerminationResult]:
        self._running = False
        if self._managed_process:
            self.last_termination = await asyncio.shield(
                self._managed_process.close(reason="cancel")
            )
            process_supervisor.forget(self._managed_process)
        elif self.process and self.process.returncode is None:
            await self.process.wait()
        return self.last_termination

    async def interrupt(self) -> Optional[TerminationResult]:
        self._running = False
        if self._managed_process:
            self.last_termination = await asyncio.shield(
                self._managed_process.close(reason="interrupt")
            )
            process_supervisor.forget(self._managed_process)
        elif self.process and self.process.returncode is None:
            await self.process.wait()
        return self.last_termination

    def is_running(self) -> bool:
        return self._running

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id


class MockCliBridge(CliBridgeBase):
    """
    Mock 桥接：在无真实 CLI 时用于前端 UI 跑通
    """

    def __init__(self):
        self._running = False
        self._event_cb = None
        self._session_id = None

    async def start_session(
        self,
        prompt: str,
        project_path: str,
        event_callback: Callable[[dict], Any],
        session_id: Optional[str] = None,
        env_overrides: Optional[Dict[str, str]] = None,
        fork_session: bool = False,
        permission_mode: str = "default",
        on_process_started: Optional[Callable[[Any], Any]] = None,
    ) -> str:
        self._running = True
        self._event_cb = event_callback
        self._session_id = session_id or str(uuid.uuid4())

        if on_process_started is not None:
            accepted = on_process_started({"containment_id": "mock"})
            if asyncio.iscoroutine(accepted):
                accepted = await accepted
            if not accepted:
                raise RuntimeError("Mock Agent process could not be attached to the current job attempt")

        logger.info(f"[Mock CLI] Session {self._session_id} | prompt_length: {len(prompt)}")

        # 模拟事件序列
        asyncio.create_task(self._simulate(prompt))
        return self._session_id

    async def _simulate(self, prompt: str):
        """模拟 CLI 输出事件"""
        try:
            # 1. system init
            await self._emit({
                "type": "system", "subtype": "init",
                "session_id": self._session_id,
                "model": "mock-model",
                "tools": ["Bash", "Edit", "Read", "Write"],
            })
            await asyncio.sleep(0.5)

            # 2. assistant thinking
            await self._emit({
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "thinking", "thinking": f"思考如何回答: {prompt[:60]}..."}],
                },
                "session_id": self._session_id,
            })
            await asyncio.sleep(1)

            # 3. assistant text
            await self._emit({
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": f"[Mock] 已收到你的指令，正在处理…"}],
                },
                "session_id": self._session_id,
            })
            await asyncio.sleep(1)

            # 4. result
            await self._emit({
                "type": "result", "subtype": "success",
                "is_error": False,
                "result": "[Mock] 处理完成",
                "session_id": self._session_id,
                "duration_ms": 2500,
                "total_cost_usd": 0.0,
            })
        finally:
            self._running = False

    async def _emit(self, event: dict):
        if self._event_cb:
            result = self._event_cb(event)
            if asyncio.iscoroutine(result):
                await result

    async def cancel(self) -> Optional[TerminationResult]:
        self._running = False
        logger.info("[Mock CLI] Cancelled")
        return None

    async def interrupt(self) -> Optional[TerminationResult]:
        self._running = False
        logger.info("[Mock CLI] Interrupted")
        return None

    def is_running(self) -> bool:
        return self._running


def create_cli_bridge(cli_path: Optional[str] = None) -> CliBridgeBase:
    """根据配置创建 CLI 桥接实例。

    兼容策略：real 模式返回 ClaudeCodeAdapter（同时实现 CliBridgeBase 与 AgentBackend）；
    mock 模式继续使用 MockCliBridge，避免旧调用方破坏。
    """
    if settings.SDD_CLI_MODE == "real":
        from app.agents.adapters.claude_code.claude_code_adapter import ClaudeCodeAdapter

        return ClaudeCodeAdapter(cli_path=cli_path)
    return MockCliBridge()
