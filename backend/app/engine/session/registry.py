"""引擎注册表：进程内 task_id -> 引擎实例，含空闲收割与优雅关停。

注册表是快速路径（resume 时优先复用内存引擎），也是优雅关停时本事件
循环所持 bridge 的权威清单。resume 正确性不依赖内存引擎：ai jobs 的
两条恢复路径都会以 DB 持久化的 session_id 重建引擎。
"""

import asyncio
import time
from typing import TYPE_CHECKING, Dict, Optional

from app.config import settings
from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.engine.session.engine import TaskAgentEngine

logger = get_logger(__name__, category="task_execution")

# ── 全局引擎注册表：task_id -> TaskAgentEngine ──
_active_engines: Dict[object, "TaskAgentEngine"] = {}

# 空闲引擎收割：非 running 引擎超过 ENGINE_IDLE_TTL_SECONDS 后由周期任务摘除。
# 正常结束后立即摘除（成功即删）；INTERRUPTED/WAITING_HITL 等可恢复态保留以便
# 快速 resume，但用户不再回来时由本收割器兜底，避免注册表只增不减。
ENGINE_IDLE_SWEEP_INTERVAL_SECONDS = 60.0
_idle_sweeper_task: Optional[asyncio.Task] = None


def _scope_key(task_id: str, scope_id: str = "main"):
    # Preserve the legacy in-process main key for older callers and diagnostics.
    return task_id if scope_id == "main" else (task_id, scope_id)


def get_engine(task_id: str, scope_id: str = "main") -> Optional["TaskAgentEngine"]:
    return _active_engines.get(_scope_key(task_id, scope_id))


def register_engine(engine: "TaskAgentEngine", *, mark_running: bool = False) -> None:
    if mark_running:
        engine.running = True
    _active_engines[_scope_key(engine.task_id, getattr(engine, "scope_id", "main"))] = engine
    _ensure_idle_sweeper()


def unregister_engine(task_id: str, scope_id: str = "main") -> None:
    _active_engines.pop(_scope_key(task_id, scope_id), None)


def sweep_idle_engines() -> int:
    """摘除非 running 且空闲超过 TTL 的引擎；返回摘除数量（仅供测试/观测）。"""
    ttl = max(1.0, float(getattr(settings, "ENGINE_IDLE_TTL_SECONDS", 1800) or 1800))
    now = time.monotonic()
    stale = [
        task_id
        for task_id, engine in _active_engines.items()
        if not engine.running and now - float(getattr(engine, "_last_idle_since", now)) >= ttl
    ]
    for task_id in stale:
        _active_engines.pop(task_id, None)
    if stale:
        logger.info(f"Swept {len(stale)} idle engine(s) from registry")
    return len(stale)


async def _idle_sweeper_loop() -> None:
    global _idle_sweeper_task
    try:
        while _active_engines:
            await asyncio.sleep(ENGINE_IDLE_SWEEP_INTERVAL_SECONDS)
            sweep_idle_engines()
    finally:
        if _idle_sweeper_task is asyncio.current_task():
            _idle_sweeper_task = None


def _ensure_idle_sweeper() -> None:
    global _idle_sweeper_task
    task = _idle_sweeper_task
    if task is not None and not task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 无事件循环（线程上下文）：等待事件循环内下一次注册触发
        return
    _idle_sweeper_task = loop.create_task(_idle_sweeper_loop())


async def shutdown_active_engines() -> None:
    """Stop every in-process engine before DB/executor shutdown.

    The registry is a fast-path only, but it is also the authoritative list of
    bridges owned by this event loop during graceful shutdown.
    """
    global _idle_sweeper_task
    sweeper = _idle_sweeper_task
    if sweeper is not None and sweeper is not asyncio.current_task():
        sweeper.cancel()
        await asyncio.gather(sweeper, return_exceptions=True)
    _idle_sweeper_task = None
    engines = list(_active_engines.values())
    if engines:
        await asyncio.gather(
            *(engine.stop() for engine in engines),
            return_exceptions=True,
        )
    _active_engines.clear()
