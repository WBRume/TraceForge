"""Closed predicate language and immutable playbook compilation (no eval/shell)."""
from copy import deepcopy
import json
import re
from pathlib import PureWindowsPath, PurePosixPath
import yaml
from .contracts import PlaybookError, digest

PHASES = ("PROBE", "HYPOTHESIZE", "REPRODUCE", "PATCH")
FACTS = {
    "mysql_probe_v1": {"probe.connection_ok": bool, "probe.correlated_samples": int, "probe.lock_or_error_artifact_refs": list},
    "hypothesis_discriminators_v1": {"hypotheses.has_discriminating_physical_evidence": bool, "hypotheses.required_conflicts_resolved": bool},
    "junit_v1": {"tests.target_node_collected": bool, "tests.target_failure": str, "tests.collected": int, "tests.errors": int},
    "transfer_deadlock_v1": {"database.error_code": int, "database.correlated_lock_cycle": bool, "oracle.matches_observed_symptom": bool},
    "baseline_patch_comparison_v1": {"comparison." + key: bool for key in ("baseline_target_failed", "patch_target_passed", "oracle_digest_equal", "environment_equal_except_patch", "expected_tests_collected", "regression_passed", "balance_conserved", "request_coverage_complete", "lock_order_consistent")},
}


def require(condition, code):
    if not condition:
        raise PlaybookError(code)


def safe_relative(path: str) -> bool:
    if not isinstance(path, str) or not path or "\x00" in path or ":" in path:
        return False
    windows = PureWindowsPath(path)
    parts = path.replace("\\", "/").split("/")
    return (not windows.drive and not windows.is_absolute() and not windows.is_reserved()
            and not PurePosixPath(path).is_absolute()
            and all(p not in {"", ".", ".."} and not p.endswith((" ", ".")) for p in parts))


def validate_predicate(node, facts, depth=0):
    require(isinstance(node, dict) and depth < 32, "INVALID_PREDICATE")
    for key in ("all", "any", "not"):
        if key in node:
            require(set(node) == {key}, "INVALID_PREDICATE")
            children = [node[key]] if key == "not" else node[key]
            require(isinstance(children, list) and 0 < len(children) <= 100, "INVALID_PREDICATE")
            for child in children:
                validate_predicate(child, facts, depth + 1)
            return
    require(set(node) <= {"op", "fact", "value"}, "INVALID_PREDICATE")
    op, fact = node.get("op"), node.get("fact")
    require(op in {"eq", "ge", "in", "nonempty", "same_digest"} and fact in facts, "UNKNOWN_FACT_OR_OPERATOR")
    if op == "nonempty":
        require(facts[fact] in (str, list), "PREDICATE_TYPE_MISMATCH")
        return
    require("value" in node, "MISSING_PREDICATE_VALUE")
    value = node["value"]
    if op == "in":
        require(isinstance(value, list) and bool(value) and all(type(v) is facts[fact] for v in value), "PREDICATE_TYPE_MISMATCH")
    else:
        require(type(value) is facts[fact], "PREDICATE_TYPE_MISMATCH")
        require(op != "ge" or facts[fact] in (int, float), "PREDICATE_TYPE_MISMATCH")
        require(op != "same_digest" or (isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value)), "INVALID_DIGEST")


def evaluate(node, facts):
    # Missing facts always invalidate the receipt before evaluating NOT/ANY.
    if "all" in node:
        return all(evaluate(child, facts) for child in node["all"])
    if "any" in node:
        return any(evaluate(child, facts) for child in node["any"])
    if "not" in node:
        return not evaluate(node["not"], facts)
    actual, value = facts[node["fact"]], node.get("value")
    return {"eq": lambda: type(actual) is type(value) and actual == value,
            "ge": lambda: actual >= value, "in": lambda: actual in value,
            "nonempty": lambda: bool(actual), "same_digest": lambda: actual == value}[node["op"]]()


