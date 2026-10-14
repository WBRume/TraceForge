"""Re-adapt preserved task output using the shared, durable Agent job lifecycle."""

from uuid import uuid4

from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.task.models.task import SddTask

from . import git, service, storage
from .git import UpdateError

KIND = "TASK_REPOSITORY_ADAPT"


def create(db, task, actor_id, operation_id, version, instruction):
    plan = service.current(task, operation_id, version, states=("READY", "CONFLICTS", "ADAPT_FAILED"))
    service.idle(db, task)
    service.validate_source(db, task, plan)
    # Keep the merge preview intact. Adaptation starts in fresh, independent
    # clones at each pinned remote commit, never in the task's original path.
    attempt_id = str(uuid4())
    root = storage.directory(task, operation_id) / "adaptations" / attempt_id
    root.mkdir(parents=True)
    for repo in plan["repositories"]:
        original = service.stage(task, plan, repo)
        destination = root / repo["rel_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        git.git(original, "clone", "--no-hardlinks", "--no-checkout", "--", str(original), str(destination))
        git.git(destination, "config", "core.longpaths", "true")
        git.git(
            destination,
            "fetch",
            "--no-tags",
            str(original),
            "+refs/traceforge/task:refs/traceforge/task",
            "+refs/traceforge/base:refs/traceforge/base",
        )
        git.git(destination, "checkout", "--detach", repo["target"])
    prompt = (
        "在当前候选工作目录中，将旧任务成果重新适配到各仓库已经检出的远端新版本。\n"
        "只修改当前目录下的仓库；不要访问或修改原任务工作目录，不推送远端，不修改 refs/traceforge/*。\n"
        "每个仓库中 refs/traceforge/task 保存全部旧任务产出，refs/traceforge/base 是共同基线。"
        "先用 git diff refs/traceforge/base refs/traceforge/task 理解原任务意图，"
        "再结合当前新版本重做必要修改，不要直接覆盖新架构。可用 git show 查看旧文件。\n"
        "完成后运行适当验证，保留修改供用户审查，不提交替换原任务；最终说明改动、验证和未解决的问题。\n"
        f"任务：{task.name}\n任务目标：{task.description or ''}\n"
        f"仓库：{', '.join(r['rel_path'] for r in plan['repositories'])}\n"
        f"用户适配要求：{instruction.strip()}"
    )
    job = SddAiJob(
        id=attempt_id,
        workspace_id=task.workspace_id,
        task_id=task.id,
        channel=AiJobChannel.ASSET_THREAD,
        queue_key=f"ASSET_THREAD:repository-update:{operation_id}",
        status=AiJobStatus.PENDING,
        max_attempts=1,
        creator_id=actor_id,
        progress=0,
        message="等待适配任务代码",
        prompt_text=prompt,
        context_json={"job_kind": KIND, "operation_id": operation_id, "candidate_root": str(root)},
    )
    db.add(job)
    db.flush()
    plan["state"], plan["job_id"], plan["error"] = "ADAPTING", job.id, None
    storage.save(db, task, plan)
    return service.view(task, plan)


def prepare_job(db, job_id, token):
    from app.agents.selection import resolve_task_backend
    from app.domains.ai.services.jobs.fencing import attempt_is_current_sync

    job = db.get(SddAiJob, job_id)
    if not job or not attempt_is_current_sync(db, job_id=job_id, run_token=token):
        raise UpdateError("Agent 适配任务已过期。")
    task = db.get(SddTask, job.task_id)
    plan = storage.load(task, job.context_json["operation_id"])
    if plan["state"] != "ADAPTING" or plan["job_id"] != job.id:
        raise UpdateError("代码适配请求已变化。")
    service.idle(db, task, ignore_job_id=job_id)
    service.validate_source(db, task, plan)
    return {
        "prompt": job.prompt_text,
        "project_path": job.context_json["candidate_root"],
        "backend_name": resolve_task_backend(db, task.id),
    }


def settle(db, job_id):
    """Publish candidates only after the shared runner proves execution ended."""
    from pathlib import Path

    from app.domains.ai.services.jobs.constants import FINAL_STATUSES

    job = db.get(SddAiJob, job_id)
    if not job or job.status not in FINAL_STATUSES:
        return
    task = db.query(SddTask).filter_by(id=job.task_id).with_for_update().one()
    plan = storage.load(task, job.context_json["operation_id"])
    if plan["state"] != "ADAPTING" or plan["job_id"] != job.id:
        return
    if job.status == AiJobStatus.SUCCESS:
        try:
            service.validate_source(db, task, plan)
            root = Path(job.context_json["candidate_root"])
            for repo in plan["repositories"]:
                candidate = root / repo["rel_path"]
                if git.git(candidate, "rev-parse", "refs/traceforge/task") != repo["task_commit"]:
                    raise UpdateError("适配过程修改了原成果引用，请重新检查。")
                if git.conflicts(candidate):
                    raise UpdateError("Agent 适配仍有未解决的 Git 冲突。")
                git.git(candidate, "add", "-A", "--", ".")
                repo["mode"], repo["resolved"] = "ADAPTED", []
            plan["candidate_directory"] = str(root)
            plan["agent_summary"] = (job.result_json or {}).get("text", "")
            plan["state"], plan["error"] = "READY", None
        except (ValueError, OSError) as exc:
            plan["state"], plan["error"] = "ADAPT_FAILED", str(exc)
    else:
        plan["state"], plan["error"] = "ADAPT_FAILED", "Agent 适配未完成，原任务代码保持不变；可调整要求后重试。"
    storage.save(db, task, plan)


async def run(job_id):
    from app.agents import current_agent_attempt
    from app.core.offload import run_db_txn
    from app.domains.ai.services.jobs import state
    from app.domains.ai.services.jobs.provider_turn import run_cli_single_turn
    from app.domains.ai.services.jobs.registry import runtime

    attempt = current_agent_attempt()
    token = attempt.run_token if attempt else None
    prepared = await run_db_txn(lambda db: prepare_job(db, job_id, token))
    result = await run_cli_single_turn(
        **prepared, max_attempts=1, run_token=token, should_cancel=lambda: runtime.is_cancel_requested(job_id)
    )
    await state.update_job_state(
        job_id,
        status=AiJobStatus.SUCCESS,
        progress=100,
        message="适配完成，等待审查",
        result_patch={"text": result.get("text", "")},
        finalize=True,
        run_token=token,
        provider_result=result,
    )
    return True
