"""回合持久化批量窗口：执行日志批、context segment/snapshot 批、任务状态/指标。

高频 provider 事件不再逐条提交：BatchFlusher 提供统一的「延迟窗口 +
单事务持久化 + 失败回填 + 有界排空」骨架；两个具体 batcher 只描述各自
缓冲什么、如何写、失败如何回填。所有线程内持久化闭包先经 SessionGate
fence 复核（job 未撤销/revision 未变），过期批次直接丢弃。
"""

import asyncio
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.config import settings
from app.core.logging import get_logger
from app.core.offload import run_db
from app.database import SessionLocal
from app.domains.task.models.log import LogType, SddExecutionLog
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.services import context_token_service

logger = get_logger(__name__, category="task_execution")

EXECUTION_LOG_CONTENT_LIMIT = 4000
EXECUTION_LOG_FLUSH_INTERVAL_SECONDS = 0.5
# 批量落库失败重试：回填缓冲后，连续失败达上限丢弃最旧批次；drain 阶段最多重试轮数
EXECUTION_LOG_MAX_CONSECUTIVE_FAILURES = 3
EXECUTION_LOG_DRAIN_MAX_ROUNDS = 3
SEGMENT_MAX_CONSECUTIVE_FAILURES = 3
SEGMENT_DRAIN_MAX_ROUNDS = 3


class BatchFlusher:
    """延迟窗口批量落库骨架：调度 → 单事务持久化 → 失败回填 → 有界排空。

    子类实现四个钩子：
    - _pending_count()：待写条数（排空判空与重试进展的计数依据）；
    - _collect()：取走全部待写数据组成一个批次；
    - _persist(batch)：经 run_db 在线程内单事务写入（失败向上抛出）；
    - _requeue(batch)：失败回填（内部用 register_failure 执行上限丢批策略）。

    事件循环缺失（线程上下文）时的入队行为由子类入口自行决定。
    """

    def __init__(
        self,
        *,
        interval_getter: Callable[[], float],
        max_consecutive_failures: int,
        drain_max_rounds: int,
    ):
        self._interval_getter = interval_getter
        self._max_consecutive_failures = max_consecutive_failures
        self._drain_max_rounds = drain_max_rounds
        self._flush_task: Optional[asyncio.Task] = None
        self._draining = False
        self._consecutive_failures = 0

    # ── 子类钩子 ──

    def _pending_count(self) -> int:
        raise NotImplementedError

    def _collect(self) -> Any:
        raise NotImplementedError

    async def _persist(self, batch: Any) -> None:
        raise NotImplementedError

    def _requeue(self, batch: Any) -> None:
        raise NotImplementedError

    # ── 骨架 ──

    def flush_soon(self, *, immediate: bool = False) -> None:
        """调度一次延迟 flush；已在排空中、已有待执行任务或无事件循环时跳过。"""
        if self._draining:
            return
        if self._flush_task is not None and not self._flush_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 线程上下文：等待事件循环内的下一次入队触发
            return
        self._flush_task = loop.create_task(self._flush_after_delay(immediate))

    def register_failure(self, dropped_count: int) -> bool:
        """记录一次持久化失败；连续失败达上限时丢弃本批并复位计数。

        返回 True 表示本批已被丢弃（调用方不应再回填）。
        """
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._max_consecutive_failures:
            logger.error(
                f"{type(self).__name__} persist failed {self._consecutive_failures}x "
                f"consecutively, dropping oldest batch ({dropped_count} entries)"
            )
            self._consecutive_failures = 0
            return True
        return False

    async def _flush_after_delay(self, immediate: bool = False) -> None:
        current_task = asyncio.current_task()
        cancelled = False
        try:
            if not immediate:
                interval = self._interval_getter()
                if interval > 0:
                    await asyncio.sleep(interval)
            await self.flush()
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            if self._flush_task is current_task:
                self._flush_task = None
            if self._pending_count() and not self._draining and not cancelled:
                self._flush_task = asyncio.create_task(self._flush_after_delay())

    async def flush(self) -> None:
        """取走当前待写数据并单事务落库；失败回填等待下轮。"""
        if not self._pending_count():
            return
        batch = self._collect()
        try:
            await self._persist(batch)
            self._consecutive_failures = 0
        except Exception as exc:
            logger.warning(f"{type(self).__name__} batch flush failed: {exc}")
            self._requeue(batch)

    async def drain(self) -> None:
        """结束/异常/HITL 前强制排空：等待已调度任务 + 有限轮数重试。

        drain 阶段不轻易丢批：每轮失败回填后重试，连续无进展达上限轮数退出，
        剩余缓冲交给后续定时窗口兜底。
        """
        self._draining = True
        try:
            scheduled = self._flush_task
            if scheduled is not None and scheduled is not asyncio.current_task():
                try:
                    await scheduled
                except asyncio.CancelledError:
                    pass
            self._flush_task = None
            retries = 0
            while self._pending_count() and retries < self._drain_max_rounds:
                before = self._pending_count()
                await self.flush()
                if self._pending_count() >= before:
                    retries += 1
        finally:
            self._draining = False


