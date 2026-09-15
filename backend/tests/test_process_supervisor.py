"""真实子进程树测试：终止必须确认 root 与 descendant 均已退出。"""

from __future__ import annotations

import asyncio
import os
import sys
import textwrap
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.errors import AgentError
from app.agents.contract import AgentRunRequest
from app.agents.adapters.claude_code.claude_code_adapter import ClaudeCodeAdapter
from app.agents.process_supervisor import (
    ManagedAgentProcess,
    ProcessWaitResult,
    TerminationResult,
    process_supervisor,
)
from app.engine.claude_bridge import SubprocessCliBridge

try:  # psutil is used for real process-tree liveness assertions.
    import psutil
except ImportError:  # pragma: no cover - packaging/runtime guard
    psutil = None  # type: ignore[assignment]


def _child_script() -> str:
    return textwrap.dedent(
        """
        import subprocess
        import sys
        import time
        child = subprocess.Popen(
            [sys.executable, '-c', 'import time; time.sleep(60)'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(child.pid, flush=True)
        time.sleep(60)
        """
    )


def test_supervisor_kills_real_process_tree():
    async def _run():
        managed = await process_supervisor.spawn(
            [sys.executable, "-c", _child_script()],
            cwd=os.getcwd(),
            env=os.environ.copy(),
            run_token="test-process-tree",
        )
        try:
            result = await managed.terminate(reason="test")
            assert result.confirmed_dead is True
            assert result.root_return_code is not None
            assert result.tree_kill_used or os.name != "nt"
        finally:
            await managed.close(reason="test_cleanup")
            process_supervisor.forget(managed)

    asyncio.run(_run())


def test_supervisor_kills_descendant_after_root_exit():
    async def _run():
        script = textwrap.dedent(
            """
            import subprocess
            import sys
            import time
            subprocess.Popen(
                [sys.executable, '-c', 'import time; time.sleep(60)'],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.2)
            """
        )
        managed = await process_supervisor.spawn(
            [sys.executable, "-c", script],
            cwd=os.getcwd(),
            env=os.environ.copy(),
            run_token="test-root-exits-first",
        )
        try:
            await managed.process.wait()
            result = await managed.terminate(reason="test_root_exit")
            assert result.confirmed_dead is True
        finally:
            await managed.close(reason="test_cleanup")
            process_supervisor.forget(managed)

    asyncio.run(_run())


def test_managed_wait_reports_confirmed_tree_death_after_root_exit():
    async def _run():
        script = textwrap.dedent(
            """
            import subprocess
            import sys
            import time
            subprocess.Popen(
                [sys.executable, '-c', 'import time; time.sleep(60)'],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.2)
            """
        )
        managed = await process_supervisor.spawn(
            [sys.executable, "-c", script],
            cwd=os.getcwd(),
            env=os.environ.copy(),
            run_token="test-managed-wait",
        )
        try:
            result = await managed.wait()
            assert isinstance(result, ProcessWaitResult)
            assert result.root_return_code is not None
            assert result.termination.confirmed_dead is True
        finally:
            await managed.close(reason="test_cleanup")
            process_supervisor.forget(managed)

    asyncio.run(_run())


def test_managed_wait_propagates_failed_descendant_cleanup():
    async def _run():
        script = textwrap.dedent(
            """
            import subprocess
            import sys
            import time
            subprocess.Popen(
                [sys.executable, '-c', 'import time; time.sleep(60)'],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.1)
            """
        )
        managed = await process_supervisor.spawn(
            [sys.executable, "-c", script],
            cwd=os.getcwd(),
            env=os.environ.copy(),
            run_token="test-managed-wait-failed",
        )
        original_close = managed.close

        async def failed_close(reason="close"):
            return TerminationResult(
                confirmed_dead=False,
                root_return_code=managed.process.returncode,
                error_code="PROCESS_TREE_STILL_ALIVE",
                remaining_pids=(managed.pid,),
            )

        managed.close = failed_close
        try:
            result = await managed.wait()
            assert result.termination.confirmed_dead is False
            assert result.termination.error_code == "PROCESS_TREE_STILL_ALIVE"
        finally:
            managed.close = original_close
            await original_close(reason="test_cleanup")
            process_supervisor.forget(managed)

    asyncio.run(_run())


