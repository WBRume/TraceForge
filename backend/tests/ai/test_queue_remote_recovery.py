import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.agents import AgentStopResult
from app.domains.ai.routers import queue
from app.domains.ai.services.jobs import attempts, publishing, reaper


@pytest.mark.parametrize("confirm_cleanup", [True, False])
@pytest.mark.parametrize("acknowledged", [True, False])
def test_administrator_remote_recovery_requires_provider_ack(monkeypatch, confirm_cleanup, acknowledged):
    adopted = {
        "job_id": "job",
        "run_token": "fenced-token",
        "execution_kind": "REMOTE_SESSION",
        "agent_backend": "opencode",
        "session_id": "remote-session",
        "task_id": "task",
        "workspace_id": "workspace",
        "reason": "recover",
        "process_pid": None,
    }
    monkeypatch.setattr(queue, "run_db_txn", AsyncMock(return_value=adopted))
    stop = AsyncMock(
        return_value=AgentStopResult(
            execution_kind="REMOTE_SESSION",
            stop_acknowledged=acknowledged,
            failure_code=None if acknowledged else "REMOTE_STOP_UNCONFIRMED",
        )
    )
    monkeypatch.setattr(reaper, "stop_remote_session", stop)
    monkeypatch.setattr(queue.process_supervisor, "verify_persisted_cleanup", lambda *a: pytest.fail("No local PID"))
    monkeypatch.setattr(queue.process_supervisor, "stop_persisted", lambda *a: pytest.fail("No local PID"))
    monkeypatch.setattr(queue.process_supervisor, "stop_attempt", lambda *a: pytest.fail("No local PID"))
    captured = {}

    async def run_db(fn, *args, **kwargs):
        assert fn is attempts.finish_termination_sync
        captured.update(kwargs)
        return {"status": "CANCELLED" if acknowledged else "ORPHANED"}

    monkeypatch.setattr(queue, "run_db", run_db)
    monkeypatch.setattr(publishing, "broadcast_job_payload", AsyncMock())
    monkeypatch.setattr(publishing, "reschedule_if_pending", lambda _: None)
    monkeypatch.setattr(queue, "audit_log", lambda **kwargs: None)

    async def run():
        args = {
            "job_id": "job",
            "operator_id": "admin",
            "reason": "recover",
            "evidence": "provider proof",
            "confirm_cleanup": confirm_cleanup,
        }
        if acknowledged:
            result = await queue._recover_orphaned_job(**args)
            assert result.confirmed_dead and result.status == "CANCELLED"
        else:
            with pytest.raises(HTTPException) as exc:
                await queue._recover_orphaned_job(**args)
            assert exc.value.status_code == 409
            assert exc.value.detail["status"] == "ORPHANED"

    asyncio.run(run())
    stop.assert_awaited_once_with(adopted)
    assert captured["confirmed_dead"] is acknowledged
    assert captured["evidence"].remote_stop_acknowledged is acknowledged
    assert captured["evidence"].execution_kind == "REMOTE_SESSION"
