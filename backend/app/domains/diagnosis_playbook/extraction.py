"""Case snapshots become editable candidates, never manufactured evidence."""
from copy import deepcopy
from pathlib import Path
import yaml
from .models import CasePlaybookLink, PlaybookSpec


def draft_from_case(db, case, source_digest):
    provenance = db.query(CasePlaybookLink).filter(CasePlaybookLink.case_id == case.id,
        CasePlaybookLink.source_run_id.is_not(None), CasePlaybookLink.spec_id.is_not(None)).order_by(CasePlaybookLink.created_at.desc()).first()
    source_spec = db.get(PlaybookSpec, provenance.spec_id) if provenance else None
    if source_spec:
        spec = deepcopy(source_spec.spec_json["spec"])
        unresolved = [key for key, value in spec.get("inputs", {}).items() if value.get("required")]
    else:
        text = " ".join(str(getattr(case, key) or "") for key in ("title", "problem_description", "analysis_process", "root_cause")).lower()
        if "mysql" in text and any(word in text for word in ("1213", "deadlock", "死锁")):
            spec = yaml.safe_load((Path(__file__).parent / "examples/mysql-transfer-deadlock.yaml").read_text(encoding="utf-8"))
            unresolved = [key for key, value in spec["inputs"].items() if value.get("required")]
            unresolved.append("application_transaction_port_compatibility")
        else:
            spec = {"apiVersion": "traceforge.dev/troubleshooting/v1", "kind": "TroubleshootingPlaybook",
                "metadata": {}, "inputs": {"source_snapshot": {"type": "snapshot_ref", "required": True}},
                "execution": {"shell": False, "bundle": "registry://unresolved/case-adapter/1"},
                "stages": [{"id": phase.lower(), "phase": phase, "agentTier": "WORKSPACE_WRITE" if phase == "PATCH" else "READONLY",
                    "objective": objective, "verification": None, "next": next_step} for phase, objective, next_step in (
                        ("PROBE", "绑定症状和只读物理探针", "hypothesize"),
                        ("HYPOTHESIZE", "提出可证伪假说及区分实验", "reproduce"),
                        ("REPRODUCE", "在冻结基线捕获目标故障", "patch"),
                        ("PATCH", "保持判别器不变，对照基线和补丁", "completed"))],
                "completion": {"requireAllStageGates": True}}
            spec["stages"][-1]["enterWhen"] = {"gatePassed": "reproduce", "quiescent": True, "sameEnvironmentFamily": True}
            unresolved = ["runner_bundle", "environment_contract", "physical_probe", "discriminating_experiments", "frozen_oracle", "regression_invariants"]
    spec["metadata"] = {**spec.get("metadata", {}), "id": "case-" + case.id,
        "version": "draft-" + source_digest.split(":")[1][:12], "title": case.title,
        "taskType": "DIAGNOSIS", "sourceCaseRefs": [case.id]}
    return spec, unresolved
