"""Transactional aggregate operations. Callers own the commit boundary."""
from copy import deepcopy
from datetime import datetime, timezone
import uuid
from sqlalchemy import update
from .compiler import FACTS, bind_inputs, compile_spec, evaluate, require
from .contracts import PlaybookError, digest
from .models import CasePlaybookLink, PlaybookRun, PlaybookSpec, TaskPlaybookBinding
from app.domains.task.models.task import SddTask
from app.runtime.evidence_runner.registry import registry, validate_stage

TERMINAL = {"COMPLETED", "CANCELLED"}
BUSY = {"VERIFYING", "AGENT_RUNNING", "RECOVERING", "POLICY_TRANSITION"}


def snapshot(run):
    return {"id": run.id, "task_id": run.task_id, "spec_id": run.spec_id,
            "workspace_id": run.workspace_id,
            "run_epoch": run.epoch, "state_version": run.state_version,
            "event_seq": run.event_seq, "phase": run.phase, "state": run.state,
            "active_step": run.active_step,
            **{k: deepcopy(v) for k, v in run.data_json.items() if k not in {
                "commands", "events", "inputs", "pending", "request", "environment",
                "active_scope", "provider_handle", "provider_handles", "scopes", "experiment_candidate", "patch_candidate", "branch_experiments"}}}


def get_run(db, ws_id, task_id, run_id):
    run = db.query(PlaybookRun).filter_by(id=run_id, task_id=task_id, workspace_id=ws_id).first()
    if run is None:
        raise PlaybookError("RUN_NOT_FOUND", status=404)
    return run


def register_spec(db, ws_id, document):
    compiled = compile_spec(document)
    spec = compiled["spec"]
    meta = spec["metadata"]
    existing = db.query(PlaybookSpec).filter_by(workspace_id=ws_id, spec_key=meta["id"], version=meta["version"]).first()
    if existing:
        if existing.spec_digest != compiled["spec_digest"]:
            raise PlaybookError("SPEC_VERSION_IMMUTABLE", status=409)
        return existing
    try:
        if spec["execution"].get("mode") == "ANALYSIS_GUIDE":
            bundle = None
            bundle_digest = "not-required"
        else:
            bundle = registry.resolve(spec["execution"]["bundle"])
            bundle_digest = bundle.digest
        for stage in spec["stages"]:
            if bundle is not None:
                validate_stage(bundle, stage)
    except PlaybookError as exc:
        if str(exc) != "BUNDLE_NOT_INSTALLED":
            raise
        bundle_digest = "unresolved"
    row = PlaybookSpec(workspace_id=ws_id, spec_key=meta["id"], version=meta["version"],
                       spec_digest=compiled["spec_digest"], bundle_digest=bundle_digest,
                       spec_json=compiled, validation_state="UNVERIFIED" if bundle_digest == "unresolved" else "SCHEMA_VALID")
    db.add(row)
    db.flush()
    return row


def serialize_spec(row):
    spec = row.spec_json["spec"]
    return {"id": row.id, "spec_key": row.spec_key, "version": row.version,
            "title": spec["metadata"]["title"], "validation_state": row.validation_state,
            "workspace_id": row.workspace_id, "execution_mode": spec["execution"].get("mode", "PHYSICAL_VERIFICATION"),
            "inputs": spec.get("inputs", {}), "match": spec.get("match", {}),
            "environment": spec.get("environment", {}), "source_case_refs": spec["metadata"].get("sourceCaseRefs", [])}


def spec_statistics(db, workspace_id):
    """Report actual run outcomes; blocked/never-executed runs are not passes."""
    from sqlalchemy import func
    counts = dict(db.query(PlaybookRun.spec_id, func.count(PlaybookRun.id)).filter_by(workspace_id=workspace_id).group_by(PlaybookRun.spec_id).all())
    values = {key: {"run_count": count, "sampled_runs": 0, "physical_runs": 0, "verified_runs": 0,
                    "physical_pass_rate": None, "average_verified_duration_seconds": None} for key, count in counts.items()}
    durations = {}
    # A bounded, explicitly labelled recent sample; never an invented global rate.
    for run in db.query(PlaybookRun).filter_by(workspace_id=workspace_id).order_by(PlaybookRun.created_at.desc()).limit(200).all():
        item = values[run.spec_id]
        item["sampled_runs"] += 1
        if run.data_json.get("evidence"):
            item["physical_runs"] += 1
        if run.state == "COMPLETED":
            item["verified_runs"] += 1
            timestamps = [run.data_json.get(key) for key in ("started_at", "completed_at")]
            if all(timestamps):
                durations.setdefault(run.spec_id, []).append((datetime.fromisoformat(timestamps[1]) - datetime.fromisoformat(timestamps[0])).total_seconds())
    for key, item in values.items():
        if item["physical_runs"]:
            item["physical_pass_rate"] = item["verified_runs"] / item["physical_runs"]
        if durations.get(key):
            item["average_verified_duration_seconds"] = round(sum(durations[key]) / len(durations[key]))
    return values