def test_bridge_wait_keeps_failed_tree_registered():
    async def _run():
        bridge = SubprocessCliBridge()
        process = SimpleNamespace(returncode=0)
        managed = MagicMock()
        managed.process = process
        managed.wait = AsyncMock(
            return_value=ProcessWaitResult(
                root_return_code=0,
                termination=TerminationResult(
                    confirmed_dead=False,
                    root_return_code=0,
                    error_code="PROCESS_TREE_STILL_ALIVE",
                ),
            )
        )
        bridge.process = process
        bridge._managed_process = managed
        bridge._running = True

        with patch("app.engine.claude_bridge.process_supervisor.forget") as forget:
            result = await bridge.wait()

        assert result is not None
        assert result.termination.confirmed_dead is False
        forget.assert_not_called()

    asyncio.run(_run())


def test_agent_result_cannot_be_success_when_tree_death_is_unconfirmed():
    async def _run():
        adapter = ClaudeCodeAdapter()
        process = SimpleNamespace(returncode=0)
        adapter._bridge = MagicMock()
        adapter._bridge.process = process
        adapter._bridge.session_id = "session-1"
        adapter._bridge.last_termination = TerminationResult(
            confirmed_dead=False,
            root_return_code=0,
            error_code="PROCESS_TREE_STILL_ALIVE",
        )
        adapter._bridge.start_session = AsyncMock(return_value="session-1")
        adapter._bridge.wait = AsyncMock(
            return_value=ProcessWaitResult(
                root_return_code=0,
                termination=adapter._bridge.last_termination,
            )
        )

        with pytest.raises(AgentError) as exc_info:
            await adapter.run(
                AgentRunRequest(
                    run_id="unconfirmed-tree",
                    prompt="hello",
                    project_path=os.getcwd(),
                ),
                AsyncMock(),
            )

        assert exc_info.value.termination_confirmed_dead is False
        assert exc_info.value.process_started is True
        assert exc_info.value.failure_code == "PROCESS_TREE_STILL_ALIVE"

    asyncio.run(_run())


def test_bridge_records_termination_evidence_into_attempt_runtime():
    """wait/cancel results must be recorded under the exact process identity."""
    import app.agents as agents_pkg
    from datetime import datetime, timezone

    from app.agents.contract import AgentProcessIdentity

    identity = AgentProcessIdentity(
        pid=4242,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        process_group_id=4242,
        containment_id="runtoken:tok-4242",
    )

    async def _run():
        bridge = SubprocessCliBridge()
        process = SimpleNamespace(returncode=0)
        managed = MagicMock()
        managed.process = process
        managed.process_identity = identity
        managed.wait = AsyncMock(
            return_value=ProcessWaitResult(
                root_return_code=0,
                termination=TerminationResult(
                    confirmed_dead=False,
                    root_return_code=0,
                    error_code="PROCESS_TREE_STILL_ALIVE",
                    error_message="descendant survived",
                    remaining_pids=(4242,),
                ),
            )
        )
        bridge.process = process
        bridge._managed_process = managed
        bridge._running = True

        runtime = agents_pkg.AgentAttemptRuntimeState()
        token = agents_pkg.bind_agent_attempt_runtime(runtime)
        try:
            await bridge.wait()
            assert runtime.termination_confirmed_dead is False
            assert runtime.termination_failure_code == "PROCESS_TREE_STILL_ALIVE"
            assert runtime.remaining_pids == (4242,)
            # A genuine termination result implies the process existed.
            assert runtime.process_started is True

            # Same identity later confirmed dead converges the unconfirmed
            # state (doc case A) instead of staying False forever.
            managed.close = AsyncMock(
                return_value=TerminationResult(confirmed_dead=True, root_return_code=0)
            )
            await bridge.cancel()
            assert runtime.termination_confirmed_dead is True

            agents_pkg.reset_agent_attempt_runtime(token)
            runtime = agents_pkg.AgentAttemptRuntimeState()
            token = agents_pkg.bind_agent_attempt_runtime(runtime)
            managed.close = AsyncMock(
                return_value=TerminationResult(confirmed_dead=True, root_return_code=0)
            )
            await bridge.cancel()
            assert runtime.termination_confirmed_dead is True
        finally:
            agents_pkg.reset_agent_attempt_runtime(token)

    asyncio.run(_run())


