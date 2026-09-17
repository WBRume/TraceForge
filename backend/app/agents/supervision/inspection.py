"""有界 inspection executor：所有进程表扫描的统一离环入口。

高频 psutil / ``/proc`` 树扫描绝不运行在主事件循环中，也不复用 DB
executor（doc §12.2）。本模块提供：

- 惰性创建的小型线程池（worker 数由配置上界）；
- 许可制有界队列（doc 修复方案 §7.4）：一次探测 = 一个工作项，提交前
  必须取得许可，饱和提交直接抛 :class:`InspectionQueueSaturated`，绝不
  静默排队；
- :func:`run_process_probe` —— 事件循环侧的 await 入口。

许可所有权（doc 审计 P1-2）：成功 ``submit`` 之后，许可的唯一释放者是
原始 ``concurrent.futures.Future`` 的完成回调——排队期取消、运行期取消、
函数异常、正常完成都恰好释放一次。asyncio 层的取消绝不提前释放许可
（底层线程可能仍在执行）；``submit`` 抛错时工作项从未入队，由提交方
释放。
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

_INSPECTION_EXECUTOR: ThreadPoolExecutor | None = None
_INSPECTION_EXECUTOR_LOCK = threading.Lock()


class InspectionQueueSaturated(RuntimeError):
    """The bounded inspection queue is full; callers must degrade to UNKNOWN.

    有界 gate（doc 修复方案 §7.4）：探测请求饱和时立刻拒绝并把调用方降级为
    UNKNOWN 稍后重试，而不是在进程表压力下继续无界排队拖垮 inspection
    worker。
    """


# 一次探测 = 一个工作项；提交前必须取得许可，探测完成后在 executor 内释放。
# 队列深度因此有硬上界，饱和提交直接失败（绝不静默排队）。
_INSPECTION_QUEUE_MAX_PENDING = 64
_INSPECTION_QUEUE_PERMITS = threading.BoundedSemaphore(_INSPECTION_QUEUE_MAX_PENDING)


def monitor_interval_seconds() -> float:
    try:
        from app.config import settings

        return max(
            0.05,
            float(getattr(settings, "AGENT_PROCESS_MONITOR_INTERVAL_SECONDS", 0.25) or 0.25),
        )
    except Exception:
        return 0.25


def _inspection_executor() -> ThreadPoolExecutor:
    global _INSPECTION_EXECUTOR
    with _INSPECTION_EXECUTOR_LOCK:
        if _INSPECTION_EXECUTOR is None:
            try:
                from app.config import settings

                workers = max(1, int(getattr(settings, "AGENT_PROCESS_INSPECTION_WORKERS", 2) or 2))
            except Exception:
                workers = 2
            _INSPECTION_EXECUTOR = ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="agent-process-inspection",
            )
    return _INSPECTION_EXECUTOR


def submit_process_probe(fn: Callable[..., Any], *args: Any):
    """Acquire one inspection permit and submit the work item (sync, non-blocking).

    队列饱和时抛 :class:`InspectionQueueSaturated`；返回原始
    ``concurrent.futures.Future``。注意：返回句柄（pidfd）的探测必须走
    :mod:`app.agents.supervision.identity` 的身份探测入口，其取消路径负责
    回收迟到结果并释放资源（doc 审计 P1-2）。
    """
    if not _INSPECTION_QUEUE_PERMITS.acquire(blocking=False):
        raise InspectionQueueSaturated(
            "process inspection queue is saturated; retry later"
        )
    executor = _inspection_executor()
    try:
        raw_future = executor.submit(fn, *args)
    except Exception:
        # The work item was never queued (executor shutdown race): release
        # here, otherwise the permit would leak and shrink the queue forever.
        _INSPECTION_QUEUE_PERMITS.release()
        raise
    raw_future.add_done_callback(
        lambda _future: _INSPECTION_QUEUE_PERMITS.release()
    )
    return raw_future


async def run_process_probe(fn: Callable[..., Any], *args: Any) -> Any:
    """Run one synchronous process probe in the bounded inspection executor.

    所有 psutil / ``/proc`` / cmdline / environ / 进程组成员访问都必须经本
    入口 offload；事件循环上只做信号发送与三态结果聚合（doc 修复方案
    §7.4）。队列饱和时抛出 :class:`InspectionQueueSaturated`，由调用方转成
    UNKNOWN 快照稍后重试。

    注意：本入口返回纯快照（不持有系统资源）。返回句柄（pidfd）的探测
    必须走 :mod:`app.agents.supervision.identity` 的身份探测入口，其取消
    路径负责回收迟到结果并释放资源（doc 审计 P1-2）。
    """
    loop = asyncio.get_running_loop()
    return await asyncio.futures.wrap_future(
        submit_process_probe(fn, *args), loop=loop
    )


async def run_process_inspection(
    fn: Callable[..., Any],
    managed: Any,
) -> Any:
    """Run one managed-tree inspection in the bounded executor (never on the loop).

    The monitor awaits the result, so a single managed process can never have
    more than one outstanding inspection and samples do not queue up.
    """
    return await run_process_probe(fn, managed)
