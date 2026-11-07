import asyncio

import pytest

from app.agents.domain_tools import DomainTool, DomainToolError
from app.agents.domain_tools.contracts import OpenAPISubmission
from app.agents.domain_tools.invocation import active_domain_run
from app.agents.errors import AgentCancelledError
from app.domains.ai.services.jobs import provider_turn
from app.domains.ai.services.jobs.domain_turn import run_domain_turn


@pytest.mark.asyncio
async def test_interface_analysis_uses_one_provider_turn_and_typed_tool(monkeypatch, tmp_path):
    calls = []

    async def provider(prompt, path, **kwargs):
        calls.append(kwargs)
        run = active_domain_run.get()
        assert run.project_path == str(tmp_path)
        assert (await run.invoke(run.tool.name, {"unexpected": True}, "bad"))["isError"]
        assert not (await run.invoke(run.tool.name, {"document": {"openapi": "3.1.0"}}, "good"))["isError"]
        return {"session_id": "same-session", "text": "This prose is ignored"}

    monkeypatch.setattr(provider_turn, "run_cli_single_turn", provider)
    result = await run_domain_turn(
        "Analyze",
        str(tmp_path),
        backend_name="opencode",
        tool=DomainTool("submit_openapi", "接口分析", OpenAPISubmission),
    )
    assert result["artifact"].document == {"openapi": "3.1.0"}
    assert result["session_id"] == "same-session"
    assert len(calls) == 1 and calls[0]["max_attempts"] == 1
    assert [e["stage"] for e in result["domain_milestones"]] == [
        "started",
        "validating",
        "repairing",
        "validating",
        "accepted",
    ]
    assert active_domain_run.get() is None


@pytest.mark.asyncio
async def test_text_without_tool_cannot_succeed(monkeypatch, tmp_path):
    async def provider(*args, **kwargs):
        return {"text": '{"document":{"openapi":"3.1.0"}}'}

    monkeypatch.setattr(provider_turn, "run_cli_single_turn", provider)
    with pytest.raises(DomainToolError, match="DOMAIN_RESULT_MISSING"):
        await run_domain_turn("Analyze", str(tmp_path), tool=DomainTool("submit", "Submit", OpenAPISubmission))


@pytest.mark.asyncio
async def test_cancel_and_timeout_revoke_tools(monkeypatch, tmp_path):
    runs = []

    async def cancelled(*args, **kwargs):
        runs.append(active_domain_run.get())
        raise AgentCancelledError("Cancelled")

    monkeypatch.setattr(provider_turn, "run_cli_single_turn", cancelled)
    with pytest.raises(AgentCancelledError):
        await run_domain_turn("Analyze", str(tmp_path), tool=DomainTool("submit", "Submit", OpenAPISubmission))
    assert runs[0]._closed

    stopped = asyncio.Event()

    async def pending(*args, **kwargs):
        runs.append(active_domain_run.get())
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(provider_turn, "run_cli_single_turn", pending)
    with pytest.raises(TimeoutError):
        await run_domain_turn(
            "Analyze", str(tmp_path), timeout_seconds=0.1, tool=DomainTool("submit", "Submit", OpenAPISubmission)
        )
    assert stopped.is_set() and runs[-1]._closed