def test_bridge_cancel_records_evidence_when_unbound_context_is_safe():
    """Recording must be a no-op when no attempt runtime state is bound."""
    import app.agents as agents_pkg

    async def _run():
        bridge = SubprocessCliBridge()
        process = SimpleNamespace(returncode=0)
        managed = MagicMock()
        managed.process = process
        managed.close = AsyncMock(
            return_value=TerminationResult(confirmed_dead=True, root_return_code=0)
        )
        bridge.process = process
        bridge._managed_process = managed
        bridge._running = True

        assert agents_pkg.current_agent_attempt_runtime() is None
        result = await bridge.cancel()
        assert result is not None and result.confirmed_dead is True

    asyncio.run(_run())

async def _wait_until(predicate, timeout: float = 10.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return predicate()


def test_spawn_callback_cancellation_closes_process_tree():
    """doc 11.2-1: on_process_started 取消窗口不得留下无人管理的 CLI。"""

    async def _run():
        import app.agents as agents_pkg

        entered = asyncio.Event()
        started_identity = {}

        async def on_started(identity):
            started_identity["identity"] = identity
            entered.set()
            await asyncio.Event().wait()  # block forever at an await point

        runtime = agents_pkg.AgentAttemptRuntimeState()
        runtime_token = agents_pkg.bind_agent_attempt_runtime(runtime)
        start_task = asyncio.create_task(
            process_supervisor.spawn(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                cwd=os.getcwd(),
                env=os.environ.copy(),
                run_token="test-cancel-window",
                on_process_started=on_started,
            )
        )
        await entered.wait()
        # Let the supervisor finish registering the managed process before
        # the callback cancellation arrives.
        await asyncio.sleep(0.2)
        managed = next(
            item
            for item in list(process_supervisor._processes)
            if item.run_token == "test-cancel-window"
        )
        pid = managed.pid

        start_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await start_task

        # The tree must be dead (or the attempt evidence must keep an
        # ORPHANED-safe unconfirmed record) before the caller observes the
        # cancellation; the uncancellable cleanup task owns this.
        assert await _wait_until(
            lambda: all(
                item.process.returncode is not None
                and not item._tree_has_live_processes()
                for item in process_supervisor._processes
            )
        ), "process tree survived the spawn-callback cancellation window"
        await process_supervisor.drain_cleanup_tasks(timeout=5.0)
        assert process_supervisor.active_count == 0
        assert not await _wait_until(
            lambda: psutil.pid_exists(pid)
            and psutil.Process(pid).is_running()
            and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE,
            timeout=2.0,
        )
        # Evidence must never claim a clean death that was not proven; the
        # record either confirms death or stays unconfirmed (ORPHANED-safe).
        assert runtime.process_started is True
        agents_pkg.reset_agent_attempt_runtime(runtime_token)
        return runtime

    runtime = asyncio.run(_run())
    assert runtime.termination_confirmed_dead in (True, False)


def test_spawn_callback_exception_closes_tree_and_reraises():
    async def _run():
        async def on_started(identity):
            raise ValueError("attach db exploded")

        with pytest.raises(ValueError):
            await process_supervisor.spawn(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                cwd=os.getcwd(),
                env=os.environ.copy(),
                run_token="test-callback-exception",
                on_process_started=on_started,
            )
        assert await _wait_until(lambda: process_supervisor.active_count == 0)
        await process_supervisor.drain_cleanup_tasks(timeout=5.0)
        assert all(item.run_token != "test-callback-exception" for item in process_supervisor._processes)

    asyncio.run(_run())


def test_spawn_callback_rejection_closes_tree():
    async def _run():
        async def on_started(identity):
            return False

        with pytest.raises(RuntimeError) as exc_info:
            await process_supervisor.spawn(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                cwd=os.getcwd(),
                env=os.environ.copy(),
                run_token="test-callback-rejected",
                on_process_started=on_started,
            )
        assert "could not be attached" in str(exc_info.value)
        assert await _wait_until(lambda: process_supervisor.active_count == 0)
        await process_supervisor.drain_cleanup_tasks(timeout=5.0)

    asyncio.run(_run())


def test_spawn_callback_timeout_closes_tree_and_raises_timeout():
    async def _run():
        async def on_started(identity):
            await asyncio.sleep(5.0)

        with pytest.raises(TimeoutError):
            await process_supervisor.spawn(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                cwd=os.getcwd(),
                env=os.environ.copy(),
                run_token="test-callback-timeout",
                on_process_started=on_started,
                process_attach_timeout_seconds=0.2,
            )
        assert await _wait_until(lambda: process_supervisor.active_count == 0)
        await process_supervisor.drain_cleanup_tasks(timeout=5.0)

    asyncio.run(_run())


def test_cleanup_false_then_true_converges_same_identity():
    """第一次清理 False、第二次清理 True（同一 identity）必须收敛为已死亡。"""
    import app.agents as agents_pkg
    from datetime import datetime, timezone

    from app.agents.contract import AgentProcessIdentity

    async def _run():
        runtime = agents_pkg.AgentAttemptRuntimeState()
        runtime_token = agents_pkg.bind_agent_attempt_runtime(runtime)

        async def on_started(identity):
            raise RuntimeError("attach failed once")

        original_close = ManagedAgentProcess.close
        first_call = {"done": False}

        async def two_phase_close(self, reason="close"):
            if not first_call["done"]:
                first_call["done"] = True
                return TerminationResult(
                    confirmed_dead=False,
                    root_return_code=None,
                    error_code="PROCESS_TREE_STILL_ALIVE",
                )
            return await original_close(self, reason=reason)

        with patch.object(ManagedAgentProcess, "close", two_phase_close):
            with pytest.raises(RuntimeError):
                await process_supervisor.spawn(
                    [sys.executable, "-c", "import time; time.sleep(60)"],
                    cwd=os.getcwd(),
                    env=os.environ.copy(),
                    run_token="test-cleanup-two-phase",
                    on_process_started=on_started,
                )
        # First unconfirmed cleanup keeps the registration (reaper may retry).
        assert any(item.run_token == "test-cleanup-two-phase" for item in process_supervisor._processes)
        assert runtime.termination_confirmed_dead is False

        # The next stop_attempt is the "second close" and must converge.
        result = await process_supervisor.stop_attempt("test-cleanup-two-phase", "reap_retry")
        assert result is not None and result.confirmed_dead is True
        assert all(item.run_token != "test-cleanup-two-phase" for item in process_supervisor._processes)
        assert runtime.termination_confirmed_dead is True
        agents_pkg.reset_agent_attempt_runtime(runtime_token)
        await process_supervisor.drain_cleanup_tasks(timeout=5.0)

    asyncio.run(_run())


def test_double_cancellation_does_not_cancel_cleanup_task():
    async def _run():
        entered = asyncio.Event()

        async def on_started(identity):
            entered.set()
            await asyncio.Event().wait()

        start_task = asyncio.create_task(
            process_supervisor.spawn(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                cwd=os.getcwd(),
                env=os.environ.copy(),
                run_token="test-double-cancel",
                on_process_started=on_started,
            )
        )
        await entered.wait()
        await asyncio.sleep(0.2)

        start_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await start_task
        # Second cancellation while cleanup is in flight must not abort it.
        start_task.cancel()
        assert await _wait_until(lambda: process_supervisor.active_count == 0)
        await process_supervisor.drain_cleanup_tasks(timeout=5.0)

    asyncio.run(_run())


def test_stop_attempt_handles_all_processes_under_run_token():
    """doc 10: stop_attempt 不得只处理 run token 下第一个进程。"""

    async def _run():
        managed_first = await process_supervisor.spawn(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=os.getcwd(),
            env=os.environ.copy(),
            run_token="test-token-multi",
        )
        managed_second = await process_supervisor.spawn(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=os.getcwd(),
            env=os.environ.copy(),
            run_token="test-token-multi",
        )
        pids = (managed_first.pid, managed_second.pid)
        assert len(
            [item for item in process_supervisor._processes if item.run_token == "test-token-multi"]
        ) == 2

        try:
            result = await process_supervisor.stop_attempt("test-token-multi", "reap_all")
            assert result is not None
            assert result.confirmed_dead is True
            assert await _wait_until(
                lambda: all(
                    not psutil.pid_exists(pid)
                    or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
                    for pid in pids
                )
            )
            assert all(
                item.run_token != "test-token-multi"
                for item in process_supervisor._processes
            )
        finally:
            await process_supervisor.stop_attempt("test-token-multi", "test_cleanup")
            process_supervisor.forget(managed_first)
            process_supervisor.forget(managed_second)
            await process_supervisor.drain_cleanup_tasks(timeout=5.0)

    asyncio.run(_run())


# ────────────────────── doc §14.6 事件循环延迟 ──────────────────────


class _FakeManaged:
    """Monitor-loop double that routes psutil sampling through the executor."""

    def __init__(self, pid: int):
        self.process = SimpleNamespace(returncode=None)
        self.pid = pid
        self.known_descendant_pids: set[int] = set()
        self.stop_monitor = False
        self._wake = None
        self.snapshots = 0

    @property
    def monitor_wake_event(self):
        if self._wake is None:
            self._wake = asyncio.Event()
        return self._wake

    def request_immediate_inspection(self):
        if self._wake is not None:
            self._wake.set()

    def apply_snapshot(self, snapshot):
        self.snapshots += 1
        self.known_descendant_pids = set(snapshot.live_descendant_pids)


def test_monitor_inspection_keeps_event_loop_responsive(monkeypatch):
    """3-5 个受管进程持续采样时 heartbeat 延迟必须保持在阈值内。"""
    from app.agents import process_supervisor as ps

    if ps.psutil is None:
        pytest.skip("psutil is required for the event-loop lag test")

    async def _run():
        child = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import time; time.sleep(30)",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        managed_items = [_FakeManaged(child.pid)]
        # 其余使用不存在的 PID：psutil 快速失败路径同样走 executor。
        for index in range(1, 5):
            managed_items.append(_FakeManaged(999999 - index))
        tasks = [
            asyncio.create_task(ps.ProcessSupervisor._monitor_tree(item))
            for item in managed_items
        ]
        max_gap = 0.0
        last_beat = asyncio.get_running_loop().time()
        deadline = last_beat + 0.8
        try:
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.02)
                now = asyncio.get_running_loop().time()
                max_gap = max(max_gap, now - last_beat)
                last_beat = now
            # inspection executor 队列不得随时间增长（worker 数为上界）。
            executor = ps._inspection_executor()
            queue_size = executor._work_queue.qsize()
            assert queue_size <= ps._inspection_executor()._max_workers + 1
        finally:
            for item in managed_items:
                item.stop_monitor = True
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            child.kill()
            await child.wait()
        # monitor cancel 后不得遗留 inspection future：所有采样任务结束，
        # 且受管进程都收到过采样（executor 真实执行过）。
        assert all(task.done() for task in tasks)
        assert all(item.snapshots > 0 for item in managed_items)
        return max_gap

    monkeypatch.setattr(
        "app.config.settings.AGENT_PROCESS_MONITOR_INTERVAL_SECONDS", 0.05
    )
    max_gap = asyncio.run(_run())
    # 主事件循环 heartbeat 延迟阈值：远小于采样周期 * 受管进程数。
    assert max_gap < 0.35, f"event loop stalled: max heartbeat gap={max_gap:.3f}s"

