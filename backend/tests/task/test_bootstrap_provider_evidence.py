"""A remote baseline must publish its real provider outcome and stop locator."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents.contract import (
    AgentAttemptContext,
    AgentAttemptRuntimeState,
    AgentStopResult,
    bind_agent_attempt,
    bind_agent_attempt_runtime,
    reset_agent_attempt,
    reset_agent_attempt_runtime,
)
from app.domains.ai.models.ai_job import AiJobStatus
from app.domains.ai.services import ai_job_convergence_service as convergence
from app.domains.ai.services.jobs import provider_turn
from app.domains.task.services import task_cli_state_service as service


@pytest.mark.parametrize("terminal", ["success", "error", "missing"])
def test_remote_baseline_records_outcome_before_ready_and_can_converge(monkeypatch, tmp_path, terminal):
    @asynccontextmanager
    async def unlocked(*args, **kwargs):
        yield

    context = {
        "spec_version_id": "v1",
        "task_spec_doc_path": str(tmp_path / "spec.md"),
        "version_original_path": "",
        "baseline_dir": str(tmp_path),
        "refresh_mode": "FULL",
        "refresh_context": {},
        "baseline_session_id": "",
        "agent_backend": "opencode",
        "workspace_id": "w",
        "task_creator_id": "u",
    }
    trace = []

    async def persist(session_id=None, **kwargs):
        assert kwargs["attempt"].job_id == "job"
        trace.append(("locator", kwargs["backend_name"], session_id))

    async def update(*args, **kwargs):
        trace.append(("state", kwargs.get("status")))

    class Bridge:
        session_id = "remote-baseline"
        process = last_termination = None

        async def start_session(self, **kwargs):
            self.callback = kwargs["event_callback"]
            return ""

        async def wait(self):
            await self.callback({"type": "system", "subtype": "init", "session_id": self.session_id})
            await self.callback({"type": "assistant", "message": {"content": [{"type": "text", "text": "read"}]}})
            if terminal != "missing":
                await self.callback({"type": "result", "is_error": terminal == "error", "result": terminal})

        def is_running(self):
            return False

        async def cancel(self):
            trace.append(("stop", self.session_id))
            return AgentStopResult(execution_kind="REMOTE_SESSION", stop_acknowledged=True)

    monkeypatch.setattr(service, "queue_bootstrap_jobs", unlocked)
    monkeypatch.setattr(service, "lock_task_bootstrap", unlocked)
    monkeypatch.setattr(service, "_get_bootstrap_lock", lambda _: unlocked())
    monkeypatch.setattr(service, "run_db", AsyncMock(return_value=context))
    monkeypatch.setattr(service, "_prepare_bootstrap_spec", AsyncMock(return_value=context["task_spec_doc_path"]))
    monkeypatch.setattr(service, "create_legacy_bridge", lambda *args, **kwargs: Bridge())
    monkeypatch.setattr(service, "probe_session_fork", AsyncMock())
    monkeypatch.setattr(service, "_update_bootstrap_state", update)
    monkeypatch.setattr(provider_turn, "_persist_turn_locator", persist)

    async def run():
        owner = bind_agent_attempt(
            AgentAttemptContext(
                job_id="job",
                task_id="t",
                queue_key="TASK_BASELINE:t",
                run_token="run",
                worker_id="worker",
                worker_boot_id="boot",
                attempt_count=1,
                execution_kind="REMOTE_SESSION",
            )
        )
        runtime = AgentAttemptRuntimeState()
        binding = bind_agent_attempt_runtime(runtime)
        try:
            result = await service._run_bootstrap("t", expected_input_revision="v1")
            evidence = convergence.resolve_attempt_evidence(execution_kind="REMOTE_SESSION", runtime=runtime)
            request = convergence.AttemptConvergenceRequest(
                job_id="job",
                run_token="run",
                worker_boot_id="boot",
                requested_status=AiJobStatus.SUCCESS if terminal == "success" else AiJobStatus.FAILED,
                reason="baseline",
                evidence=evidence,
                intent=convergence.ConvergenceIntent.NORMAL_FINALIZE,
            )
            final, _ = convergence._decide_final_status(SimpleNamespace(), request, "REMOTE_SESSION")
            assert final == (AiJobStatus.SUCCESS if terminal == "success" else AiJobStatus.FAILED)
            assert evidence.provider_outcome_seen is (terminal != "missing")
            assert trace[0] == ("locator", "opencode", None)
            assert ("locator", "opencode", "remote-baseline") in trace
            if terminal == "success":
                assert result["status"] == "READY"
                assert trace.index(("locator", "opencode", "remote-baseline")) < trace.index(("state", "READY"))
            else:
                assert result["status"] == "FAILED"
                assert ("state", "READY") not in trace
            if terminal == "missing":
                assert ("stop", "remote-baseline") in trace
                assert result["failure_code"] == "PROVIDER_OUTCOME_MISSING"
        finally:
            reset_agent_attempt_runtime(binding)
            reset_agent_attempt(owner)

    asyncio.run(run())