def _event(run, data, kind):
    seq = run.event_seq + 1
    event = {"task_id": run.task_id, "run_id": run.id, "run_epoch": run.epoch,
             "event_seq": seq, "state_version": run.state_version,
             "type": kind, "payload": {}, "delivered": False}
    data["events"] = [*data.get("events", []), event]
    return seq


def transition(db, run, data, *, state=None, step=None, phase=None, epoch=None, kind="playbook.updated"):
    if state in TERMINAL and not data.get("completed_at"):
        data["completed_at"] = datetime.now(timezone.utc).isoformat()
    previous_version = run.state_version
    next_version = previous_version + 1
    seq = _event(run, data, kind)
    data["events"][-1]["state_version"] = next_version
    data["events"][-1]["run_epoch"] = epoch or run.epoch
    values = dict(data_json=data, state_version=next_version, event_seq=seq,
                  state=state or run.state, active_step=step or run.active_step,
                  phase=phase or run.phase, epoch=epoch or run.epoch)
    changed = db.execute(update(PlaybookRun).where(PlaybookRun.id == run.id, PlaybookRun.state_version == previous_version).values(**values), execution_options={"synchronize_session": False})
    if changed.rowcount != 1:
        raise PlaybookError("STATE_VERSION_CONFLICT", status=409, version=previous_version)
    db.expire(run)
    db.refresh(run)
    return snapshot(run)


def attach(db, task, spec_id, inputs, key, creator_id, environment_ref, advisory_ack=False):
    require(task.task_type == "DIAGNOSIS", "DIAGNOSIS_ONLY")
    # Serialize creation with manual case association and competing attach requests.
    db.query(SddTask).filter_by(id=task.id).with_for_update().one()
    request = {"spec_id": spec_id, "inputs": inputs, "environment_ref": environment_ref, "advisory_ack": advisory_ack}
    prior = db.query(PlaybookRun).filter_by(task_id=task.id, idempotency_key=key).first()
    if prior:
        if prior.request_digest != digest(request):
            raise PlaybookError("IDEMPOTENCY_PAYLOAD_CONFLICT", status=409, version=prior.state_version)
        return snapshot(prior)
    binding = db.get(TaskPlaybookBinding, task.id)
    if binding and binding.active_run_id:
        raise PlaybookError("ACTIVE_RUN_EXISTS", status=409)
    spec_row = db.query(PlaybookSpec).filter_by(id=spec_id, workspace_id=task.workspace_id).first()
    if spec_row is None:
        raise PlaybookError("SPEC_NOT_FOUND", status=404)
    spec = spec_row.spec_json["spec"]
    require(spec["execution"].get("mode") != "ANALYSIS_GUIDE", "ANALYSIS_GUIDE_USE_TASK_CREATION")
    bound_inputs = bind_inputs(spec, inputs)
    first = spec["stages"][0]
    run = PlaybookRun(id=str(uuid.uuid4()), workspace_id=task.workspace_id, task_id=task.id, spec_id=spec_id,
                      creator_id=creator_id, idempotency_key=key, request_digest=digest(request), epoch=1,
                      state_version=1, event_seq=1, phase=first["phase"], active_step=first["id"], state="READY",
                      data_json={"inputs": bound_inputs, "environment_ref": environment_ref, "advisory_ack": advisory_ack,
                                 "started_at": datetime.now(timezone.utc).isoformat(),
                                 "session_generation": task.session_generation, "session_revision": task.session_revision,
                                 "stages": [{"id": s["id"], "phase": s["phase"], "objective": s["objective"]} for s in spec["stages"]],
                                 "title": spec["metadata"]["title"], "spec_version": spec_row.version,
                                 "attempts": [], "hypotheses": [], "evidence": [], "gate_decisions": [],
                                 "commands": {}, "pending": True, "cancel_requested": False, "policy_epoch": 1})
    run.data_json["events"] = [{"task_id": task.id, "run_id": run.id, "run_epoch": 1, "event_seq": 1,
                               "state_version": 1, "type": "playbook.created", "payload": {}, "delivered": False}]
    from app.config import settings
    missing = []
    if not settings.DIAGNOSIS_PLAYBOOK_WORKER_ENABLED:
        missing.append("DIAGNOSIS_PLAYBOOK_WORKER_DISABLED")
    try:
        registry.resolve(spec["execution"]["bundle"])
    except PlaybookError:
        missing.append("BUNDLE_NOT_INSTALLED")
    if missing:
        run.state = "ENVIRONMENT_BLOCKED"
        run.data_json.update(missing_facts=missing, pending=False)
    db.add(run)
    db.flush()
    if binding is None:
        binding = TaskPlaybookBinding(task_id=task.id)
        db.add(binding)
    binding.active_run_id = run.id
    task.task_meta_json = {**(task.task_meta_json or {}), "playbook_run_id": run.id}
    db.flush()
    return snapshot(run)