import app.agents.process_supervisor as supervisor_module

# ────────────── P0-2：三态探测与假死亡证明防护（doc §5） ──────────────


def _snapshot_managed(pid: int, *, returncode=None, known=None, job_handle=None, group_id=None):
    """Minimal ManagedAgentProcess-like object for pure snapshot tests."""
    return SimpleNamespace(
        process=SimpleNamespace(returncode=returncode),
        pid=pid,
        job_handle=job_handle,
        process_group_id=group_id,
        process_start_time=None,
        known_descendant_pids=set(known or ()),
    )


def test_access_denied_snapshot_is_unknown_and_keeps_known_descendants(monkeypatch):
    managed = _snapshot_managed(991001, returncode=0, known=[991002])

    def denied(pid):
        raise psutil.AccessDenied(pid=pid)

    monkeypatch.setattr(supervisor_module.psutil, "Process", denied)
    snapshot = supervisor_module.inspect_process_tree_snapshot(managed)

    assert snapshot.state == supervisor_module.ProcessProbeState.UNKNOWN
    assert snapshot.live_descendant_pids == ()
    # UNKNOWN 快照不得清空已知 PID（doc §5.4.3）。
    managed_known = {991002}
    fake = SimpleNamespace(
        apply_snapshot=lambda s: None,
        known_descendant_pids=managed_known,
    )
    real_managed = ManagedAgentProcess(
        process=SimpleNamespace(pid=991001, returncode=0),
        known_descendant_pids={991002},
    )
    real_managed.apply_snapshot(snapshot)
    assert real_managed.known_descendant_pids == {991002}
    assert fake.known_descendant_pids == {991002}


