"""Workspace-scoped API. No arbitrary set_state, receipt ingestion or shell API."""
from typing import Any, Literal
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.task.routers.task.deps import get_task_or_404, verify_workspace_access, verify_workspace_permission
from .contracts import PlaybookError
from .models import CasePlaybookLink, PlaybookRun, PlaybookSpec
from .promotion import PromotionResult
from . import service

router = APIRouter(prefix="/workspaces/{ws_id}", tags=["Diagnosis Playbooks"])
global_router = APIRouter(prefix="/cases", tags=["Diagnosis Playbooks (Global)"])


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AttachRequest(StrictRequest):
    spec_id: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    environment_ref: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=120)
    advisory_ack: bool = False


class CommandRequest(StrictRequest):
    action: Literal["continue", "cancel", "replace_input", "exclude", "restore", "validate", "select_case"]
    expected_state_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=120)
    inputs: dict[str, Any] = Field(default_factory=dict)
    hypothesis_id: str | None = None
    case_id: str | None = None
    reason: str = ""


class SpecRequest(StrictRequest):
    document: dict[str, Any] | str


class GuideCommandRequest(StrictRequest):
    action: Literal["advance", "approve_hypothesis", "exclude_hypothesis", "restore_hypothesis", "enable_auto", "disable_auto"]
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=120)
    hypothesis_id: str | None = None


@router.get("/tasks/{task_id}/guide-session")
def guide_session(ws_id: str, task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = access(db, ws_id, user, task_id)
    from .guide_session import public
    return commit(db, lambda: public(task))


@router.post("/tasks/{task_id}/guide-session/commands")
def guide_command(ws_id: str, task_id: str, body: GuideCommandRequest, background: BackgroundTasks,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = access(db, ws_id, user, task_id, write=True)
    from .guide_execution import command, dispatch
    result = commit(db, lambda: command(db, task, body.model_dump(), user.id))
    background.add_task(dispatch, task_id, result)
    return result


class ExtractionRequest(StrictRequest):
    idempotency_key: str = Field(min_length=1, max_length=120)


class RecommendationRequest(StrictRequest):
    name: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=50000)
    task_type: Literal["DEVELOPMENT", "DIAGNOSIS"] = "DEVELOPMENT"
    keyword: str = Field(default="", max_length=200)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=8, ge=1, le=50)


@router.post("/playbook-recommendations")
async def recommend_draft(ws_id: str, body: RecommendationRequest, request: Request, user: User = Depends(get_current_user)):
    from app.core.offload import run_db_txn
    await run_db_txn(lambda db: access(db, ws_id, user))
    from .recommendation import recommend
    items, retrieval = await recommend(request.app.state.search_es, request.app.state.search_http, ws_id, body.name + " " + body.description, keyword=body.keyword)
    start = (body.page - 1) * body.page_size
    return {"items": items[start:start + body.page_size], "total": len(items),
            "page": body.page, "page_size": body.page_size, "retrieval": retrieval}


class PromotionRequest(StrictRequest):
    case_ids: list[str] = Field(min_length=1, max_length=20)
    idempotency_key: str = Field(min_length=1, max_length=120)


@global_router.get('/playbook-promotions/active')
def active_promotions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from .promotion import KIND, view
    from app.domains.ai.models.ai_job import SddAiJob
    from app.domains.ai.services.jobs.constants import FINAL_STATUSES
    from app.domains.auth.models.user import WorkspaceMember
    accessible = db.query(WorkspaceMember.workspace_id).filter_by(user_id=user.id)
    from sqlalchemy import or_
    rows = db.query(SddAiJob).filter(SddAiJob.creator_id == user.id,
        SddAiJob.workspace_id.in_(accessible), SddAiJob.queue_key.like(f'{KIND}:%'),
        or_(SddAiJob.status.notin_(FINAL_STATUSES), SddAiJob.result_json['review_state'].as_string() == 'PENDING')).order_by(SddAiJob.created_at.desc()).limit(100).all()
    return {'items': [view(row) for row in rows]}


