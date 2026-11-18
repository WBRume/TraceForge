"""Read-only workload projection over durable workspace facts."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, exists, func, or_
from sqlalchemy.orm import Session

from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.task.models.chat import ChatMessage, MessageRole
from app.domains.task.models.session_turn import TaskSessionTurn, TaskSessionTurnStatus
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.workspace.services.workspace_service import list_workspace_members
from app.domains.workspace_asset.models.workspace_asset import HumanReviewStatus, SddHumanReview
from app.domains.workspace_asset.schemas.workload import (
    MemberWorkload,
    WorkloadItem,
    WorkloadLimits,
    WorkspaceWorkload,
)
from app.domains.workspace_asset.services.workload_operators import (
    GRAPH_VERSION,
    execution_state,
    interaction_accumulator,
    register,
    slot_projection,
    verify_graph,
)
from app.domains.workspace_asset.services.workload_requirements import requirement_workload

ACTIVE_STATUSES = {AiJobStatus.RUNNING, AiJobStatus.ORPHANED, AiJobStatus.TERMINATING}
ITEMS_WITH_WAIT_TIME = {"reply", "check", "acceptance", "failure"}
WAIT_LIMIT = timedelta(minutes=30)


@register("ExecutionProject")
def _job_facts(db: Session, workspace_id: str):
    # The active job and the current task generation must agree. Older data may
    # have a nullable job generation, in which case the task's run ID is required.
    matching_generation = or_(
        SddTask.session_generation == SddAiJob.session_generation,
        and_(SddAiJob.session_generation.is_(None), SddTask.status_run_id == SddAiJob.id),
    )
    return (
        db.query(SddAiJob, SddTask)
        .join(SddTask, SddTask.id == SddAiJob.task_id)
        .filter(
            SddAiJob.workspace_id == workspace_id,
            SddTask.workspace_id == workspace_id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
            SddAiJob.visibility == "workspace",
            matching_generation,
            or_(
                SddAiJob.status.in_(ACTIVE_STATUSES | {AiJobStatus.WAITING_HITL}),
                SddTask.status_run_id == SddAiJob.id,
            ),
        )
        .all()
    )


def _phase_starts(db: Session, workspace_id: str, task_ids: set[str], phase_ends: dict[str, datetime]):
    conditions = [
        and_(SddAiJob.task_id == task_id, SddAiJob.started_at > phase_ends[task_id])
        for task_id in task_ids & phase_ends.keys()
    ]
    if not conditions:
        return {}
    return dict(
        db.query(SddAiJob.task_id, func.min(SddAiJob.started_at))
        .join(SddTask, SddTask.id == SddAiJob.task_id)
        .filter(
            SddAiJob.workspace_id == workspace_id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
            SddAiJob.session_generation == SddTask.session_generation,
            SddAiJob.status != AiJobStatus.PENDING,
            or_(*conditions),
        )
        .group_by(SddAiJob.task_id)
        .all()
    )


@register("EventNormalize")
def _followup_events(db: Session, workspace_id: str, task_ids: set[str]):
    result = defaultdict(list)
    if not task_ids:
        return result
    # The initial task launch has a job receipt, but no TaskSessionTurn row.
    # A first persisted human turn following that result is already a follow-up.
    prior_result = exists().where(
        SddAiJob.task_id == TaskSessionTurn.task_id,
        SddAiJob.session_generation == TaskSessionTurn.session_generation,
        SddAiJob.channel == AiJobChannel.TASK_CHAT,
        SddAiJob.status == AiJobStatus.SUCCESS,
        SddAiJob.finished_at <= ChatMessage.created_at,
    )
    rows = (
        db.query(
            TaskSessionTurn.task_id,
            ChatMessage.creator_id,
            ChatMessage.id,
            ChatMessage.created_at,
            ChatMessage.metadata_json,
        )
        .join(SddTask, SddTask.id == TaskSessionTurn.task_id)
        .join(
            ChatMessage,
            ChatMessage.id == TaskSessionTurn.user_message_id,
        )
        .filter(
            TaskSessionTurn.workspace_id == workspace_id,
            TaskSessionTurn.task_id.in_(task_ids),
            TaskSessionTurn.session_generation == SddTask.session_generation,
            TaskSessionTurn.status == TaskSessionTurnStatus.ACTIVE,
            or_(TaskSessionTurn.turn_index > 1, prior_result),
            ChatMessage.role == MessageRole.USER,
        )
        .all()
    )
    for task_id, user_id, message_id, timestamp, metadata in rows:
        metadata = metadata if isinstance(metadata, dict) else {}
        if metadata.get("interaction_id") or metadata.get("confirmation_context"):
            continue
        client_id = metadata.get("client_message_id")
        key = f"{user_id}:{client_id}" if isinstance(client_id, str) and client_id else message_id
        result[task_id].append((key, timestamp))
    return result


@register("HumanItemProject")
def _pending_questions(db: Session, workspace_id: str, facts):
    jobs = {
        job.id: (job, task)
        for job, task in facts
        if job.status in ACTIVE_STATUSES | {AiJobStatus.WAITING_HITL} or task.status == TaskStatus.AWAITING_INPUT
    }
    pending = defaultdict(list)
    if not jobs:
        return pending
    confirmation = ChatMessage.metadata_json["confirmation"]
    outcome = ChatMessage.metadata_json["confirmation_resolution"]
    rows = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.workspace_id == workspace_id,
            ChatMessage.role == MessageRole.ASSISTANT,
            or_(confirmation["job_id"].as_string().in_(jobs), outcome["job_id"].as_string().in_(jobs)),
        )
        .order_by(ChatMessage.created_at, ChatMessage.id)
        .all()
    )
    questions, resolved = {}, set()
    for row in rows:
        metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        reply = metadata.get("confirmation_resolution")
        entry = reply if isinstance(reply, dict) else metadata.get("confirmation")
        if not isinstance(entry, dict) or not isinstance(entry.get("interaction_id"), str):
            continue
        pair = jobs.get(entry.get("job_id"))
        if not pair or (row.task_id, row.session_generation) != (pair[1].id, pair[1].session_generation):
            continue
        if pair[0].attempt_count > 1 and pair[0].started_at and row.created_at < pair[0].started_at:
            continue
        key = (entry["job_id"], entry["interaction_id"])
        if isinstance(reply, dict):
            resolved.add(key)
        elif pair[0].status != AiJobStatus.SUCCESS or entry.get("delivery_mode") == "turn":
            questions.setdefault(key, (row, entry))
    if questions:
        answers = (
            db.query(ChatMessage.task_id, ChatMessage.session_generation, ChatMessage.metadata_json)
            .filter(
                ChatMessage.workspace_id == workspace_id,
                ChatMessage.role == MessageRole.USER,
                ChatMessage.metadata_json["reply_to_message_id"]
                .as_string()
                .in_([row.id for row, _ in questions.values()]),
            )
            .all()
        )
        by_message = {row.id: (key, row) for key, (row, _) in questions.items()}
        for task_id, generation, metadata in answers:
            target = by_message.get(metadata.get("reply_to_message_id"))
            if (
                target
                and (task_id, generation) == (target[1].task_id, target[1].session_generation)
                and metadata.get("interaction_id") == target[0][1]
                and metadata.get("confirmation_context")
            ):
                resolved.add(target[0])
    for (job_id, interaction_id), (question, entry) in questions.items():
        if (job_id, interaction_id) not in resolved:
            job, task = jobs[job_id]
            # The platform routes confirmation notifications to the run initiator.
            recipient = entry.get("recipient_id") or job.creator_id
            pending[job_id].append(
                (
                    recipient,
                    WorkloadItem(
                        id=f"reply:{job_id}:{interaction_id}",
                        kind="reply",
                        title=task.name,
                        task_id=task.id,
                        since=question.created_at,
                    ),
                )
            )
    return pending


@register("MemberAggregate")
def get_workload(db: Session, workspace_id: str, *, can_edit_limits: bool, as_of: datetime) -> WorkspaceWorkload:
    members = {
        row.user_id: MemberWorkload(
            user_id=row.user_id,
            display_name=row.user.display_name or row.user.email,
            role=row.role.value,
            avatar_url=row.user.avatar_url,
            limits=WorkloadLimits(**(row.workload_limits or {})),
        )
        for row in list_workspace_members(db, workspace_id)
    }
    facts = _job_facts(db, workspace_id)
    states = {job.id: execution_state(job, as_of, task.session_revision) for job, task in facts}
    running_ids = {task.id for job, task in facts if states[job.id] == "active"}
    possible_producers = {task.id for job, task in facts if states[job.id] is not None}
    items, phase_ends, unspecified = requirement_workload(db, workspace_id, possible_producers)
    followups = _followup_events(db, workspace_id, running_ids)
    phase_starts = _phase_starts(db, workspace_id, running_ids, phase_ends)
    pending = _pending_questions(db, workspace_id, facts)
    next_evaluate_at = None
    gaps = 0
    for job, task in facts:
        questions = pending.get(job.id, [])
        items.extend(questions)
        state = states[job.id]
        member = members.get(job.creator_id)
        if state and member:
            interaction = interaction_accumulator(followups[task.id], as_of, since=phase_starts.get(task.id))
            member.executions.append(slot_projection(job, task, state, questions, interaction, as_of))
            if interaction.next_evaluate_at:
                next_evaluate_at = min(next_evaluate_at or interaction.next_evaluate_at, interaction.next_evaluate_at)
        if job.status == AiJobStatus.FAILED and task.status != TaskStatus.COMPLETED:
            items.append(
                (
                    job.creator_id,
                    WorkloadItem(
                        id=f"failure:{job.id}",
                        kind="failure",
                        title=task.name,
                        task_id=task.id,
                        since=job.finished_at or job.state_changed_at,
                    ),
                )
            )
        if job.status == AiJobStatus.WAITING_HITL and not questions:
            gaps += 1

    reviews = (
        db.query(SddHumanReview, SddTask.name)
        .join(SddTask, SddTask.id == SddHumanReview.task_id)
        .filter(
            SddHumanReview.workspace_id == workspace_id,
            SddTask.workspace_id == workspace_id,
            SddHumanReview.status.in_([HumanReviewStatus.OPEN, HumanReviewStatus.IN_REVIEW]),
        )
        .all()
    )
    items.extend(
        (
            review.reviewer_id,
            WorkloadItem(
                id=f"review:{review.id}",
                kind="check",
                title=review.title or name,
                task_id=review.task_id,
                since=review.created_at,
                overdue=bool(review.due_date and review.due_date <= as_of),
            ),
        )
        for review, name in reviews
    )

    unassigned = []
    for recipient, item in items:
        if item.kind in ITEMS_WITH_WAIT_TIME and item.since:
            item.overdue = item.overdue or as_of - item.since >= WAIT_LIMIT
        if recipient in members:
            members[recipient].items.append(item)
        else:
            unassigned.append(item)
    for member in members.values():
        member.items.sort(key=lambda item: (not item.overdue, item.since or datetime.max, item.id))
        member.executions.sort(key=lambda item: (item.since or datetime.min, item.id))
    return WorkspaceWorkload(
        graph_version=GRAPH_VERSION,
        as_of=as_of.replace(tzinfo=timezone.utc),
        next_evaluate_at=next_evaluate_at.replace(tzinfo=timezone.utc) if next_evaluate_at else None,
        can_edit_limits=can_edit_limits,
        members=list(members.values()),
        unassigned=unassigned,
        observation_gaps=gaps + len(unspecified & running_ids),
    )


verify_graph()
