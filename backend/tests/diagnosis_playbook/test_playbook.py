import asyncio
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import sys
import uuid
import pytest
from app.domains.diagnosis_playbook.compiler import compile_spec, evaluate
from app.domains.diagnosis_playbook.contracts import ExecutionEnvelope, PlaybookError, digest
from app.domains.diagnosis_playbook.models import PlaybookRun, TaskPlaybookBinding, CasePlaybookLink
from app.domains.diagnosis_playbook import service
from app.domains.diagnosis_playbook.broker import reserve
from app.domains.diagnosis_playbook.projector import project
from app.runtime.evidence_runner.registry import RunnerBundle
from app.runtime.evidence_runner.supervisor import EvidenceRunner
from tests.workspace_asset.test_workspace_asset_boundary import _seed_workspace


@pytest.fixture
def spec():
    stages = []
    for phase in ("PROBE", "HYPOTHESIZE", "REPRODUCE", "PATCH"):
        stages.append({"id": phase.lower(), "phase": phase, "agentTier": "WORKSPACE_WRITE" if phase == "PATCH" else "READONLY",
                       "objective": phase, "next": "completed", "verification": {
                           "command": {"argv": ["python", "-m", "trusted_probe"], "cwd": "${bound.scratch}", "timeoutSeconds": 2, "effect": "ISOLATED_FIXTURE"},
                           "expectExitCodes": [1] if phase == "REPRODUCE" else [0],
                           "artifacts": [{"name": "probe.json", "parser": "mysql_probe_v1", "source": "runner_output"}],
                           "passWhen": {"op": "eq", "fact": "probe.connection_ok", "value": True}}})
    for a, b in zip(stages, stages[1:]):
        a["next"] = b["id"]
    stages[-1]["enterWhen"] = {"gatePassed": "reproduce", "quiescent": True, "sameEnvironmentFamily": True}
    return {"apiVersion": "traceforge.dev/troubleshooting/v1", "kind": "TroubleshootingPlaybook",
            "metadata": {"id": "test", "version": "1", "title": "Test", "taskType": "DIAGNOSIS"},
            "inputs": {"clients": {"type": "integer", "minimum": 2, "maximum": 64, "default": 16}},
            "execution": {"shell": False, "bundle": "registry://tests/1"}, "stages": stages,
            "completion": {"requireAllStageGates": True}}


@pytest.mark.parametrize("mutation,code", [
    (lambda s: s["stages"][1].update(next="probe"), "INVALID_DAG"),
    (lambda s: s["stages"][0].update(agentTier="WORKSPACE_WRITE"), "INVALID_PERMISSION_TIER"),
    (lambda s: s["stages"][0]["verification"]["artifacts"][0].update(parser="unknown"), "UNKNOWN_PARSER"),
    (lambda s: s["stages"][0]["verification"]["artifacts"][0].update(name="../forged.json"), "UNSAFE_ARTIFACT_PATH"),
    (lambda s: s["stages"][0]["verification"]["passWhen"].update(value=1), "PREDICATE_TYPE_MISMATCH"),
    (lambda s: s["stages"][0]["verification"]["passWhen"].update(fact="model.says_pass"), "UNKNOWN_FACT"),
    (lambda s: s["stages"][-1]["enterWhen"].update(gatePassed="probe"), "PATCH_WITHOUT_REPRODUCTION"),
    (lambda s: s["stages"][0]["verification"]["command"].update(argv=["python", "--arg=${inputs.clients}"]), "INVALID_PLACEHOLDER"),
])
def test_reject_invalid_contract(spec, mutation, code):
    mutation(spec)
    with pytest.raises(PlaybookError, match=code):
        compile_spec(spec)


def test_yaml_tags_and_non_boolean_comparisons():
    with pytest.raises(PlaybookError):
        compile_spec("!!python/object/apply:os.system ['echo unsafe']")
    assert not evaluate({"op": "eq", "fact": "x", "value": True}, {"x": 1})


