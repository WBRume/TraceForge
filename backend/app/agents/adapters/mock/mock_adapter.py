"""Mock Agent backend：用于前端/测试，不调用真实模型。"""

from __future__ import annotations

import asyncio
import uuid

from app.agents.contract import (
    AgentBackend,
    AgentCapabilities,
    AgentRunRequest,
    AgentRunResult,
    AgentEventSink,
)
from app.agents.events import AgentEvent


class MockAdapter(AgentBackend):
    name = "mock"
    capabilities = AgentCapabilities(
        supports_resume=True,
        supports_streaming_text=False,
        supports_tool_events=True,
        hitl_modes=["turn_based"],
        supports_usage=True,
        skill_layouts=["mock-skills"],
        preferred_mode="subprocess",
    )

    def __init__(self) -> None:
        self._running = False
        self._session_id: str | None = None

    async def run(self, request: AgentRunRequest, on_event: AgentEventSink) -> AgentRunResult:
        self._validate_request(request)
        self._running = True
        session_id = request.session_id or str(uuid.uuid4())
        self._session_id = session_id
        try:
            await on_event(AgentEvent(
                type="session_started",
                payload={"provider_session_id": session_id, "model": request.model or "mock-model"},
                provider=self.name,
                raw={"type": "system", "subtype": "init", "session_id": session_id},
            ))

            await asyncio.sleep(0.01)
            await on_event(AgentEvent(
                type="thinking",
                payload={"text": f"[Mock] 正在思考: {request.prompt[:80]}"},
                provider=self.name,
            ))

            await asyncio.sleep(0.01)
            await on_event(AgentEvent(
                type="text",
                payload={"text": "[Mock] 已收到你的指令，正在处理…"},
                provider=self.name,
            ))

            await asyncio.sleep(0.01)
            await on_event(AgentEvent(
                type="tool_use",
                payload={"tool_use_id": "mock_tool_1", "tool_name": "echo", "tool_input": {"text": request.prompt}},
                provider=self.name,
            ))
            await on_event(AgentEvent(
                type="tool_result",
                payload={"tool_use_id": "mock_tool_1", "output": "[mock output]", "is_error": False},
                provider=self.name,
            ))

            await on_event(AgentEvent(
                type="result",
                payload={
                    "success": True,
                    "result": "[Mock] 处理完成",
                    "finish_reason": "completed",
                    "session_id": session_id,
                    "duration_ms": 30,
                    "cost_usd": 0.0,
                },
                provider=self.name,
            ))

            return AgentRunResult(
                run_id=request.run_id,
                session_id=session_id,
                success=True,
                result_text="[Mock] 处理完成",
                finish_reason="completed",
                duration_ms=30,
                cost_usd=0.0,
            )
        finally:
            self._running = False

    async def interrupt(self, run_id: str | None = None) -> None:
        self._running = False

    async def cancel(self, run_id: str | None = None) -> None:
        self._running = False

    def is_running(self, run_id: str | None = None) -> bool:
        return self._running

    async def close(self) -> None:
        self._running = False
        self._session_id = None