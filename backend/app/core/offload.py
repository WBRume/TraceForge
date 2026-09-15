"""
同步阻塞操作的统一 offload 层。

事件循环内禁止直接执行同步 DB / git / 大文件 IO；统一通过本模块的
专用线程池执行。规则：

- 线程闭包内自行创建和关闭 Session（优先用 run_db_txn）；
- 禁止把 request session 或 engine 持有的 session 带入线程；
- DB、git、文件复制分属不同 executor，避免互相拖死；
- MySQL connect/read/write timeout 由 app.database 统一配置，
  防止 executor 线程被无超时查询永久占用；
- 每个池有在飞任务上限（信号量背压）：提交方在事件循环上 await 等待，
  而不是让待执行队列无限堆积（ThreadPoolExecutor 内部队列无界）。

用法::

    # 自由闭包（内部自行管理 session）
    rows = await run_db(load_history, task_id)

    # 事务闭包（线程内创建 SessionLocal，body 正常返回即 commit）
    msg = await run_db_txn(lambda db: task_service.save_chat_message(
        db, task_id, workspace_id, creator_id, role="user", content=content,
    ))
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional, TypeVar

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__, category="offload")

T = TypeVar("T")

_db_executor: Optional[ThreadPoolExecutor] = None
_git_executor: Optional[ThreadPoolExecutor] = None
_file_executor: Optional[ThreadPoolExecutor] = None

_db_gate: Optional["InflightGate"] = None
_git_gate: Optional["InflightGate"] = None
_file_gate: Optional["InflightGate"] = None

_executors: list[ThreadPoolExecutor] = []
_gates: list["InflightGate"] = []


class InflightGate:
    """在飞任务上限（信号量背压）。

    pending 上限超出 worker 数，允许少量排队；提交方 acquire 时在事件循环
    await 等待，把背压传导给产生任务的源头，而不是让队列无限堆积。
    """

    def __init__(self, *, workers: int, pending_limit: int, name: str) -> None:
        self._semaphore = threading.Semaphore(max(1, int(pending_limit)))
        self.name = name
        self.inflight = 0

    async def acquire(self) -> None:
        semaphore = self._semaphore
        while not semaphore.acquire(blocking=False):
            await asyncio.sleep(0.01)
        self.inflight += 1

    def release(self) -> None:
        self.inflight = max(0, self.inflight - 1)
        self._semaphore.release()


def _limit_config(workers: int, attr: str, default: int) -> int:
    configured = getattr(settings, attr, None)
    if configured is None:
        return default
    try:
        value = int(configured)
    except (TypeError, ValueError):
        value = default
    return max(workers, value)


def _ensure_executors() -> tuple[ThreadPoolExecutor, ThreadPoolExecutor, ThreadPoolExecutor]:
    global _db_executor, _git_executor, _file_executor
    global _db_gate, _git_gate, _file_gate
    if _db_executor is None:
        db_workers = max(1, int(settings.DB_OFFLOAD_WORKERS))
        git_workers = max(1, int(settings.GIT_OFFLOAD_WORKERS))
        file_workers = max(1, int(settings.FILE_OFFLOAD_WORKERS))
        _db_executor = ThreadPoolExecutor(max_workers=db_workers, thread_name_prefix="db-offload")
        _git_executor = ThreadPoolExecutor(max_workers=git_workers, thread_name_prefix="git-offload")
        _file_executor = ThreadPoolExecutor(max_workers=file_workers, thread_name_prefix="file-offload")
        _executors.extend([_db_executor, _git_executor, _file_executor])
        # 在飞上限 = worker 数 + 有限排队额度；提交方等待而非无限堆积
        _db_gate = InflightGate(
            workers=db_workers,
            pending_limit=_limit_config(db_workers, "DB_OFFLOAD_MAX_INFLIGHT", db_workers + 16),
            name="db",
        )
        _git_gate = InflightGate(
            workers=git_workers,
            pending_limit=_limit_config(git_workers, "GIT_OFFLOAD_MAX_INFLIGHT", git_workers + 8),
            name="git",
        )
        _file_gate = InflightGate(
            workers=file_workers,
            pending_limit=_limit_config(file_workers, "FILE_OFFLOAD_MAX_INFLIGHT", file_workers + 8),
            name="file",
        )
        _gates.extend([_db_gate, _git_gate, _file_gate])
    return _db_executor, _git_executor, _file_executor


def db_executor() -> ThreadPoolExecutor:
    db, _, _ = _ensure_executors()
    return db


def git_executor() -> ThreadPoolExecutor:
    _, git, _ = _ensure_executors()
    return git


def file_executor() -> ThreadPoolExecutor:
    _, _, file = _ensure_executors()
    return file


async def run_in_executor(
    executor: ThreadPoolExecutor,
    fn: Callable[..., T],
    *args: Any,
    gate: Optional["InflightGate"] = None,
    **kwargs: Any,
) -> T:
    """在指定线程池中执行 fn，事件循环不被阻塞；gate 提供在飞背压。"""
    loop = asyncio.get_running_loop()
    call = lambda: fn(*args, **kwargs)  # noqa: E731
    if gate is None:
        return await loop.run_in_executor(executor, call)
    await gate.acquire()
    try:
        return await loop.run_in_executor(executor, call)
    finally:
        gate.release()


async def run_db(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """在 DB 专用线程池中执行同步函数（函数内部自行管理 session/事务）。"""
    _ensure_executors()
    return await run_in_executor(db_executor(), fn, *args, gate=_db_gate, **kwargs)


async def run_git_job(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """在 git 专用线程池中执行同步函数（git 子进程 + 快照/工作树操作）。

    git 子进程由 app.core.subprocess_runner 保证硬超时与整组回收，
    不会永久占用本池线程；本池与 DB/file 池隔离，避免互相拖死。
    """
    _ensure_executors()
    return await run_in_executor(git_executor(), fn, *args, gate=_git_gate, **kwargs)


async def run_file_job(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """在文件专用线程池中执行同步函数（大文件复制/删除等）。"""
    _ensure_executors()
    return await run_in_executor(file_executor(), fn, *args, gate=_file_gate, **kwargs)


async def run_db_txn(body: Callable[[Any], T]) -> T:
    """线程内创建 SessionLocal 执行 body；body 正常返回即 commit，异常即 rollback。

    Session 在 finally 中关闭；这是把同步 service 函数搬出事件循环的标准姿势。
    """
    from app.database import SessionLocal

    def _run() -> T:
        db = SessionLocal()
        try:
            result = body(db)
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return await run_db(_run)


async def run_db_txn_with_bind(bind: Any, body: Callable[[Any], T]) -> T:
    """Run a short transaction against an explicitly supplied SQLAlchemy bind.

    Request-scoped dependency sessions may point at an application-specific
    engine (notably tests and tenant-bound deployments).  Capture only the
    bind before an async boundary, then create the worker-thread session from
    that bind; the request ``Session`` itself never crosses threads.
    """
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=bind, expire_on_commit=False)

    def _run() -> T:
        db = session_factory()
        try:
            result = body(db)
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return await run_db(_run)


def shutdown_offload_executors(wait: bool = False, timeout: float = 10.0) -> None:
    """应用关闭时释放线程池。

    两阶段：先 shutdown(wait=False, cancel_futures=False) 停止接收新任务
    且**不取消**排队中的任务（取消 = 丢落库数据）；随后有限轮询在飞线程，
    超时后放弃等待（git/db 均有硬超时兜底，线程最终会退出）。
    两种模式都会重置全局句柄，下一次调用会重建全新 executor；
    wait=False 仅用于测试/异常兜底。
    """
    for executor in list(_executors):
        try:
            executor.shutdown(wait=False, cancel_futures=False)
        except Exception:
            logger.exception("Failed to shutdown offload executor")

    if wait:
        import time as _time

        deadline = _time.monotonic() + max(0.0, float(timeout))
        for executor in list(_executors):
            while _time.monotonic() < deadline:
                busy = [t for t in list(getattr(executor, "_threads", [])) if t.is_alive()]
                if not busy:
                    break
                _time.sleep(0.05)

    _executors.clear()
    _gates.clear()
    global _db_executor, _git_executor, _file_executor
    global _db_gate, _git_gate, _file_gate
    _db_executor = _git_executor = _file_executor = None
    _db_gate = _git_gate = _file_gate = None