def setup_run(db, spec):
    user, workspace, task = _seed_workspace(db)
    task.task_type = "DIAGNOSIS"
    row = service.register_spec(db, workspace.id, spec)
    result = service.attach(db, task, row.id, {}, "attach", user.id, "fixture")
    db.commit()
    return user, task, row, db.get(PlaybookRun, result["id"])


def test_attach_idempotence_and_legacy_guard(db, spec):
    user, task, row, run = setup_run(db, spec)
    same = service.attach(db, task, row.id, {}, "attach", user.id, "fixture")
    assert same["id"] == run.id
    with pytest.raises(PlaybookError, match="IDEMPOTENCY_PAYLOAD_CONFLICT"):
        service.attach(db, task, row.id, {"clients": 17}, "attach", user.id, "fixture")
    with pytest.raises(PlaybookError, match="ACTIVE_RUN_EXISTS"):
        service.attach(db, task, row.id, {}, "second", user.id, "fixture")
    task.task_type = "DEVELOPMENT"
    with pytest.raises(PlaybookError, match="DIAGNOSIS_ONLY"):
        service.attach(db, task, row.id, {}, "third", user.id, "fixture")


def test_command_conflict_retry_and_binding_release(db, spec):
    user, task, row, run = setup_run(db, spec)
    request = {"action": "cancel", "idempotency_key": "cancel", "expected_state_version": run.state_version}
    result = service.command(db, run, request, user.id)
    assert result["state"] == "CANCELLED"
    assert db.get(TaskPlaybookBinding, task.id).active_run_id is None
    assert service.command(db, run, request, user.id)["state_version"] == result["state_version"]
    request.update(idempotency_key="another")
    with pytest.raises(PlaybookError, match="STATE_VERSION_CONFLICT"):
        service.command(db, run, request, user.id)


def make_receipt(db, run, *, exit_code=0, facts=None):
    envelope = ExecutionEnvelope(str(uuid.uuid4()), run.id, run.epoch, run.active_step, str(uuid.uuid4()), "main",
                                 digest("contract"), digest("env"), digest("source"), 1, digest("bundle"), ("python",), ".", 1, "WORKTREE_BROKER")
    reserve(db, run, envelope, {"environment_digest": digest("env")})
    receipt = {**asdict(envelope), "exit_code": exit_code, "termination": "CONFIRMED", "timed_out": False,
               "artifacts": [{"name": "probe.json", "digest": digest("physical report")}],
               "facts": facts if facts is not None else {"probe.connection_ok": True, "probe.correlated_samples": 1, "probe.lock_or_error_artifact_refs": ["independent-collector"]}}
    receipt["receipt_digest"] = digest(receipt)
    return receipt


@pytest.mark.parametrize("field,value", [("run_epoch", 99), ("branch_id", "foreign"), ("environment_digest", "foreign"), ("contract_digest", "foreign"), ("source_snapshot_digest", "foreign"), ("policy_epoch", 99)])
def test_old_or_foreign_receipts_cannot_advance(db, spec, field, value):
    _, _, _, run = setup_run(db, spec)
    receipt = make_receipt(db, run)
    receipt[field] = value
    receipt["receipt_digest"] = digest({k: v for k, v in receipt.items() if k != "receipt_digest"})
    with pytest.raises(PlaybookError, match="STALE_OR_FOREIGN"):
        service.accept_receipt(db, run, receipt)
    assert run.active_step == "probe"


def test_model_pass_missing_facts_cannot_pass(db, spec):
    _, _, _, run = setup_run(db, spec)
    receipt = make_receipt(db, run, facts={"model": "PASS", "stderr": "all tests passed"})
    result = service.accept_receipt(db, run, receipt)
    assert result["state"] == "NEEDS_INPUT"
    assert result["gate_decisions"][-1]["verdict"] == "ERROR"


