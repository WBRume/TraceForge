"""SessionGate：事件门禁——内存判定 + TTL 周期 DB 重校验 + interrupt 立即失效。

- is_current()：O(1) 内存判定，事件热路径零 DB 查询；
- TTL 过期后经 run_db 异步重校验一次（周期兜底，跨请求撤销可见）；
- 关键最终写入（任务状态/聊天消息/segment 批/执行日志批）在线程闭包内用
  fence_sync(db) 复核，作为条件更新兜底；
- interrupt() 或撤销路径调用 invalidate() 立即丢弃后续事件。
"""

import asyncio
import time
from typing import Optional

from app.agents import AgentAttemptContext
from app.config import settings
from app.core.logging import get_logger
from app.core.offload import run_db
from app.database import SessionLocal
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.task.models.task import SddTask

logger = get_logger(__name__, category="task_execution")


class SessionGate:
    """事件门禁：内存态判定 + TTL 周期 DB 重校验 + interrupt 立即失效。

    - is_current()：O(1) 内存判定，事件热路径零 DB 查询（替代旧
      "每事件 1-2 次 DB 查询"）；
    - TTL 过期后经 run_db 异步重校验一次（周期兜底，跨请求撤销可见）；
    - 关键最终写入（任务状态/聊天消息/segment 批/执行日志批）在线程闭包内用
      fence_sync(db) 复核，作为条件更新兜底；
    - interrupt() 或撤销路径调用 invalidate() 立即丢弃后续事件。
    """

    def __init__(
        self,
        *,
        task_id: str,
        job_id: Optional[str],
        session_revision: Optional[int],
        ttl_seconds: float,
        attempt: Optional[AgentAttemptContext] = None,
        additional_fences=(),
    ):
        self.task_id = task_id
        self.job_id = job_id
        self.session_revision = session_revision
        self.attempt = attempt
        self.additional_fences = tuple(additional_fences)
        self._ttl = max(0.0, float(ttl_seconds))
        self._armed = bool(job_id and session_revision is not None)
        self._stale = False
        self._db_current = True
        self._last_refresh = 0.0
        self._refresh_task: Optional[asyncio.Task] = None

    def invalidate(self) -> None:
        self._stale = True
        self._db_current = False

    def is_current(self) -> bool:
        if self._stale:
            return False
        if not self._armed:
            return True
        now = time.monotonic()
        if now - self._last_refresh >= self._ttl:
            # 立即推进时间戳，保证一个 TTL 窗口内只调度一次重校验
            self._last_refresh = now
            self._schedule_refresh()
        return self._db_current

    def _schedule_refresh(self) -> None:
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 线程上下文（如执行日志落库闭包）：跳过，由事件循环内下一次判定触发
            return
        self._refresh_task = loop.create_task(self.refresh())

    async def load(self) -> None:
        """run() 开始时的基线校验：加载 job/task revision 快照。"""
        if not self._armed:
            return
        try:
            await self.refresh()
        except Exception as exc:
            logger.warning(f"Session gate initial load failed: {exc}")

    async def refresh(self) -> bool:
        def _check() -> bool:
            db = SessionLocal()
            try:
                return self.fence_sync(db)
            except Exception:
                # 瞬时 DB 故障按过期处理：宁可丢事件，也不把过期事件写进历史
                return False
            finally:
                db.close()

        try:
            result = await run_db(_check)
        except Exception as exc:
            logger.warning(f"Session gate refresh failed: {exc}")
            return self._db_current
        self._db_current = result
        self._last_refresh = time.monotonic()
        return result

    def fence_sync(self, db) -> bool:
        """线程闭包内的关键写入复核（复用调用方 session，不另开连接）。"""
        if self._stale:
            return False
        for fence in self.additional_fences:
            if not fence.fence_sync(db):
                return False
        if not self._armed:
            return True
        try:
            job = db.query(SddAiJob).filter(SddAiJob.id == self.job_id).first()
            if not job or job.status in {
                AiJobStatus.REVERTED,
                AiJobStatus.CANCELLED,
                AiJobStatus.TERMINATING,
                AiJobStatus.ORPHANED,
            }:
                return False
            if self.attempt is not None and (
                str(job.run_token or "") != self.attempt.run_token
                or str(job.worker_boot_id or "") != self.attempt.worker_boot_id
                or job.cancel_requested_at is not None
                or job.status != AiJobStatus.RUNNING
            ):
                return False
            if job.task_id:
                task = db.query(SddTask).filter(SddTask.id == job.task_id).first()
                if not task or int(task.session_revision if task.session_revision is not None else -1) != int(self.session_revision):
                    return False
            return int(job.session_revision if job.session_revision is not None else -1) == int(self.session_revision)
        except Exception:
            return False
