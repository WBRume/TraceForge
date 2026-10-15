"""Re-adapt preserved task output using the shared, durable Agent job lifecycle."""

from uuid import uuid4

from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services.jobs.constants import queue_key_for_task
from app.domains.task.models.task import SddTask

from . import git, service, storage
from .git import UpdateError

KIND = "TASK_REPOSITORY_ADAPT"


def create(db, task, actor_id, operation_id, version, instruction, *, auto_apply=False):
    plan = service.current(task, operation_id, version, states=("READY", "CONFLICTS", "ADAPT_FAILED"))
    service.idle(db, task)
    service.validate_source(db, task, plan)
    if not task.session_id:
        raise UpdateError("任务没有可继续的 Agent 会话，请先恢复任务会话后再适配。", "SESSION_REQUIRED")
    if str(getattr(task.status, "value", task.status)) in {"INTERRUPTED", "FAILED"}:
        raise UpdateError("请先恢复任务会话后再适配。", "SESSION_REQUIRED")
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
        "继续当前任务会话，沿用此前的需求、讨论和决策，将任务成果适配到远端新版本。\n"
        f"本轮候选工作目录：{root.resolve()}\n"
        "本轮所有文件读取、修改和验证均使用上述候选目录的绝对路径，执行命令时显式切换到候选目录。\n"
        "会话的原工作目录仅用于保留上下文；不要修改原任务代码，不推送远端，不修改 refs/traceforge/*。\n"
        "每个仓库中 refs/traceforge/task 保存全部旧任务产出，refs/traceforge/base 是共同基线。"
        "结合会话历史和 git diff refs/traceforge/base refs/traceforge/task 理解原任务意图，"
        "再结合当前新版本重做必要修改，不要直接覆盖新架构。可用 git show 查看旧文件。\n"
        "完成后运行适当验证，解决全部冲突；最终说明改动、验证和未解决的问题。\n"
        + (
            "用户已确认适配成功后自动应用。完成候选代码后，系统会保留恢复快照并自动应用到任务仓库，"
            "无需再次请用户确认；不要自行替换原任务代码。\n"
            if auto_apply
            else "保留候选修改供用户审查，不提交替换原任务。\n"
        )
        + f"任务：{task.name}\n任务目标：{task.description or ''}\n"
        f"仓库：{', '.join(r['rel_path'] for r in plan['repositories'])}\n"
        f"用户适配要求：{instruction.strip()}"
    )
    from app.domains.task.models.task_event_outbox import TaskEventOutbox
    from app.domains.task.services import reading_capture_service, task_session_service

    task.session_revision = int(task.session_revision or 0) + 1
    plan["session_revision"] = task.session_revision
    message = task_session_service._new_chat_message(
        db,
        task_id=task.id,
        workspace_id=task.workspace_id,
        actor_user_id=actor_id,
        content="请结合当前会话的需求和讨论，处理远端更新并适配任务代码。"
        + ("解决冲突并验证后，自动应用到任务代码，无需再次确认。" if auto_apply else "")
        + f"\n\n{instruction.strip()}",
        metadata_json={"job_kind": KIND, "operation_id": operation_id, "session_revision": task.session_revision},
        session_generation=task.session_generation,
    )
    reading_capture_service.record_message_change(db, task_id=task.id, message=message)
    db.add(
        TaskEventOutbox(
            event_id=str(uuid4()),
            task_id=task.id,
            payload_json={"event_type": "chat_message", **task_session_service._chat_message_event_dto(db, message)},
        )
    )
    job = SddAiJob(
        id=attempt_id,
        workspace_id=task.workspace_id,
        task_id=task.id,
        channel=AiJobChannel.TASK_CHAT,
        queue_key=queue_key_for_task(task.id),
        session_id=task.session_id,
        session_generation=task.session_generation,
        session_revision=task.session_revision,
        status=AiJobStatus.PENDING,
        max_attempts=1,
        creator_id=actor_id,
        progress=0,
        message="等待适配任务代码",
        prompt_text=prompt,
        context_json={
            "job_kind": KIND,
            "operation_id": operation_id,
            "candidate_root": str(root.resolve()),
            "chat_message_id": message.id,
            "auto_apply": auto_apply,
        },
    )
    db.add(job)
    db.flush()
    plan["state"], plan["job_id"], plan["error"] = "ADAPTING", job.id, None
    plan["auto_apply"] = auto_apply
    storage.save(db, task, plan)
    return service.view(task, plan)


