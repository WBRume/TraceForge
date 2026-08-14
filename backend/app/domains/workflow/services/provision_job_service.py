"""
Provision job orchestration service.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.distributed_lock import (
    LockAcquireTimeout,
    lock_workspace_repo,
    lock_workspace_repo_creation,
    queue_provision_jobs,
    queue_workspace_task_creation,
)
from app.core.logging import audit_log, bind_log_context, get_logger
from app.database import SessionLocal
from app.domains.workflow.models.provision_job import (
    ProvisionJobStatus,
    ProvisionJobType,
    SddProvisionJob,
)
from app.domains.auth.models.user import User, Workspace
from app.domains.skill.services import skill_service
from app.domains.task.services import task_service
from app.domains.workspace.services import workspace_service
from app.domains.task.services import git_worktree_service

logger = get_logger(__name__, category="application")
task_logger = get_logger(__name__, category="task_execution")


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _utcnow() -> datetime:
    return datetime.utcnow()


def get_job(db: Session, job_id: str) -> Optional[SddProvisionJob]:
    return db.query(SddProvisionJob).filter(SddProvisionJob.id == str(job_id or "").strip()).first()


def serialize_job(job: SddProvisionJob) -> Dict[str, Any]:
    return {
        "job_id": job.id,
        "job_type": _enum_value(job.job_type),
        "status": _enum_value(job.status),
        "progress": int(job.progress or 0),
        "stage": str(job.stage or ""),
        "message": job.message,
        "error_message": job.error_message,
        "result_json": dict(job.result_json or {}) if isinstance(job.result_json, dict) else job.result_json,
        "context_json": dict(job.context_json or {}) if isinstance(job.context_json, dict) else job.context_json,
        "workspace_id": job.workspace_id,
        "task_id": job.task_id,
        "creator_id": job.creator_id,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def serialize_accepted(job: SddProvisionJob) -> Dict[str, Any]:
    payload = serialize_job(job)
    return {
        "job_id": payload["job_id"],
        "job_type": payload["job_type"],
        "status": payload["status"],
        "progress": payload["progress"],
        "stage": payload["stage"],
        "message": payload["message"],
        "workspace_id": payload["workspace_id"],
        "task_id": payload["task_id"],
        "created_at": payload["created_at"],
    }


def create_job(
    db: Session,
    *,
    job_type: ProvisionJobType,
    creator_id: str,
    workspace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    context_json: Optional[Dict[str, Any]] = None,
    stage: str = "QUEUED",
    message: Optional[str] = None,
) -> SddProvisionJob:
    job = SddProvisionJob(
        job_type=job_type,
        status=ProvisionJobStatus.PENDING,
        progress=0,
        stage=str(stage or "QUEUED").strip() or "QUEUED",
        message=message,
        context_json=context_json or {},
        creator_id=str(creator_id or "").strip(),
        workspace_id=(str(workspace_id).strip() if workspace_id else None),
        task_id=(str(task_id).strip() if task_id else None),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def retry_job(
    db: Session,
    *,
    source_job: SddProvisionJob,
    creator_id: str,
    message: Optional[str] = None,
) -> SddProvisionJob:
    context_json = (
        dict(source_job.context_json or {})
        if isinstance(source_job.context_json, dict)
        else {}
    )
    return create_job(
        db,
        job_type=source_job.job_type,
        creator_id=str(creator_id or "").strip(),
        workspace_id=source_job.workspace_id,
        task_id=source_job.task_id,
        context_json=context_json,
        stage="QUEUED",
        message=message or "Provision retry queued",
    )


def _set_job_state(
    db: Session,
    job: SddProvisionJob,
    *,
    status: Optional[ProvisionJobStatus] = None,
    progress: Optional[int] = None,
    stage: Optional[str] = None,
    message: Optional[str] = None,
    error_message: Optional[str] = None,
    result_json: Optional[Dict[str, Any]] = None,
    workspace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
) -> SddProvisionJob:
    if status is not None:
        job.status = status
    if progress is not None:
        job.progress = max(0, min(int(progress), 100))
    if stage is not None:
        job.stage = str(stage or "").strip() or job.stage
    if message is not None:
        job.message = message
    if error_message is not None:
        job.error_message = error_message
    if result_json is not None:
        job.result_json = result_json
    if workspace_id is not None:
        job.workspace_id = workspace_id
    if task_id is not None:
        job.task_id = task_id
    if started_at is not None:
        job.started_at = started_at
    if finished_at is not None:
        job.finished_at = finished_at
    db.commit()
    db.refresh(job)
    return job


def mark_running(job_id: str, *, stage: str, progress: int, message: Optional[str] = None) -> None:
    db = SessionLocal()
    try:
        job = get_job(db, job_id)
        if not job:
            return
        _set_job_state(
            db,
            job,
            status=ProvisionJobStatus.RUNNING,
            stage=stage,
            progress=progress,
            message=message if message is not None else job.message,
            started_at=job.started_at or _utcnow(),
            error_message=None,
        )
    finally:
        db.close()


def mark_progress(job_id: str, *, stage: str, progress: int, message: Optional[str] = None) -> None:
    db = SessionLocal()
    try:
        job = get_job(db, job_id)
        if not job:
            return
        _set_job_state(
            db,
            job,
            stage=stage,
            progress=progress,
            message=message if message is not None else job.message,
        )
    finally:
        db.close()


def mark_success(
    job_id: str,
    *,
    stage: str,
    message: Optional[str],
    result_json: Optional[Dict[str, Any]] = None,
    workspace_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> None:
    db = SessionLocal()
    try:
        job = get_job(db, job_id)
        if not job:
            return
        _set_job_state(
            db,
            job,
            status=ProvisionJobStatus.SUCCESS,
            stage=stage,
            progress=100,
            message=message,
            result_json=result_json or {},
            workspace_id=workspace_id if workspace_id is not None else job.workspace_id,
            task_id=task_id if task_id is not None else job.task_id,
            finished_at=_utcnow(),
        )
    finally:
        db.close()


def mark_failed(
    job_id: str,
    *,
    stage: str,
    message: Optional[str],
    error_message: str,
) -> None:
    db = SessionLocal()
    try:
        job = get_job(db, job_id)
        if not job:
            return
        _set_job_state(
            db,
            job,
            status=ProvisionJobStatus.FAILED,
            stage=stage,
            progress=max(int(job.progress or 0), 1),
            message=message,
            error_message=str(error_message or "Provisioning failed"),
            finished_at=_utcnow(),
        )
    finally:
        db.close()


def _get_job_payload(job_id: str) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        job = get_job(db, job_id)
        if not job:
            return None
        return serialize_job(job)
    finally:
        db.close()


def _create_workspace_sync(*, job_id: str, creator_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == str(creator_id or "").strip()).first()
        if not user:
            raise ValueError("Workspace creator not found")

        workspace = workspace_service.create_workspace(
            db,
            user,
            str(context.get("name") or "").strip(),
            context.get("description"),
            project_path=context.get("project_path"),
            git_repo_url=context.get("git_repo_url"),
            project_id=context.get("project_id"),
            repositories=context.get("repositories") if isinstance(context.get("repositories"), list) else None,
        )
        repositories = [workspace_service.serialize_workspace_repository(row) for row in workspace.repositories]
        return {
            "workspace_id": workspace.id,
            "workspace_name": workspace.name,
            "project_path": workspace.project_path,
            "project_id": workspace.project_id,
            "repositories": repositories,
        }
    finally:
        db.close()


def _materialize_workspace_repos_sync(*, workspace_id: str) -> Dict[str, Any]:
    import os as _os

    from app.domains.workspace.models.workspace_repository import (
        SddWorkspaceRepository,
        WorkspaceRepositoryState,
    )

    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if workspace and workspace.project_path:
            _os.makedirs(workspace.project_path, exist_ok=True)
        rows = (
            db.query(SddWorkspaceRepository)
            .filter(SddWorkspaceRepository.workspace_id == workspace_id)
            .order_by(SddWorkspaceRepository.created_at.asc())
            .all()
        )
        results: Dict[str, Any] = {"repositories": []}
        for row in rows:
            try:
                git_worktree_service.ensure_base_repository(row.repo_url, row.base_dir or "")
                head = git_worktree_service.read_repo_head_sha(row.base_dir or "")
                row.state = WorkspaceRepositoryState.READY
                row.base_commit_sha = head
                row.error_message = None
                results["repositories"].append(
                    {"repository_id": row.repository_id, "repo_name": row.repo_name, "state": "READY"}
                )
            except Exception as exc:
                row.state = WorkspaceRepositoryState.FAILED
                row.error_message = str(exc)
                results["repositories"].append(
                    {"repository_id": row.repository_id, "repo_name": row.repo_name, "state": "FAILED", "error": str(exc)}
                )
        db.commit()
        return results
    finally:
        db.close()


def _prepare_task_sync(*, workspace_id: str, task_id: str) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        task = task_service.prepare_task_resources_for_provision(
            db,
            workspace_id=workspace_id,
            task_id=task_id,
        )
        return {
            "workspace_id": task.workspace_id,
            "task_id": task.id,
            "task_name": task.name,
        }
    finally:
        db.close()


def _import_skill_sync(*, creator_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == str(creator_id or "").strip()).first()
        if not user:
            raise ValueError("Skill import user not found")

        skill = skill_service.import_skill_from_github(
            db,
            user,
            context_workspace_id=str(context.get("context_workspace_id") or "").strip(),
            repo_url=str(context.get("repo_url") or "").strip(),
            skill_name=str(context.get("skill_name") or "").strip(),
            description=context.get("description"),
            dimension_value=str(context.get("dimension") or "WORKSPACE").strip() or "WORKSPACE",
            workspace_id=context.get("workspace_id"),
            follow_official_source=bool(context.get("follow_official_source")),
        )
        dimension = skill.dimension.value if hasattr(skill.dimension, "value") else str(skill.dimension)
        return {
            "skill_id": skill.id,
            "skill_name": skill.name,
            "dimension": dimension,
            "workspace_id": skill.workspace_id,
            "source_repo_url": skill.source_repo_url,
            "source_subdir": skill.source_subdir,
            "source_commit_sha": skill.source_commit_sha,
        }
    finally:
        db.close()


def _mark_task_prepare_failed(*, workspace_id: str, task_id: str, error_message: str) -> None:
    db = SessionLocal()
    try:
        task_service.mark_task_prepare_failed(
            db,
            workspace_id=workspace_id,
            task_id=task_id,
            error_message=error_message,
        )
    finally:
        db.close()


def _workspace_uses_git(workspace_id: str) -> bool:
    from app.domains.workspace.models.workspace_repository import SddWorkspaceRepository

    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.id == str(workspace_id or "").strip()).first()
        if not workspace:
            return False
        if git_worktree_service.should_use_git_worktree(workspace.project_path, workspace.git_repo_url):
            return True
        repo_count = (
            db.query(SddWorkspaceRepository)
            .filter(SddWorkspaceRepository.workspace_id == workspace.id)
            .count()
        )
        return repo_count > 0
    finally:
        db.close()


async def run_create_workspace_job(job_id: str) -> None:
    payload = _get_job_payload(job_id)
    if not payload:
        return

    context = payload.get("context_json") if isinstance(payload.get("context_json"), dict) else {}
    creator_id = str(payload.get("creator_id") or "").strip()
    project_path = str(context.get("project_path") or "").strip()
    git_repo_url = str(context.get("git_repo_url") or "").strip()
    project_id = str(context.get("project_id") or "").strip()
    use_multi_repo = bool(project_id)
    use_repo_lock = bool(project_path and git_repo_url)
    creation_lock_url = git_repo_url if use_repo_lock else (f"project:{project_id}" if use_multi_repo else "")

    with bind_log_context(job_id=job_id, user_id=creator_id):
        try:
            mark_progress(
                job_id,
                stage="WAITING_EXECUTION_QUEUE",
                progress=1,
                message="Waiting for provision execution slot",
            )
            async with queue_provision_jobs(queue_tag="create_workspace"):
                mark_running(job_id, stage="VALIDATING_INPUT", progress=5, message="Validating workspace request")
                if use_repo_lock or use_multi_repo:
                    mark_progress(job_id, stage="WAITING_REPO_LOCK", progress=15, message="Waiting for repository lock")
                    try:
                        async with lock_workspace_repo_creation(
                            project_path=project_path,
                            git_repo_url=creation_lock_url,
                        ):
                            if use_multi_repo:
                                mark_progress(job_id, stage="CREATING_WORKSPACE", progress=25, message="Creating workspace")
                                result = await asyncio.to_thread(
                                    _create_workspace_sync,
                                    job_id=job_id,
                                    creator_id=creator_id,
                                    context=context,
                                )
                                mark_progress(
                                    job_id,
                                    stage="MATERIALIZE_REPOS",
                                    progress=40,
                                    message="Materializing workspace repositories",
                                )
                                repo_result = await asyncio.to_thread(
                                    _materialize_workspace_repos_sync,
                                    workspace_id=str(result.get("workspace_id") or "").strip(),
                                )
                                result["repository_materialization"] = repo_result
                            else:
                                mark_progress(job_id, stage="CLONING_REPOSITORY", progress=30, message="Cloning workspace repository")
                                result = await asyncio.to_thread(
                                    _create_workspace_sync,
                                    job_id=job_id,
                                    creator_id=creator_id,
                                    context=context,
                                )
                    except LockAcquireTimeout as exc:
                        raise ValueError("Workspace repository is busy. Please retry later.") from exc
                else:
                    mark_progress(job_id, stage="CREATING_WORKSPACE", progress=40, message="Creating workspace")
                    result = await asyncio.to_thread(
                        _create_workspace_sync,
                        job_id=job_id,
                        creator_id=creator_id,
                        context=context,
                    )

            workspace_id = str(result.get("workspace_id") or "").strip()
            mark_success(
                job_id,
                stage="COMPLETED",
                message="Workspace is ready",
                result_json=result,
                workspace_id=workspace_id or None,
            )
            audit_log(
                action="create_workspace",
                outcome="success",
                resource_type="workspace",
                resource_id=workspace_id or None,
                user_id=creator_id,
                job_id=job_id,
            )
        except LockAcquireTimeout as exc:
            err = "Provision queue is busy. Please retry later."
            mark_failed(
                job_id,
                stage="FAILED",
                message="Workspace provisioning failed",
                error_message=err,
            )
            logger.warning(
                "Workspace provision lock timeout: job_id={}, resource_type={}, lock_key={}",
                job_id,
                exc.resource_type,
                exc.lock_key,
            )
            audit_log(
                action="create_workspace",
                outcome="failed",
                resource_type="workspace",
                user_id=creator_id,
                job_id=job_id,
                reason=err,
            )
        except Exception as exc:
            logger.exception("Workspace provision job failed: job_id={}, error={}", job_id, str(exc))
            mark_failed(
                job_id,
                stage="FAILED",
                message="Workspace provisioning failed",
                error_message=str(exc),
            )
            audit_log(
                action="create_workspace",
                outcome="failed",
                resource_type="workspace",
                user_id=creator_id,
                job_id=job_id,
                reason=str(exc),
            )


async def run_create_task_job(job_id: str) -> None:
    payload = _get_job_payload(job_id)
    if not payload:
        return

    creator_id = str(payload.get("creator_id") or "").strip()
    workspace_id = str(payload.get("workspace_id") or "").strip()
    task_id = str(payload.get("task_id") or "").strip()
    use_repo_lock = _workspace_uses_git(workspace_id)

    with bind_log_context(job_id=job_id, workspace_id=workspace_id, task_id=task_id, user_id=creator_id):
        try:
            mark_progress(
                job_id,
                stage="WAITING_EXECUTION_QUEUE",
                progress=1,
                message="Waiting for provision execution slot",
            )
            async with queue_provision_jobs(queue_tag="create_task"):
                mark_running(job_id, stage="PREPARING_TASK", progress=5, message="Task request accepted")
                if use_repo_lock:
                    mark_progress(job_id, stage="WAITING_TASK_QUEUE", progress=10, message="Waiting in create task queue")
                    async with queue_workspace_task_creation(workspace_id):
                        mark_progress(job_id, stage="WAITING_REPO_LOCK", progress=20, message="Waiting for repository lock")
                        async with lock_workspace_repo(workspace_id):
                            mark_progress(
                                job_id,
                                stage="PREPARING_WORKTREE",
                                progress=40,
                                message="Preparing repository worktree",
                            )
                            result = await asyncio.to_thread(
                                _prepare_task_sync,
                                workspace_id=workspace_id,
                                task_id=task_id,
                            )
                else:
                    mark_progress(
                        job_id,
                        stage="PREPARING_LOCAL_WORKSPACE",
                        progress=35,
                        message="Preparing local workspace",
                    )
                    result = await asyncio.to_thread(
                        _prepare_task_sync,
                        workspace_id=workspace_id,
                        task_id=task_id,
                    )

            mark_success(
                job_id,
                stage="COMPLETED",
                message="Task is ready",
                result_json=result,
                workspace_id=workspace_id,
                task_id=task_id,
            )
            audit_log(
                action="create_task",
                outcome="success",
                resource_type="task",
                resource_id=task_id,
                user_id=creator_id,
                workspace_id=workspace_id,
                job_id=job_id,
            )
        except LockAcquireTimeout as exc:
            if str(exc.resource_type or "").strip() == "provision_queue":
                err = "Provision queue is busy. Please retry later."
            else:
                err = "Workspace repository is busy. Please retry later."
            mark_failed(
                job_id,
                stage="FAILED",
                message="Task provisioning failed",
                error_message=err,
            )
            _mark_task_prepare_failed(workspace_id=workspace_id, task_id=task_id, error_message=err)
            task_logger.warning(
                "Task provision lock timeout: job_id={}, workspace_id={}, task_id={}, lock_key={}",
                job_id,
                workspace_id,
                task_id,
                exc.lock_key,
            )
        except Exception as exc:
            mark_failed(
                job_id,
                stage="FAILED",
                message="Task provisioning failed",
                error_message=str(exc),
            )
            _mark_task_prepare_failed(workspace_id=workspace_id, task_id=task_id, error_message=str(exc))
            task_logger.exception(
                "Task provision job failed: job_id={}, workspace_id={}, task_id={}, error={}",
                job_id,
                workspace_id,
                task_id,
                str(exc),
            )


def _sync_repo_refs_sync(*, repository_id: str) -> Dict[str, Any]:
    from app.domains.management.services import repository_service

    db = SessionLocal()
    try:
        repository = repository_service.get_repository(db, repository_id)
        if not repository:
            raise ValueError("Repository not found")
        return repository_service.sync_repository_refs(db, repository)
    finally:
        db.close()


async def run_sync_repo_refs_job(job_id: str) -> None:
    payload = _get_job_payload(job_id)
    if not payload:
        return

    context = payload.get("context_json") if isinstance(payload.get("context_json"), dict) else {}
    creator_id = str(payload.get("creator_id") or "").strip()
    repository_id = str(context.get("repository_id") or "").strip()

    with bind_log_context(job_id=job_id, user_id=creator_id):
        try:
            mark_progress(
                job_id,
                stage="WAITING_EXECUTION_QUEUE",
                progress=1,
                message="Waiting for repo ref sync execution slot",
            )
            async with queue_provision_jobs(queue_tag="sync_repo_refs"):
                mark_running(job_id, stage="SYNCING_REFS", progress=20, message="Fetching branches and tags")
                result = await asyncio.to_thread(
                    _sync_repo_refs_sync,
                    repository_id=repository_id,
                )

            mark_success(
                job_id,
                stage="COMPLETED",
                message="Repository refs synced",
                result_json=result,
            )
            audit_log(
                action="sync_repository_refs",
                outcome="success",
                resource_type="repository",
                resource_id=repository_id,
                user_id=creator_id,
                job_id=job_id,
            )
        except LockAcquireTimeout as exc:
            err = "Provision queue is busy. Please retry later."
            mark_failed(job_id, stage="FAILED", message="Repository ref sync failed", error_message=err)
            logger.warning("Repo ref sync queue timeout: job_id={}, key={}", job_id, exc.lock_key)
        except Exception as exc:
            logger.exception("Repository ref sync job failed: job_id={}, error={}", job_id, str(exc))
            mark_failed(
                job_id,
                stage="FAILED",
                message="Repository ref sync failed",
                error_message=str(exc),
            )


async def run_import_skill_job(job_id: str) -> None:
    payload = _get_job_payload(job_id)
    if not payload:
        return

    context = payload.get("context_json") if isinstance(payload.get("context_json"), dict) else {}
    creator_id = str(payload.get("creator_id") or "").strip()
    workspace_id = str(payload.get("workspace_id") or "").strip()
    repo_url = str(context.get("repo_url") or "").strip()
    skill_name = str(context.get("skill_name") or "").strip()

    with bind_log_context(job_id=job_id, workspace_id=workspace_id or None, user_id=creator_id):
        try:
            mark_progress(
                job_id,
                stage="WAITING_EXECUTION_QUEUE",
                progress=1,
                message="Waiting for skill import execution slot",
            )
            async with queue_provision_jobs(queue_tag="import_skill"):
                mark_running(
                    job_id,
                    stage="VALIDATING_INPUT",
                    progress=5,
                    message="Validating GitHub skill import request",
                )
                mark_progress(
                    job_id,
                    stage="CLONING_REPOSITORY",
                    progress=20,
                    message=f"Importing {skill_name or 'skill'} from GitHub",
                )
                result = await asyncio.to_thread(
                    _import_skill_sync,
                    creator_id=creator_id,
                    context=context,
                )

            result_workspace_id = str(result.get("workspace_id") or "").strip()
            skill_id = str(result.get("skill_id") or "").strip()
            mark_success(
                job_id,
                stage="COMPLETED",
                message="Skill import completed",
                result_json=result,
                workspace_id=result_workspace_id or None,
            )
            audit_log(
                action="import_skill",
                outcome="success",
                resource_type="skill",
                resource_id=skill_id or None,
                user_id=creator_id,
                workspace_id=result_workspace_id or None,
                repo_url=repo_url,
                skill_name=result.get("skill_name") or skill_name,
                source="github",
                job_id=job_id,
            )
        except LockAcquireTimeout as exc:
            err = "Provision queue is busy. Please retry later."
            mark_failed(
                job_id,
                stage="FAILED",
                message="Skill import failed",
                error_message=err,
            )
            logger.warning(
                "Skill import provision lock timeout: job_id={}, resource_type={}, lock_key={}",
                job_id,
                exc.resource_type,
                exc.lock_key,
            )
            audit_log(
                action="import_skill",
                outcome="failed",
                resource_type="skill",
                user_id=creator_id,
                workspace_id=workspace_id or None,
                repo_url=repo_url,
                skill_name=skill_name,
                reason=err,
                source="github",
                job_id=job_id,
            )
        except Exception as exc:
            logger.exception("Skill import provision job failed: job_id={}, error={}", job_id, str(exc))
            mark_failed(
                job_id,
                stage="FAILED",
                message="Skill import failed",
                error_message=str(exc),
            )
            audit_log(
                action="import_skill",
                outcome="failed",
                resource_type="skill",
                user_id=creator_id,
                workspace_id=workspace_id or None,
                repo_url=repo_url,
                skill_name=skill_name,
                reason=str(exc),
                source="github",
                job_id=job_id,
            )