def test_expected_failure_and_atomic_projection(db, spec):
    _, task, _, run = setup_run(db, spec)
    for phase in ("probe", "hypothesize", "reproduce", "patch"):
        assert run.active_step == phase
        if phase == "hypothesize":
            service.propose_hypotheses(db, run, [{"id": f"h{i}", "claim": "test", "predictions": ["predict"], "falsifiers": ["falsify"], "discriminator_script": "candidate"} for i in range(2)], run.state_version)
        receipt = make_receipt(db, run, exit_code=1 if phase == "reproduce" else 0)
        service.accept_receipt(db, run, receipt)
    assert run.state == "PROJECTING"
    project(db, run)
    db.commit()
    assert run.state == "COMPLETED"
    assert db.query(CasePlaybookLink).filter_by(source_run_id=run.id).count() == 1
    from app.domains.case_center.models.case import SddCase, SddCaseReviewRecord
    case = db.query(SddCase).filter_by(source_task_id=task.id).one()
    assert case.status == "TECHNICALLY_VERIFIED" and case.archive_origin == "PLAYBOOK"
    assert db.query(SddCaseReviewRecord).count() == 0


def test_runner_real_process_replay_and_unknown(tmp_path):
    async def scenario():
        runner = EvidenceRunner(tmp_path / "evidence")
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        script = scratch / "probe.py"
        script.write_text("print('physical output')\nraise SystemExit(1)\n", encoding="utf-8")
        bundle = RunnerBundle("test", digest("bundle"), sys.executable, str(scratch), (), lambda *_: {}, lambda *_: ({"observed": True}, []))
        envelope = ExecutionEnvelope(str(uuid.uuid4()), "run", 1, "step", "attempt", "main", digest(1), digest(2), digest(3), 1, bundle.digest, ("python", str(script)), str(scratch), 10, "ADVISORY_GUARD")
        async def emit(*_): pass
        async def cancelled(): return False
        receipt = await runner.execute(envelope, bundle, emit=emit, cancelled=cancelled)
        assert receipt["exit_code"] == 1 and receipt["termination"] == "CONFIRMED"
        assert "physical output" in (runner.directory(envelope.execution_id) / "stdout").read_text()
        assert (await runner.execute(envelope, bundle, emit=emit, cancelled=cancelled))["receipt_digest"] == receipt["receipt_digest"]
        unknown = ExecutionEnvelope(**{**asdict(envelope), "execution_id": str(uuid.uuid4())})
        runner.directory(unknown.execution_id).mkdir()
        with pytest.raises(PlaybookError, match="EXECUTION_UNKNOWN"):
            await runner.execute(unknown, bundle, emit=emit, cancelled=cancelled)
    asyncio.run(scenario())


def test_technical_case_search_authorization(db):
    from app.domains.case_center.models.case import SddCase
    from app.domains.search.worker import current_document
    from app.domains.search.service import hydrate
    user, workspace, task = _seed_workspace(db)
    case = SddCase(workspace_id=workspace.id, creator_id=user.id, title="physical deadlock", status="TECHNICALLY_VERIFIED", archive_origin="PLAYBOOK", root_cause="lock order")
    db.add(case)
    db.commit()
    doc = current_document(db, f"case:{case.id}")
    assert doc["kind"] == "case"
    result = hydrate(db, user.id, [doc], 0, 10, "deadlock", [workspace.id])
    assert result[0][0]["target"]["params"]["caseId"] == case.id
    assert hydrate(db, user.id, [doc], 0, 10, "deadlock", ["other-workspace"])[0] == []
    case.status = "DRAFT"
    db.flush()
    assert current_document(db, f"case:{case.id}")["deleted"]


