"""Bind frozen argv to server-probed resources before durable execution intent."""
from dataclasses import asdict
from copy import deepcopy
from pathlib import Path
import re
import uuid
from .contracts import ExecutionEnvelope, PlaybookError, digest
from .compiler import require, safe_relative
from .service import transition


def contained(root, path):
    root, path = Path(root).resolve(strict=True), Path(path).resolve(strict=True)
    require(path.is_relative_to(root), "PATH_ESCAPE")
    return path


def materialize_experiment(root, files):
    """Agent proposals are data. They cannot overwrite a frozen experiment."""
    root = Path(root).resolve(strict=True)
    for name, content in files.items():
        require(safe_relative(name) and isinstance(content, str), "INVALID_EXPERIMENT_FILE")
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        contained(root, target.parent)
        with target.open("x", encoding="utf-8") as output:
            output.write(content)
    return digest(files)


def bind(run, spec_row, bundle, environment):
    data = run.data_json
    require(not data["cancel_requested"] and run.state == "READY", "DISPATCH_REVOKED")
    spec = spec_row.spec_json["spec"]
    pinned_bundle = data.get("bundle_digest", spec_row.bundle_digest)
    require(pinned_bundle == bundle.digest or (pinned_bundle == "unresolved" and not data["attempts"]), "BUNDLE_DIGEST_CHANGED")
    require(environment.get("sealed_evidence") is True and environment.get("workspace_isolation") is True, "ENVIRONMENT_NOT_ISOLATED")
    enforcement = environment.get("enforcement")
    from app.config import settings
    requested = settings.DIAGNOSIS_PLAYBOOK_ENFORCEMENT_LEVEL
    if requested != "ADVISORY_GUARD":
        require(enforcement == requested, "CONFIGURED_ENFORCEMENT_UNAVAILABLE")
    require(enforcement in {"CONTAINER_SANDBOX", "WORKTREE_BROKER", "ADVISORY_GUARD"}, "ENFORCEMENT_UNAVAILABLE")
    if enforcement == "ADVISORY_GUARD":
        require(data.get("advisory_ack") and spec.get("environment", {}).get("allowAdvisory") is True, "ADVISORY_NOT_AUTHORIZED")
    required = spec.get("match", {}).get("requiredFacts", {})
    require(all(environment.get("facts", {}).get(k) == v for k, v in required.items()), "ENVIRONMENT_FACT_MISMATCH")
    require(environment.get("quiescent") is True, "EXECUTION_NOT_QUIESCENT")
    for key in ("environment_digest", "source_snapshot_digest", "policy_digest"):
        require(isinstance(environment.get(key), str) and re.fullmatch(r"sha256:[0-9a-f]{64}", environment[key]), "MISSING_ENVIRONMENT_IDENTITY")
    previous = data.get("environment")
    if previous:
        require(previous["environment_digest"] == environment["environment_digest"], "ENVIRONMENT_DRIFT")
    stage = next(s for s in spec["stages"] if s["id"] == run.active_step)
    require(environment.get("effective_tier") == stage["agentTier"], "POLICY_NOT_APPLIED")
    if run.phase == "PATCH":
        require(any(g["verdict"] == "PASS" and g["run_epoch"] == run.epoch and g["step_id"] == stage["enterWhen"]["gatePassed"] for g in data["gate_decisions"]), "PATCH_GATE_MISSING")
        require(environment.get("protected_artifacts_verified") is True, "PROTECTED_ARTIFACT_CHANGED")
    template = stage["verification"]["command"]
    from app.runtime.evidence_runner.registry import validate_stage
    validate_stage(bundle, stage)
    bound = environment["bindings"]
    def resolve(value):
        match = re.fullmatch(r"\$\{(inputs|bound)\.([a-z_][a-z0-9_]*)\}", value)
        if not match:
            return value
        source = data["inputs"] if match[1] == "inputs" else bound
        require(match[2] in source, "MISSING_BINDING")
        # References are opaque. Credentials are never expanded in argv.
        if match[1] == "inputs":
            require(spec["inputs"][match[2]]["type"] != "connection_ref", "CREDENTIAL_REFERENCE_IN_ARGV")
        return str(source[match[2]])
    scratch = contained(environment["root"], bound["scratch"])
    for key, value in bound.items():
        if key in {"source", "input_manifest", "hypothesis_manifest", "comparison_manifest"}:
            contained(environment["root"], value)
    envelope = ExecutionEnvelope(str(uuid.uuid4()), run.id, run.epoch, run.active_step, str(uuid.uuid4()), "main",
                                 digest({"stage": stage, "inputs": data["inputs"], "bundle": bundle.digest, "evaluator": "1"}),
                                 environment["environment_digest"], environment["source_snapshot_digest"],
                                 data["policy_epoch"], bundle.digest, tuple(resolve(a) for a in template["argv"]),
                                 str(scratch), template["timeoutSeconds"], enforcement)
    return envelope


def reserve(db, run, envelope, environment, owner_id=None):
    data = deepcopy(run.data_json)
    data["environment"] = environment
    data["bundle_digest"] = envelope.bundle_digest
    data["enforcement"] = envelope.enforcement
    data["attempts"].append({"id": envelope.step_attempt_id, "state": "DISPATCH_INTENT", "envelope": asdict(envelope)})
    data["pending"] = False
    transition(db, run, data, state="VERIFYING", kind="playbook.verifying")
    if owner_id:
        import time
        run.lease_owner, run.lease_until = owner_id, time.time() + 120