def command(db, run, request, actor):
    data = deepcopy(run.data_json)
    request_digest = digest(request)
    previous = data["commands"].get(request["idempotency_key"])
    if previous:
        if previous != request_digest:
            raise PlaybookError("IDEMPOTENCY_PAYLOAD_CONFLICT", status=409, version=run.state_version)
        return snapshot(run)
    if request["expected_state_version"] != run.state_version:
        raise PlaybookError("STATE_VERSION_CONFLICT", status=409, version=run.state_version)
    if run.state in TERMINAL:
        raise PlaybookError("RUN_TERMINAL", status=409, version=run.state_version)
    action = request["action"]
    state, epoch = run.state, run.epoch
    if action == "cancel":
        data["cancel_requested"] = True
        if data.get("active_scope"):
            data["active_scope"]["ticket_hash"] = ""
        data["pending"] = False
        state = "RECOVERING" if run.state in BUSY else "CANCELLED"
    elif action in {"continue", "replace_input"}:
        if run.state not in {"NEEDS_INPUT", "ENVIRONMENT_BLOCKED", "READY"}:
            raise PlaybookError("EXECUTION_NOT_QUIESCENT", status=409, version=run.state_version)
        require("CASE_SELECTION_REQUIRED" not in data.get("missing_facts", []), "CASE_SELECTION_REQUIRED")
        if action == "replace_input":
            spec = db.get(PlaybookSpec, run.spec_id).spec_json["spec"]
            data["inputs"] = bind_inputs(spec, request.get("inputs", {}))
            epoch += 1
            data["gate_decisions"] = []
            data["hypotheses"] = []
            data["environment"] = None
            data["repairs"] = {}
            data["branch_turns"] = {}
            first = spec["stages"][0]
            data["commands"][request["idempotency_key"]] = request_digest
            data["pending"] = True
            return transition(db, run, data, state="READY", step=first["id"], phase=first["phase"], epoch=epoch)
        data["pending"] = True
        # A failed model turn must actually run again. A failed physical check
        # also permits a new candidate, rather than replaying the same proposal.
        if data.get("active_scope"):
            data["active_scope"]["state"] = "RETRY_REQUESTED"
        data["missing_facts"] = []
        state = "READY"
    elif action == "select_case":
        require(run.state == "NEEDS_INPUT" and "CASE_SELECTION_REQUIRED" in data.get("missing_facts", []), "CASE_SELECTION_NOT_PENDING")
        require(request.get("case_id") in {c["id"] for c in data.get("case_candidates", [])}, "INVALID_CASE_SELECTION")
        data["selected_case_id"] = request["case_id"]
        data["missing_facts"] = []
        state = "PROJECTING"
    elif action in {"exclude", "restore", "validate"}:
        if run.state in BUSY:
            raise PlaybookError("EXECUTION_NOT_QUIESCENT", status=409)
        hypothesis = next((h for h in data["hypotheses"] if h["id"] == request.get("hypothesis_id")), None)
        require(hypothesis is not None and bool(request.get("reason", "").strip()), "HYPOTHESIS_OR_REASON_MISSING")
        # validate schedules physical work, it never marks a hypothesis proven.
        hypothesis.update(state="EXCLUDED" if action == "exclude" else "QUEUED", reason=request["reason"],
                          actor_id=actor, decided_at=datetime.now(timezone.utc).isoformat(),
                          decision_version=hypothesis.get("decision_version", 0) + 1)
        data["gate_decisions"] = []
        epoch += 1
        # Re-probe under the new decision epoch; old epoch receipts remain
        # historical and cannot accidentally satisfy the new final gate.
        spec = db.get(PlaybookSpec, run.spec_id).spec_json["spec"]
        data["environment"] = None
        data["repairs"] = {}
        data["branch_turns"] = {}
        data["commands"][request["idempotency_key"]] = request_digest
        first = spec["stages"][0]
        return transition(db, run, data, state="READY", epoch=epoch, step=first["id"], phase=first["phase"])
    else:
        raise PlaybookError("UNKNOWN_COMMAND")
    data["commands"][request["idempotency_key"]] = request_digest
    result = transition(db, run, data, state=state, epoch=epoch)
    if state == "CANCELLED":
        binding = db.get(TaskPlaybookBinding, run.task_id)
        binding.active_run_id = None
    return result


