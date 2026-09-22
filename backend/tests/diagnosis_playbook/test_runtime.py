"""Execution profile, revocable tool authority, and lost-owner recovery contracts."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import time
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.agents.contract import AgentRunResult
from app.agents.runtime_control import BackendRuntimeControl, SessionHandle, ExecutionPolicy
from app.domains.diagnosis_playbook import execution_profile, service, tool_server, worker
from app.domains.diagnosis_playbook.contracts import PlaybookError, digest
from app.domains.diagnosis_playbook.models import TaskPlaybookBinding
from tests.diagnosis_playbook.test_playbook import spec, setup_run


class Backend:
    name = "claude-code"
    capabilities = SimpleNamespace(supports_resume=True, supports_fork=True, execution_kind="LOCAL_PROCESS")

    async def probe(self):
        return "test-runtime/1"

    def is_running(self):
        return False

    def get_runtime_control(self):
        return BackendRuntimeControl(self)


def transactions(monkeypatch, db):
    async def transaction(fn):
        result = fn(db)
        db.flush()
        return result
    monkeypatch.setattr(execution_profile, "run_db_txn", transaction)
    monkeypatch.setattr(worker, "run_db_txn", transaction)


def environment(tmp_path):
    return {"environment_digest": digest("env"), "source_snapshot_digest": digest("source"),
            "bindings": {"source": str(tmp_path), "patch": str(tmp_path / "patch")}}


def activate(db, run, token="ticket", **values):
    data = deepcopy(run.data_json)
    data["active_scope"] = {"scope_id": "playbook:" + run.id, "call_id": "call", "run_epoch": run.epoch,
                            "state": "DISPATCH_INTENT", "backend_key": "claude-code", "step_id": run.active_step,
                            "ticket_hash": hashlib.sha256(token.encode()).hexdigest(), "expires_at": time.time() + 60,
                            "lease_until": time.time() - 1, "dispatch_at": time.time() - 120, "owner_id": "dead-worker",
                            "tool_calls": {}, **values}
    service.transition(db, run, data, state="AGENT_RUNNING")
    run.lease_owner = "dead-worker"
    run.lease_until = data["active_scope"]["lease_until"]


@pytest.mark.asyncio
async def test_profile_pins_scope_and_rehydrates_at_new_path(db, spec, tmp_path, monkeypatch):
    spec["environment"] = {"allowAdvisory": True}
    _, task, _, run = setup_run(db, spec)
    transactions(monkeypatch, db)
    data = deepcopy(run.data_json)
    data["advisory_ack"] = True
    backend = Backend()
    control = backend.get_runtime_control()
    data["provider_handle"] = asdict(SessionHandle("logical", backend.name, control.host_identity, "old-session", "READY", 1, "locator"))
    data["active_scope"] = {"project_path": "old-path"}
    service.transition(db, run, data, state="READY")
    profile = execution_profile.DiagnosisExecutionProfile(run_id=run.id, task_id=task.id,
        environment=environment(tmp_path), tool_url="http://localhost/playbook-tools", backend_key="claude-code")
    request = await profile.prepare_turn(SimpleNamespace(cli=backend), "diagnose")
    assert request.session_id is None
    assert request.provider_options["execution_policy"]["enforcement"] == "ADVISORY_GUARD"
    assert run.state == "AGENT_RUNNING"
    assert "active_scope" not in service.snapshot(run)
    assert "environment" not in service.snapshot(run)
    await profile.before_dispatch(request)
    task.session_revision += 1
    with pytest.raises(PlaybookError, match="DISPATCH_REVOKED"):
        await profile.before_dispatch(request)


@pytest.mark.asyncio
async def test_profile_cannot_settle_without_process_death(db, spec, tmp_path, monkeypatch):
    spec["environment"] = {"allowAdvisory": True}
    _, task, _, run = setup_run(db, spec)
    transactions(monkeypatch, db)
    data = deepcopy(run.data_json)
    data["advisory_ack"] = True
    service.transition(db, run, data, state="READY")
    profile = execution_profile.DiagnosisExecutionProfile(run_id=run.id, task_id=task.id,
        environment=environment(tmp_path), tool_url="http://localhost/tools", backend_key="claude-code")
    await profile.prepare_turn(SimpleNamespace(cli=Backend()), "diagnose")
    with pytest.raises(PlaybookError, match="PROVIDER_TERMINATION_UNKNOWN"):
        await profile.after_provider_settled(AgentRunResult(success=True, termination_confirmed_dead=False))
    assert run.state == "AGENT_RUNNING"
    await profile.after_provider_settled(AgentRunResult(success=True, termination_confirmed_dead=True))
    assert run.state == "READY"
    assert not run.data_json["active_scope"]["ticket_hash"]


def test_mcp_ticket_payload_retry_revocation_and_task_fence(db, spec):
    user, task, _, run = setup_run(db, spec)
    activate(db, run)
    request = tool_server.RpcRequest(id=1, method="tools/call", params={
        "name": "propose_experiment", "arguments": {"files": {"experiment.py": "print('candidate')"}}})
    assert not tool_server.invoke(db, run.id, "Bearer ticket", request)["isError"]
    version = run.state_version
    tool_server.invoke(db, run.id, "Bearer ticket", request)
    assert run.state_version == version
    request.params["arguments"]["files"]["experiment.py"] = "changed"
    with pytest.raises(PlaybookError, match="TOOL_CALL_ID_CONFLICT"):
        tool_server.invoke(db, run.id, "Bearer ticket", request)
    task.session_revision += 1
    with pytest.raises(HTTPException) as error:
        tool_server.authorize(db, run.id, "Bearer ticket")
    assert error.value.status_code == 409
    task.session_revision -= 1
    service.command(db, run, {"action": "cancel", "idempotency_key": "cancel", "expected_state_version": run.state_version}, user.id)
    with pytest.raises(HTTPException):
        tool_server.authorize(db, run.id, "Bearer ticket")


@pytest.mark.asyncio
async def test_lost_owner_never_dispatches_again_without_stop_evidence(db, spec, tmp_path, monkeypatch):
    _, _, _, run = setup_run(db, spec)
    transactions(monkeypatch, db)
    activate(db, run)
    from app.agents.supervision.supervisor import process_supervisor
    async def unknown(*args, **kwargs):
        return None
    monkeypatch.setattr(process_supervisor, "stop_by_run_token_discovery", unknown)
    dispatcher = worker.PlaybookWorker(tmp_path)
    await dispatcher.recover_provider(run)
    assert run.state == "RECOVERING"
    assert run.data_json["missing_facts"] == ["PROVIDER_TERMINATION_UNKNOWN"]
    assert run.data_json["active_scope"]["ticket_hash"] == ""
    assert db.get(TaskPlaybookBinding, run.task_id).active_run_id == run.id


@pytest.mark.asyncio
async def test_live_owner_not_reclaimed(db, spec, tmp_path, monkeypatch):
    _, _, _, run = setup_run(db, spec)
    transactions(monkeypatch, db)
    activate(db, run, lease_until=time.time() + 60)
    version = run.state_version
    await worker.PlaybookWorker(tmp_path).recover_provider(run)
    assert run.state_version == version


def test_continue_reruns_failed_provider(db, spec):
    user, _, _, run = setup_run(db, spec)
    data = deepcopy(run.data_json)
    data["active_scope"] = {"state": "SETTLED", "provider_success": False}
    service.transition(db, run, data, state="NEEDS_INPUT")
    service.command(db, run, {"action": "continue", "idempotency_key": "retry", "expected_state_version": run.state_version}, user.id)
    assert run.data_json["active_scope"]["state"] == "RETRY_REQUESTED"


def test_dsh_tool_schemas_match_platform():
    import json
    from pathlib import Path
    location = Path(__file__).resolve().parents[3] / "integrations/dsh-playbook/tools.json"
    assert json.loads(location.read_text(encoding="utf-8")) == tool_server.TOOLS


@pytest.mark.asyncio
async def test_losing_dispatch_cannot_revoke_the_winning_scope(db, spec, tmp_path, monkeypatch):
    _, task, _, run = setup_run(db, spec)
    transactions(monkeypatch, db)
    activate(db, run)
    profile = execution_profile.DiagnosisExecutionProfile(run_id=run.id, task_id=task.id,
        environment=environment(tmp_path), tool_url="http://localhost/tools", backend_key="claude-code")
    version = run.state_version
    await profile.on_error(PlaybookError("STATE_VERSION_CONFLICT"))
    assert run.state_version == version
    assert run.data_json["active_scope"]["ticket_hash"]


@pytest.mark.asyncio
async def test_lease_heartbeat_does_not_invalidate_user_command_version(db, spec, tmp_path, monkeypatch):
    spec["environment"] = {"allowAdvisory": True}
    _, task, _, run = setup_run(db, spec)
    transactions(monkeypatch, db)
    data = deepcopy(run.data_json)
    data["advisory_ack"] = True
    service.transition(db, run, data, state="READY")
    profile = execution_profile.DiagnosisExecutionProfile(run_id=run.id, task_id=task.id,
        environment=environment(tmp_path), tool_url="http://localhost/tools", backend_key="claude-code")
    await profile.prepare_turn(SimpleNamespace(cli=Backend()), "diagnose")
    version = run.state_version
    await profile.heartbeat()
    db.refresh(run)
    assert run.state_version == version


@pytest.mark.asyncio
async def test_opencode_refuses_to_configure_shared_host():
    from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
    from app.agents.contract import AgentRunRequest
    from app.agents.errors import AgentError
    backend = OpenCodeAdapter()
    try:
        with pytest.raises(AgentError, match="DEDICATED_BACKEND_HOST_REQUIRED"):
            await backend._send_prompt("session", AgentRunRequest(provider_options={"execution_policy": {"tier": "READONLY"}}))
    finally:
        await backend._client.aclose()


def test_self_healing_has_finite_budget_and_never_converts_error_to_pass(db, spec):
    from tests.diagnosis_playbook.test_playbook import make_receipt
    spec["execution"]["selfHealing"] = {"maxConsecutiveSameFailure": 2, "maxRepairsPerStage": 3, "onExhausted": "NEEDS_INPUT"}
    _, _, _, run = setup_run(db, spec)
    service.accept_receipt(db, run, make_receipt(db, run, facts={}))
    assert run.state == "READY"
    service.accept_receipt(db, run, make_receipt(db, run, facts={}))
    assert run.state == "NEEDS_INPUT"
    assert "SELF_HEALING_EXHAUSTED" in run.data_json["missing_facts"]
    assert not any(g["verdict"] == "PASS" for g in run.data_json["gate_decisions"])


def test_case_extraction_does_not_turn_narrative_into_verified_evidence(db):
    from app.domains.case_center.models.case import SddCase
    from app.domains.diagnosis_playbook.extraction import draft_from_case
    from app.domains.diagnosis_playbook.compiler import compile_spec
    from tests.workspace_asset.test_workspace_asset_boundary import _seed_workspace
    user, workspace, _ = _seed_workspace(db)
    case = SddCase(workspace_id=workspace.id, creator_id=user.id, title="MySQL 1213 deadlock", root_cause="模型说已经通过")
    db.add(case)
    db.flush()
    candidate, missing = draft_from_case(db, case, digest("case"))
    compiled = compile_spec(candidate)
    assert compiled["spec"]["metadata"]["sourceCaseRefs"] == [case.id]
    assert "application_transaction_port_compatibility" in missing
    case.title = "Unknown application defect"
    candidate, missing = draft_from_case(db, case, digest("case2"))
    with pytest.raises(PlaybookError):
        compile_spec(candidate)


@pytest.mark.asyncio
async def test_renewed_lease_cannot_be_stolen_by_stale_reader(db, spec, tmp_path, monkeypatch):
    from copy import copy
    _, _, _, run = setup_run(db, spec)
    transactions(monkeypatch, db)
    activate(db, run)
    stale = SimpleNamespace(id=run.id, state_version=run.state_version, lease_until=0)
    run.lease_until = time.time() + 120
    db.flush()
    assert not await worker.PlaybookWorker(tmp_path).claim_expired_lease(stale)


@pytest.mark.asyncio
async def test_missing_remote_session_rehydrates_without_prompt():
    from unittest.mock import AsyncMock
    backend = SimpleNamespace(name="dsh", server_url="http://dedicated", is_running=lambda: False,
                              _rpc=AsyncMock(return_value={"items": []}))
    control = BackendRuntimeControl(backend)
    original = SessionHandle("logical", "dsh", control.host_identity, "lost-provider", "READY", 4, "locator")
    resumed = await control.resume_session(original, None)
    assert resumed.logical_session_id == "logical" and resumed.provider_session_id is None
    assert resumed.binding_revision == 5
    backend._rpc.assert_awaited_once_with("session.list", {})


def test_projection_requires_case_choice_and_preserves_confirmed_result(db, spec):
    from app.domains.case_center.models.case import SddCase
    from app.domains.task.models.diagnosis import SddDiagnosisResult
    from app.domains.diagnosis_playbook.projector import project
    from app.domains.diagnosis_playbook.models import CasePlaybookLink
    from tests.diagnosis_playbook.test_playbook import make_receipt
    user, task, _, run = setup_run(db, spec)
    result = SddDiagnosisResult(task_id=task.id, workspace_id=task.workspace_id, created_by_id=user.id,
                                summary="工程师已确认的结果", status="CONFIRMED", extracted_from_ai=False)
    db.add(result)
    cases = [SddCase(workspace_id=task.workspace_id, source_task_id=task.id, creator_id=user.id,
                     title=title, status="APPROVED", archive_origin="MANUAL") for title in ("first", "chosen")]
    db.add_all(cases)
    db.flush()
    for phase in ("probe", "hypothesize", "reproduce", "patch"):
        if phase == "hypothesize":
            service.propose_hypotheses(db, run, [{"id": f"h{i}", "claim": "candidate", "predictions": ["p"],
                "falsifiers": ["f"], "discriminator_script": "registered"} for i in range(2)], run.state_version)
        service.accept_receipt(db, run, make_receipt(db, run, exit_code=1 if phase == "reproduce" else 0))
    assert project(db, run)["state"] == "NEEDS_INPUT"
    assert not db.query(CasePlaybookLink).filter_by(source_run_id=run.id).first()
    service.command(db, run, {"action": "select_case", "case_id": cases[1].id,
        "expected_state_version": run.state_version, "idempotency_key": "choose"}, user.id)
    project(db, run)
    assert db.query(CasePlaybookLink).filter_by(source_run_id=run.id).one().case_id == cases[1].id
    assert result.summary == "工程师已确认的结果" and result.status == "CONFIRMED"
    assert cases[1].status == "APPROVED" and cases[1].archive_origin == "MANUAL"
