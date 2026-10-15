"""Stop the old writer, pin every upstream, reset incrementally, publish one new turn."""

import logging
import time
from datetime import datetime
from uuid import uuid4

from app.core.offload import run_file_job
from app.domains.ai.models.ai_job import SddAiJob
from app.domains.ai.services.jobs import publishing
from app.domains.ai.services.jobs.store import serialize_job
from app.domains.local_resource import service as resources
from app.domains.local_resource.client import ResourceClient
from app.domains.task.models.session_turn import TaskSessionOperation, TaskSessionOperationStatus
from app.domains.task.models.task import SddTask
from app.domains.task.models.task_repository import SddTaskRepository
from app.domains.task.services import task_session_control_service as control
from app.domains.task.services import task_session_service as turns
from app.domains.task.services.task_attempt_recovery_service import recover_task_attempts
from app.domains.workspace_collaboration.models import CollaborationState

from . import state, worktree

PROTECTED = [".sdd/assets", ".sdd/spec", ".agents/skills", ".claude/skills", ".dsh/skills"]
logger = logging.getLogger(__name__)


def _load(db, ws_id, task_id, operation_id):
    task = db.query(SddTask).filter_by(id=task_id, workspace_id=ws_id).first()
    if not task:
        raise control.TaskSessionControlError("Task not found", status_code=404)
    operation = state.current(task)
    receipt = (task.task_meta_json or {}).get("initialization_receipts", {}).get(operation_id)
    if receipt:
        return {**receipt, "id": operation_id, "state": "COMPLETED"}
    if operation and operation["state"] != "COMPLETED":
        if operation_id and operation_id != operation["id"]:
            raise state.InitializationError("已有未完成的初始化，请刷新并继续原操作。")
        return operation
    return operation if operation.get("id") == operation_id else None


def _begin(db, ws_id, task_id, actor_id, operation_id, request):
    task = db.query(SddTask).filter_by(id=task_id, workspace_id=ws_id).with_for_update().one()
    control._ensure_task_not_baselined(task)
    if control._initialize_has_active_jobs_sync(db, task_id=task_id):
        raise state.InitializationError("旧任务执行尚未清理完成，请稍后重试初始化。")
    if (
        db.query(TaskSessionOperation.id)
        .filter_by(task_id=task_id, status=TaskSessionOperationStatus.REVERTING)
        .first()
    ):
        raise state.InitializationError("请先完成尚未结束的会话恢复，再初始化。")
    rows = db.query(SddTaskRepository).filter_by(task_id=task_id).order_by(SddTaskRepository.id).all()
    if any(str(getattr(row.state, "value", row.state)) != "READY" for row in rows):
        raise state.InitializationError("请先完成任务仓库准备。")
    if any(row.rel_path == "." for row in rows):
        raise state.InitializationError("旧版任务根目录仓库不支持重置，请使用独立仓库目录创建任务。")
    protected = list(PROTECTED)
    if not resources.is_local(task):
        roots = [worktree.repository_root(task.project_path, row.rel_path) for row in rows]
        if any(
            a == b or a.is_relative_to(b) or b.is_relative_to(a)
            for index, a in enumerate(roots)
            for b in roots[index + 1 :]
        ):
            raise state.InitializationError("任务仓库目录重叠。")
    operation = {
        "id": operation_id or str(uuid4()),
        "state": "FETCHING",
        "actor_id": actor_id,
        "request": request,
        "created_at": datetime.utcnow().isoformat(),
        "error": None,
        "generation": int(task.session_generation or 0) + 1,
        "repositories": [
            {
                "id": row.id,
                "repository_id": row.repository_id,
                "name": row.repo_slug,
                "rel_path": row.rel_path,
                "url": row.repo_url,
                "branch": row.branch_name,
            }
            for row in rows
        ],
        "roots": task.project_path,
        "protected": protected,
        "local": resources.is_local(task),
    }
    # Fence every old desktop binding before the first file mutation. A new
    # conversation must never upload its previous local files as fresh input.
    collaboration = db.get(CollaborationState, task.id)
    if collaboration:
        from app.domains.workspace_collaboration.service import _bump

        collaboration.enabled = False
        collaboration.lease_epoch += 1
        collaboration.lease_expires_at = datetime.utcnow()
        collaboration.binding_id = str(uuid4())
        collaboration.snapshot_id = collaboration.input_snapshot_id = collaboration.progress_snapshot_id = None
        collaboration.pending_submission_id = collaboration.input_submission_id = None
        collaboration.sync_phase = "READY"
        _bump(collaboration)
    return state.save(db, task, operation)


