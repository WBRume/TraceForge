"""进程内 AI 作业运行时注册表。

这里集中了所有 process-local 的可变状态：worker 身份、队列 runner 注册表、
取消信号、心跳任务、常驻 worker 任务与关停标志。除此之外的模块不持有
作业级内存状态，测试也只需替换本模块的 :data:`runtime` 单例。
"""

from __future__ import annotations

import asyncio
import socket
import uuid
from typing import Any, Dict

from app.config import settings
from app.core.logging import get_logger
from app.domains.ai.models.ai_job import AiJobStatus

logger = get_logger(__name__, category="ai_session")

WORKER_BOOT_ID = str(uuid.uuid4())
WORKER_ID = (
    f"{socket.gethostname()}:{getattr(settings, 'WORKER_SERVICE_NAME', 'traceforge-api')}"
    f":{getattr(settings, 'WORKER_INDEX', '0')}"
)


class JobRuntime:
    """单事件循环内的作业运行时状态（随进程生命周期存续）。"""

    def __init__(self) -> None:
        self.queue_locks: Dict[str, asyncio.Lock] = {}
        self.queue_runners: Dict[str, asyncio.Task] = {}
        self.cancel_events: Dict[str, asyncio.Event] = {}
        self.heartbeat_tasks: Dict[str, asyncio.Task] = {}
        # reaper / dispatcher 常驻 worker 任务（由 workers 模块写入）。
        self.worker_tasks: Dict[str, asyncio.Task] = {}
        self.shutting_down: bool = False

    # ── 关停 ────────────────────────────────────────────────────────────

    def shutdown_in_progress(self) -> bool:
        """Return true only while shutdown is actively draining workers.

        After shutdown has fully completed, a new application lifecycle (or an
        isolated event loop in tests) may schedule a queue again.  The durable
        process itself is still protected because claims are blocked while the
        reaper/dispatcher workers are being drained.
        """
        return bool(self.shutting_down and self.worker_tasks)

    # ── 队列 runner 调度 ────────────────────────────────────────────────

    def queue_lock(self, queue_key: str) -> asyncio.Lock:
        lock = self.queue_locks.get(queue_key)
        if lock is None:
            lock = asyncio.Lock()
            self.queue_locks[queue_key] = lock
        return lock

    def reap_queue_runner(self, queue_key: str, task: "asyncio.Task") -> None:
        """Runner 结束后回收注册表条目（单事件循环内同步判定，无 await 夹缝）。

        仅当条目仍指向本 task 时摘除（避免误删后继 runner）；同 key 锁在无后继
        runner 且未被持有时一并回收。顺带消费未检视的异常避免告警噪音。
        """
        if self.queue_runners.get(queue_key) is not task:
            return
        self.queue_runners.pop(queue_key, None)
        if not task.cancelled():
            exc = task.exception()
            if exc is not None:
                logger.warning(f"AI queue runner exited with error: queue_key={queue_key}, error={exc}")
        lock = self.queue_locks.get(queue_key)
        if lock is not None and not lock.locked():
            self.queue_locks.pop(queue_key, None)

    def schedule_queue(self, queue_key: str) -> None:
        from app.domains.ai.services.jobs.queue_runner import run_queue

        if self.shutdown_in_progress():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        running = self.queue_runners.get(queue_key)
        if running and not running.done():
            return
        runner = loop.create_task(run_queue(queue_key))
        self.queue_runners[queue_key] = runner
        runner.add_done_callback(lambda task: self.reap_queue_runner(queue_key, task))

    # ── 取消信号 ────────────────────────────────────────────────────────

    def get_or_create_cancel_event(self, job_id: str) -> asyncio.Event:
        event = self.cancel_events.get(job_id)
        if event is None:
            event = asyncio.Event()
            self.cancel_events[job_id] = event
        return event

    def request_cancel(self, job_id: str) -> None:
        event = self.get_or_create_cancel_event(job_id)
        event_loop = getattr(event, "_loop", None)
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if event_loop is not None and event_loop.is_running() and event_loop is not current_loop:
            event_loop.call_soon_threadsafe(event.set)
        else:
            event.set()

    def is_cancel_requested(self, job_id: str) -> bool:
        event = self.cancel_events.get(job_id)
        return bool(event and event.is_set())

    def clear_cancel(self, job_id: str) -> None:
        self.cancel_events.pop(job_id, None)

    def clear_cancel_for_payload(self, payload: Dict[str, Any]) -> None:
        """可恢复 INTERRUPTED 行必须回收取消事件，避免恢复回合被旧信号误杀。"""
        if str(payload.get("status") or "") == AiJobStatus.INTERRUPTED.value:
            self.clear_cancel(str(payload.get("id") or ""))


runtime = JobRuntime()
