from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session
from app.dependencies import get_current_user, get_db
from app.config import settings
from app.domains.local_resource import service
from app.domains.local_resource.client import ResourceError
from app.domains.local_resource.models import LocalResource
from app.domains.local_resource.schemas import ConnectionInput, ResourceInput

router = APIRouter(prefix="/workspaces/{ws_id}/local-resources", tags=["Local resources"])


def call(operation):
    try:
        return operation()
    except ResourceError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)}) from exc


@router.get("")
def list_resources(ws_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    call(lambda: service.require_member(db, ws_id, user.id))
    rows = db.query(LocalResource).filter_by(workspace_id=ws_id, owner_user_id=user.id).order_by(LocalResource.created_at.desc(), LocalResource.id.desc()).all()
    return {"enabled": settings.LOCAL_RESOURCES_MODE == "intranet", "items": [service.serialize(row) for row in rows]}


@router.post("")
def create_resource(ws_id: str, data: ResourceInput, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return call(lambda: service.serialize(service.save(db, ws_id, user.id, data)))


@router.post("/check-connection")
def check_connection(ws_id: str, data: ConnectionInput, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return call(lambda: service.check_connection(db, ws_id, user.id, data))


@router.put("/{resource_id}")
def update_resource(ws_id: str, resource_id: str, data: ResourceInput, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return call(lambda: service.serialize(service.save(db, ws_id, user.id, data, resource_id)))


@router.post("/{resource_id}/verify")
def verify_resource(ws_id: str, resource_id: str, background_tasks: BackgroundTasks, user=Depends(get_current_user), db: Session = Depends(get_db)):
    row = call(lambda: service.owned(db, resource_id, user.id, ws_id))
    result = call(lambda: service.verify(service.profile(row)))
    row.host_id = result["host_id"]
    row.verification_json = result
    db.commit()
    service.reconcile_cleanup(db, row)
    from app.domains.task.models.task import SddTask, TaskStatus
    from app.domains.workflow.services import provision_job_service
    tasks = db.query(SddTask).filter_by(local_resource_id=row.id, execution_location="LOCAL", status=TaskStatus.PROVISIONING).all()
    for task in tasks:
        # Retry the original job only after an explicit verification succeeds.
        from app.domains.workflow.models.provision_job import SddProvisionJob
        job = db.query(SddProvisionJob).filter_by(task_id=task.id, stage="RESOURCE_UNAVAILABLE").order_by(SddProvisionJob.created_at.desc()).first()
        if job:
            background_tasks.add_task(provision_job_service.run_create_task_job, job.id)
    return service.serialize(row)


from pydantic import BaseModel, Field

class ApplyProposalInput(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=36)


@router.post("/{resource_id}/apply-proposal")
def apply_proposal(ws_id: str, resource_id: str, data: ApplyProposalInput,
                   user=Depends(get_current_user), db: Session = Depends(get_db)):
    import base64
    import hashlib
    import uuid
    from app.domains.workflow.services import change_proposal_service as proposals
    from app.domains.local_resource.client import ResourceClient
    resource = call(lambda: service.owned(db, resource_id, user.id, ws_id))
    proposal = proposals.get_visible_proposal(db, proposal_id=data.proposal_id, user_id=user.id)
    if not proposal or proposal.workspace_id != ws_id:
        raise HTTPException(404, "Published proposal not found")
    mappings = {r["repository_id"]: r for r in resource.repositories_json}
    repos = []
    for patch in proposals.list_proposal_repo_patches(db, proposal_id=proposal.id):
        mapping = mappings.get(patch.repository_id)
        if not mapping:
            raise HTTPException(409, "请先配置自己的仓库映射")
        raw, _ = proposals.read_repo_patch_file(db, patch)
        repos.append({**mapping, "repo_slug": patch.repo_slug, "base_branch": patch.base_branch,
                      "base_commit_sha": patch.base_commit_sha, "patch": base64.b64encode(raw).decode(),
                      "sha256": hashlib.sha256(raw).hexdigest()})
    if not repos:
        raise HTTPException(409, "没有可用的已发布补丁")
    operation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"apply:{resource.id}:{proposal.id}"))
    client = call(lambda: ResourceClient(service.profile(resource)))
    return call(lambda: client.operation(operation_id, "apply_patch",
        {"workspace_root": resource.workspace_root, "repositories": repos}, operation_id))