def test_root_alive_with_denied_child_is_live(monkeypatch):
    managed = _snapshot_managed(991001, returncode=None, known=[991002])

    def denied(pid):
        raise psutil.AccessDenied(pid=pid)

    monkeypatch.setattr(supervisor_module.psutil, "Process", denied)
    snapshot = supervisor_module.inspect_process_tree_snapshot(managed)

    # root 明确存活（asyncio returncode 权威）：LIVE，绝不折叠成死亡。
    assert snapshot.state == supervisor_module.ProcessProbeState.LIVE
    assert 991001 in snapshot.remaining_pids


def test_root_exited_and_known_child_access_denied_is_unknown(monkeypatch):
    managed = _snapshot_managed(991001, returncode=0, known=[991002])

    calls = {"n": 0}

    def first_denied_then_no_such(pid):
        calls["n"] += 1
        raise psutil.AccessDenied(pid=pid)

    monkeypatch.setattr(supervisor_module.psutil, "Process", first_denied_then_no_such)
    snapshot = supervisor_module.inspect_process_tree_snapshot(managed)

    assert snapshot.state == supervisor_module.ProcessProbeState.UNKNOWN
    assert snapshot.failure_code


def test_confirmed_dead_requires_every_identity_gone(monkeypatch):
    managed = _snapshot_managed(991001, returncode=0, known=[991002, 991003])

    real_pids = {991002}

    def process_for(pid):
        if int(pid) in real_pids:
            raise psutil.NoSuchProcess(int(pid))
        raise psutil.AccessDenied(pid=pid)

    monkeypatch.setattr(supervisor_module.psutil, "Process", process_for)
    snapshot = supervisor_module.inspect_process_tree_snapshot(managed)

    # 一个 identity confirmed dead、另一个 unknown：聚合必须是 UNKNOWN。
    assert snapshot.state == supervisor_module.ProcessProbeState.UNKNOWN

    real_pids.add(991003)
    snapshot_after = supervisor_module.inspect_process_tree_snapshot(managed)
    assert snapshot_after.state == supervisor_module.ProcessProbeState.CONFIRMED_DEAD


