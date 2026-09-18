"""问题定位任务路由：辅助文档上传 / 定位结果 / 一键转案例 / 一键总结问题案例。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.distributed_lock import LockAcquireTimeout, lock_task
from app.core.logging import audit_log, bind_task_context, get_logger
from app.dependencies import get_current_user, get_db
from app.domains.ai.models.ai_job import SddAiJob
from app.domains.ai.services.jobs import publishing as ai_job_publishing
from app.domains.ai.services.jobs.store import serialize_job
from app.domains.asset.services import asset_document_service
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.case_center.schemas.case import CaseDraftCreateRequest, CaseResponse
from app.domains.case_center.services import case_service
from app.domains.task.routers.task.deps import (
    TASKS_ROUTE_PREFIX,
    ensure_task_not_baselined,
    get_db_bind,
    get_task_or_404,
    raise_task_lock_conflict,
    run_route_db_txn,
    verify_workspace_access,
    verify_workspace_permission,
)
from app.domains.task.schemas.diagnosis import (
    DiagnosisResultResponse,
    DiagnosisResultUpsertRequest,
)
from app.domains.task.services import (
    chat_submission_service,
    diagnosis_result_service,
)
from app.domains.workspace.services import workspace_service

router = APIRouter(prefix=TASKS_ROUTE_PREFIX, tags=["Tasks"])
logger = get_logger(__name__, category="task_execution")


def _require_diagnosis_task(db: Session, task_id: str, ws_id: str):
    task = get_task_or_404(db, task_id, ws_id)
    if getattr(task, "task_type", None) != "DIAGNOSIS":
        raise HTTPException(status_code=403, detail="Only diagnosis tasks support diagnosis results")
    return task


def _create_diagnosis_doc_sync(
    db: Session,
    *,
    ws_id: str,
    task_id: str,
    creator_id: str,
    file_name,
    file_content: bytes,
) -> dict:
    task = get_task_or_404(db, task_id, ws_id)
    ensure_task_not_baselined(task)
    if getattr(task, "task_type", None) != "DIAGNOSIS":
        raise HTTPException(
            status_code=403,
            detail="Only diagnosis tasks support diagnosis documents",
        )
    asset, version, cli_path = asset_document_service.create_diagnosis_doc_asset_version(
        db,
        task,
        creator_id=creator_id,
        file_name=file_name,
        file_content=file_content,
        change_note="Uploaded diagnosis document",
    )
    db.commit()
    return {
        "status": "success",
        "path": cli_path,
        "filename": file_name,
        "asset_id": asset.id,
        "version_id": version.id,
    }


@router.post("/{task_id}/upload-diagnosis-doc", response_model=dict)
async def upload_task_diagnosis_doc(
    ws_id: str,
    task_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """问题定位任务：上传需求/日志等辅助文档（供 AI 会话与诊断文档抽屉使用）。"""
    db_bind = get_db_bind(db)
    await run_route_db_txn(
        db,
        db_bind,
        lambda session: verify_workspace_permission(
            ws_id,
            current_user.id,
            session,
            WorkspacePermission.UPLOAD_TASK_SPEC,
            "No permission to upload diagnosis documents",
        ),
    )
    db.close()

    with bind_task_context(task_id=task_id, workspace_id=ws_id, user_id=current_user.id):
        try:
            content = await file.read()
            if len(content) > 20 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="Diagnosis document is too large (max 20MB)")
            async with lock_task(task_id):
                return await run_route_db_txn(
                    db, db_bind,
                    lambda session: _create_diagnosis_doc_sync(
                        db=session,
                        ws_id=ws_id,
                        task_id=task_id,
                        creator_id=current_user.id,
                        file_name=file.filename,
                        file_content=content,
                    ),
                )
        except LockAcquireTimeout as exc:
            raise_task_lock_conflict(exc)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception(f"Failed to upload diagnosis doc for task {task_id}: {exc}")
            raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{task_id}/diagnosis-result", response_model=Optional[DiagnosisResultResponse])
def get_diagnosis_result(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_access(ws_id, current_user.id, db)
    task = _require_diagnosis_task(db, task_id, ws_id)
    result = task.diagnosis_result
    if not result:
        # 尚无定位结果（AI 会话收敛后自动反填）：返回 200 + null，避免 404 噪音
        return None
    return diagnosis_result_service.serialize_diagnosis_result(result)


@router.put("/{task_id}/diagnosis-result", response_model=DiagnosisResultResponse)
def upsert_diagnosis_result(
    ws_id: str,
    task_id: str,
    data: DiagnosisResultUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_workspace_permission(
        ws_id,
        current_user.id,
        db,
        WorkspacePermission.MANAGE_TASK_STATUS,
        "No permission to update diagnosis results",
    )
    task = _require_diagnosis_task(db, task_id, ws_id)

    result = diagnosis_result_service.upsert_diagnosis_result_from_user(
        db,
        task=task,
        data=data,
        actor_user_id=current_user.id,
    )
    audit_log(
        action="diagnosis_result_upsert",
        outcome="success",
        resource_type="task_diagnosis_result",
        resource_id=result.id,
        user_id=current_user.id,
        workspace_id=ws_id,
        task_id=task.id,
    )
    return diagnosis_result_service.serialize_diagnosis_result(result)


@router.post("/{task_id}/case-draft", response_model=CaseResponse, status_code=201)
def create_case_draft_from_task(
    ws_id: str,
    task_id: str,
    data: CaseDraftCreateRequest = Body(default=CaseDraftCreateRequest()),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """问题定位任务：确认采纳 → 一键转案例（生成案例草稿，可一步提交专家评审）。"""
    verify_workspace_permission(
        ws_id,
        current_user.id,
        db,
        WorkspacePermission.CREATE_TASK,
        "No permission to create cases",
    )
    task = _require_diagnosis_task(db, task_id, ws_id)
    try:
        case = case_service.create_case_draft_from_task(
            db,
            task=task,
            creator=current_user,
            workspace_id=ws_id,
            data=data,
        )
    except case_service.CaseError as exc:
        raise HTTPException(status_code=int(getattr(exc, "status_code", 400)), detail=str(exc))
    member = workspace_service.get_workspace_member(db, ws_id, current_user.id)
    payload = case_service.serialize_case(case)
    payload["my_can_manage"] = True
    payload["my_can_review"] = bool(member.is_expert) if member else False
    return payload


@router.post("/{task_id}/diagnosis-summary", response_model=dict)
async def trigger_diagnosis_summary(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """问题定位任务：一键总结问题案例。

    创建一次性的「诊断总结」后台 AI 任务：汇总问题定位会话过程，按原定位结果
    JSON 契约生成结构化结果，完成后原位刷新「定位结果」卡片并广播到任务房间。
    同任务已有进行中的总结任务时直接返回既有任务（幂等）。
    """
    db_bind = get_db_bind(db)
    db.close()

    try:
        async with lock_task(task_id):
            prepared = await run_route_db_txn(
                db,
                db_bind,
                lambda session: diagnosis_result_service.prepare_diagnosis_summary_sync(
                    session,
                    ws_id=ws_id,
                    task_id=task_id,
                    actor_user_id=current_user.id,
                ),
            )
    except LockAcquireTimeout as exc:
        raise_task_lock_conflict(exc)
    except diagnosis_result_service.DiagnosisSummaryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except chat_submission_service.SubmissionError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)}) from exc

    if not prepared["created"]:
        return {
            "job_id": prepared["job_id"],
            "status": prepared["status"],
            "task_id": prepared["task_id"],
        }

    audit_log(
        action="diagnosis_summary_triggered",
        outcome="success",
        resource_type="ai_job",
        resource_id=prepared["job_id"],
        user_id=current_user.id,
        workspace_id=ws_id,
        task_id=prepared["task_id"],
    )
    await ai_job_publishing.enqueue_task_chat_job(prepared["job_id"])
    return {
        "job_id": prepared["job_id"],
        "status": prepared["status"],
        "task_id": prepared["task_id"],
    }


@router.get("/{task_id}/diagnosis-summary/{job_id}", response_model=dict)
def get_diagnosis_summary_status(
    ws_id: str,
    task_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """问题定位任务：查询「一键总结问题案例」后台任务状态（供前端轮询收敛）。"""
    verify_workspace_access(ws_id, current_user.id, db)
    job = (
        db.query(SddAiJob)
        .filter(
            SddAiJob.id == job_id,
            SddAiJob.task_id == task_id,
        )
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Diagnosis summary job not found")
    payload = serialize_job(job)
    return {
        "job_id": job.id,
        "task_id": task_id,
        "status": str(payload.get("status") or ""),
        "message": payload.get("message"),
    }
