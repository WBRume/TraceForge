"""
Claude CLI 桥接引擎
支持 Mock (降级) 和 Real (subprocess + stream-json) 两种模式
Real 模式通过 asyncio subprocess 启动 claudecode CLI，以 NDJSON 流式解析输出
"""

import sys
import json
import asyncio
import uuid
import os
import re
import shutil
import signal
import subprocess
from datetime import datetime
from abc import ABC, abstractmethod
from typing import Optional, Callable, Any, TextIO, Dict

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__, category="ai_session")


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
    async def cancel(self) -> None:
        """取消正在运行的 CLI 进程"""
        pass

    @abstractmethod
    async def interrupt(self) -> None:
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
        self._reader_task: Optional[asyncio.Task] = None
        self._event_cb: Optional[Callable] = None
        self._session_id: Optional[str] = None
        self._running = False
        self._cli_path = (cli_path or settings.CLAUDE_CLI_PATH).strip() or settings.CLAUDE_CLI_PATH
        self._session_trace_fp: Optional[TextIO] = None
        self._session_trace_path: Optional[str] = None
        self._session_trace_started_at: Optional[datetime] = None
        self._task_id: Optional[str] = None
        self._workspace_id: Optional[str] = None
        self._job_id: Optional[str] = None

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

    def _log_ai_event(self, level: str, event_type: str, message: str, **extra: Any) -> None:
        payload = {
            "task_id": self._task_id,
            "workspace_id": self._workspace_id,
            "job_id": self._job_id,
            "session_id": self._session_id,
            "event_type": event_type,
        }
        payload.update(extra)
        logger.bind(**payload).log(level.upper(), message)

    def _sanitize_filename_part(self, value: str, fallback: str = "session") -> str:
        source = str(value or "").strip()
        cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "-" for ch in source)
        cleaned = cleaned.strip("-_.")
        if not cleaned:
            return fallback
        return cleaned[:80]

    def _get_trace_dir(self) -> str:
        raw_dir = (settings.AI_SESSION_LOG_DIR or "").strip() or os.path.join(settings.LOG_DIR, "ai_sessions")
        trace_dir = os.path.abspath(raw_dir)
        os.makedirs(trace_dir, exist_ok=True)
        return trace_dir

    def _trace_write(self, text: str = "") -> None:
        if not self._session_trace_fp:
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        payload = str(text or "")
        lines = payload.splitlines() or [""]
        try:
            for line in lines:
                self._session_trace_fp.write(f"{timestamp} | {line}\n")
            self._session_trace_fp.flush()
        except Exception:
            pass

    def _close_session_trace(self, *, reason: str, return_code: Optional[int] = None) -> None:
        if not self._session_trace_fp:
            return
        try:
            self._trace_write(f"session_end_reason: {reason}")
            if return_code is not None:
                self._trace_write(f"process_return_code: {return_code}")
            if self._session_trace_started_at:
                elapsed = (datetime.now() - self._session_trace_started_at).total_seconds()
                self._trace_write(f"elapsed_seconds: {elapsed:.3f}")
            self._trace_write("=== END SESSION TRACE ===")
        finally:
            try:
                self._session_trace_fp.close()
            except Exception:
                pass
            self._session_trace_fp = None
            self._session_trace_path = None
            self._session_trace_started_at = None

    def _open_session_trace(
        self,
        *,
        args: list[str],
        project_path: str,
        prompt: str,
        resumed_session_id: Optional[str],
    ) -> None:
        self._close_session_trace(reason="reopen_trace")
        self._session_trace_started_at = datetime.now()
        ts = self._session_trace_started_at.strftime("%Y%m%d_%H%M%S_%f")
        sid_part = self._sanitize_filename_part(resumed_session_id or self._session_id or "new")
        trace_name = f"{ts}_{sid_part}.log"
        trace_path = os.path.join(self._get_trace_dir(), trace_name)

        try:
            self._session_trace_fp = open(trace_path, "w", encoding="utf-8")
            self._session_trace_path = trace_path
            command_for_log = list(args)
            if command_for_log:
                command_for_log[-1] = "<PROMPT_IN_USER_SECTION>"

            self._trace_write("=== CLAUDE CLI SESSION TRACE ===")
            self._trace_write(f"trace_file: {trace_path}")
            self._trace_write(f"cwd: {os.path.abspath(project_path)}")
            self._trace_write(f"session_mode: {'resume' if resumed_session_id else 'new'}")
            if resumed_session_id:
                self._trace_write(f"resume_session_id: {resumed_session_id}")
            self._trace_write(f"cli_command: {' '.join(command_for_log)}")
            self._trace_write("----- USER PROMPT BEGIN -----")
            self._trace_write(prompt)
            self._trace_write("----- USER PROMPT END -----")
        except Exception as exc:
            self._session_trace_fp = None
            self._session_trace_path = None
            self._session_trace_started_at = None
            logger.warning(f"Failed to open AI session trace file: {exc}")

    async def start_session(
        self,
        prompt: str,
        project_path: str,
        event_callback: Callable[[dict], Any],
        session_id: Optional[str] = None,
        env_overrides: Optional[Dict[str, str]] = None,
    ) -> str:
        self._event_cb = event_callback
        self._running = True

        # 构建命令行参数。Windows 的 npm .cmd shim 会经由 cmd.exe 解析参数，
        # prompt 中的 "|" 等字符会被当作 shell 运算符；这里直接解析到真实入口。
        args = self._resolve_cli_base_args()

        args.extend([
            "-p",
            "--output-format", "stream-json",
            "--permission-mode", "bypassPermissions",
            "--verbose",
        ])

        # 恢复已有会话
        if session_id:
            args.extend(["--resume", session_id])
            self._session_id = session_id
        else:
            # 新会话：生成 session_id
            self._session_id = str(uuid.uuid4())
            args.extend(["--session-id", self._session_id])

        # 追加 prompt
        args.append(prompt)

        self._open_session_trace(
            args=args,
            project_path=project_path,
            prompt=prompt,
            resumed_session_id=session_id,
        )
        self._trace_write("starting_claude_cli_process")
        self._task_id = str((env_overrides or {}).get("TASK_ID") or "").strip() or None
        self._workspace_id = str((env_overrides or {}).get("WORKSPACE_ID") or "").strip() or None
        self._job_id = str((env_overrides or {}).get("AI_JOB_ID") or "").strip() or None
        self._log_ai_event(
            "info",
            "session_start",
            "Starting Claude CLI session",
            resumed=bool(session_id),
            project_path=os.path.abspath(project_path),
        )

        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            if env_overrides:
                logged_pairs: list[str] = []
                for key, value in env_overrides.items():
                    if key and value is not None:
                        text_key = str(key)
                        text_value = str(value)
                        env[text_key] = text_value
                        if text_key.upper() in {"ACCESS_TOKEN", "AUTHORIZATION", "BEARER_TOKEN"}:
                            logged_pairs.append(f"{text_key}=***")
                        else:
                            logged_pairs.append(f"{text_key}={text_value[:200]}")
                if logged_pairs:
                    self._trace_write(f"env_overrides: {', '.join(logged_pairs)}")

            self.process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=project_path,
                env=env,
                **self._subprocess_kwargs(),
            )
            self._trace_write(f"process_started_pid: {self.process.pid}")

            # 启动异步读取循环
            self._reader_task = asyncio.create_task(self._read_loop())

            # 启动 stderr 读取
            asyncio.create_task(self._read_stderr())

            self._log_ai_event(
                "info",
                "process_started",
                "Claude CLI process started",
                pid=self.process.pid,
            )
            return self._session_id

        except Exception as e:
            self._trace_write(f"process_start_failed: {e}")
            self._close_session_trace(reason="start_failed")
            self._log_ai_event("error", "process_start_failed", "Failed to start Claude CLI", error=str(e))
            logger.exception(f"Failed to start Claude CLI: {e}")
            self._running = False
            raise

    async def _read_loop(self):
        """逐块读取 stdout 并解析 NDJSON 事件流"""
        buffer = ""
        try:
            while True:
                chunk = await self.process.stdout.read(4096)
                if not chunk:
                    break
                
                text = chunk.decode("utf-8", errors="replace")
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
                        self._trace_write(f"[stdout.non_json] {line[:1000]}")
                        continue

                    # 从 system.init 事件提取真实 session_id
                    if event.get("type") == "system" and event.get("subtype") == "init":
                        real_sid = event.get("session_id")
                        if real_sid:
                            self._session_id = real_sid
                            self._trace_write(f"[system.init] session_id={real_sid}")
                            self._log_ai_event("info", "session_init", "Received CLI session init")

                    event_type = str(event.get("type") or "")
                    if event_type == "assistant":
                        message = event.get("message") if isinstance(event.get("message"), dict) else {}
                        blocks = message.get("content") if isinstance(message, dict) else []
                        if isinstance(blocks, list):
                            for block in blocks:
                                if not isinstance(block, dict):
                                    continue
                                block_type = str(block.get("type") or "")
                                if block_type == "text":
                                    text = str(block.get("text") or "").strip()
                                    if text:
                                        self._trace_write("----- ASSISTANT REPLY CHUNK BEGIN -----")
                                        self._trace_write(text)
                                        self._trace_write("----- ASSISTANT REPLY CHUNK END -----")
                                elif block_type == "thinking":
                                    thinking = str(block.get("thinking") or "").strip()
                                    if thinking:
                                        self._trace_write(f"[assistant.thinking] {thinking[:500]}")
                    elif event_type == "result":
                        subtype = str(event.get("subtype") or "").strip()
                        is_error = bool(event.get("is_error"))
                        duration_ms = event.get("duration_ms")
                        cost_usd = event.get("total_cost_usd")
                        self._trace_write(
                            f"[result] subtype={subtype or 'unknown'} is_error={is_error} duration_ms={duration_ms} cost_usd={cost_usd}"
                        )
                        result_text = str(event.get("result") or "").strip()
                        if result_text:
                            self._trace_write("----- RESULT TEXT BEGIN -----")
                            self._trace_write(result_text)
                            self._trace_write("----- RESULT TEXT END -----")

                    # 回调分发事件
                    if self._event_cb:
                        try:
                            result = self._event_cb(event)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as e:
                            logger.exception(f"Event callback error: {e}")
                            
                # 如果缓冲中迟迟不换行，表明可能遭遇了交互式挂起
                if len(buffer) > 0 and not buffer.endswith("\n"):
                    self._trace_write(f"[stdout.buffered_tail] {buffer[-300:]}")
                    
        except Exception as e:
            self._trace_write(f"[stdout.read_error] {e}")
            if self._running:
                self._log_ai_event("error", "stdout_read_error", "CLI stdout read error", error=str(e))
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
                text = chunk.decode("utf-8", errors="replace").strip()
                if text:
                    self._trace_write(f"[stderr] {text}")
        except Exception as e:
            self._trace_write(f"[stderr.read_error] {e}")
            self._log_ai_event("error", "stderr_read_error", "CLI stderr read error", error=str(e))
            logger.exception(f"Stderr read error: {e}")

    async def wait(self):
        """等待 CLI 进程结束"""
        if self._reader_task:
            await self._reader_task
        if self.process:
            await self.process.wait()
            self._log_ai_event(
                "info",
                "session_wait_completed",
                "Claude CLI wait completed",
                return_code=self.process.returncode,
            )
            self._close_session_trace(
                reason="wait_completed",
                return_code=self.process.returncode,
            )
        else:
            self._close_session_trace(reason="wait_completed_without_process")

    async def _wait_for_exit(self, timeout: float) -> bool:
        if not self.process:
            return True
        try:
            await asyncio.wait_for(self.process.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def _send_process_signal(self, sig: signal.Signals) -> None:
        if not self.process or self.process.returncode is not None:
            return
        if os.name != "nt":
            try:
                os.killpg(os.getpgid(self.process.pid), sig)
                return
            except Exception as exc:
                self._trace_write(f"process_group_signal_failed: {exc}")
        self.process.send_signal(sig)

    def _send_interrupt_signal(self) -> str:
        if os.name == "nt":
            break_signal = getattr(signal, "CTRL_BREAK_EVENT", None)
            if break_signal is not None:
                self._send_process_signal(break_signal)
                return "CTRL_BREAK_EVENT"
        self._send_process_signal(signal.SIGINT)
        return "SIGINT"

    async def _taskkill_tree(self) -> None:
        if os.name != "nt" or not self.process:
            return
        try:
            taskkill = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(self.process.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await taskkill.wait()
            self._trace_write("taskkill_tree_completed")
        except Exception as exc:
            self._trace_write(f"taskkill_tree_failed: {exc}")

    async def _force_stop_process(self, *, reason: str) -> None:
        if not self.process or self.process.returncode is not None:
            return
        try:
            self.process.terminate()
            self._trace_write(f"{reason}_terminate_sent")
            if await self._wait_for_exit(2.0):
                return
            self.process.kill()
            self._trace_write(f"{reason}_kill_sent")
            if await self._wait_for_exit(2.0):
                return
            await self._taskkill_tree()
        except ProcessLookupError:
            return
        except Exception as exc:
            self._trace_write(f"{reason}_force_stop_failed: {exc}")
            self._log_ai_event("error", f"{reason}_force_stop_failed", "Failed to stop CLI process", error=str(exc))
            logger.exception(f"Failed to stop Claude CLI process: {exc}")

    async def cancel(self) -> None:
        self._running = False
        self._trace_write("cancel_requested")
        if self.process and self.process.returncode is None:
            await self._force_stop_process(reason="cancel")
            await self._wait_for_exit(1.0)
            self._log_ai_event(
                "warning",
                "cancel_completed",
                "Claude CLI process cancelled",
                return_code=self.process.returncode,
            )
            self._close_session_trace(
                reason="cancel_completed",
                return_code=self.process.returncode,
            )
            return
        self._close_session_trace(reason="cancel_without_process")

    async def interrupt(self) -> None:
        self._running = False
        self._trace_write("interrupt_requested")
        if self.process and self.process.returncode is None:
            try:
                signal_name = self._send_interrupt_signal()
                self._trace_write(f"interrupt_signal_sent: {signal_name}")
                if not await self._wait_for_exit(3.0):
                    await self._force_stop_process(reason="interrupt")
            except Exception as exc:
                self._trace_write(f"interrupt_signal_failed: {exc}")
                await self._force_stop_process(reason="interrupt")
            await self._wait_for_exit(1.0)
            self._log_ai_event(
                "warning",
                "interrupt_completed",
                "Claude CLI process interrupted",
                return_code=self.process.returncode,
            )
            self._close_session_trace(
                reason="interrupt_completed",
                return_code=self.process.returncode,
            )
            return
        self._close_session_trace(reason="interrupt_without_process")

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
    ) -> str:
        self._running = True
        self._event_cb = event_callback
        self._session_id = session_id or str(uuid.uuid4())

        logger.info(f"[Mock CLI] Session {self._session_id} | prompt: {prompt[:80]}")

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

    async def cancel(self) -> None:
        self._running = False
        logger.info("[Mock CLI] Cancelled")

    async def interrupt(self) -> None:
        self._running = False
        logger.info("[Mock CLI] Interrupted")

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