def test_unknown_snapshot_never_manufactures_death(monkeypatch):
    """探测异常后 termination 不得把 UNKNOWN 编码成 confirmed_dead=True。"""
    managed = ManagedAgentProcess(
        process=SimpleNamespace(pid=991001, returncode=0),
        known_descendant_pids={991002},
    )

    def denied(pid):
        raise psutil.AccessDenied(pid=pid)

    monkeypatch.setattr(supervisor_module.psutil, "Process", denied)

    async def _run():
        # _result 消费三态快照：UNKNOWN -> confirmed_dead=None。
        result = await managed._result((), False, 0.0)
        return result

    result = asyncio.run(_run())
    assert result.confirmed_dead is None
    assert result.error_code == supervisor_module.PROCESS_TREE_UNKNOWN


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object containment")
def test_windows_job_query_failure_is_unknown(monkeypatch):
    managed = _snapshot_managed(991001, returncode=0, job_handle=424242)

    class _FailingKernel32:
        def QueryInformationJobObject(self, *args, **kwargs):
            return False

    monkeypatch.setattr(supervisor_module, "_windows_kernel32", lambda: _FailingKernel32())
    state, pids = supervisor_module._windows_job_probe(managed)
    assert state == supervisor_module.ProcessProbeState.UNKNOWN
    assert pids == set()


