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
    ProcessWaitResult,
    TerminationResult,
    process_supervisor,
)
from app.engine.claude_bridge import SubprocessCliBridge


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

    asyncio.run(_run())