def _start_generation(db, ws_id, task_id, operation):
    task = db.query(SddTask).filter_by(id=task_id).with_for_update().one()
    current = state.current(task)
    if current.get("id") != operation["id"]:
        raise state.InitializationError("初始化操作已变化。")
    if current["state"] == "STARTING":
        return control.build_session_prompt(task, operation["request"]["requested_prompt"])
    request = operation["request"]
    return control.apply_initialize_sync(
        db,
        ws_id=ws_id,
        task_id=task_id,
        actor_user_id=operation["actor_id"],
        initialization_id=operation["id"],
        **request,
    )


async def initialize(db, *, ws_id, task_id, actor_user_id, operation_id=None, **request):
    run = control._bind_txn_runner(db, control._session_bind(db))
    await run(lambda session: control._require_local_actor(session, task_id, actor_user_id))
    operation = await run(lambda session: _load(session, ws_id, task_id, operation_id))
    if not operation:
        await _stop_previous(run, ws_id, task_id, actor_user_id)
        operation = await run(lambda session: _begin(session, ws_id, task_id, actor_user_id, operation_id, request))
    if operation["actor_id"] != actor_user_id:
        raise state.InitializationError("请由发起初始化的成员继续该操作。")
    if operation["state"] == "COMPLETED":
        job = await run(lambda session: serialize_job(session.get(SddAiJob, operation["job_id"])))
        await publishing.enqueue_task_chat_job(operation["job_id"])
        return {"msg": "Task initialized", "operation_id": operation["id"], "job": job}
    identifier = operation["id"]

    async def update(**patch):
        return await run(lambda session: state.update(session, task_id, identifier, **patch))

    config = await run_file_job(resources.task_profile, task_id) if operation["local"] else None

    async def action(kind, index=None, repo=None):
        if config:
            payload = {"action": kind, "repository": repo, "protected": operation["protected"]}
            return await run_file_job(
                ResourceClient(config).operation,
                task_id,
                "initialize",
                payload,
                f"init-{identifier}-{kind}-{index if index is not None else 'root'}",
            )
        if kind == "clean":
            return await run_file_job(
                worktree.clean_root, operation["roots"], operation["repositories"], operation["protected"]
            )
        return await run_file_job(getattr(worktree, kind), operation["roots"], repo)

    try:
        if operation["state"] != "STARTING":
            repos = operation["repositories"]
            for index, repo in enumerate(repos):
                if not repo.get("target"):
                    repo.update(await action("fetch", index, repo))
                    operation = await update(repositories=repos, error=None)
            operation = await update(state="RESETTING", error=None)
            for index, repo in enumerate(repos):
                if not repo.get("completed"):
                    repo.update(await action("reset", index, repo))
                    operation = await update(repositories=repos)
            await action("clean")
        result = await run(lambda session: _start_generation(session, ws_id, task_id, operation))
        baseline_started = time.monotonic()
        created = await turns.create_task_chat_turn(
            task_id=task_id,
            actor_user_id=actor_user_id,
            content=result["user_display"],
            prompt_text=result["prompt"],
            fresh_session=True,
            initialization_id=identifier,
            context_json={
                "source": "task_initialize",
                "fresh_session": True,
                "initialize_reason": str(operation["request"].get("reason") or ""),
            },
        )
        await update(baseline_seconds=round(time.monotonic() - baseline_started, 3))
    except Exception as exc:
        # Keep pinned heads and completed repository steps. No rollback or copy
        # of discarded output: retry resumes forward after process/network loss.
        await update(error="初始化中断或失败；请点击初始化继续。")
        logger.exception("Task initialization failed: task=%s operation=%s", task_id, identifier)
        if isinstance(exc, (state.InitializationError, control.TaskSessionControlError)):
            raise
        raise state.InitializationError("初始化中断或失败；请点击初始化继续。") from exc
    await publishing.enqueue_task_chat_job(created.job_id)
    job = await run(lambda session: serialize_job(session.get(SddAiJob, created.job_id)))
    return {"msg": "Task initialized", "operation_id": identifier, "job": job}


async def _stop_previous(run, ws_id, task_id, actor_id):
    prepared = await run(
        lambda db: control.prepare_initialize_sync(db, ws_id=ws_id, task_id=task_id, actor_user_id=actor_id)
    )
    engine = control.get_engine(task_id)
    if engine:
        await engine.stop()
    for job_id in prepared["cancelled_job_ids"]:
        await publishing.publish_job(job_id)
    await recover_task_attempts(task_id, run_txn=run, wait_for_running=True)
