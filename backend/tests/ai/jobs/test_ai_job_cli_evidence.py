"""Durable AI job ownership 状态机检查（原 test_ai_job_reliability.py）。

覆盖：typed agent error 携带终止证据、run_cli_single_turn 的
超时/提供方错误/取消证据传播与 runtime state 记录。
"""

from __future__ import annotations

import asyncio

import pytest

from app.domains.ai.services.jobs import provider_turn as ai_provider_turn


class _StubBridge:
    """Minimal bridge double for run_cli_single_turn evidence propagation."""

    def __init__(self, *, termination=None, raise_timeout=False, error_result=False):
        self.termination = termination
        self.raise_timeout = raise_timeout
        self.error_result = error_result
        self.start_calls = 0
        self.cancel_calls = 0
        self.wait_calls = 0
        self.session_id = "session-1"
        self.process = None
        self.last_termination = termination
        self._running = False

    async def start_session(self, **_kwargs):
        self.start_calls += 1
        self._running = True
        return "session-1"

    async def wait(self):
        self.wait_calls += 1
        # 真实 bridge 的 wait() 一定有 await 点；yield 一次让 cancel monitor
        # 获得首次轮询机会（Python 3.12+ 的 wait_for 不再为协程创建 task）。
        await asyncio.sleep(0)
        if self.raise_timeout:
            raise asyncio.TimeoutError()
        if self.error_result:
            self._events = [{"type": "result", "is_error": True, "result": "provider down"}]
        self.last_termination = self.termination
        return self.termination

    async def cancel(self):
        self.cancel_calls += 1
        self.last_termination = self.termination
        return self.termination

    async def interrupt(self):
        return await self.cancel()

    def is_running(self):
        return self._running


def test_typed_agent_errors_carry_termination_evidence():
    from app.agents.errors import (
        AgentCancelledError,
        AgentError,
        AgentProviderError,
        AgentTimeoutError,
    )

    timeout = AgentTimeoutError(
        "hard timeout",
        phase="hard",
        limit_seconds=10.0,
        termination_confirmed_dead=True,
        process_started=True,
    )
    assert timeout.failure_code == "HARD_TIMEOUT"
    assert timeout.termination_confirmed_dead is True

    provider = AgentProviderError(
        "boom",
        termination_confirmed_dead=False,
        process_started=True,
        failure_code="PROVIDER_ERROR",
    )
    assert provider.failure_code == "PROVIDER_ERROR"
    assert provider.termination_confirmed_dead is False

    cancelled = AgentCancelledError(
        "cancelled",
        termination_confirmed_dead=True,
        process_started=True,
        failure_code="USER_CANCELLED",
    )
    assert cancelled.failure_code == "USER_CANCELLED"

    # Backward compatibility: typed errors stay catchable as RuntimeError.
    try:
        raise provider
    except RuntimeError:
        pass
    try:
        raise AgentError("plain")
    except RuntimeError:
        pass


def test_run_cli_single_turn_timeout_unconfirmed_tree_raises_typed_error(monkeypatch):
    from app.agents.errors import AgentError
    from app.agents.supervision import TerminationResult

    bridge = _StubBridge(
        termination=TerminationResult(
            confirmed_dead=False,
            root_return_code=None,
            error_code="PROCESS_TREE_STILL_ALIVE",
        ),
        raise_timeout=True,
    )
    monkeypatch.setattr("app.engine.claude_bridge.create_cli_bridge", lambda *a, **kw: bridge)

    async def _run():
        with pytest.raises(AgentError) as exc_info:
            await ai_provider_turn.run_cli_single_turn("hi", ".", max_attempts=2)
        assert exc_info.value.termination_confirmed_dead is False
        assert exc_info.value.failure_code == "PROCESS_TREE_STILL_ALIVE"

    asyncio.run(_run())
    # An unconfirmed tree forbids starting the next retry process.
    assert bridge.start_calls == 1


