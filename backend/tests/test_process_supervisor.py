"""真实子进程树测试：终止必须确认 root 与 descendant 均已退出。"""

from __future__ import annotations

import asyncio
import os
import sys
import textwrap

from app.agents.process_supervisor import process_supervisor


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
