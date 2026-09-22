"""Atomic technical revisions; human-confirmed or edited results are preserved."""
from copy import deepcopy
from .compiler import require
from .contracts import digest
from .models import CasePlaybookLink, PlaybookSpec, TaskPlaybookBinding
from .service import transition
from app.domains.case_center.models.case import SddCase
from app.domains.task.models.task import SddTask
from app.domains.task.models.diagnosis import SddDiagnosisResult
from app.domains.task.schemas.diagnosis import DiagnosisResultPayload
from app.domains.task.services import diagnosis_result_service


def project(db, run):
    require(run.state == "PROJECTING", "FINAL_GATES_NOT_PASSED")
    task = db.query(SddTask).filter_by(id=run.task_id).with_for_update().one()
    if task.session_generation != run.data_json["session_generation"] or task.session_revision != run.data_json["session_revision"]:
        data = deepcopy(run.data_json)
        data.update(cancel_requested=True, missing_facts=["TASK_SESSION_CHANGED"])
        db.get(TaskPlaybookBinding, run.task_id).active_run_id = None
        return transition(db, run, data, state="CANCELLED")
    link = db.query(CasePlaybookLink).filter_by(source_run_id=run.id).first()
    data = deepcopy(run.data_json)
    spec = db.get(PlaybookSpec, run.spec_id)
    if link is None:
        candidates = db.query(SddCase).filter_by(source_task_id=task.id, workspace_id=run.workspace_id).order_by(SddCase.created_at, SddCase.id).all()
        selected_case = data.get("selected_case_id")
        case = next((c for c in candidates if c.id == selected_case), None) if selected_case else (candidates[0] if len(candidates) == 1 else None)
        if len(candidates) > 1 and case is None:
            data["case_candidates"] = [{"id": c.id, "title": c.title} for c in candidates]
            data["missing_facts"] = ["CASE_SELECTION_REQUIRED"]
            return transition(db, run, data, state="NEEDS_INPUT")
        receipts = {r["execution_id"]: r for r in data["evidence"]}
        decisions = [g for g in data["gate_decisions"] if g["run_epoch"] == run.epoch and g["verdict"] == "PASS"]
        require({g["step_id"] for g in decisions} == {s["id"] for s in spec.spec_json["spec"]["stages"]}, "MISSING_FINAL_GATES")
        require(all(g["execution_id"] in receipts for g in decisions), "MISSING_SEALED_EVIDENCE")
        evidence_chain = "\n".join(f"{g['step_id']}: PASS / {g['execution_id']} / {g['receipt_digest']}" for g in decisions)
        payload = DiagnosisResultPayload(summary=f"{spec.spec_json['spec']['metadata']['title']}：已完成限定环境物理验证。",
                                        evidence_chain=evidence_chain,
                                        fix_suggestion="修复适用范围以本次环境、源码快照及基线/补丁对照回执为准。")
        # Do not infer a root cause from an unverified narrative.
        existing_result = db.query(SddDiagnosisResult).filter_by(task_id=task.id).first()
        result = None
        if existing_result is None:
            result = diagnosis_result_service.write_diagnosis_result(db, task=task, payload=payload, actor_user_id=run.creator_id)
            from app.domains.task.models.chat import ChatMessage
            card = db.get(ChatMessage, result.source_chat_message_id)
            card.metadata_json = {**card.metadata_json, "playbook_provenance": {
                "run_id": run.id, "spec_version": spec.version, "verification_status": "PASSED",
                "archive_origin": "PLAYBOOK", "verified_snapshot_digest": data["environment"].get("source_snapshot_digest"),
                "evidence_manifest_ref": f"playbook://{run.id}/evidence"}}
        if case is None:
            case = SddCase(workspace_id=run.workspace_id, source_task_id=task.id, creator_id=run.creator_id,
                           title=task.name, problem_description=task.description,
                           analysis_process=evidence_chain, solution=payload.fix_suggestion,
                           archive_origin="PLAYBOOK", status="TECHNICALLY_VERIFIED")
            db.add(case)
            db.flush()
            from app.domains.rag.services.outbox_service import enqueue_case_published
            enqueue_case_published(db, case, diagnosis_result=result)
        bundle = {"run_id": run.id, "task_id": run.task_id, "workspace_id": run.workspace_id, "run_epoch": run.epoch, "spec_version": spec.version,
                  "environment": {key: data["environment"].get(key) for key in
                      ("environment_digest", "source_snapshot_digest", "enforcement", "facts")}, "gate_decisions": decisions,
                  "evidence_manifest": [{"execution_id": r["execution_id"], "receipt_digest": r["receipt_digest"]} for r in receipts.values()],
                  "diagnosis": payload.model_dump(), "diagnosis_result_id": result.id if result else None,
                  "preserved_existing_result": existing_result is not None}
        bundle["projection_digest"] = digest(bundle)
        link = CasePlaybookLink(case_id=case.id, spec_id=spec.id, source_run_id=run.id, revision_json=bundle)
        db.add(link)
        db.flush()
    data["projection"] = {"case_id": link.case_id, "revision_id": link.id, "run_id": run.id,
                          "verification_status": "PASSED", "archive_origin": "PLAYBOOK"}
    spec.validation_state = "VERIFIED_ON_ENVIRONMENT"
    db.get(TaskPlaybookBinding, task.id).active_run_id = None
    return transition(db, run, data, state="COMPLETED", kind="playbook.completed")