def propose_hypotheses(db, run, hypotheses, expected_version):
    """Trusted tool boundary; free text and client PASS assertions are not accepted."""
    require(run.phase == "HYPOTHESIZE" and run.state_version == expected_version, "HYPOTHESIS_STAGE_CONFLICT")
    require(isinstance(hypotheses, list) and 2 <= len(hypotheses) <= 3, "INVALID_HYPOTHESES")
    import re
    ids = set()
    for h in hypotheses:
        require(isinstance(h, dict) and set(h) == {"id", "claim", "predictions", "falsifiers", "discriminator_script"}, "INVALID_HYPOTHESIS")
        require(isinstance(h["id"], str) and re.fullmatch(r"[a-z0-9_]+", h["id"]) and h["id"] not in ids, "INVALID_HYPOTHESIS_ID")
        ids.add(h["id"])
        require(all(isinstance(h[k], str) and h[k].strip() for k in ("claim", "discriminator_script")), "INVALID_HYPOTHESIS")
        require(all(isinstance(h[k], list) and h[k] and all(isinstance(v, str) and v for v in h[k]) for k in ("predictions", "falsifiers")), "INVALID_HYPOTHESIS")
    data = deepcopy(run.data_json)
    decisions = {h["id"]: h for h in data["hypotheses"] if h.get("decision_version", 0) > 0}
    require(set(decisions) <= ids, "HUMAN_HYPOTHESIS_DECISION_MUST_BE_PRESERVED")
    data["hypotheses"] = [{**h, **({k: v for k, v in decisions[h["id"]].items() if k not in {"claim", "predictions", "falsifiers", "discriminator_script"}} if h["id"] in decisions else {"state": "QUEUED", "decision_version": 0})} for h in hypotheses]
    return transition(db, run, data)


