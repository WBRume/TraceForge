from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents.contract import (
    AgentAttemptContext,
    AgentAttemptRuntimeState,
    bind_agent_attempt,
    bind_agent_attempt_runtime,
    reset_agent_attempt,
    reset_agent_attempt_runtime,
)
from app.agents.errors import AgentError
from app.domains.ai.models.ai_job import AiJobStatus
from app.domains.ai.services import ai_job_convergence_service as convergence
from app.domains.ai.services.jobs import provider_turn
from app.domains.diagnosis_playbook import promotion
from tests.diagnosis_playbook.test_business_flow import seed_case


@pytest.mark.asyncio
@pytest.mark.parametrize("started", [False, True])
async def test_async_remote_start_failure_uses_real_session_evidence(db, monkeypatch, started):
    from app import database

    user, ws, _, case = seed_case(db)
    job = promotion.create(db, ws.id, [case.id], user.id, "start")
    db.commit()
    job.status = AiJobStatus.RUNNING
    job.run_token = "run"
    job.worker_boot_id = "boot"
    job.process_execution_kind = "REMOTE_SESSION"
    db.commit()

    @contextmanager
    def begin():
        yield db
        db.commit()

    monkeypatch.setattr(database, "SessionLocal", SimpleNamespace(begin=begin))

    async def inline(fn, *args):
        return fn(*args)

    monkeypatch.setattr(provider_turn, "run_db", inline)

    class Bridge:
        async def start_session(self, **kwargs):
            self.callback = kwargs["event_callback"]
            return ""  # Real remote shim schedules creation and returns immediately.

        async def wait(self):
            if started:
                await self.callback({"type": "system", "subtype": "init", "session_id": "remote-session"})
                assert db.get(type(job), job.id).session_id == "remote-session"
            raise AgentError("stream disconnected" if started else "create session failed: HTTP 401")

        def is_running(self):
            return False

        cancel = AsyncMock()

    bridge = Bridge()
    monkeypatch.setattr("app.agents.selection.create_legacy_bridge", lambda *a, **k: bridge)
    attempt = AgentAttemptContext(
        job_id=job.id,
        task_id=None,
        queue_key=job.queue_key,
        run_token="run",
        worker_id="worker",
        worker_boot_id="boot",
        attempt_count=1,
        execution_kind="REMOTE_SESSION",
    )
    owner = bind_agent_attempt(attempt)
    state = AgentAttemptRuntimeState()
    binding = bind_agent_attempt_runtime(state)
    try:
        with pytest.raises(AgentError):
            await provider_turn.run_cli_single_turn("test", ".", backend_name="opencode", max_attempts=1)
        evidence = convergence.resolve_attempt_evidence(execution_kind="REMOTE_SESSION", runtime=state)
        status, _ = convergence._decide_final_status(
            job,
            convergence.AttemptConvergenceRequest(
                job_id=job.id,
                run_token="run",
                worker_boot_id="boot",
                requested_status=AiJobStatus.FAILED,
                evidence=evidence,
                reason="test failure",
            ),
            "REMOTE_SESSION",
        )
        assert status == (AiJobStatus.ORPHANED if started else AiJobStatus.FAILED)
        assert job.agent_backend == "opencode"
        assert job.session_id == ("remote-session" if started else None)
        # Stale callbacks must not attach a session to a new attempt.
        job.run_token = "replacement"
        db.commit()
        with pytest.raises(convergence.AttemptFencedError):
            provider_turn._persist_turn_locator_sync(attempt, "opencode", "stale")
    finally:
        reset_agent_attempt_runtime(binding)
        reset_agent_attempt(owner)