def test_run_cli_single_turn_provider_error_confirmed_dead_raises_typed(monkeypatch):
    from app.agents.errors import AgentProviderError
    from app.agents.supervision import TerminationResult

    class _ErrorResultBridge(_StubBridge):
        def __init__(self):
            super().__init__(
                termination=TerminationResult(confirmed_dead=True, root_return_code=0)
            )
            self._event_callback = None

        async def start_session(self, **kwargs):
            self._event_callback = kwargs.get("event_callback")
            return await super().start_session(**kwargs)

        async def wait(self):
            self.wait_calls += 1
            self.last_termination = self.termination
            callback = self._event_callback
            await callback({"type": "result", "is_error": True, "result": "provider down"})
            return self.termination

    bridge = _ErrorResultBridge()
    monkeypatch.setattr("app.engine.claude_bridge.create_cli_bridge", lambda *args, **kwargs: bridge)

    async def _run():
        with pytest.raises(AgentProviderError) as exc_info:
            await ai_provider_turn.run_cli_single_turn("hi", ".", max_attempts=1)
        assert exc_info.value.termination_confirmed_dead is True
        assert exc_info.value.failure_code == "PROVIDER_ERROR"
        assert bridge.last_termination.confirmed_dead is True

    asyncio.run(_run())


def test_run_cli_single_turn_cancelled_raises_typed_cancelled(monkeypatch):
    from app.agents.errors import AgentCancelledError
    from app.agents.supervision import TerminationResult

    bridge = _StubBridge(
        termination=TerminationResult(confirmed_dead=True, root_return_code=None),
    )
    monkeypatch.setattr("app.engine.claude_bridge.create_cli_bridge", lambda *args, **kwargs: bridge)

    async def _run():
        with pytest.raises(AgentCancelledError) as exc_info:
            await ai_provider_turn.run_cli_single_turn(
                "hi",
                ".",
                max_attempts=1,
                should_cancel=lambda: True,
            )
        assert exc_info.value.termination_confirmed_dead is True
        assert exc_info.value.failure_code == "USER_CANCELLED"

    asyncio.run(_run())


def test_run_cli_single_turn_records_evidence_in_runtime_state(monkeypatch):
    import app.agents as agents_pkg
    from app.agents.contract import record_attempt_termination
    from app.agents.supervision import TerminationResult

    class _RecordingBridge(_StubBridge):
        """Mirror the real SubprocessCliBridge evidence contract."""

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._event_callback = None

        async def start_session(self, **kwargs):
            self._event_callback = kwargs.get("event_callback")
            return await super().start_session(**kwargs)

        async def wait(self):
            self.wait_calls += 1
            self.last_termination = self.termination
            record_attempt_termination(self.last_termination)
            # 真实 bridge 在 wait 返回前一定会发出终局 result 事件
            # （07e04775 §4.3：没有 result 事件不构成 outcome）。
            callback = self._event_callback
            if callback is not None:
                await callback({"type": "result", "is_error": False, "result": "ok"})
            return self.last_termination

        async def cancel(self):
            self.cancel_calls += 1
            self.last_termination = self.termination
            record_attempt_termination(self.last_termination)
            return self.termination

    bridge = _RecordingBridge(
        termination=TerminationResult(confirmed_dead=True, root_return_code=0),
    )
    monkeypatch.setattr("app.engine.claude_bridge.create_cli_bridge", lambda *args, **kwargs: bridge)

    async def _run():
        runtime = agents_pkg.AgentAttemptRuntimeState()
        token = agents_pkg.bind_agent_attempt_runtime(runtime)
        try:
            result = await ai_provider_turn.run_cli_single_turn("hi", ".", max_attempts=1)
            assert result["termination_confirmed_dead"] is True
            # The stub never spawned a real process; a real bridge/spawn would
            # have recorded process_started via the supervisor.
            assert runtime.process_started is False
            assert runtime.termination_confirmed_dead is True
        finally:
            agents_pkg.reset_agent_attempt_runtime(token)

    asyncio.run(_run())
