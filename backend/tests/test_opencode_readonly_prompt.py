"""OpenCode adapter read-only 权限行为测试。

read-only（「一键总结问题案例」）不再切换到 plan agent——plan agent 的
“调研→计划”行为会把结论写进计划消息而非直接输出，破坏「仅输出 JSON 总结」
契约；改为注入只读约束前缀。显式 plan 模式保持原行为。
"""

import asyncio
import os
import sys

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter  # noqa: E402
from app.agents.contract import AgentRunRequest  # noqa: E402


class _FakeResponse:
    status_code = 200
    text = ""


class _FakeClient:
    def __init__(self, captured):
        self._captured = captured

    async def post(self, url, **kwargs):
        self._captured["url"] = url
        self._captured["kwargs"] = kwargs
        return _FakeResponse()


def _run_send_prompt(permission_mode):
    adapter = OpenCodeAdapter(server_url="http://test")
    captured = {}
    adapter._ensure_client = lambda: _async_return(_FakeClient(captured))
    request = AgentRunRequest(
        run_id="run-1",
        prompt="把会话过程总结为定位结果",
        project_path=".",
        permission_mode=permission_mode,
    )
    asyncio.run(adapter._send_prompt("sess-1", request))
    return captured


async def _async_return(value):
    return value


def test_readonly_injects_constraint_and_keeps_build_agent():
    captured = _run_send_prompt("read-only")
    body = captured["kwargs"]["json"]
    # 不再切换 plan agent
    assert "agent" not in body
    # prompt 前注入只读约束（与 dsh adapter 一致）
    text = body["parts"][0]["text"]
    assert text.startswith("[只读会话约束]")
    assert "禁止创建、修改、删除文件" in text
    assert "把会话过程总结为定位结果" in text


def test_readonly_alias_treated_the_same():
    first = _run_send_prompt("read-only")["kwargs"]["json"]
    second = _run_send_prompt("readonly")["kwargs"]["json"]
    assert first["parts"][0]["text"] == second["parts"][0]["text"]
    assert "agent" not in second


def test_default_mode_has_no_constraint_prefix():
    captured = _run_send_prompt("default")
    body = captured["kwargs"]["json"]
    assert "agent" not in body
    assert body["parts"][0]["text"] == "把会话过程总结为定位结果"


def test_explicit_plan_still_switches_plan_agent():
    captured = _run_send_prompt("plan")
    body = captured["kwargs"]["json"]
    assert body["agent"] == "plan"
    # plan 模式不注入只读前缀（原样交给 plan agent）
    assert body["parts"][0]["text"] == "把会话过程总结为定位结果"
