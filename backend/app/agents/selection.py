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
import os
import shutil
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.agents.run_logging import run_agent_backend_with_logging
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
        "label": "DSH (JSON-RPC)",
        "supports_resume": True,
        "preferred_mode": "server",
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
    options: list[Dict[str, Any]] = []
    for meta in AGENT_BACKEND_META.values():
        item = dict(meta)
        item["supports_fork"] = backend_supports_fork(meta["value"])
        if meta["value"] == "dsh" and dsh_server_mode_enabled():
            # server 模式下 dsh 能力完整（resume / usage / 工具事件）
            item = {
                **item,
                "label": "DSH (JSON-RPC)",
                "supports_resume": True,
                "preferred_mode": "server",
            }
        options.append(item)
    return options


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


def dsh_server_mode_enabled() -> bool:
    return bool(str(getattr(settings, "DSH_SERVER_URL", "") or "").strip())


def create_agent_backend_by_name(backend_name: Optional[str] = None):
    """按名称创建统一 AgentBackend 实例（engine 路径使用）。

    claude-code 返回双接口 ClaudeCodeAdapter；dsh 在配置 DSH_SERVER_URL 时
    走 Web Host server 模式（支持 resume/事件/usage），否则 headless CLI。
    """
    from app.agents.registry import get_agent_backend

    name = normalize_backend_name(backend_name) or default_backend_name()
    if name in ("claude-code", "mock"):
        return create_cli_bridge()
    if name == "opencode":
        return get_agent_backend(
            "opencode",
            server_url=getattr(settings, "OPENCODE_SERVER_URL", "http://127.0.0.1:4097"),
        )
    if name == "dsh":
        if dsh_server_mode_enabled():
            from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter

            return DshServerAdapter(server_url=str(settings.DSH_SERVER_URL).strip())
        return get_agent_backend("dsh", dsh_cli=getattr(settings, "DSH_CLI_PATH", "dsh"))
    return get_agent_backend(name)


def create_legacy_bridge(backend_name: Optional[str] = None):
    """创建满足旧 CliBridgeBase 鸠尾接口的 bridge。

    - claude-code/mock：沿用 create_cli_bridge()（含 SDD_CLI_MODE mock 兼容）
    - opencode/dsh：AgentBackend + LegacyBridgeShim
    """
    name = normalize_backend_name(backend_name) or default_backend_name()
    if name in ("claude-code", "mock"):
        return create_cli_bridge()
    backend = create_agent_backend_by_name(name)
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
        fork_session: bool = False,
        permission_mode: str = "default",
    ) -> str:
        from app.agents.contract import AgentRunRequest
        from app.agents.errors import AgentError

        resume_id = session_id
        if fork_session:
            if not resume_id:
                raise AgentError("fork-on-resume requires an existing session id")
            if not getattr(self.backend.capabilities, "supports_fork", False):
                raise AgentError(
                    f"agent backend {self.backend_name!r} does not support session fork"
                )
            # Server backends fork eagerly and then resume the child.  Claude's
            # native --fork-session path is handled by ClaudeCodeAdapter itself
            # and therefore never reaches this shim.
            resume_id = await self.backend.fork_session(
                resume_id,
                source_dir=project_path,
                target_dir=project_path,
            )
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
            metadata={
                "task_id": str((env_overrides or {}).get("TASK_ID") or "").strip() or None,
                "workspace_id": str((env_overrides or {}).get("WORKSPACE_ID") or "").strip() or None,
                "user_id": str((env_overrides or {}).get("USER_ID") or "").strip() or None,
                "ai_job_id": str((env_overrides or {}).get("AI_JOB_ID") or "").strip() or None,
            },
            timeout_seconds=float(getattr(settings, "AGENT_MAX_RUNTIME_SECONDS", 7200) or 7200),
            startup_timeout_seconds=float(
                getattr(settings, "AGENT_STARTUP_TIMEOUT_SECONDS", 60) or 60
            ),
            idle_timeout_seconds=float(
                getattr(settings, "AGENT_IDLE_TIMEOUT_SECONDS", 600) or 600
            ),
            permission_mode=permission_mode,
        )

        async def _on_event(agent_event) -> None:
            legacy = agent_event_to_legacy_payload(agent_event)
            if legacy is None:
                return
            result = event_callback(legacy)
            if asyncio.iscoroutine(result):
                await result

        async def _run() -> None:
            result = await run_agent_backend_with_logging(self.backend, request, _on_event)
            if result and result.session_id:
                self._session_id = result.session_id

        self._run_task = asyncio.create_task(_run())
        return resume_id or ""

    async def wait(self) -> None:
        if self._run_task is not None:
            try:
                await self._run_task
            finally:
                await self.backend.close()

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

    async def close(self) -> None:
        await self.backend.close()

    def is_running(self) -> bool:
        return bool(self._run_task and not self._run_task.done())

    async def fork_session(
        self,
        session_id: str,
        *,
        source_dir: str,
        target_dir: str,
    ) -> str:
        return await self.backend.fork_session(session_id, source_dir=source_dir, target_dir=target_dir)