class ExecutionLogBatcher(BatchFlusher):
    """业务相关终端事件（工具调用/结果、压缩标记等）的短窗口批量执行日志。"""

    def __init__(self, owner):
        super().__init__(
            interval_getter=lambda: EXECUTION_LOG_FLUSH_INTERVAL_SECONDS,
            max_consecutive_failures=EXECUTION_LOG_MAX_CONSECUTIVE_FAILURES,
            drain_max_rounds=EXECUTION_LOG_DRAIN_MAX_ROUNDS,
        )
        self._owner = owner
        self._buffer: List[Tuple[str, LogType, int]] = []
        self._order = time.time_ns()

    def queue(self, content: str, log_type: LogType = LogType.STDOUT) -> None:
        """Queue a business-relevant terminal event for short-window batching."""
        if not content:
            return

        self._order = max(time.time_ns(), self._order + 1)
        self._buffer.append((content, log_type, self._order))
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # 线程上下文：立即同步刷一批（不经 run_db 卸载）
            batch, self._buffer = self._buffer, []
            try:
                self._persist_sync(batch)
                self._consecutive_failures = 0
            except Exception as exc:
                logger.warning(f"Execution log batch flush failed: {exc}")
                self._requeue(batch)
            return

        self.flush_soon()

    def _pending_count(self) -> int:
        return len(self._buffer)

    def _collect(self) -> List[Tuple[str, LogType, int]]:
        batch, self._buffer = self._buffer, []
        return batch

    async def _persist(self, batch: List[Tuple[str, LogType, int]]) -> None:
        await run_db(self._persist_sync, batch)

    def _persist_sync(self, entries: List[Tuple[str, LogType, int]]) -> None:
        """Persist one execution-log batch in a single transaction (线程内执行).

        失败抛出由骨架负责回填重试（见 _requeue）。
        """
        if not entries:
            return

        db = SessionLocal()
        try:
            # 关键写入兜底：复用同一 session 做门禁复核（job 未撤销/revision 未变）
            gate = self._owner.gate
            if gate is not None and not gate.fence_sync(db):
                return
            db.add_all([
                SddExecutionLog(
                    task_id=self._owner.task_id,
                    workspace_id=self._owner.ws_id,
                    creator_id=self._owner.user_id,
                    log_type=log_type,
                    content=content[:EXECUTION_LOG_CONTENT_LIMIT],
                    event_order=event_order,
                    session_turn_id=self._owner.session_turn_id,
                )
                for content, log_type, event_order in entries
            ])
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _requeue(self, batch: List[Tuple[str, LogType, int]]) -> None:
        """落库失败：回填缓冲保持顺序；连续失败达上限则丢弃最旧批次（防缓冲无限增长）。"""
        if self.register_failure(len(batch)):
            return
        self._buffer[:0] = batch