def accept_receipt(db, run, receipt):
    """Internal Runner-only boundary. There is intentionally no HTTP receipt POST."""
    data = deepcopy(run.data_json)
    if any(r["execution_id"] == receipt["execution_id"] for r in data["evidence"]):
        return snapshot(run)
    attempt = data["attempts"][-1]
    expected = attempt["envelope"]
    for key in ("execution_id", "run_id", "run_epoch", "step_id", "step_attempt_id", "branch_id", "contract_digest", "environment_digest", "source_snapshot_digest", "policy_epoch", "bundle_digest"):
        require(receipt.get(key) == expected[key], "STALE_OR_FOREIGN_RECEIPT:" + key)
    require(run.epoch == receipt["run_epoch"] and run.active_step == receipt["step_id"], "STALE_RECEIPT")
    require(receipt.get("receipt_digest") == digest({k: v for k, v in receipt.items() if k != "receipt_digest"}), "RECEIPT_DIGEST_MISMATCH")
    require(receipt.get("termination") == "CONFIRMED", "EXECUTION_NOT_QUIESCENT")
    task = db.get(SddTask, run.task_id)
    if task.session_generation != data["session_generation"] or task.session_revision != data["session_revision"]:
        data["evidence"].append(receipt)
        data["cancel_requested"] = True
        data["missing_facts"] = ["TASK_SESSION_CHANGED"]
        data["pending"] = False
        db.get(TaskPlaybookBinding, run.task_id).active_run_id = None
        return transition(db, run, data, state="CANCELLED")
    spec = db.get(PlaybookSpec, run.spec_id).spec_json["spec"]
    stage = next(s for s in spec["stages"] if s["id"] == run.active_step)
    verification = stage["verification"]
    catalog = {key: kind for artifact in verification["artifacts"] for key, kind in FACTS[artifact["parser"]].items()}
    facts = receipt.get("facts", {})
    artifact_names = {a["name"] for a in receipt.get("artifacts", []) if a.get("digest", "").startswith("sha256:")}
    complete = all(key in facts and type(facts[key]) is kind for key, kind in catalog.items()) and all(a["name"] in artifact_names for a in verification["artifacts"])
    verdict = "ERROR"
    if complete and not receipt.get("timed_out") and not receipt.get("cancelled") and receipt.get("cleanup_confirmed", True) is True:
        if receipt["exit_code"] in verification["expectExitCodes"]:
            verdict = "PASS" if evaluate(verification["passWhen"], facts) else "FAIL"
    if stage["phase"] == "HYPOTHESIZE" and len(data["hypotheses"]) < 2:
        verdict = "ERROR"
    if stage["phase"] == "HYPOTHESIZE" and isinstance(facts.get("hypotheses.decisions"), list):
        decisions = {d.get("id"): d for d in facts["hypotheses.decisions"] if isinstance(d, dict)}
        for hypothesis in data["hypotheses"]:
            decision = decisions.get(hypothesis["id"])
            if hypothesis["state"] != "EXCLUDED" and decision and decision.get("state") in {"SUPPORTED", "REFUTED", "INCONCLUSIVE"}:
                hypothesis.update(state=decision["state"], reason=decision.get("reason", ""),
                                  physical_execution_id=receipt["execution_id"], scenario=decision.get("scenario"))
    data["evidence"].append(receipt)
    data["gate_decisions"].append({"step_id": run.active_step, "run_epoch": run.epoch, "verdict": verdict,
                                    "execution_id": receipt["execution_id"], "receipt_digest": receipt["receipt_digest"],
                                    "contract_digest": receipt["contract_digest"], "evaluator_version": "1"})
    attempt["state"] = "SETTLED"
    run.lease_until = 0
    data["pending"] = False
    if data["cancel_requested"]:
        db.get(TaskPlaybookBinding, run.task_id).active_run_id = None
        return transition(db, run, data, state="CANCELLED")
    if verdict != "PASS":
        data["missing_facts"] = [k for k in catalog if k not in facts]
        healing = spec.get("execution", {}).get("selfHealing", {})
        if healing and (verdict == "ERROR" or stage["phase"] == "PATCH") and not receipt.get("cancelled"):
            fingerprint = digest({"exit_code": receipt["exit_code"], "facts": facts,
                                  "missing": data["missing_facts"], "timed_out": receipt.get("timed_out", False)})
            repairs = data.setdefault("repairs", {})
            previous = repairs.get(run.active_step, {})
            consecutive = previous.get("consecutive", 0) + 1 if previous.get("fingerprint") == fingerprint else 1
            count = previous.get("count", 0)
            repairs[run.active_step] = {"count": count, "consecutive": consecutive, "fingerprint": fingerprint}
            if count < healing["maxRepairsPerStage"] and consecutive < healing["maxConsecutiveSameFailure"]:
                repairs[run.active_step]["count"] += 1
                data["repair_feedback"] = {"step_id": run.active_step, "verdict": verdict, "facts": facts,
                    "missing_facts": data["missing_facts"], "allowed_repairs": ["patch_candidate"] if stage["phase"] == "PATCH" else ["experiment_candidate"],
                    "immutable_constraints": ["source_snapshot_digest", "oracle", "verification_contract", "target_symptom"]}
                if data.get("active_scope"):
                    data["active_scope"]["state"] = "REPAIR_REQUIRED"
                return transition(db, run, data, state="READY", kind="playbook.repair_required")
            data["missing_facts"].append("SELF_HEALING_EXHAUSTED")
        return transition(db, run, data, state="NEEDS_INPUT", kind="playbook.verification_failed")
    if stage["next"] == "completed":
        data["missing_facts"] = []
        data.pop("repair_feedback", None)
        passed = {d["step_id"] for d in data["gate_decisions"] if d["run_epoch"] == run.epoch and d["verdict"] == "PASS"}
        require(passed == {s["id"] for s in spec["stages"]}, "MISSING_STAGE_GATE")
        return transition(db, run, data, state="PROJECTING", kind="playbook.verification_passed")
    next_stage = next(s for s in spec["stages"] if s["id"] == stage["next"])
    if next_stage["agentTier"] != stage["agentTier"]:
        data["policy_epoch"] += 1
    data["pending"] = True
    data["missing_facts"] = []
    data.pop("repair_feedback", None)
    return transition(db, run, data, state="READY", step=next_stage["id"], phase=next_stage["phase"], kind="playbook.verification_passed")
