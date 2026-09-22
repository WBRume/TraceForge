"""Server-configured MySQL family, immutable inputs, independent fact collector."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
import yaml
from app.domains.diagnosis_playbook.compiler import require
from app.domains.diagnosis_playbook.contracts import digest, PlaybookError
from app.runtime.evidence_runner.registry import RunnerBundle, registry
from .files import freeze_tree, immutable_json, tree_manifest
from .programs.tf_mysql.controller import observe, connect
from .programs.tf_mysql.oracle import facts, hypothesis_decisions

ROOT = Path(__file__).resolve().parent
URI = "registry://traceforge/mysql-deadlock/1.0.0"
SCENARIOS = ["builtin:mysql-deadlock/" + name for name in ("lock_order", "pool_wait", "range_lock")]


class MysqlBundle:
    def __init__(self, configuration):
        self.configuration = deepcopy(configuration)
        self.work_root = Path(configuration["work_root"]).resolve()
        require(Path(configuration["work_root"]).is_absolute(), "ABSOLUTE_WORK_ROOT_REQUIRED")
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.environments = configuration["environments"]
        self.code_manifest = self._code_manifest()
        import pymysql
        self.bundle_digest = digest({"programs": self.code_manifest, "python": sys.version,
                                     "pymysql": pymysql.__version__})

    @staticmethod
    def _code_manifest():
        return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in ROOT.rglob("*.py") if "example_app" not in p.parts and "__pycache__" not in p.parts}

    @staticmethod
    def connections(config):
        result = {}
        for name, key in (("observation", "observation_connection"), ("fixture", "fixture_template")):
            declaration = config[key]
            password = os.environ.get(declaration["password_env"])
            require(bool(password), "MYSQL_CREDENTIAL_NOT_AVAILABLE")
            result[name] = {**{k: declaration[k] for k in ("host", "port", "user", "database")}, "password": password}
            if name == "observation":
                result[name]["table"] = declaration["table"]
        require(re.fullmatch(r"tf_playbook_[a-zA-Z0-9_]+", result["fixture"]["database"]), "FIXTURE_DATABASE_PREFIX_REQUIRED")
        require((result["fixture"]["host"], result["fixture"]["port"], result["fixture"]["database"]) !=
                (result["observation"]["host"], result["observation"]["port"], result["observation"]["database"]), "OBSERVATION_FIXTURE_MUST_DIFFER")
        return result

    def probe(self, run, inputs):
        require(self._code_manifest() == self.code_manifest, "RUNNER_BUNDLE_CHANGED")
        data = run["internal"]
        config = self.environments.get(data["environment_ref"])
        require(isinstance(config, dict), "UNKNOWN_MANAGED_ENVIRONMENT")
        require(run.get("workspace_id") in config.get("workspace_ids", []), "ENVIRONMENT_WORKSPACE_DENIED")
        for key in ("source_snapshot", "observation_connection", "fixture_template", "observed_error_sample"):
            require(inputs[key] == config[key]["ref"], "ENVIRONMENT_REFERENCE_MISMATCH:" + key)
        require(inputs["target_operation"] == config["target_operation"] and re.fullmatch(r"[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*:[a-zA-Z_]\w*", inputs["target_operation"]), "TARGET_OPERATION_NOT_BOUND")
        source_config = config["source_snapshot"]
        source = Path(source_config["path"]).resolve(strict=True)
        require(not source.is_relative_to(self.work_root) and not self.work_root.is_relative_to(source), "WORK_ROOT_OVERLAPS_SOURCE")
        sample_bytes = Path(config["observed_error_sample"]["path"]).read_bytes()
        require("sha256:" + hashlib.sha256(sample_bytes).hexdigest() == config["observed_error_sample"]["digest"], "INCIDENT_SAMPLE_CHANGED")
        sample = json.loads(sample_bytes)
        try:
            connections = self.connections(config)
            observation = observe(connections["observation"], sample)
            with connect(connections["fixture"]) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT VERSION(), @@transaction_isolation")
                    fixture_version, fixture_isolation = cursor.fetchone()
        except Exception as exc:
            raise PlaybookError("MYSQL_OBSERVATION_UNAVAILABLE", status=409, missing_facts=[type(exc).__name__]) from exc
        require(observation["table_engine"] == "InnoDB", "MYSQL_TABLE_ENGINE_MISMATCH")
        require("MariaDB" not in observation["version"] and observation["version"].startswith(("8.", "9.")), "MYSQL_VERSION_UNSUPPORTED")
        run_root = self.work_root / run["id"] / str(run["run_epoch"])
        baseline = run_root / "baseline"
        freeze_tree(source, baseline, source_config["digest"])
        candidate = data.get("patch_candidate", {})
        changes = candidate.get("files", {}) if candidate.get("run_epoch") == run["run_epoch"] else {}
        patch_key = digest(changes).split(":")[1]
        patch = run_root / ("patch-" + patch_key)
        patch_digest = freeze_tree(baseline, patch, source_config["digest"], changes)
        scope = data.get("active_scope", {})
        settled = scope.get("state") == "SETTLED" and scope.get("step_id") == run["active_step"] and scope.get("run_epoch") == run["run_epoch"]
        if settled and run["phase"] == "PATCH":
            require(bool(changes), "PATCH_CANDIDATE_REQUIRED")
        hypotheses = [h for h in data["hypotheses"] if h["state"] != "EXCLUDED"]
        if settled and run["phase"] == "HYPOTHESIZE":
            require(2 <= len(hypotheses) <= 3 and all(h["discriminator_script"] in SCENARIOS for h in hypotheses), "REGISTERED_DISCRIMINATOR_REQUIRED")
            require(len({h["discriminator_script"] for h in hypotheses}) == len(hypotheses), "DUPLICATE_DISCRIMINATOR")
        experiment = data.get("experiment_candidate", {})
        if experiment.get("run_epoch") == run["run_epoch"]:
            immutable_json(run_root / "experiments" / (experiment["candidate_digest"].split(":")[1] + ".json"), experiment)
        for branch_id, proposal in data.get("branch_experiments", {}).items():
            if proposal.get("run_epoch") == run["run_epoch"]:
                immutable_json(run_root / "branches" / branch_id / (proposal["candidate_digest"].split(":")[1] + ".json"), proposal)
        identity = {"source": source_config["digest"], "mysql_version": observation["version"],
                    "fixture_version": fixture_version, "fixture_isolation": fixture_isolation,
                    "observation_binding": {k: config["observation_connection"][k] for k in ("host", "port", "database", "table")},
                    "isolation": observation["isolation"], "fixture": {k: v for k, v in config["fixture_template"].items() if k != "password_env"},
                    "bundle": self.bundle_digest, "incident": config["observed_error_sample"]["digest"],
                    "target_operation": inputs["target_operation"], "parallel_clients": inputs.get("parallel_clients", 16)}
        environment_digest = digest(identity)
        scratch = run_root / "attempts" / str(run["state_version"])
        scratch.mkdir(parents=True, exist_ok=True)
        manifest_path = scratch / "manifest.json"
        manifest = {"phase": run["phase"], "environment_ref": data["environment_ref"],
                    "source": str(baseline), "patch": str(patch), "patch_digest": patch_digest,
                    "source_digest": source_config["digest"], "environment_digest": environment_digest,
                    "oracle_digest": self.bundle_digest, "parallel_clients": inputs.get("parallel_clients", 16),
                    "hypotheses": hypotheses, "target_operation": inputs["target_operation"],
                    "observed_sample": sample, "observed_error_code": sample.get("error_code")}
        immutable_json(manifest_path, manifest)
        # Local Python source runs under the current OS identity. Do not claim
        # a sandbox merely because the model's tools are brokered.
        environment = {"root": str(run_root), "bindings": {"source": str(baseline), "patch": str(patch),
            "scratch": str(scratch), "input_manifest": str(manifest_path), "hypothesis_manifest": str(manifest_path), "comparison_manifest": str(manifest_path)},
            "environment_digest": environment_digest, "source_snapshot_digest": source_config["digest"],
            "policy_digest": digest({"tier": "WORKSPACE_WRITE" if run["phase"] == "PATCH" else "READONLY", "epoch": data["policy_epoch"]}),
            "effective_tier": "WORKSPACE_WRITE" if run["phase"] == "PATCH" else "READONLY", "quiescent": settled,
            "enforcement": "ADVISORY_GUARD", "workspace_isolation": True, "sealed_evidence": True,
            "protected_artifacts_verified": True, "facts": {"database.engine": "mysql", "database.table_engine": "InnoDB"},
            "registered_discriminators": SCENARIOS, "target_contract": "sync transfer(tx, source_id, target_id, integer_cents); tx.lock_account(id), tx.set_balance(id, balance)"}
        for key in ("dedicated_backend_host", "backend_url", "guard_control"):
            if key in config:
                environment[key] = deepcopy(config[key])
        return environment

    def child_environment(self, envelope):
        path = Path(envelope.cwd) / "manifest.json"
        require(path.resolve(strict=True).is_relative_to(self.work_root), "MANIFEST_PATH_ESCAPE")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        require(manifest["environment_digest"] == envelope.environment_digest and manifest["source_digest"] == envelope.source_snapshot_digest,
                "MANIFEST_ENVELOPE_MISMATCH")
        require(self._code_manifest() == self.code_manifest, "RUNNER_BUNDLE_CHANGED")
        require(digest(tree_manifest(manifest["source"])) == manifest["source_digest"] and digest(tree_manifest(manifest["patch"])) == manifest["patch_digest"], "SNAPSHOT_CHANGED_BEFORE_EXECUTION")
        return {"TF_MYSQL_MANIFEST": str(path), "TF_EXECUTION_ID": envelope.execution_id,
                "TF_MYSQL_CONNECTIONS": json.dumps(self.connections(self.environments[manifest["environment_ref"]]))}

    def cleanup(self, envelope):
        """Drop only this execution's generated fixture tables, after tree death."""
        execution = envelope.execution_id.replace("-", "")
        require(re.fullmatch(r"[a-f0-9]{32}", execution), "INVALID_EXECUTION_ID")
        manifest_path = (Path(envelope.cwd) / "manifest.json").resolve(strict=True)
        require(manifest_path.is_relative_to(self.work_root), "MANIFEST_PATH_ESCAPE")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        require(manifest["environment_digest"] == envelope.environment_digest, "MANIFEST_ENVELOPE_MISMATCH")
        config = self.connections(self.environments[manifest["environment_ref"]])["fixture"]
        with connect(config) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s", (config["database"],))
                names = [row[0] for row in cursor.fetchall() if re.fullmatch("tf_" + execution + "_[a-f0-9]{16}", row[0])]
                for name in names:
                    cursor.execute(f"DROP TABLE `{name}`")

    def collect(self, envelope, directory):
        require(self._code_manifest() == self.code_manifest, "RUNNER_BUNDLE_CHANGED")
        manifest_path = Path(envelope.cwd) / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        require(digest(tree_manifest(manifest["source"])) == manifest["source_digest"] and digest(tree_manifest(manifest["patch"])) == manifest["patch_digest"], "TARGET_MUTATED_FROZEN_SNAPSHOT")
        stdout = directory / "stdout"
        if stdout.stat().st_size > 5_000_000:
            raise PlaybookError("CONTROLLER_REPORT_TOO_LARGE")
        try:
            report = json.loads(stdout.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}, []  # Harness errors stay errors, never target failures.
        require(report.get("manifest_digest") == hashlib.sha256(manifest_path.read_bytes()).hexdigest(), "CONTROLLER_REPORT_BINDING_MISMATCH")
        require(report.get("phase") == manifest["phase"], "CONTROLLER_REPORT_PHASE_MISMATCH")
        values = facts(report)
        phase = manifest["phase"]
        name = {"PROBE": "probe.json", "HYPOTHESIZE": "discriminators.json", "REPRODUCE": "oracle.json", "PATCH": "comparison.json"}[phase]
        if phase == "HYPOTHESIZE":
            report["decisions"] = hypothesis_decisions(report)
            values["hypotheses.decisions"] = report["decisions"]
        immutable_json(directory / name, {"controller": report, "facts": values})
        names = [name]
        if phase == "REPRODUCE":
            suite = ET.Element("testsuite", name="transfer_pair", tests="1", errors=str(values["tests.errors"]), failures="1" if values["database.error_code"] == 1213 else "0")
            case = ET.SubElement(suite, "testcase", name="transfer_pair", classname="bound_application")
            if values["tests.errors"]:
                ET.SubElement(case, "error", type="HarnessError")
            elif values["database.error_code"] == 1213:
                ET.SubElement(case, "failure", type="TransferDeadlockAssertion").text = "Correlated MySQL 1213 in the bound application entry"
            with (directory / "junit.xml").open("xb") as stream:
                stream.write(ET.tostring(suite, encoding="utf-8", xml_declaration=True))
            names.append("junit.xml")
        return values, names


def install(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    implementation = MysqlBundle(config)
    spec_path = Path(__file__).resolve().parents[4] / "domains" / "diagnosis_playbook" / "examples" / "mysql-transfer-deadlock.yaml"
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    bundle = RunnerBundle(URI, implementation.bundle_digest, sys.executable, str(ROOT / "programs"),
        tuple(tuple(s["verification"]["command"]["argv"]) for s in spec["stages"]),
        implementation.probe, implementation.collect, implementation.child_environment,
        tuple((s["phase"], digest({"verification": s["verification"], "oracle": s.get("oracle")})) for s in spec["stages"]),
        implementation.cleanup)
    registry.register(bundle)
    return bundle