class ContextSegmentBatcher(BatchFlusher):
    """context segment / snapshot 批量窗口（高频事件不再逐条提交）。

    - record(recorder, **kwargs)：入队 segment；
    - update_snapshot(...)：瞬态 snapshot 合并（last-write-wins），随批落库；
    - thinking 不逐 delta 提交：仅 mark_thinking_dirty() 打脏标记，flush 时
      以 ThinkingStream 的合并累积内容落一条（revision 对比判定脏）。
    """

    def __init__(self, owner):
        super().__init__(
            interval_getter=lambda: float(getattr(settings, "SEGMENT_FLUSH_INTERVAL_SECONDS", 0.2)),
            max_consecutive_failures=SEGMENT_MAX_CONSECUTIVE_FAILURES,
            drain_max_rounds=SEGMENT_DRAIN_MAX_ROUNDS,
        )
        self._owner = owner
        self._buffer: List[Tuple[str, Dict[str, Any]]] = []
        self._pending_snapshot: Dict[str, Any] = {}
        self._thinking: Optional[Any] = None  # ThinkingStream，由引擎装配
        self._last_thinking_revision = -1

    def attach_thinking(self, thinking: Any) -> None:
        self._thinking = thinking

    def _thinking_pending(self) -> bool:
        return (
            self._thinking is not None
            and self._thinking.revision != self._last_thinking_revision
        )

    def mark_thinking_dirty(self) -> None:
        """thinking 内容已变化：打脏标记并调度窗口（flush 时读取合并内容）。"""
        if not self._owner.is_current():
            return
        self.flush_soon(immediate=self._buffer_full())

    def record(self, recorder: str, **kwargs: Any) -> None:
        """入队 context segment，按数量/时间窗口批量落库（调用方已在事件入口过门禁）。"""
        if not self._owner.is_current():
            return
        self._buffer.append((recorder, kwargs))
        self.flush_soon(immediate=self._buffer_full())

    def update_snapshot(
        self,
        *,
        usage: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
        status: Optional[str] = None,
        duration_ms: Optional[int] = None,
        total_cost_usd: Optional[float] = None,
        raw_usage_json: Any = None,
    ) -> None:
        """瞬态 snapshot 更新：合并进内存 pending，随 segment 批量窗口一次落库。

        可合并字段按最后写入者胜出；usage 内非 None 字段浅合并。
        最终写入点（result/超时/异常）调用方负责随后 await flush()。
        """
        if not self._owner.is_current():
            return
        pending = self._pending_snapshot
        if usage is not None:
            current_usage = pending.get("usage") if isinstance(pending.get("usage"), dict) else {}
            merged_usage = dict(current_usage)
            if isinstance(usage, dict):
                for key, value in usage.items():
                    if value is not None:
                        merged_usage[key] = value
            pending["usage"] = merged_usage
        if model is not None:
            pending["model"] = model
        if status is not None:
            pending["status"] = status
        if duration_ms is not None:
            pending["duration_ms"] = duration_ms
        if total_cost_usd is not None:
            pending["total_cost_usd"] = total_cost_usd
        if raw_usage_json is not None:
            pending["raw_usage_json"] = raw_usage_json
        self.flush_soon(immediate=self._buffer_full())

    def _buffer_full(self) -> bool:
        return len(self._buffer) >= int(getattr(settings, "SEGMENT_FLUSH_MAX_ITEMS", 50))

    def _pending_count(self) -> int:
        return (
            len(self._buffer)
            + (1 if self._thinking_pending() else 0)
            + (1 if self._pending_snapshot else 0)
        )

    def _collect(self) -> Tuple[List[Tuple[str, Dict[str, Any]]], Optional[Dict[str, Any]]]:
        entries: List[Tuple[str, Dict[str, Any]]] = []
        if self._thinking_pending():
            self._last_thinking_revision = self._thinking.revision
            content = self._thinking.content
            if content.strip():
                entries.append(("thinking", {
                    "workspace_id": self._owner.ws_id,
                    "task_id": self._owner.task_id,
                    "ai_job_id": self._owner.current_job_id,
                    "session_id": self._owner.session_id,
                    "content": content,
                }))
        if self._buffer:
            buffered, self._buffer = self._buffer, []
            entries.extend(buffered)
        snapshot_update: Optional[Dict[str, Any]] = None
        if self._pending_snapshot:
            pending, self._pending_snapshot = self._pending_snapshot, {}
            snapshot_update = {
                **pending,
                "workspace_id": self._owner.ws_id,
                "task_id": self._owner.task_id,
                "ai_job_id": self._owner.current_job_id,
                "session_id": self._owner.session_id,
            }
        return entries, snapshot_update

    async def _persist(self, batch) -> None:
        entries, snapshot_update = batch
        if not entries and not snapshot_update:
            return
        await run_db(self._persist_sync, entries, snapshot_update)

    def _persist_sync(
        self,
        entries: List[Tuple[str, Dict[str, Any]]],
        snapshot_update: Optional[Dict[str, Any]] = None,
    ) -> None:
        """线程内执行：单事务写入一批 segment（可选顺带 snapshot 更新）。

        失败抛出由骨架负责回填重试（见 _requeue）。
        """
        if not entries and not snapshot_update:
            return
        db = SessionLocal()
        try:
            gate = self._owner.gate
            if gate is not None and not gate.fence_sync(db):
                return
            context_token_service.record_segments_batch(
                db, entries, snapshot_update=snapshot_update,
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _requeue(self, batch) -> None:
        """落库失败：回填 segment 与 snapshot 待写值；连续失败达上限丢最旧 segment 批。"""
        entries, snapshot_update = batch
        if snapshot_update:
            # snapshot 是 last-write-wins 合并值，失败后先恢复为 pending
            merged = dict(snapshot_update)
            if self._pending_snapshot:
                merged.update(self._pending_snapshot)
            self._pending_snapshot = merged
        dropped = self.register_failure(len(entries))
        if not dropped:
            self._buffer[:0] = entries
        self.flush_soon(immediate=self._buffer_full())


# ─────────────── 任务状态 / 指标（off-loop 条件写入） ───────────────


def update_task_status(owner, status: TaskStatus, error_msg: Optional[str] = None):
    """任务状态更新（off-loop，条件更新兜底 fence）。"""
    return run_db(_update_task_status_sync, owner, status, error_msg)


def _update_task_status_sync(owner, status: TaskStatus, error_msg: Optional[str] = None):
    db = SessionLocal()
    try:
        gate = owner.gate
        if gate is not None and not gate.fence_sync(db):
            return
        task = db.query(SddTask).filter(SddTask.id == owner.task_id).first()
        if task:
            task.status = status
            if error_msg:
                task.error_message = error_msg
            db.commit()
    except Exception as e:
        db.rollback()
        logger.exception(f"Update task status failed: {e}")
    finally:
        db.close()


def update_task_metrics(owner, cost: Optional[float], duration: Optional[int], status: Optional[str] = None):
    """累加消耗并记录指标（off-loop）。"""
    return run_db(_update_task_metrics_sync, owner, cost, duration, status)


def _update_task_metrics_sync(owner, cost: Optional[float], duration: Optional[int], status: Optional[str] = None):
    from app.domains.dashboard.models.metric import SddDashboardMetric

    db = SessionLocal()
    try:
        gate = owner.gate
        if gate is not None and not gate.fence_sync(db):
            return
        task = db.query(SddTask).filter(SddTask.id == owner.task_id).first()
        if not task:
            return

        # 如果任务已完成，不再增加统计 (HITL 后的额外操作可能需要用户决定)
        if task.status in {TaskStatus.DONE, TaskStatus.BASELINED}:
            return

        if cost:
            task.total_cost_usd += cost
            # 记录成本指标
            task.dashboard_metrics.append(SddDashboardMetric(
                workspace_id=owner.ws_id,
                metric_type="COST", metric_value=cost
            ))
        if duration:
            task.total_duration_ms += duration
            # 记录耗时指标
            task.dashboard_metrics.append(SddDashboardMetric(
                workspace_id=owner.ws_id,
                metric_type="DURATION", metric_value=duration
            ))

        if status:
            # 记录状态变更指标 (用于即使删了 Task 也保留统计)
            task.dashboard_metrics.append(SddDashboardMetric(
                workspace_id=owner.ws_id,
                metric_type="TASK_RESULT", metric_value=1.0 if status == "DONE" else 0.0
            ))

        db.commit()
    except Exception as e:
        logger.exception(f"Update task metrics failed: {e}")
        db.rollback()
    finally:
        db.close()
