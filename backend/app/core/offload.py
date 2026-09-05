"""
同步阻塞操作的统一 offload 层。

事件循环内禁止直接执行同步 DB / git / 大文件 IO；统一通过本模块的
专用线程池执行。规则：

- 线程闭包内自行创建和关闭 Session（优先用 run_db_txn）；
- 禁止把 request session 或 engine 持有的 session 带入线程；
- DB、git、文件复制分属不同 executor，避免互相拖死；
- MySQL connect/read/write timeout 由 app.database 统一配置，
  防止 executor 线程被无超时查询永久占用。

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
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional, TypeVar

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__, category="offload")

T = TypeVar("T")

_db_executor: Optional[ThreadPoolExecutor] = None
_git_executor: Optional[ThreadPoolExecutor] = None
_file_executor: Optional[ThreadPoolExecutor] = None

_executors: list[ThreadPoolExecutor] = []


def _ensure_executors() -> tuple[ThreadPoolExecutor, ThreadPoolExecutor, ThreadPoolExecutor]:
    global _db_executor, _git_executor, _file_executor
    if _db_executor is None:
        _db_executor = ThreadPoolExecutor(
            max_workers=max(1, int(settings.DB_OFFLOAD_WORKERS)),
            thread_name_prefix="db-offload",
        )
        _executors.append(_db_executor)
    if _git_executor is None:
        _git_executor = ThreadPoolExecutor(
            max_workers=max(1, int(settings.GIT_OFFLOAD_WORKERS)),
            thread_name_prefix="git-offload",
        )
        _executors.append(_git_executor)
    if _file_executor is None:
        _file_executor = ThreadPoolExecutor(
            max_workers=max(1, int(settings.FILE_OFFLOAD_WORKERS)),
            thread_name_prefix="file-offload",
        )
        _executors.append(_file_executor)
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
    **kwargs: Any,
) -> T:
    """在指定线程池中执行 fn，事件循环不被阻塞。"""
    loop = asyncio.get_running_loop()
    call = lambda: fn(*args, **kwargs)  # noqa: E731
    return await loop.run_in_executor(executor, call)


async def run_db(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """在 DB 专用线程池中执行同步函数（函数内部自行管理 session/事务）。"""
    return await run_in_executor(db_executor(), fn, *args, **kwargs)


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


def shutdown_offload_executors(wait: bool = False) -> None:
    """应用关闭时释放线程池；wait=False 立即返回，不等待队列排空。"""
    for executor in list(_executors):
        try:
            executor.shutdown(wait=wait, cancel_futures=not wait)
        except Exception:
            logger.exception("Failed to shutdown offload executor")
    _executors.clear()
    global _db_executor, _git_executor, _file_executor
    _db_executor = _git_executor = _file_executor = None
