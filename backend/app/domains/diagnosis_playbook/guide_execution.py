"""Durable SOP continuation using the ordinary chat submission/checkpoint pipeline."""
from uuid import uuid4
from app.core.logging import get_logger

from . import guide_session as sop
from .contracts import PlaybookError

logger = get_logger(__name__, category="task_execution")


def active(db, task):
    from app.domains.ai.models.ai_job import SddAiJob, AiJobChannel, AiJobStatus
    from app.domains.task.models.chat_submission import TaskChatSubmission
    return (db.query(TaskChatSubmission.id).filter_by(active_task_id=task.id).first()
            or db.query(SddAiJob.id).filter(SddAiJob.task_id == task.id,
                SddAiJob.channel == AiJobChannel.TASK_CHAT, SddAiJob.status.in_([
                    AiJobStatus.PENDING, AiJobStatus.RUNNING, AiJobStatus.WAITING_HITL,
                    AiJobStatus.TERMINATING, AiJobStatus.ORPHANED])).first())


def enqueue(db, task, user_id):
    from app.domains.task.services.chat_submission_service import _accept_sync
    from app.domains.task.routers.task.deps import verify_workspace_permission
    from app.domains.auth.models.user import WorkspacePermission
    verify_workspace_permission(task.workspace_id, user_id, db, WorkspacePermission.CREATE_TASK,
                                "No permission to continue diagnosis")
    if str(getattr(task.status, "value", task.status)) not in {"CODING", "TESTING", "REVIEWING"}:
        raise PlaybookError("TASK_NOT_EXECUTABLE", status=409)
    state = sop.snapshot(task)
    if state["completed"] or active(db, task):
        return sop.public(task)
    previous = state.get("next_submission")
    if previous and previous["phase"] == state["active_phase"]:
        from app.domains.task.models.chat_submission import TaskChatSubmission
        row = db.get(TaskChatSubmission, previous["id"])
        if row and row.status in {"PREPARING", "EXECUTING"}:
            return sop.public(task)
    phase = state["active_phase"]
    receipt = _accept_sync(db, task.id, user_id,
        f"sop:{task.session_generation}:{phase}:{state['version']}",
        f"请执行 SOP 的「{sop.TITLES[sop.PHASES.index(phase)]}」阶段，补充本次证据和阶段结果。",
        {"source": "diagnosis_sop", "sop_phase": phase})
    state["next_submission"] = {"id": receipt["id"], "phase": phase}
    return sop.save(task, state)


def pause(task, reason):
    state = sop.snapshot(task)
    state.update(auto_run=False, auto_pause_reason=reason)
    return sop.save(task, state)


def advance_automatic(db, task):
    state = sop.snapshot(task)
    user_id = state["auto_run_by"]
    report = state["reports"].get(state["active_phase"])
    if state["error"] or not report or not report["ready_for_review"] or not report["evidence"] or report["outcome"] == "FAILED":
        return pause(task, "阶段证据不足或报告失败，自动执行已暂停，请补充排查。")
    if state["active_phase"] == "HYPOTHESIZE":
        approved = next((h for h in state["hypotheses"] if h["state"] == "APPROVED" and sop.supported(h)), None)
        if not approved:
            candidate = next((h for h in state["hypotheses"]
                if h["id"] == report.get("root_cause_hypothesis_id") and h["state"] != "EXCLUDED" and sop.supported(h)), None)
            if not candidate:
                return pause(task, "尚无明确且有证据的根因建议，自动执行已暂停，请确认根因。")
            candidate.update(state="APPROVED", decided_by=user_id, decision_mode="AUTOMATIC")
            sop.save(task, state)
    db.flush()
    try:
        result = sop.command(db, task, {"action": "advance", "expected_version": sop.public(task)["version"],
                             "idempotency_key": str(uuid4())}, user_id)
    except PlaybookError as exc:
        return pause(task, f"阶段条件尚未满足，自动执行已暂停：{exc}")
    state = sop.snapshot(task)
    state["confirmations"][report["phase"]]["mode"] = "AUTOMATIC"
    sop.save(task, state)
    if not result["completed"]:
        return enqueue(db, task, user_id)
    return sop.public(task)


def command(db, task, request, user_id):
    db.refresh(task, with_for_update=True)
    state = sop.snapshot(task)
    if request["idempotency_key"] in state["commands"]:
        return sop.command(db, task, request, user_id)
    if request["action"] not in {"enable_auto", "disable_auto"} and active(db, task):
        raise PlaybookError("AGENT_TURN_ACTIVE", status=409)
    result = sop.command(db, task, request, user_id)
    db.flush()
    if request["action"] == "advance" and not result["completed"]:
        return enqueue(db, task, user_id)
    if request["action"] == "enable_auto" and not active(db, task):
        if result["reports"].get(result["active_phase"]) and not result["error"]:
            return advance_automatic(db, task)
        return enqueue(db, task, user_id)
    return result


def on_job_finished(db, job):
    from app.domains.task.models.task import SddTask
    task = db.query(SddTask).filter_by(id=job.task_id).populate_existing().with_for_update().one_or_none()
    if not task or not (task.task_meta_json or {}).get("diagnosis_playbook_guide"):
        return None
    if job.session_generation is not None and job.session_generation != task.session_generation:
        return None
    state = sop.snapshot(task)
    if not state["auto_run"] or state["completed"]:
        return None
    if str(getattr(job.status, "value", job.status)) != "SUCCESS":
        return pause(task, "本轮执行未成功，自动执行已暂停。")
    report = state["reports"].get(state["active_phase"])
    if not report or report["job_id"] != job.id:
        return pause(task, "本轮未获得有效阶段报告，自动执行已暂停。")
    db.flush()  # release the old submission's active_task_id before accepting the next
    try:
        with db.begin_nested():
            return advance_automatic(db, task)
    except Exception:
        # A queue/permission failure must not roll back the completed Agent job.
        logger.exception("Automatic SOP continuation failed: task_id={}, job_id={}", task.id, job.id)
        return pause(task, "下一阶段未能入队，自动执行已暂停，请检查任务状态和权限后重试。")


async def dispatch(task_id, state):
    from app.domains.task.services import chat_submission_service
    submission = state.get("next_submission")
    if submission:
        chat_submission_service.schedule(submission["id"])
    try:
        await sop.publish(task_id, state)
    finally:
        await chat_submission_service.wake_event_publisher()
