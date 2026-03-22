"""
Claude CLI 桥接引擎
支持 Mock (降级) 和 Real (subprocess + stream-json) 两种模式
Real 模式通过 asyncio subprocess 启动 claudecode CLI，以 NDJSON 流式解析输出
"""

import sys
import json
import asyncio
import uuid
from abc import ABC, abstractmethod
from typing import Optional, Callable, Any
from loguru import logger

from app.config import settings


class CliBridgeBase(ABC):
    """CLI 桥接抽象基类"""

    @abstractmethod
    async def start_session(
        self,
        prompt: str,
        project_path: str,
        event_callback: Callable[[dict], Any],
        session_id: Optional[str] = None,
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
    def is_running(self) -> bool:
        pass


class SubprocessCliBridge(CliBridgeBase):
    """
    真实 CLI 桥接：通过 asyncio subprocess 启动 claude CLI
    使用 --print --output-format stream-json --verbose 模式
    逐行解析 NDJSON 事件流 (system / assistant / result)
    """

    def __init__(self):
        self.process: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._event_cb: Optional[Callable] = None
        self._session_id: Optional[str] = None
        self._running = False

    async def start_session(
        self,
        prompt: str,
        project_path: str,
        event_callback: Callable[[dict], Any],
        session_id: Optional[str] = None,
    ) -> str:
        self._event_cb = event_callback
        self._running = True

        # 构建命令行参数
        cli_path = settings.CLAUDE_CLI_PATH
        
        import os
        import shutil
        args = []
        if os.name == 'nt' and not cli_path.lower().endswith(('.exe', '.js')):
            resolved_path = shutil.which(cli_path)
            if resolved_path and resolved_path.lower().endswith('.cmd'):
                # 绕过 .cmd 隐式调用的 cmd.exe，直接定位 node 入口
                dp0 = os.path.dirname(resolved_path)
                cli_js = os.path.join(dp0, "node_modules", "@anthropic-ai", "claude-code", "cli.js")
                if os.path.exists(cli_js):
                    args = ["node", cli_js]
                else:
                    args = [resolved_path]
            else:
                args = [resolved_path or cli_path]
        else:
            args = [cli_path]

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

        logger.info(f"Starting Claude CLI: {' '.join(args)} in {project_path}")

        try:
            import os
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            
            self.process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=project_path,
                env=env,
            )

            # 启动异步读取循环
            self._reader_task = asyncio.create_task(self._read_loop())

            # 启动 stderr 读取
            asyncio.create_task(self._read_stderr())

            return self._session_id

        except Exception as e:
            logger.error(f"Failed to start Claude CLI: {e}")
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
                        logger.warning(f"Non-JSON CLI output: {line[:200]}")
                        continue

                    # 从 system.init 事件提取真实 session_id
                    if event.get("type") == "system" and event.get("subtype") == "init":
                        real_sid = event.get("session_id")
                        if real_sid:
                            self._session_id = real_sid
                            logger.info(f"CLI session initialized: {real_sid}")

                    # 回调分发事件
                    if self._event_cb:
                        try:
                            result = self._event_cb(event)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as e:
                            logger.error(f"Event callback error: {e}")
                            
                # 如果缓冲中迟迟不换行，表明可能遭遇了交互式挂起
                if len(buffer) > 0 and not buffer.endswith("\n"):
                    # 仅仅是打印观察，如果不卡死就不影响后续 json
                    logger.debug(f"CLI stdout buffered (no newline): {buffer[-100:]}")
                    
        except Exception as e:
            if self._running:
                logger.error(f"CLI stdout read error: {e}")
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
                    logger.debug(f"CLI stderr: {text}")
        except Exception as e:
            logger.error(f"Stderr read error: {e}")

    async def wait(self):
        """等待 CLI 进程结束"""
        if self._reader_task:
            await self._reader_task
        if self.process:
            await self.process.wait()

    async def cancel(self) -> None:
        self._running = False
        if self.process and self.process.returncode is None:
            try:
                self.process.terminate()
                # 给 2 秒优雅退出
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    self.process.kill()
                logger.info("Claude CLI process terminated")
            except Exception as e:
                logger.error(f"Failed to terminate CLI: {e}")

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

    def is_running(self) -> bool:
        return self._running


def create_cli_bridge() -> CliBridgeBase:
    """根据配置创建 CLI 桥接实例"""
    if settings.SDD_CLI_MODE == "real":
        return SubprocessCliBridge()
    return MockCliBridge()