def backend_supports_fork(backend_name: Optional[str] = None) -> bool:
    """backend 是否声明支持会话 fork（用于前端提示与 baseline 演练）。"""
    try:
        bridge = create_legacy_bridge(backend_name)
    except Exception:
        return False
    if isinstance(bridge, LegacyBridgeShim):
        return bool(getattr(bridge.backend.capabilities, "supports_fork", False))
    return bool(getattr(bridge, "capabilities", None) is not None and getattr(
        getattr(bridge, "capabilities"), "supports_fork", False
    ))


async def fork_session_for_backend(
    backend_name: Optional[str],
    session_id: str,
    *,
    source_dir: str,
    target_dir: str,
) -> str:
    """把 source_dir 下的会话 fork 成 target_dir 下的独立新会话，返回新会话 id。"""
    from app.agents.errors import SessionForkError

    name = normalize_backend_name(backend_name) or default_backend_name()
    bridge = create_legacy_bridge(name)
    fork = getattr(bridge, "fork_session", None)
    if fork is None:
        raise SessionForkError(f"agent backend {name!r} does not support session fork")
    try:
        return await fork(session_id, source_dir=source_dir, target_dir=target_dir)
    finally:
        close = getattr(bridge, "close", None)
        if close is not None:
            result = close()
            if asyncio.iscoroutine(result):
                await result


async def probe_session_fork(
    backend_name: Optional[str],
    session_id: str,
    *,
    source_dir: str,
) -> bool:
    """baseline 完成后的 fork 演练：尽早暴露不可 fork 的情况，产物随即清理。"""
    from app.agents.errors import SessionForkError

    name = normalize_backend_name(backend_name) or default_backend_name()
    if not backend_supports_fork(name):
        return False
    try:
        if name in ("claude-code", "mock"):
            import tempfile

            from app.agents.adapters.claude_code.claude_code_adapter import _claude_project_store_dir

            with tempfile.TemporaryDirectory(prefix="tf-fork-drill-") as drill_dir:
                await fork_session_for_backend(
                    name, session_id, source_dir=source_dir, target_dir=drill_dir
                )
                drill_store = _claude_project_store_dir(drill_dir)
                import shutil

                shutil.rmtree(drill_store, ignore_errors=True)
            return True
        if name == "opencode":
            drill_dir = os.path.abspath(os.path.join(source_dir, ".fork-drill"))
            new_id = await fork_session_for_backend(
                name,
                session_id,
                source_dir=source_dir,
                target_dir=drill_dir,
            )
            from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter

            bridge = create_legacy_bridge(name)
            adapter = bridge.backend if isinstance(bridge, LegacyBridgeShim) else None
            if isinstance(adapter, OpenCodeAdapter):
                deleted = await adapter.delete_session(new_id)
                if not deleted:
                    logger.warning(
                        "opencode fork drill left orphan session {} (delete API unavailable)",
                        new_id,
                    )
            shutil.rmtree(drill_dir, ignore_errors=True)
            return True
        if name == "dsh":
            from app.agents.adapters.dsh import session_files
            from app.agents.adapters.dsh.dsh_adapter import dsh_sessions_root

            root = dsh_sessions_root()
            _path, suffix = session_files.locate_session_log(root, session_id)
            new_id = f"session-tf-drill-{uuid.uuid4().hex}"
            session_files.fork_session_log(
                root,
                session_id,
                new_session_id=new_id,
                target_cwd=source_dir,
            )
            drill_path, _suffix = session_files.locate_session_log(root, new_id)
            shutil.rmtree(os.path.dirname(drill_path), ignore_errors=True)
            return True
        return False
    except SessionForkError as exc:
        logger.warning("session fork probe failed for backend {}: {}", name, exc)
        return False
    except Exception as exc:
        logger.warning("session fork probe errored for backend {}: {}", name, exc)
        return False