def test_cancelled_terminal_event_fans_out_to_both_clients(db, spec, monkeypatch):
    import json
    from app.domains.diagnosis_playbook import worker
    from app.domains.websocket.ws.manager import ConnectionManager
    from tests.websocket.test_websocket_managers import _FakeTextSocket, _wait_all
    user, task, _, run = setup_run(db, spec)
    service.command(db, run, {"action": "cancel", "expected_state_version": 1, "idempotency_key": "cancel"}, user.id)
    db.commit()
    async def txn(fn):
        result = fn(db)
        db.commit()
        return result
    monkeypatch.setattr(worker, "run_db_txn", txn)
    manager = ConnectionManager()
    monkeypatch.setattr(worker, "manager", manager)
    async def scenario():
        sockets = [_FakeTextSocket(), _FakeTextSocket()]
        for socket in sockets:
            connection = await manager.connect(socket, task.id)
            await connection.wait_flushed()
            initial = json.loads(socket.sent_texts[0])
            await manager.complete_resync(socket, task.id, epoch=initial["epoch"], barrier_sequence=initial["barrier_sequence"])
        await worker.PlaybookWorker.publish(run.id)
        await _wait_all(manager, *sockets)
        for socket in sockets:
            events = [json.loads(frame) for frame in socket.sent_texts if json.loads(frame).get("type") == "event"]
            assert events[-1]["payload"]["payload"]["snapshot"]["state"] == "CANCELLED"
        assert db.get(PlaybookRun, run.id).published_seq == run.event_seq
        await manager.shutdown()
    asyncio.run(scenario())


def test_api_scope_etag_and_no_receipt_write(db, spec, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from unittest.mock import AsyncMock
    from app.dependencies import get_db, get_current_user
    from app.domains.diagnosis_playbook.router import router
    from app.domains.diagnosis_playbook.worker import PlaybookWorker
    user, task, _, run = setup_run(db, spec)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(PlaybookWorker, "publish", AsyncMock())
    with TestClient(app) as client:
        base = f"/workspaces/{task.workspace_id}/tasks/{task.id}/playbook-runs/{run.id}"
        result = client.get(base)
        assert result.status_code == 200 and result.headers["etag"] == '"1"'
        assert client.get(base.replace(task.workspace_id, "foreign-workspace")).status_code == 403
        assert client.post(base + "/evidence/forged", json={"exit_code": 0}).status_code == 405
        assert client.post(base + "/commands", json={"action": "set_state", "expected_state_version": 1, "idempotency_key": "x"}).status_code == 422
        request = {"action": "cancel", "expected_state_version": 1, "idempotency_key": "cancel"}
        assert client.post(base + "/commands", json=request).json()["state"] == "CANCELLED"
        events = client.get(base + "/events", params={"after_seq": 1}).json()
        assert len(events["events"]) == 1 and events["snapshot"]["state"] == "CANCELLED"
        assert client.post(base + "/commands", json=request).status_code == 200


def test_incremental_migration_upgrade_and_downgrade_preserve_old_case():
    import importlib.util
    from sqlalchemy import create_engine, inspect, text
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    filename = Path(__file__).parents[2] / "alembic" / "versions" / "b7d91a36c204_diagnosis_playbooks.py"
    module_spec = importlib.util.spec_from_file_location("playbook_migration", filename)
    migration = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE sdd_cases (id VARCHAR(36) PRIMARY KEY, title TEXT)"))
            conn.execute(text("INSERT INTO sdd_cases VALUES ('existing', 'preserved')"))
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
                assert conn.execute(text("SELECT archive_origin FROM sdd_cases WHERE id='existing'")).scalar() == "MANUAL"
                assert "playbook_runs" in inspect(conn).get_table_names()
                migration.downgrade()
            assert conn.execute(text("SELECT title FROM sdd_cases WHERE id='existing'")).scalar() == "preserved"
            assert "playbook_runs" not in inspect(conn).get_table_names()
    finally:
        engine.dispose()


def test_playbook_route_precedence_over_case_detail():
    from app.main import app
    from fastapi.testclient import TestClient
    from app.dependencies import get_current_user
    user = type("U", (), {"id": "test-user", "is_active": True})()
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        with TestClient(app) as client:
            res = client.get("/api/workspaces/nonexistent-ws-id/cases/playbooks")
            assert res.status_code == 403
            assert res.json()["detail"] == "No access to this workspace"
    finally:
        app.dependency_overrides.pop(get_current_user, None)

