import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.agents.activity_watchdog import AgentActivityWatchdog
from app.agents.errors import AgentTimeoutError
from app.agents.contract import AgentRunRequest


def test_watchdog_times_out_when_agent_never_starts_activity():
    async def _run():
        watchdog = AgentActivityWatchdog(
            startup_timeout_seconds=0.02,
            idle_timeout_seconds=1,
            hard_timeout_seconds=1,
        )
        with pytest.raises(AgentTimeoutError, match="startup"):
            await watchdog.wait(asyncio.sleep(10))

    asyncio.run(_run())


def test_watchdog_resets_idle_deadline_on_meaningful_events():
    async def _run():
        watchdog = AgentActivityWatchdog(
            startup_timeout_seconds=0.05,
            idle_timeout_seconds=0.05,
            hard_timeout_seconds=0.5,
        )

        async def _active_turn():
            for event_type in ("session_started", "thinking", "tool_use", "text"):
                watchdog.mark(event_type)
                await asyncio.sleep(0.03)
            return "done"

        assert await watchdog.wait(_active_turn()) == "done"

    asyncio.run(_run())


def test_watchdog_hard_limit_wins_even_when_events_keep_arriving():
    async def _run():
        watchdog = AgentActivityWatchdog(
            startup_timeout_seconds=0.05,
            idle_timeout_seconds=0.05,
            hard_timeout_seconds=0.08,
        )

        async def _never_finishes():
            while True:
                watchdog.mark("text_delta")
                await asyncio.sleep(0.01)

        with pytest.raises(AgentTimeoutError, match="hard runtime"):
            await watchdog.wait(_never_finishes())

    asyncio.run(_run())


def test_claude_adapter_activity_timeout_cancels_process_bridge():
    from app.agents.adapters.claude_code.claude_code_adapter import ClaudeCodeAdapter

    async def _run():
        adapter = ClaudeCodeAdapter(cli_path="claude")

        async def _never_returns():
            await asyncio.sleep(10)

        bridge = SimpleNamespace(
            _task_id="",
            _workspace_id="",
            _job_id="",
            start_session=AsyncMock(return_value="session-1"),
            wait=AsyncMock(side_effect=_never_returns),
            cancel=AsyncMock(return_value=None),
            session_id="session-1",
            process=None,
        )
        adapter._bridge = bridge

        with pytest.raises(AgentTimeoutError, match="startup"):
            await adapter.run(
                AgentRunRequest(
                    prompt="hello",
                    project_path=".",
                    startup_timeout_seconds=0.02,
                    idle_timeout_seconds=1,
                    timeout_seconds=1,
                ),
                AsyncMock(return_value=None),
            )
        bridge.cancel.assert_awaited_once()

    asyncio.run(_run())


def test_opencode_adapter_idle_timeout_interrupts_server_turn():
    from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter

    async def _run():
        adapter = OpenCodeAdapter("http://mock:4097")

        async def _never_returns(*_args, **_kwargs):
            await asyncio.sleep(10)

        adapter._ensure_client = AsyncMock(return_value=None)
        adapter._create_session = AsyncMock(return_value="session-1")
        adapter._consume_sse = _never_returns
        adapter._fetch_final_message = AsyncMock(return_value={})
        adapter.interrupt = AsyncMock(return_value=None)

        with pytest.raises(AgentTimeoutError, match="meaningful activity"):
            await adapter.run(
                AgentRunRequest(
                    prompt="hello",
                    project_path=".",
                    startup_timeout_seconds=1,
                    idle_timeout_seconds=0.02,
                    timeout_seconds=1,
                ),
                AsyncMock(return_value=None),
            )
        adapter.interrupt.assert_awaited_once()

    asyncio.run(_run())


def test_dsh_adapter_idle_timeout_cancels_server_turn_and_applies_read_only_prompt():
    from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter

    async def _run():
        adapter = DshServerAdapter("http://mock:3080")
        prompt_payloads = []

        async def _rpc(method, payload):
            if method == "session.prompt":
                prompt_payloads.append(payload)
            return {}

        async def _never_returns(*_args, **_kwargs):
            await asyncio.sleep(10)

        adapter._ensure_client = AsyncMock(return_value=None)
        adapter._create_session = AsyncMock(return_value="session-1")
        adapter._consume_events = _never_returns
        adapter._rpc = _rpc
        adapter.cancel = AsyncMock(return_value=None)

        with pytest.raises(AgentTimeoutError, match="meaningful activity"):
            await adapter.run(
                AgentRunRequest(
                    prompt="summarize",
                    project_path=".",
                    startup_timeout_seconds=1,
                    idle_timeout_seconds=0.02,
                    timeout_seconds=1,
                    permission_mode="read-only",
                ),
                AsyncMock(return_value=None),
            )
        adapter.cancel.assert_awaited_once()
        assert prompt_payloads
        prompt_text = prompt_payloads[0]["content"][0]["text"]
        assert "只读会话约束" in prompt_text
        assert prompt_text.endswith("summarize")

    asyncio.run(_run())