# ────────────── P1-4：终止路径检查不在事件循环执行（doc §9） ──────────────


def test_inspect_tree_runs_off_loop_and_serializes_per_managed(monkeypatch):
    import time as _time

    in_flight = {"n": 0, "max": 0}

    def slow_snapshot(managed):
        in_flight["n"] += 1
        in_flight["max"] = max(in_flight["max"], in_flight["n"])
        _time.sleep(0.03)
        in_flight["n"] -= 1
        return supervisor_module.ProcessTreeSnapshot(
            state=supervisor_module.ProcessProbeState.CONFIRMED_DEAD,
            root_return_code=0,
        )

    monkeypatch.setattr(supervisor_module, "inspect_process_tree_snapshot", slow_snapshot)

    async def _run():
        managed = ManagedAgentProcess(
            process=SimpleNamespace(pid=991001, returncode=0),
            known_descendant_pids={991002},
        )
        snapshots = await asyncio.gather(managed.inspect_tree(), managed.inspect_tree())
        return snapshots

    snapshots = asyncio.run(_run())
    assert all(s.state == supervisor_module.ProcessProbeState.CONFIRMED_DEAD for s in snapshots)
    # 同一 managed process 同时最多一个在飞采样（有界 gate，doc §9.4）。
    assert in_flight["max"] == 1


def test_concurrent_inspect_tree_keeps_event_loop_responsive(monkeypatch):
    import time as _time

    def slow_snapshot(managed):
        _time.sleep(0.05)
        return supervisor_module.ProcessTreeSnapshot(
            state=supervisor_module.ProcessProbeState.CONFIRMED_DEAD,
            root_return_code=0,
        )

    monkeypatch.setattr(supervisor_module, "inspect_process_tree_snapshot", slow_snapshot)

    async def _run():
        loop = asyncio.get_running_loop()
        managed_items = [
            ManagedAgentProcess(process=SimpleNamespace(pid=1000 + i, returncode=0))
            for i in range(5)
        ]
        max_lag = 0.0
        stop = asyncio.Event()

        async def heartbeat():
            nonlocal max_lag
            while not stop.is_set():
                started = loop.time()
                await asyncio.sleep(0.01)
                max_lag = max(max_lag, loop.time() - started - 0.01)

        hb = asyncio.create_task(heartbeat())
        results = await asyncio.gather(*(item.inspect_tree() for item in managed_items))
        stop.set()
        await hb
        return results, max_lag

    results, max_lag = asyncio.run(_run())
    assert all(
        r.state == supervisor_module.ProcessProbeState.CONFIRMED_DEAD for r in results
    )
    # 5 个并发 50ms 假检查全部发生在 inspection executor 中；
    # 事件循环 heartbeat 不应被阻塞超过调度余量。
    assert max_lag < 0.1, f"event loop stalled: max heartbeat lag={max_lag:.3f}s"