@router.post('/cases/playbook-promotions', status_code=202)
def promote(ws_id: str, body: PromotionRequest, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    access(db, ws_id, user, write=True)
    from .promotion import create, view
    from app.domains.ai.services.jobs.publishing import enqueue_asset_thread_job
    result = commit(db, lambda: view(create(db, ws_id, body.case_ids, user.id, body.idempotency_key)))
    background.add_task(enqueue_asset_thread_job, result['job_id'])
    return result


@router.get('/cases/playbook-promotions')
def promotion_jobs(ws_id: str, job_id: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    access(db, ws_id, user)
    from .promotion import KIND, view
    from app.domains.ai.models.ai_job import SddAiJob
    query = db.query(SddAiJob).filter_by(workspace_id=ws_id, creator_id=user.id, queue_key=f'{KIND}:{ws_id}')
    if job_id:
        query = query.filter_by(id=job_id)
    rows = query.order_by(SddAiJob.created_at.desc()).limit(20).all()
    return {'items': [view(job) for job in rows]}


class PromotionReviewRequest(StrictRequest):
    draft_revision: str = Field(min_length=1, max_length=100)


class PromotionConfirmRequest(PromotionReviewRequest):
    draft: PromotionResult


class PromotionRegenerateRequest(PromotionReviewRequest):
    idempotency_key: str = Field(min_length=1, max_length=120)


@router.post('/cases/playbook-promotions/{job_id}/confirm')
def confirm_promotion(ws_id: str, job_id: str, body: PromotionConfirmRequest, background: BackgroundTasks,
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    access(db, ws_id, user, write=True)
    from .promotion import owned_job, confirm_draft
    from app.domains.ai.services.jobs.publishing import publish_job_state
    result = commit(db, lambda: confirm_draft(db, owned_job(db, ws_id, job_id, user.id), body.draft_revision, body.draft, user.id))
    background.add_task(publish_job_state, job_id)
    return result


@router.post('/cases/playbook-promotions/{job_id}/discard')
def discard_promotion(ws_id: str, job_id: str, body: PromotionReviewRequest, background: BackgroundTasks,
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    access(db, ws_id, user, write=True)
    from .promotion import owned_job, discard_draft
    from app.domains.ai.services.jobs.publishing import publish_job_state
    result = commit(db, lambda: discard_draft(owned_job(db, ws_id, job_id, user.id), body.draft_revision))
    background.add_task(publish_job_state, job_id)
    return result


@router.post('/cases/playbook-promotions/{job_id}/regenerate', status_code=202)
def regenerate_promotion(ws_id: str, job_id: str, body: PromotionRegenerateRequest, background: BackgroundTasks,
                         db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    access(db, ws_id, user, write=True)
    from .promotion import owned_job, regenerate, view
    from app.domains.ai.services.jobs.publishing import publish_job_state, enqueue_asset_thread_job
    result = commit(db, lambda: view(regenerate(db, owned_job(db, ws_id, job_id, user.id), body.draft_revision, body.idempotency_key, user.id)))
    background.add_task(publish_job_state, job_id)
    background.add_task(enqueue_asset_thread_job, result['job_id'])
    return result


@router.post('/cases/playbook-promotions/{job_id}/cancel')
def cancel_promotion(ws_id: str, job_id: str, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    access(db, ws_id, user, write=True)
    from .promotion import KIND, view
    from app.domains.ai.models.ai_job import SddAiJob
    from app.domains.ai.services.jobs.attempts import cancel_job
    from app.domains.ai.services.jobs.publishing import publish_job_state
    job = db.query(SddAiJob).filter_by(id=job_id, workspace_id=ws_id, creator_id=user.id, queue_key=f'{KIND}:{ws_id}').first()
    if not job:
        raise HTTPException(404, 'Promotion not found')
    cancel_job(db, workspace_id=ws_id, job_id=job_id)
    db.commit(); db.refresh(job)
    background.add_task(publish_job_state, job_id)
    return view(job)


def access(db, ws_id, user, task_id=None, write=False):
    if write:
        verify_workspace_permission(ws_id, user.id, db, WorkspacePermission.CREATE_TASK, "No permission to manage diagnosis tasks")
    else:
        verify_workspace_access(ws_id, user.id, db)
    return get_task_or_404(db, task_id, ws_id) if task_id else None


def commit(db, operation):
    try:
        result = operation()
        db.commit()
        return result
    except PlaybookError as exc:
        db.rollback()
        raise HTTPException(exc.status, exc.detail) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, {"code": "CONCURRENT_WRITE", "recoverable": True, "missing_facts": [], "current_state_version": None}) from exc


@router.get("/cases/playbooks")
def list_specs(ws_id: str, tags: str = "", symptoms: str = "", keyword: str = "", page: int = Query(1, ge=1), page_size: int = Query(12, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    access(db, ws_id, user)
    from .library import page_specs
    return page_specs(db, [ws_id], page=page, page_size=page_size, keyword=keyword, tags=tags, symptoms=symptoms)


@router.get('/cases/playbooks/{spec_id}')
def read_spec(ws_id: str, spec_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    access(db, ws_id, user)
    from .library import get_spec, detail
    from app.domains.workspace.services import workspace_service
    result = commit(db, lambda: detail(get_spec(db, ws_id, spec_id)))
    result['can_edit'] = workspace_service.user_has_permission(db, ws_id, user.id, WorkspacePermission.CREATE_TASK)
    return result


@router.put('/cases/playbooks/{spec_id}')
def edit_spec(ws_id: str, spec_id: str, body: SpecRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    access(db, ws_id, user, write=True)
    from .library import edit_spec as save
    return commit(db, lambda: save(db, ws_id, spec_id, body.document))


@router.post("/cases/playbooks")
def create_spec(ws_id: str, body: SpecRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    access(db, ws_id, user, write=True)
    return commit(db, lambda: service.serialize_spec(service.register_spec(db, ws_id, body.document)))


@router.delete('/cases/playbooks/{spec_id}')
def delete_spec(ws_id: str, spec_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    access(db, ws_id, user, write=True)
    from .library import delete_spec as remove
    return commit(db, lambda: remove(db, ws_id, spec_id))


class GlobalSpecRequest(StrictRequest):
    document: dict[str, Any] | str
    workspace_id: str = ""


@global_router.get("/playbooks")
def list_global_specs(
    workspace_id: str = "",
    tags: str = "",
    symptoms: str = "",
    keyword: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if workspace_id:
        verify_workspace_access(workspace_id, user.id, db)
        user_ws_ids = [workspace_id]
    else:
        from app.domains.auth.models.user import WorkspaceMember
        user_ws_ids = [m.workspace_id for m in db.query(WorkspaceMember).filter_by(user_id=user.id).all()]
    from .library import page_specs
    return page_specs(db, user_ws_ids, page=page, page_size=page_size, keyword=keyword, tags=tags, symptoms=symptoms)


@global_router.post("/playbooks")
def create_global_spec(
    body: GlobalSpecRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ws_id = body.workspace_id
    if not ws_id:
        from app.domains.auth.models.user import WorkspaceMember
        membership = db.query(WorkspaceMember).filter_by(user_id=user.id).first()
        if not membership:
            raise HTTPException(400, "No active workspace found to register playbook")
        ws_id = membership.workspace_id
    verify_workspace_permission(ws_id, user.id, db, WorkspacePermission.CREATE_TASK, "No permission to manage diagnosis playbooks")
    return commit(db, lambda: service.serialize_spec(service.register_spec(db, ws_id, body.document)))


@global_router.delete("/playbooks/{spec_id}")
def delete_global_spec(
    spec_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = db.query(PlaybookSpec).filter_by(id=spec_id).first()
    if not row:
        raise HTTPException(404, "Playbook spec not found")
    verify_workspace_permission(row.workspace_id, user.id, db, WorkspacePermission.CREATE_TASK, "No permission to manage diagnosis playbooks")
    from .library import delete_spec as remove
    return commit(db, lambda: remove(db, row.workspace_id, spec_id))


@router.post("/tasks/{task_id}/playbook-recommendations")
def recommendations(ws_id: str, task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = access(db, ws_id, user, task_id)
    text = (task.description or "") + task.name
    rows = db.query(PlaybookSpec).filter_by(workspace_id=ws_id).all()
    items = []
    for row in rows:
        item = service.serialize_spec(row)
        matches = [symptom for symptom in item["match"].get("symptoms", []) if symptom.lower() in text.lower()]
        item.update(reasons=matches, requires_environment_probe=True)
        items.append(item)
    return {"items": sorted(items, key=lambda x: (x["validation_state"] == "VERIFIED_ON_ENVIRONMENT", len(x["reasons"])), reverse=True)}


@router.post("/tasks/{task_id}/playbook-runs")
def attach(ws_id: str, task_id: str, body: AttachRequest, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = access(db, ws_id, user, task_id, write=True)
    result = commit(db, lambda: service.attach(db, task, body.spec_id, body.inputs, body.idempotency_key, user.id, body.environment_ref, body.advisory_ack))
    from .worker import PlaybookWorker
    background.add_task(PlaybookWorker.publish, result["id"])
    return result


@router.get("/tasks/{task_id}/playbook-runs")
def list_runs(ws_id: str, task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    access(db, ws_id, user, task_id)
    return {"items": [service.snapshot(r) for r in db.query(PlaybookRun).filter_by(workspace_id=ws_id, task_id=task_id).order_by(PlaybookRun.created_at.desc()).limit(20).all()]}


@router.get("/tasks/{task_id}/playbook-runs/{run_id}")
def read_run(ws_id: str, task_id: str, run_id: str, response: Response, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    access(db, ws_id, user, task_id)
    result = commit(db, lambda: service.snapshot(service.get_run(db, ws_id, task_id, run_id)))
    response.headers["ETag"] = f'"{result["state_version"]}"'
    return result


@router.post("/tasks/{task_id}/playbook-runs/{run_id}/commands")
def command(ws_id: str, task_id: str, run_id: str, body: CommandRequest, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    access(db, ws_id, user, task_id, write=True)
    result = commit(db, lambda: service.command(db, service.get_run(db, ws_id, task_id, run_id), body.model_dump(), user.id))
    from .worker import PlaybookWorker
    background.add_task(PlaybookWorker.publish, run_id)
    return result


@router.get("/tasks/{task_id}/playbook-runs/{run_id}/events")
def events(ws_id: str, task_id: str, run_id: str, after_seq: int = Query(0, ge=0), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    access(db, ws_id, user, task_id)
    def read():
        run = service.get_run(db, ws_id, task_id, run_id)
        return {"events": [{k: v for k, v in e.items() if k != "delivered"} for e in run.data_json["events"] if e["event_seq"] > after_seq], "snapshot": service.snapshot(run), "event_seq": run.event_seq}
    return commit(db, read)


@router.get("/tasks/{task_id}/playbook-runs/{run_id}/evidence/{execution_id}")
def evidence(ws_id: str, task_id: str, run_id: str, execution_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    access(db, ws_id, user, task_id)
    def read():
        run = service.get_run(db, ws_id, task_id, run_id)
        receipt = next((r for r in run.data_json["evidence"] if r["execution_id"] == execution_id), None)
        if receipt is None:
            raise PlaybookError("EVIDENCE_NOT_FOUND", status=404)
        return receipt
    return commit(db, read)


@router.get("/cases/{case_id}/technical-revisions")
def revisions(ws_id: str, case_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    access(db, ws_id, user)
    from app.domains.case_center.models.case import SddCase
    case = db.query(SddCase).filter_by(id=case_id, workspace_id=ws_id).first()
    if case is None:
        raise HTTPException(404, "Case not found")
    return {"items": [{**r.revision_json, "linked_spec_id": r.spec_id} for r in db.query(CasePlaybookLink).filter_by(case_id=case_id).order_by(CasePlaybookLink.created_at.desc()).all()]}


@router.post("/cases/{case_id}/playbook-extractions")
def extract_case(ws_id: str, case_id: str, body: ExtractionRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    access(db, ws_id, user, write=True)
    from app.domains.case_center.models.case import SddCase
    from .contracts import digest
    def extract():
        case = db.query(SddCase).filter_by(id=case_id, workspace_id=ws_id).with_for_update().first()
        if case is None:
            raise PlaybookError("CASE_NOT_FOUND", status=404)
        source = {k: getattr(case, k) for k in ("title", "problem_description", "analysis_process", "root_cause", "solution", "diagnosis_detail_json")}
        source_digest = digest(source)
        links = db.query(CasePlaybookLink).filter_by(case_id=case_id, source_run_id=None).all()
        for link in links:
            candidate = link.revision_json
            if candidate.get("idempotency_key") == body.idempotency_key:
                if candidate.get("source_digest") != source_digest:
                    raise PlaybookError("IDEMPOTENCY_PAYLOAD_CONFLICT", status=409)
                return candidate
            if candidate.get("source_digest") == source_digest:
                return candidate
        from .extraction import draft_from_case
        spec_candidate, unresolved = draft_from_case(db, case, source_digest)
        candidate = {"case_id": case_id, "source_digest": source_digest, "source": source,
                     "idempotency_key": body.idempotency_key, "validation_state": "UNVERIFIED",
                     "unresolved_inputs": unresolved, "spec_candidate": spec_candidate,
                     "hypothesis_candidate": {"claim": case.root_cause, "falsifiers": [], "predictions": []},
                     "spec_id": None}
        from app.domains.auth.models.user import generate_uuid
        candidate["extraction_id"] = generate_uuid()
        db.add(CasePlaybookLink(id=candidate["extraction_id"], case_id=case.id, revision_json=candidate))
        db.flush()
        return candidate
    return commit(db, extract)


@router.post("/cases/{case_id}/playbook-extractions/{extraction_id}/spec")
def save_extracted_spec(ws_id: str, case_id: str, extraction_id: str, body: SpecRequest,
                        db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    access(db, ws_id, user, write=True)
    from app.domains.case_center.models.case import SddCase
    from .compiler import compile_spec, require
    def save():
        case = db.query(SddCase).filter_by(id=case_id, workspace_id=ws_id).with_for_update().first()
        link = db.query(CasePlaybookLink).filter_by(id=extraction_id, case_id=case_id, source_run_id=None).first()
        if case is None or link is None:
            raise PlaybookError("EXTRACTION_NOT_FOUND", status=404)
        if case.status != 'APPROVED':
            raise PlaybookError('CASE_NOT_APPROVED', status=409)
        compiled = compile_spec(body.document)
        require(case_id in compiled["spec"]["metadata"].get("sourceCaseRefs", []), "SOURCE_CASE_REFERENCE_REQUIRED")
        row = service.register_spec(db, ws_id, compiled["spec"])
        if link.spec_id is not None and link.spec_id != row.id:
            raise PlaybookError("EXTRACTION_VERSION_IMMUTABLE", status=409)
        link.spec_id = row.id
        return service.serialize_spec(row)
    return commit(db, save)


@router.get("/tasks/{task_id}/playbook-runs/{run_id}/evidence/{execution_id}/artifacts/{name:path}")
def artifact(ws_id: str, task_id: str, run_id: str, execution_id: str, name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    access(db, ws_id, user, task_id)
    from fastapi.responses import FileResponse
    from app.config import settings
    from app.runtime.evidence_runner.supervisor import EvidenceRunner
    from .contracts import ExecutionEnvelope
    from pathlib import Path
    def read():
        run = service.get_run(db, ws_id, task_id, run_id)
        attempt = next((a for a in run.data_json["attempts"] if a["envelope"]["execution_id"] == execution_id), None)
        if attempt is None or not any(r["execution_id"] == execution_id for r in run.data_json["evidence"]):
            raise PlaybookError("EVIDENCE_NOT_FOUND", status=404)
        runner = EvidenceRunner(Path(settings.DIAGNOSIS_PLAYBOOK_EVIDENCE_ROOT))
        receipt = runner.inspect(ExecutionEnvelope(**attempt["envelope"]))
        if receipt is None or name not in {a["name"] for a in receipt["artifacts"]}:
            raise PlaybookError("ARTIFACT_NOT_FOUND", status=404)
        return runner.directory(execution_id) / name
    path = commit(db, read)
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")
