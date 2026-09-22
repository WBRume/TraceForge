import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.agents.contract import AgentRunRequest, AgentRunResult
from app.agents.errors import AgentConfigurationError
from app.agents.runtime_control import BackendRuntimeControl
from app.config import Settings, settings
from app.domains.diagnosis_playbook import execution_profile, service
from tests.diagnosis_playbook.test_playbook import spec, setup_run
from tests.diagnosis_playbook.test_runtime import Backend, environment, transactions


def test_configuration_defaults_and_rejects_unknown(monkeypatch):
    monkeypatch.delenv("DIAGNOSIS_PLAYBOOK_ENFORCEMENT_LEVEL", raising=False)
    credentials = {"DB_PASSWORD": "test-password", "JWT_SECRET_KEY": "test-secret-that-is-long-enough-for-validation"}
    assert Settings(_env_file=None, **credentials).DIAGNOSIS_PLAYBOOK_ENFORCEMENT_LEVEL == "ADVISORY_GUARD"
    with pytest.raises(ValidationError, match="DIAGNOSIS_PLAYBOOK_ENFORCEMENT_LEVEL"):
        Settings(_env_file=None, **credentials, DIAGNOSIS_PLAYBOOK_ENFORCEMENT_LEVEL="sandbox")


@pytest.mark.asyncio
@pytest.mark.parametrize("level", ["WORKTREE_BROKER", "CONTAINER_SANDBOX"])
async def test_stronger_strategy_requires_actual_matching_isolation(monkeypatch, level):
    monkeypatch.setattr(settings, "DIAGNOSIS_PLAYBOOK_ENFORCEMENT_LEVEL", level)
    control = BackendRuntimeControl(Backend())
    with pytest.raises(AgentConfigurationError, match="CONFIGURED_ENFORCEMENT_UNAVAILABLE"):
        await control.negotiate({"allow_advisory": True, "enforcement": "ADVISORY_GUARD"})
    capabilities = await control.negotiate({"backend_isolation_verified": True,
        "backend_host_identity": control.host_identity, "enforcement": level})
    assert capabilities.readonly_enforcement == level


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_name", ["dsh", "opencode", "claude-code"])
async def test_advisory_shared_host_without_guard_or_ticket(db, spec, tmp_path, monkeypatch, backend_name):
    from app.agents import playbook_guard
    guard = AsyncMock(side_effect=AssertionError("Advisory must not contact guard"))
    monkeypatch.setattr(playbook_guard, "guard_request", guard)
    monkeypatch.setattr(settings, "DIAGNOSIS_PLAYBOOK_ENFORCEMENT_LEVEL", "ADVISORY_GUARD")
    _, task, _, run = setup_run(db, spec)
    service.transition(db, run, run.data_json, state="READY")
    transactions(monkeypatch, db)
    backend = Backend()
    backend.name = backend_name
    profile = execution_profile.DiagnosisExecutionProfile(run_id=run.id, task_id=task.id,
        environment=environment(tmp_path), tool_url="", backend_key=backend_name)
    request = await profile.prepare_turn(SimpleNamespace(cli=backend), "分析上传的堆栈")
    assert request.provider_options["execution_policy"]["mcp_config"] == {}
    assert "guard_control" not in request.provider_options
    assert "Bearer" not in request.prompt
    assert "traceforge-playbook" in request.prompt
    assert not run.data_json["active_scope"]["ticket_hash"]
    guard.assert_not_awaited()


@pytest.mark.asyncio
async def test_advisory_output_records_proposals_not_receipts_and_rolls_back_invalid_batch(db, spec, tmp_path, monkeypatch):
    _, task, _, run = setup_run(db, spec)
    service.transition(db, run, run.data_json, state="READY")
    transactions(monkeypatch, db)
    profile = execution_profile.DiagnosisExecutionProfile(run_id=run.id, task_id=task.id,
        environment=environment(tmp_path), tool_url="", backend_key="claude-code")
    await profile.prepare_turn(SimpleNamespace(cli=Backend()), "diagnose")
    proposal = {"name": "propose_experiment", "arguments": {"files": {"probe.py": "print('candidate')"}}}
    text = "```traceforge-playbook\n" + json.dumps({"proposals": [proposal, {"name": "accept_receipt", "arguments": {"verdict": "PASS"}}]}) + "\n```"
    await profile.after_provider_settled(AgentRunResult(success=True, result_text=text, termination_confirmed_dead=True))
    assert run.state == "NEEDS_INPUT"
    assert not run.data_json.get("experiment_candidate")
    assert not run.data_json["gate_decisions"]
    assert run.data_json["missing_facts"] == ["ADVISORY_PROPOSAL_NOT_ALLOWED"]


@pytest.mark.asyncio
async def test_opencode_advisory_does_not_mutate_host_mcp_or_tools():
    from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
    backend = OpenCodeAdapter()
    client = SimpleNamespace(post=AsyncMock(return_value=SimpleNamespace(status_code=204)))
    backend._ensure_client = AsyncMock(return_value=client)
    await backend._send_prompt("session", AgentRunRequest(provider_options={"execution_policy": {"enforcement": "ADVISORY_GUARD"}}))
    assert client.post.await_count == 1
    args, kwargs = client.post.call_args
    assert args[0].endswith("/session/session/prompt_async")
    assert "tools" not in kwargs["json"]


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_session", [False, True])
async def test_advisory_accepts_candidate_only_for_current_session(db, spec, tmp_path, monkeypatch, changed_session):
    _, task, _, run = setup_run(db, spec)
    service.transition(db, run, run.data_json, state="READY")
    transactions(monkeypatch, db)
    profile = execution_profile.DiagnosisExecutionProfile(run_id=run.id, task_id=task.id,
        environment=environment(tmp_path), tool_url="", backend_key="claude-code")
    await profile.prepare_turn(SimpleNamespace(cli=Backend()), "diagnose")
    if changed_session:
        task.session_revision += 1
    text = '```traceforge-playbook\n{"proposals":[{"name":"propose_experiment","arguments":{"files":{"probe.py":"candidate"}}}]}\n```'
    await profile.after_provider_settled(AgentRunResult(success=True, result_text=text, termination_confirmed_dead=True))
    assert run.state == ("CANCELLED" if changed_session else "READY")
    assert bool(run.data_json.get("experiment_candidate")) is not changed_session
    assert not run.data_json["gate_decisions"]