def prepare_job(db, job_id, token):
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
    if not job.session_id or job.session_id != task.session_id:
        raise UpdateError("原任务会话已变化，无法继续本次适配。", "SOURCE_CHANGED")
    from pathlib import Path

    root = Path(job.context_json["candidate_root"]).resolve()
    expected = (storage.directory(task, plan["id"]) / "adaptations" / job.id).resolve()
    if root != expected or not root.is_dir():
        raise UpdateError("候选代码目录不存在或与适配请求不一致。")
    return str(root)


def settle(db, job_id):
    """Settle under the task lock, applying only after the runner has ended."""
    from pathlib import Path

    from app.domains.ai.services.jobs.constants import FINAL_STATUSES

    job = db.get(SddAiJob, job_id)
    if not job or job.status not in {*FINAL_STATUSES, AiJobStatus.INTERRUPTED}:
        return
    if job.status == AiJobStatus.INTERRUPTED:
        from app.domains.ai.services.jobs.store import row_has_leaked_interrupted_ownership

        if row_has_leaked_interrupted_ownership(job):
            return
    task = db.query(SddTask).filter_by(id=job.task_id).with_for_update().one()
    plan = storage.load(task, job.context_json["operation_id"])
    if plan["state"] != "ADAPTING" or plan["job_id"] != job.id:
        return
    if job.status == AiJobStatus.SUCCESS:
        try:
            service.validate_source(db, task, plan)
            if not job.session_id or job.session_id != task.session_id:
                raise UpdateError("原任务会话已变化，无法应用本次适配。", "SOURCE_CHANGED")
            root = Path(job.context_json["candidate_root"])
            expected = (storage.directory(task, plan["id"]) / "adaptations" / job.id).resolve()
            if root.resolve() != expected:
                raise UpdateError("候选代码目录与适配请求不一致。")
            for repo in plan["repositories"]:
                candidate = root / repo["rel_path"]
                if git.git(candidate, "rev-parse", "refs/traceforge/task") != repo["task_commit"]:
                    raise UpdateError("适配过程修改了原成果引用，请重新检查。")
                if git.conflicts(candidate):
                    raise UpdateError("Agent 适配仍有未解决的 Git 冲突。")
                git.git(candidate, "add", "-A", "--", ".")
                # Check against the pinned remote, including edits the Agent
                # already committed; ignore whitespace-only lint warnings.
                checked = git.command(
                    candidate,
                    "-c",
                    "core.whitespace=-blank-at-eol,-blank-at-eof,-space-before-tab",
                    "diff",
                    "--cached",
                    "--check",
                    repo["target"],
                    allowed=(0, 2),
                )
                if checked.returncode:
                    raise UpdateError("Agent 适配结果仍有冲突标记，未应用到任务代码。", "CONFLICTS_REMAIN")
                repo["mode"], repo["resolved"] = "ADAPTED", []
            plan["candidate_directory"] = str(root)
            plan["agent_summary"] = (job.result_json or {}).get(
                "result_preview", (job.result_json or {}).get("text", "")
            )
            plan["error"] = None
            if job.context_json.get("auto_apply"):
                # Never publish READY between execution and application: other
                # writers must remain fenced until the whole operation ends.
                service.apply_plan(db, task, job.creator_id, plan)
                return
            plan["state"] = "READY"
        except (ValueError, OSError) as exc:
            saved = storage.load(task, plan["id"])
            if saved["state"] in {"APPLYING", "RECOVERY_REQUIRED", "APPLIED"}:
                return
            plan["state"], plan["error"] = "ADAPT_FAILED", str(exc)
    else:
        plan["state"], plan["error"] = "ADAPT_FAILED", "Agent 适配未完成，原任务代码保持不变；可调整要求后重试。"
    storage.save(db, task, plan)
