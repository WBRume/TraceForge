"""Agent backend 选择与旧接口兼容层。

职责：
- 按工作区解析生效的 agent backend（workspace.agent_backend 优先，回退 .env AGENT_BACKEND）
- 任务级粘性：任务/baseline 首次运行后固定 backend，切换工作区配置不影响已有上下文
- LegacyBridgeShim：将统一 AgentBackend 适配为旧 CliBridgeBase 鸠尾接口
  （start_session/wait/session_id/process/cancel），并输出 Claude 风格事件，
  让既有事件解析代码（baseline、run_cli_single_turn）无需感知后端差异。
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.core.logging import get_logger
from app.engine.claude_bridge import create_cli_bridge

logger = get_logger(__name__, category="agent")

#: 可在工作区设置中选择的 backend（不含 mock）
SELECTABLE_AGENT_BACKENDS = ("claude-code", "opencode", "dsh")

DEFAULT_AGENT_BACKEND = "claude-code"

#: backend 展示元信息（用于 API 输出）
AGENT_BACKEND_META: Dict[str, Dict[str, Any]] = {
    "claude-code": {
        "value": "claude-code",
        "label": "Claude Code CLI",
        "supports_resume": True,
        "preferred_mode": "subprocess",
    },
    "opencode": {
        "value": "opencode",
        "label": "OpenCode (Server)",
        "supports_resume": True,
        "preferred_mode": "server",
    },
    "dsh": {
        "value": "dsh",
        "label": "DSH CLI",
        "supports_resume": False,
        "preferred_mode": "subprocess",
    },
}


def default_backend_name() -> str:
    name = str(getattr(settings, "AGENT_BACKEND", "") or "").strip()
    return _normalize(name) or DEFAULT_AGENT_BACKEND


def _normalize(name: Optional[str]) -> Optional[str]:
    normalized = str(name or "").strip()
    return normalized or None


def normalize_backend_name(name: Optional[str]) -> Optional[str]:
    """校验 backend 名称；非法或未知值返回 None。"""
    normalized = _normalize(name)
    if normalized is None:
        return None
    from app.agents.registry import AGENT_BACKENDS
    from app.agents.adapters import register_all

    if not AGENT_BACKENDS:
        register_all()
    if normalized not in AGENT_BACKENDS:
        return None
    return normalized


def list_agent_backends() -> list[Dict[str, Any]]:
    return [dict(meta) for meta in AGENT_BACKEND_META.values()]


def resolve_workspace_backend(db: Session, workspace_id: Optional[str]) -> str:
    """工作区生效的 agent backend：workspace 配置优先，回退全局 .env。"""
    if workspace_id:
        from app.domains.auth.models.user import Workspace

        ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if ws is not None:
            resolved = normalize_backend_name(ws.agent_backend)
            if resolved:
                return resolved
    return default_backend_name()


def resolve_task_backend(db: Session, task_id: str) -> str:
    """任务粘性 backend：任务已固定则沿用（保持既有上下文），否则取工作区配置并固化。"""
    from app.domains.task.models.task import SddTask

    task = db.query(SddTask).filter(SddTask.id == task_id).first()
    if task is None:
        return default_backend_name()
    sticky = normalize_backend_name(task.agent_backend)
    if sticky:
        return sticky
    resolved = resolve_workspace_backend(db, task.workspace_id)
    task.agent_backend = resolved
    db.commit()
    return resolved


def create_legacy_bridge(backend_name: Optional[str] = None):
    """创建满足旧 CliBridgeBase 鸠尾接口的 bridge。

    - claude-code/mock：沿用 create_cli_bridge()（含 SDD_CLI_MODE mock 兼容）
    - opencode/dsh：AgentBackend + LegacyBridgeShim
    """
    name = normalize_backend_name(backend_name) or default_backend_name()
    if name in ("claude-code", "mock"):
        return create_cli_bridge()
    from app.agents.registry import get_agent_backend

    if name == "opencode":
        backend = get_agent_backend(
            "opencode",
            server_url=getattr(settings, "OPENCODE_SERVER_URL", "http://127.0.0.1:4097"),
        )
    elif name == "dsh":
        backend = get_agent_backend("dsh", dsh_cli=getattr(settings, "DSH_CLI_PATH", "dsh"))
    else:
        backend = get_agent_backend(name)
    return LegacyBridgeShim(backend, backend_name=name)


def agent_event_to_legacy_payload(event) -> Optional[Dict[str, Any]]:
    """统一 AgentEvent → Claude 风格事件 dict（旧解析代码可继续工作）。"""
    etype = getattr(event, "type", "")
    payload = getattr(event, "payload", None) or {}
    if etype == "session_started":
        return {
            "type": "system",
            "subtype": "init",
            "session_id": str(payload.get("provider_session_id") or ""),
        }
    if etype == "text":
        return {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": payload.get("text") or ""}]},
        }
    if etype == "result":
        success = bool(payload.get("success", True))
        return {
            "type": "result",
            "subtype": "success" if success else "error",
            "is_error": not success,
            "result": payload.get("result") or "",
            "session_id": payload.get("session_id") or "",
        }
    if etype == "error":
        return {
            "type": "result",
            "subtype": "error",
            "is_error": True,
            "result": payload.get("result") or payload.get("message") or "",
        }
    return None


class LegacyBridgeShim:
    """将统一 AgentBackend 包装为旧 CliBridgeBase 鸠尾接口。

    事件以 Claude 风格 dict 回调（见 agent_event_to_legacy_payload），
    因此外层 wait/session_id/process/cancel 用法与 ClaudeCodeAdapter 一致。
    """

    def __init__(self, backend, *, backend_name: str = "") -> None:
        self.backend = backend
        self.backend_name = backend_name or getattr(backend, "name", "agent")
        self._run_task: Optional[asyncio.Task] = None
        self._session_id: Optional[str] = None

    async def start_session(
        self,
        prompt: str,
        project_path: str,
        event_callback: Callable[[Dict[str, Any]], Any],
        session_id: Optional[str] = None,
        env_overrides: Optional[Dict[str, str]] = None,
    ) -> str:
        from app.agents.contract import AgentRunRequest

        resume_id = session_id
        if resume_id and not getattr(self.backend.capabilities, "supports_resume", True):
            # 例：DSH headless 不支持 resume；降级为新会话而非报错
            logger.warning(
                "agent backend {} does not support resume; starting fresh session (dropped session_id={})",
                self.backend_name,
                resume_id,
            )
            resume_id = None

        request = AgentRunRequest(
            run_id=f"legacy-{self.backend_name}-{id(self)}",
            prompt=prompt,
            project_path=project_path,
            session_id=resume_id,
            env=dict(env_overrides or {}),
            # 外层调用方通过 asyncio.wait_for(bridge.wait()) 控制超时；
            # 内层给足上限避免双重超时误杀。
            timeout_seconds=float(getattr(settings, "CLAUDE_CLI_TIMEOUT", 3600) or 3600) + 600.0,
        )

        async def _on_event(agent_event) -> None:
            legacy = agent_event_to_legacy_payload(agent_event)
            if legacy is None:
                return
            result = event_callback(legacy)
            if asyncio.iscoroutine(result):
                await result

        async def _run() -> None:
            result = await self.backend.run(request, _on_event)
            if result and result.session_id:
                self._session_id = result.session_id

        self._run_task = asyncio.create_task(_run())
        return resume_id or ""

    async def wait(self) -> None:
        if self._run_task is not None:
            try:
                await self._run_task
            except asyncio.CancelledError:
                raise
            except Exception:
                # 失败细节已经通过事件流下发，这里保持与旧 bridge 一致的静默语义；
                # 外层根据 result 事件中的 is_error 判定失败。
                pass

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    @property
    def process(self):
        # 旧调用方通过 getattr(bridge, "process", None) 读取 returncode；
        # server 模式无本地进程，返回 None 即可。
        return None

    async def cancel(self) -> None:
        if self._run_task is not None and not self._run_task.done():
            self._run_task.cancel()
        try:
            await self.backend.cancel()
        except Exception:
            logger.warning("agent backend {} cancel failed", self.backend_name)

    async def interrupt(self) -> None:
        try:
            await self.backend.interrupt()
        except Exception:
            logger.warning("agent backend {} interrupt failed", self.backend_name)

    def is_running(self) -> bool:
        return bool(self._run_task and not self._run_task.done())