def _compile_spec(document):
    if isinstance(document, str):
        require(len(document) <= 500_000, "SPEC_TOO_LARGE")
        try:
            document = yaml.safe_load(document)
        except yaml.YAMLError as exc:
            raise PlaybookError("INVALID_YAML") from exc
    require(isinstance(document, dict), "INVALID_SPEC")
    require(len(json.dumps(document, ensure_ascii=False)) <= 500_000, "SPEC_TOO_LARGE")
    spec = deepcopy(document)
    require(set(spec) <= {"apiVersion", "kind", "metadata", "match", "inputs", "environment", "context", "execution", "stages", "completion"}, "UNKNOWN_SPEC_FIELD")
    require(spec.get("apiVersion") == "traceforge.dev/troubleshooting/v1" and spec.get("kind") == "TroubleshootingPlaybook", "INVALID_SPEC_VERSION")
    meta = spec.get("metadata", {})
    require(meta.get("taskType") == "DIAGNOSIS" and all(isinstance(meta.get(k), str) and meta[k] for k in ("id", "version", "title")), "INVALID_METADATA")
    require(len(meta["id"]) <= 120 and len(meta["version"]) <= 40 and len(meta["title"]) <= 500, "INVALID_METADATA")
    if spec.get("execution", {}).get("mode") == "ANALYSIS_GUIDE":
        require(spec["execution"] == {"mode": "ANALYSIS_GUIDE"}, "INVALID_ANALYSIS_EXECUTION")
        require(not spec.get("inputs") and not spec.get("completion") and not spec.get("environment"), "INVALID_ANALYSIS_CONTRACT")
        require(isinstance(spec.get("context", {}), dict), "INVALID_ANALYSIS_CONTEXT")
        stages = spec.get("stages")
        require(isinstance(stages, list) and 1 <= len(stages) <= 32, "INVALID_STAGES")
        require(all(isinstance(s, dict) and set(s) == {"id", "objective"} and
                    isinstance(s["id"], str) and re.fullmatch(r"[a-z][a-z0-9_]*", s["id"]) and
                    isinstance(s["objective"], str) and bool(s["objective"].strip()) for s in stages), "INVALID_ANALYSIS_STAGE")
        order = [s["id"] for s in stages]
        require(len(set(order)) == len(order), "INVALID_STAGE_IDS")
        return {"spec": spec, "spec_digest": digest(spec), "stage_order": order, "evaluator_version": "analysis-1"}
    declarations = spec.get("inputs", {})
    require(isinstance(declarations, dict) and len(declarations) <= 64, "INVALID_INPUT_DECLARATIONS")
    for key, declaration in declarations.items():
        require(isinstance(key, str) and re.fullmatch(r"[a-z_][a-z0-9_]*", key) and isinstance(declaration, dict), "INVALID_INPUT_DECLARATION")
        require(set(declaration) <= {"type", "required", "default", "minimum", "maximum", "effect", "description"}, "UNKNOWN_INPUT_FIELD")
        require(declaration.get("type") in {"integer", "string", "snapshot_ref", "connection_ref", "fixture_ref", "symbol_ref", "artifact_ref"}, "INVALID_INPUT_TYPE")
        require(type(declaration.get("required", False)) is bool, "INVALID_INPUT_REQUIRED")
        if declaration["type"] == "integer":
            for limit in ("minimum", "maximum", "default"):
                require(limit not in declaration or type(declaration[limit]) is int, "INVALID_INPUT_BOUND")
            require(declaration.get("minimum", -2**63) <= declaration.get("maximum", 2**63 - 1), "INVALID_INPUT_BOUND")
        elif "default" in declaration:
            require(isinstance(declaration["default"], str) and bool(declaration["default"]), "INVALID_INPUT_DEFAULT")
    environment = spec.get("environment", {})
    require(isinstance(environment, dict) and type(environment.get("allowAdvisory", False)) is bool, "INVALID_ENVIRONMENT")
    execution = spec.get("execution", {})
    require(execution.get("shell") is False and isinstance(execution.get("bundle"), str), "SHELL_OR_BUNDLE_INVALID")
    healing = execution.get("selfHealing")
    if healing is not None:
        require(isinstance(healing, dict) and set(healing) == {"maxConsecutiveSameFailure", "maxRepairsPerStage", "onExhausted"}, "INVALID_SELF_HEALING")
        require(healing["onExhausted"] == "NEEDS_INPUT" and all(type(healing[k]) is int and 1 <= healing[k] <= 5 for k in ("maxConsecutiveSameFailure", "maxRepairsPerStage")), "INVALID_SELF_HEALING")
    require(spec.get("completion", {}).get("requireAllStageGates") is True, "ALL_GATES_REQUIRED")
    stages = spec.get("stages")
    require(isinstance(stages, list) and 1 <= len(stages) <= 32, "INVALID_STAGES")
    ids = [s.get("id") for s in stages if isinstance(s, dict)]
    require(len(ids) == len(stages) and len(set(ids)) == len(ids) and all(isinstance(s, str) and re.fullmatch(r"[a-z][a-z0-9_]*", s) for s in ids), "INVALID_STAGE_IDS")
    by_id = {s["id"]: s for s in stages}
    cursor, visited = ids[0], []
    while cursor != "completed":
        require(cursor in by_id and cursor not in visited, "INVALID_DAG")
        visited.append(cursor)
        cursor = by_id[cursor].get("next")
    require(set(visited) == set(ids), "UNREACHABLE_STAGE")
    seen_phases = []
    for sid in visited:
        stage = by_id[sid]
        require(set(stage) <= {"id", "phase", "agentTier", "objective", "verification", "next", "candidate", "oracle", "hypotheses", "toolContract", "enterWhen", "protectedArtifacts"}, "UNKNOWN_STAGE_FIELD")
        phase = stage.get("phase")
        require(phase in PHASES and isinstance(stage.get("objective"), str) and bool(stage["objective"]), "INVALID_STAGE")
        require(not seen_phases or PHASES.index(phase) >= PHASES.index(seen_phases[-1]), "PHASE_ORDER_REGRESSION")
        require(stage.get("agentTier") == ("WORKSPACE_WRITE" if phase == "PATCH" else "READONLY"), "INVALID_PERMISSION_TIER")
        if phase == "PATCH":
            enter = stage.get("enterWhen", {})
            require("REPRODUCE" in seen_phases and "HYPOTHESIZE" in seen_phases and enter.get("quiescent") is True and enter.get("sameEnvironmentFamily") is True and enter.get("gatePassed") in visited[:visited.index(sid)] and by_id[enter["gatePassed"]]["phase"] == "REPRODUCE", "PATCH_WITHOUT_REPRODUCTION")
        seen_phases.append(phase)
        verification = stage.get("verification", {})
        require(set(verification) == {"command", "expectExitCodes", "artifacts", "passWhen"}, "INVALID_VERIFICATION")
        command = verification["command"]
        require(set(command) == {"argv", "cwd", "timeoutSeconds", "effect"}, "INVALID_COMMAND")
        require(type(command["timeoutSeconds"]) is int and 1 <= command["timeoutSeconds"] <= 3600, "INVALID_TIMEOUT")
        require(command["effect"] in {"OBSERVATION_READONLY", "ISOLATED_FIXTURE"}, "INVALID_EFFECT")
        argv = command["argv"]
        require(isinstance(argv, list) and bool(argv) and all(isinstance(a, str) and a and "\x00" not in a for a in argv), "INVALID_ARGV")
        for argument in [*argv, command["cwd"]]:
            require(isinstance(argument, str), "INVALID_PATH")
            if "${" in argument:
                match = re.fullmatch(r"\$\{(inputs|bound)\.([a-z_][a-z0-9_]*)\}", argument)
                require(bool(match), "INVALID_PLACEHOLDER")
                if match[1] == "inputs":
                    require(match[2] in spec.get("inputs", {}), "UNKNOWN_INPUT")
                else:
                    require(match[2] in {"scratch", "source", "input_manifest", "hypothesis_manifest", "comparison_manifest"}, "UNKNOWN_BINDING")
        require(command["cwd"] == "${bound.scratch}", "UNSAFE_CWD")
        require(isinstance(verification["expectExitCodes"], list) and bool(verification["expectExitCodes"]) and all(type(x) is int for x in verification["expectExitCodes"]), "INVALID_EXIT_CODES")
        facts = {}
        artifacts = verification["artifacts"]
        require(isinstance(artifacts, list) and bool(artifacts), "MISSING_ARTIFACTS")
        for artifact in artifacts:
            require(set(artifact) == {"name", "parser", "source"} and safe_relative(artifact["name"]), "UNSAFE_ARTIFACT_PATH")
            require(artifact["parser"] in FACTS and artifact["source"] == "runner_output", "UNKNOWN_PARSER")
            facts.update(FACTS[artifact["parser"]])
        validate_predicate(verification["passWhen"], facts)
    require(set(seen_phases) == set(PHASES), "INCOMPLETE_PLAYBOOK")
    return {"spec": spec, "spec_digest": digest(spec), "stage_order": visited, "evaluator_version": "1"}


def compile_spec(document):
    try:
        return _compile_spec(document)
    except PlaybookError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError, OverflowError) as exc:
        raise PlaybookError("INVALID_SPEC_STRUCTURE") from exc


def bind_inputs(spec, supplied):
    declarations = spec.get("inputs", {})
    require(set(supplied) <= set(declarations), "UNKNOWN_INPUT")
    result = {}
    for key, declaration in declarations.items():
        value = supplied.get(key, declaration.get("default"))
        if value is None:
            require(not declaration.get("required"), "MISSING_INPUT:" + key)
            continue
        if declaration["type"] == "integer":
            require(type(value) is int and declaration.get("minimum", value) <= value <= declaration.get("maximum", value), "INVALID_INPUT:" + key)
        else:
            require(declaration["type"] in {"snapshot_ref", "connection_ref", "fixture_ref", "symbol_ref", "artifact_ref", "string"} and isinstance(value, str) and bool(value), "INVALID_INPUT:" + key)
        result[key] = value
    return result
