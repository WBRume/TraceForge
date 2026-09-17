"""ProcessSupervisor：本地 Agent 进程注册表与生命周期编排入口。

职责边界（重构自 3456 行单体的对外门面只保留编排，不保留逻辑）：

- **注册表**：跟踪本 worker 内所有受管进程；``active_count`` 仅供诊断
  （树检查只能在 inspection executor 中执行）；
- **spawn**：委托 :mod:`...spawn` 的编排流程，成功后登记；
- **attempt 级停止**（本 worker 持有的进程）：``stop_attempt`` /
  ``stop_all``，必须处理同一 run token 下的全部进程（doc 10）；
- **boot 级回收**（上一轮 boot 的遗留进程）：``stop_persisted`` /
  ``stop_by_run_token_discovery`` / ``verify_persisted_cleanup`` 委托
  :mod:`...reclaim`——这些流程不接触注册表状态，是独立的领域边界。

单例 :data:`process_supervisor` 是全部调用方（adapters / jobs / routers）
共享的入口。
"""

from __future__ import annotations

import asyncio
from typing import Optional

from app.agents.contract import record_attempt_termination
from app.agents.supervision import reclaim, spawn
from app.agents.supervision.managed import ManagedAgentProcess
from app.agents.supervision.model import (
    TerminationResult,
)


class ProcessSupervisor:
    """Tracks every locally spawned Agent process in this worker."""

    def __init__(self) -> None:
        self._processes: set = set()
        # Strong references for uncancellable cleanup tasks: they must not be
        # garbage-collected while a caller cancellation storm is in progress.
        self._cleanup_tasks: set = set()

    # ── 注册表 ──────────────────────────────────────────────────────

    def register(self, managed: ManagedAgentProcess) -> None:
        self._processes.add(managed)

    def unregister(self, managed: ManagedAgentProcess) -> None:
        self._processes.discard(managed)

    def register_cleanup_task(self, task: asyncio.Task) -> None:
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    @property
    def active_count(self) -> int:
        """Approximate active count from cached state (never scans the tree on-loop).

        树检查只能在 inspection executor 中执行；本计数以 asyncio returncode
        与缓存的已知后代为准，仅供诊断展示。
        """
        return sum(
            1
            for item in self._processes
            if item.process.returncode is None or item.known_descendant_pids
        )

    def forget(self, managed: ManagedAgentProcess) -> None:
        cached = managed._last_termination
        if managed._closed or (
            managed.process.returncode is not None
            and bool(cached is not None and cached.confirmed_dead)
        ):
            self._processes.discard(managed)

    # ── spawn（委托编排流程）────────────────────────────────────────

    async def spawn(
        self,
        args: list,
        *,
        cwd: str,
        env: dict,
        run_token: Optional[str] = None,
        worker_boot_id: Optional[str] = None,
        on_process_started=None,
        containment_id: Optional[str] = None,
        process_attach_timeout_seconds: Optional[float] = None,
    ) -> ManagedAgentProcess:
        return await spawn.spawn_supervised(
            self,
            args,
            cwd=cwd,
            env=env,
            run_token=run_token,
            worker_boot_id=worker_boot_id,
            on_process_started=on_process_started,
            containment_id=containment_id,
            process_attach_timeout_seconds=process_attach_timeout_seconds,
        )

    # ── attempt 级停止（本 worker 持有的进程）───────────────────────

    async def stop_attempt(self, run_token: str, reason: str) -> Optional[TerminationResult]:
        """Stop every process registered under this run token (doc 10).

        Must not stop only the first match: a retry or a spawn race can leave
        more than one live tree under the same durable token.
        """
        matches = [item for item in self._processes if item.run_token == run_token]
        if not matches:
            return None
        results: list = []
        for managed in matches:
            result = await managed.close(reason=reason)
            record_attempt_termination(result, managed.process_identity)
            if result.confirmed_dead or result.error_code == "PID_REUSED":
                self._processes.discard(managed)
            results.append(result)
        if len(results) == 1:
            return results[0]
        failed = next((item for item in results if not item.confirmed_dead), None)
        if failed is not None:
            return failed
        return TerminationResult(
            confirmed_dead=True,
            root_return_code=next(
                (item.root_return_code for item in results if item.root_return_code is not None),
                None,
            ),
            signals_sent=tuple(
                signal for item in results for signal in item.signals_sent
            ),
            tree_kill_used=any(item.tree_kill_used for item in results),
        )

    async def stop_all(self, reason: str = "worker_shutdown") -> list:
        processes = list(self._processes)
        results = await asyncio.gather(
            *(item.close(reason=reason) for item in processes),
            return_exceptions=True,
        )
        output: list = []
        for managed, result in zip(processes, results):
            if isinstance(result, TerminationResult):
                record_attempt_termination(result, managed.process_identity)
                output.append(result)
                if result.confirmed_dead:
                    self._processes.discard(managed)
            else:
                output.append(
                    TerminationResult(
                        confirmed_dead=False,
                        root_return_code=None,
                        error_code="TERMINATION_EXCEPTION",
                        error_message=str(result),
                    )
                )
        return output

    async def drain_cleanup_tasks(self, timeout: float = 10.0) -> None:
        """Wait for background cleanup tasks (used during graceful shutdown)."""
        tasks = [task for task in list(self._cleanup_tasks) if not task.done()]
        if not tasks:
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=max(0.1, timeout),
            )
        except asyncio.TimeoutError:
            pass

    # ── boot 级回收（上一轮 boot 的遗留进程，不接触注册表）──────────

    async def stop_persisted(
        self,
        pid: Optional[int],
        process_started_at,
        reason: str,
        process_group_id: Optional[int] = None,
        run_token: Optional[str] = None,
        not_before=None,
    ) -> TerminationResult:
        return await reclaim.stop_persisted(
            pid,
            process_started_at,
            reason,
            process_group_id=process_group_id,
            run_token=run_token,
            not_before=not_before,
        )

    async def stop_by_run_token_discovery(
        self,
        run_token: str,
        reason: str,
        *,
        not_before=None,
        not_after=None,
    ) -> Optional[TerminationResult]:
        return await reclaim.stop_by_run_token_discovery(
            run_token,
            reason,
            not_before=not_before,
            not_after=not_after,
        )

    async def verify_persisted_cleanup(
        self,
        pid: Optional[int],
        process_started_at,
        process_group_id: Optional[int] = None,
    ) -> TerminationResult:
        return await reclaim.verify_persisted_cleanup(
            pid,
            process_started_at,
            process_group_id,
        )


process_supervisor = ProcessSupervisor()
