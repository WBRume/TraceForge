"""Independent oracle negatives plus explicitly opted-in real MySQL coverage."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid
import pytest
import yaml
from app.domains.diagnosis_playbook.contracts import ExecutionEnvelope, PlaybookError, digest
from app.runtime.evidence_runner.bundles.mysql_deadlock.bundle import MysqlBundle, ROOT
from app.runtime.evidence_runner.bundles.mysql_deadlock.files import freeze_tree, tree_manifest
from app.runtime.evidence_runner.bundles.mysql_deadlock.programs.tf_mysql import oracle, controller
from app.runtime.evidence_runner.registry import RunnerBundle
from app.runtime.evidence_runner.supervisor import EvidenceRunner

FIXED = '''def transfer(tx, source_id, target_id, amount):
    if source_id == target_id:
        raise ValueError("same_account")
    if amount <= 0:
        raise ValueError("invalid_amount")
    rows = {key: tx.lock_account(key) for key in sorted({source_id, target_id})}
    if rows[source_id] < amount:
        raise ValueError("insufficient_funds")
    tx.set_balance(source_id, rows[source_id] - amount)
    tx.set_balance(target_id, rows[target_id] + amount)
'''


def successful_batch():
    return {"requested_count": 1, "requests": [{"completed": True, "exit_code": 0, "committed": True,
        "outcome": "success", "errors": [], "locks": [1, 2], "acquired": [1, 2],
        "reads": {"1": 1000, "2": 1000},
        "operations": [{"account_id": 1, "balance": 999}, {"account_id": 2, "balance": 1001}],
        "request": {"source_id": 1, "target_id": 2, "amount": 1}}], "balances": {"1": 999, "2": 1001}}


@pytest.mark.parametrize("mutation", [
    lambda b: b.update(requests=[]),
    lambda b: b.update(balances={"1": 1000, "2": 1000}),
    lambda b: b["requests"][0].update(acquired=[], operations=[]),
    lambda b: b["requests"][0].update(harness_error="import failed"),
    lambda b: b["requests"][0].update(errors=[1205]),
    lambda b: b["requests"][0].update(committed=False),
    lambda b: b.update(requested_count=2),
])
def test_oracle_rejects_deleted_requests_noop_patch_and_harness_errors(mutation):
    value = successful_batch()
    assert oracle.target_passed(value)
    mutation(value)
    assert not oracle.target_passed(value)


def test_only_correlated_database_deadlock_is_target_failure():
    value = successful_batch()
    value["requests"][0]["errors"] = [1213]
    assert not oracle.target_failed(value)
    value["correlated_lock_cycle"] = True
    assert not oracle.target_failed(value)  # A handled error is not a failed request.
    value["requests"][0].update(committed=False, outcome="error")
    assert oracle.target_failed(value)
    value["requests"][0]["harness_error"] = "timeout"
    assert not oracle.target_failed(value)


def test_balanced_opposing_noop_requests_cannot_pass():
    value = successful_batch()
    first = value["requests"][0]
    first["operations"] = [{"account_id": 1, "balance": 1000}, {"account_id": 2, "balance": 1000}]
    second = deepcopy(first)
    second["request"] = {"source_id": 2, "target_id": 1, "amount": 1}
    value.update(requested_count=2, requests=[first, second], balances={"1": 1000, "2": 1000})
    assert oracle.balances_match(value)
    assert not oracle.target_passed(value)


def test_patch_freezing_keeps_baseline_and_rejects_protected_files(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "transfer.py").write_text("original", encoding="utf-8")
    (source / "test_transfer.py").write_text("assert True", encoding="utf-8")
    original = digest(tree_manifest(source))
    frozen = tmp_path / "baseline"
    freeze_tree(source, frozen, original)
    patch = tmp_path / "patch"
    freeze_tree(frozen, patch, original, {"transfer.py": "fixed"})
    assert (frozen / "transfer.py").read_text() == "original"
    assert (patch / "transfer.py").read_text() == "fixed"
    with pytest.raises(PlaybookError, match="PROTECTED_ARTIFACT_CHANGED"):
        freeze_tree(source, tmp_path / "forged", original, {"test_transfer.py": "pass"})
    (patch / "transfer.py").write_text("tampered", encoding="utf-8")
    with pytest.raises(PlaybookError, match="FROZEN_TREE_CHANGED"):
        freeze_tree(frozen, patch, original, {"transfer.py": "fixed"})


@pytest.mark.skipif(os.environ.get("TRACEFORGE_MYSQL_PLAYBOOK_LIVE") != "1", reason="explicit real MySQL fixture opt-in required")
@pytest.mark.asyncio
async def test_real_mysql_controller_and_supervised_four_stage_bundle(db, tmp_path, monkeypatch):
    """Create two uniquely named test schemas; never migrate/reset application DB."""
    from app.config import settings
    import pymysql
    connection = dict(host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER, password=settings.DB_PASSWORD)
    schema_names = ["tf_playbook_test_" + uuid.uuid4().hex for _ in range(2)]
    observation_db, fixture_db = schema_names
    with pymysql.connect(**connection, autocommit=True) as admin:
        try:
            with admin.cursor() as cursor:
                for name in schema_names:
                    assert re.fullmatch(r"tf_playbook_test_[a-f0-9]{32}", name)
                    cursor.execute(f"CREATE DATABASE `{name}`")
            observation = {**connection, "database": observation_db}
            source = ROOT / "example_app"
            requests = [{"source_id": 1, "target_id": 2, "amount": 1}, {"source_id": 2, "target_id": 1, "amount": 1}]
            # Produce the incident through the actual vulnerable application,
            # not standalone SQL designed solely to deadlock.
            incident = controller.batch(observation, source, "transfer:transfer", requests, retain=True, delay=0.2)
            assert oracle.target_failed(incident), json.dumps(incident, ensure_ascii=False)
            sample_path = tmp_path / "incident.json"
            sample_path.write_text(json.dumps({"error_code": 1213, "table": incident["table"], "captured_at": time.time(),
                "connection_ids": [r["connection_id"] for r in incident["requests"]]}), encoding="utf-8")
            monkeypatch.setenv("TF_TEST_MYSQL_SECRET", settings.DB_PASSWORD)
            conn_ref = {k: connection[k] for k in ("host", "port", "user")}
            config = {"work_root": str(tmp_path / "runs"), "environments": {"test": {
                "workspace_ids": ["workspace"], "target_operation": "transfer:transfer",
                "source_snapshot": {"ref": "snapshot", "path": str(source), "digest": digest(tree_manifest(source))},
                "observation_connection": {**conn_ref, "ref": "observation", "database": observation_db, "table": incident["table"], "password_env": "TF_TEST_MYSQL_SECRET"},
                "fixture_template": {**conn_ref, "ref": "fixture", "database": fixture_db, "password_env": "TF_TEST_MYSQL_SECRET"},
                "observed_error_sample": {"ref": "incident", "path": str(sample_path), "digest": "sha256:" + hashlib.sha256(sample_path.read_bytes()).hexdigest()}}}}
            implementation = MysqlBundle(config)
            spec = yaml.safe_load((ROOT.parents[3] / "domains/diagnosis_playbook/examples/mysql-transfer-deadlock.yaml").read_text(encoding="utf-8"))
            bundle = RunnerBundle("test", implementation.bundle_digest, __import__('sys').executable, str(ROOT / "programs"),
                tuple(tuple(s["verification"]["command"]["argv"]) for s in spec["stages"]), implementation.probe, implementation.collect, implementation.child_environment,
                cleanup=implementation.cleanup)
            data = {"environment_ref": "test", "policy_epoch": 1, "hypotheses": [
                {"id": "lock_order", "state": "QUEUED", "discriminator_script": "builtin:mysql-deadlock/lock_order"},
                {"id": "pool_wait", "state": "QUEUED", "discriminator_script": "builtin:mysql-deadlock/pool_wait"}]}
            inputs = {"source_snapshot": "snapshot", "observation_connection": "observation", "fixture_template": "fixture",
                      "observed_error_sample": "incident", "target_operation": "transfer:transfer", "parallel_clients": 16}
            runner = EvidenceRunner(tmp_path / "evidence")
            async def emit(*_): pass
            async def cancelled(): return False
            receipts = []
            run_id = str(uuid.uuid4())
            for index, stage in enumerate(spec["stages"]):
                data["active_scope"] = {"state": "SETTLED", "step_id": stage["id"], "run_epoch": 1}
                if stage["phase"] == "PATCH":
                    data["patch_candidate"] = {"run_epoch": 1, "files": {"transfer.py": FIXED}}
                context = {"id": run_id, "workspace_id": "workspace", "run_epoch": 1, "state_version": index + 1,
                           "active_step": stage["id"], "phase": stage["phase"], "internal": data}
                environment = implementation.probe(context, inputs)
                bound = environment["bindings"]
                argv = tuple(bound[a[8:-1]] if a.startswith("${bound.") else a for a in stage["verification"]["command"]["argv"])
                envelope = ExecutionEnvelope(str(uuid.uuid4()), run_id, 1, stage["id"], str(uuid.uuid4()), "main", digest(stage),
                    environment["environment_digest"], environment["source_snapshot_digest"], 1, bundle.digest, argv, bound["scratch"], 90, "ADVISORY_GUARD")
                receipt = await runner.execute(envelope, bundle, emit=emit, cancelled=cancelled)
                from app.domains.diagnosis_playbook.compiler import evaluate
                assert receipt["exit_code"] in stage["verification"]["expectExitCodes"], (receipt, (runner.directory(envelope.execution_id) / "stderr").read_text())
                assert evaluate(stage["verification"]["passWhen"], receipt["facts"]), receipt
                assert receipt["termination"] == "CONFIRMED"
                receipts.append(receipt)
            assert len(receipts) == 4
            assert receipts[-1]["facts"]["comparison.regression_passed"]

            # Exercise the actual engine/profile/worker/MCP/projection path as
            # well. Only the model output is a fixture; all SQL and Runner
            # process receipts still come from the real supervised execution.
            from dataclasses import replace
            from types import SimpleNamespace
            from unittest.mock import AsyncMock
            from app.agents.contract import AgentEvent, AgentRunResult
            from app.agents import selection
            from app.domains.diagnosis_playbook import execution_profile, service, tool_server, worker
            from app.domains.diagnosis_playbook.models import PlaybookRun, CasePlaybookLink
            from app.runtime.evidence_runner.registry import registry
            from tests.diagnosis_playbook.test_runtime import Backend
            from tests.workspace_asset.test_workspace_asset_boundary import _seed_workspace
            user, workspace, task = _seed_workspace(db)
            task.task_type, task.agent_backend = "DIAGNOSIS", "claude-code"
            config["environments"]["test"]["workspace_ids"].append(workspace.id)
            implementation.environments["test"]["workspace_ids"].append(workspace.id)
            # Refresh the observed incident: comparison experiments have since
            # replaced MySQL's latest-deadlock record.
            fresh = controller.batch(observation, source, "transfer:transfer", requests, retain=True, delay=0.2)
            sample_path.write_text(json.dumps({"error_code": 1213, "table": fresh["table"], "captured_at": time.time(),
                "connection_ids": [r["connection_id"] for r in fresh["requests"]]}), encoding="utf-8")
            declaration = implementation.environments["test"]
            declaration["observation_connection"]["table"] = fresh["table"]
            declaration["observed_error_sample"]["digest"] = "sha256:" + hashlib.sha256(sample_path.read_bytes()).hexdigest()
            monkeypatch.setattr(settings, "DIAGNOSIS_PLAYBOOK_WORKER_ENABLED", True)
            monkeypatch.setitem(registry._bundles, spec["execution"]["bundle"], replace(bundle, uri=spec["execution"]["bundle"]))
            row = service.register_spec(db, workspace.id, spec)
            snapshot = service.attach(db, task, row.id, inputs, "live-worker", user.id, "test", advisory_ack=True)
            db.commit()
            run_id = snapshot["id"]

            async def transaction(fn):
                try:
                    result = fn(db)
                    db.commit()
                    return result
                except BaseException:
                    db.rollback()
                    raise
            monkeypatch.setattr(worker, "run_db_txn", transaction)
            monkeypatch.setattr(execution_profile, "run_db_txn", transaction)
            manager = SimpleNamespace(send_message_to_room=AsyncMock())
            monkeypatch.setattr(worker, "manager", manager)
            monkeypatch.setattr(execution_profile, "manager", manager)

            class FixtureModel(Backend):
                async def run(self, request, on_event):
                    await on_event(AgentEvent(type="session_started", provider="claude-code", payload={"provider_session_id": "fixture-model-session"}))
                    run = db.get(PlaybookRun, run_id)
                    assert request.provider_options["execution_policy"]["mcp_config"] == {}
                    proposals = []
                    if run.phase == "HYPOTHESIZE" and not run.data_json["active_scope"].get("hypothesis_id"):
                        args = {"hypotheses": [{"id": key, "claim": key, "predictions": ["expected physical result"], "falsifiers": ["contradictory physical result"],
                            "discriminator_script": "builtin:mysql-deadlock/" + key} for key in ("lock_order", "pool_wait")]}
                        proposals.append({"name": "propose_hypotheses", "arguments": args})
                    elif run.phase == "PATCH":
                        proposals.append({"name": "propose_patch", "arguments": {"files": {"transfer.py": FIXED}}})
                    db.commit()
                    return AgentRunResult(success=True, session_id="fixture-model-session", termination_confirmed_dead=True,
                        result_text="```traceforge-playbook\n" + json.dumps({"proposals": proposals}) + "\n```")
            monkeypatch.setattr(selection, "create_agent_backend_by_name", lambda *_: FixtureModel())
            dispatcher = worker.PlaybookWorker(tmp_path / "worker-evidence")
            for _ in range(12):
                await dispatcher.tick(run_id)
                state = db.get(PlaybookRun, run_id)
                if state.state == "COMPLETED":
                    break
                assert state.state not in {"ENVIRONMENT_BLOCKED", "NEEDS_INPUT", "RECOVERING"}, service.snapshot(state)
            assert db.get(PlaybookRun, run_id).state == "COMPLETED"
            assert db.query(CasePlaybookLink).filter_by(source_run_id=run_id).count() == 1
            assert manager.send_message_to_room.await_count > 0
        finally:
            with admin.cursor() as cursor:
                for name in schema_names:
                    assert re.fullmatch(r"tf_playbook_test_[a-f0-9]{32}", name)
                    cursor.execute(f"DROP DATABASE IF EXISTS `{name}`")
