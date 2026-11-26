from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.auth.models.user import User, Workspace, WorkspaceMember, WorkspaceRole
from app.domains.task.models.chat import ChatMessage, MessageRole
from app.domains.task.models.session_turn import TaskSessionTurn, TaskSessionTurnStatus
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.workspace_asset.models.workspace_asset import (
    HumanReviewStatus,
    RequirementAuditAction,
    RequirementStatus,
    SddHumanReview,
    SddRequirement,
    SddRequirementAuditLog,
    SddTaskRequirement,
    TaskRequirementRelationType,
)
from app.domains.workspace_asset.routers import workspace_asset_workload as routes
from app.domains.workspace_asset.services.workload import get_workload
from app.domains.workspace_asset.services.workload_overview import get_workspace_member_workload

NOW = datetime(2026, 11, 18, 12)
WORKSPACE = "workload"
EXPERT = "expert"
DEVELOPER = "developer"
REVIEWER = "reviewer"
ACCEPTOR = "acceptor"


def at(seconds=0):
    return NOW + timedelta(seconds=seconds)


@dataclass
class Scenario:
    db: Session

    def task(self, task_id, **fields):
        task = SddTask(
            id=task_id,
            **{
                "workspace_id": WORKSPACE,
                "creator_id": EXPERT,
                "name": task_id,
                "status": TaskStatus.RUNNING,
                "session_generation": 2,
                "session_revision": 3,
                "created_at": at(-20000),
                "updated_at": at(-60),
                **fields,
            },
        )
        self.db.add(task)
        self.db.flush()
        return task

    def job(self, task, job_id, *, started=-20, current=True, **fields):
        job = SddAiJob(
            id=job_id,
            task_id=task.id,
            **{
                "creator_id": task.creator_id,
                "workspace_id": task.workspace_id,
                "channel": AiJobChannel.TASK_CHAT,
                "queue_key": f"task:{task.id}",
                "status": AiJobStatus.RUNNING,
                "agent_backend": "opencode",
                "session_generation": task.session_generation,
                "session_revision": task.session_revision,
                "started_at": at(started) if started is not None else None,
                "lease_expires_at": at(3600),
                "created_at": at(-20000),
                "state_changed_at": at(-60),
                **fields,
            },
        )
        self.db.add(job)
        if current:
            task.status_run_id = job.id
        self.db.flush()
        return job

    def requirement(self, requirement_id, *tasks, **fields):
        item = SddRequirement(
            id=requirement_id,
            title=requirement_id,
            **{
                "workspace_id": WORKSPACE,
                "owner_id": EXPERT,
                "reviewer_id": REVIEWER,
                "acceptor_id": ACCEPTOR,
                "status": RequirementStatus.READY,
                "result_check_required": True,
                "created_at": at(-20000),
                "updated_at": at(-20000),
                **fields,
            },
        )
        self.db.add(item)
        self.db.flush()
        self.db.add_all(
            SddTaskRequirement(
                workspace_id=item.workspace_id,
                requirement_id=item.id,
                task_id=task.id,
                relation_type=TaskRequirementRelationType.COVERS,
            )
            for task in tasks
        )
        return item

    def message(self, task, when, role, metadata=None, **fields):
        message = ChatMessage(
            task_id=task.id,
            creator_id=task.creator_id,
            role=role,
            content="workload scenario event",
            metadata_json=metadata,
            created_at=at(when),
            **{"workspace_id": task.workspace_id, "session_generation": task.session_generation, **fields},
        )
        self.db.add(message)
        self.db.flush()
        return message

    def followup(self, task, index, when, *, client_id=None, role=MessageRole.USER, metadata=None, **fields):
        message = self.message(
            task, when, role, {"client_message_id": client_id or f"{task.id}:{index}", **(metadata or {})}
        )
        self.db.add(
            TaskSessionTurn(
                task_id=task.id,
                user_message_id=message.id,
                workspace_id=task.workspace_id,
                turn_index=index,
                session_revision=task.session_revision,
                provider="opencode",
                **{"session_generation": task.session_generation, **fields},
            )
        )
        return message

    def question(self, task, job, key, when, **fields):
        return self.message(
            task,
            when,
            MessageRole.ASSISTANT,
            {
                "confirmation": {"job_id": job.id, "interaction_id": key, "delivery_mode": "live", **fields},
            },
        )

    def resolve(self, task, job, key, when):
        return self.message(
            task,
            when,
            MessageRole.ASSISTANT,
            {
                "confirmation_resolution": {"job_id": job.id, "interaction_id": key, "status": "answered"},
            },
        )

    def audit(self, requirement, audit_id, when, **metadata):
        self.db.add(
            SddRequirementAuditLog(
                id=audit_id,
                workspace_id=WORKSPACE,
                requirement_id=requirement.id,
                action=RequirementAuditAction.UPDATED,
                created_at=at(when),
                source_metadata_json=metadata,
            )
        )

    def read(self, seconds=0):
        self.db.flush()
        self.db.expire_all()
        return get_workload(self.db, WORKSPACE, can_edit_limits=True, as_of=at(seconds))


@pytest.fixture
def scenario(db):
    db.add_all(
        User(id=user, display_name=user, email=f"{user}@example.test", hashed_password="fixture")
        for user in (EXPERT, DEVELOPER, REVIEWER, ACCEPTOR)
    )
    db.flush()
    db.add(Workspace(id=WORKSPACE, name="Workload projection", owner_id=EXPERT))
    db.flush()
    db.add_all(
        WorkspaceMember(
            workspace_id=WORKSPACE,
            user_id=user,
            role=WorkspaceRole.OWNER if user == EXPERT else WorkspaceRole.DEVELOPER,
        )
        for user in (EXPERT, DEVELOPER, REVIEWER, ACCEPTOR)
    )
    db.flush()
    return Scenario(db)


def member(view, user_id):
    return next(row for row in view.members if row.user_id == user_id)


def slots(view, user_id):
    return {run.id: (run.slot, run.reason) for run in member(view, user_id).executions}


def items(view, user_id, *kinds):
    source = member(view, user_id).items if user_id is not None else view.unassigned
    return {item.id: item for item in source if not kinds or item.kind in kinds}


def finish(task, job, when=0):
    job.status = AiJobStatus.SUCCESS
    job.finished_at = at(when)
    task.status = TaskStatus.ROUND_COMPLETED
    task.updated_at = at(when)


@pytest.mark.parametrize("shared_output", [True, False], ids=["one-shared-output", "three-independent-outputs"])
def test_three_long_sessions_return_without_inflating_attention_or_checks(scenario, shared_output):
    long_tasks = [scenario.task(f"long-{index}") for index in range(3)]
    long_jobs = [scenario.job(task, f"job-{task.id}", started=-10800) for task in long_tasks]
    parent = scenario.requirement("umbrella", *long_tasks)
    if shared_output:
        scenario.requirement("shared-result", *long_tasks, parent_requirement_id=parent.id)
        check_ids = {"check:shared-result:initial"}
    else:
        for task in long_tasks:
            scenario.requirement(f"result-{task.id}", task, parent_requirement_id=parent.id)
        check_ids = {f"check:result-{task.id}:initial" for task in long_tasks}
    short_task = scenario.task("UI interaction", creator_id=DEVELOPER)
    scenario.job(short_task, "ui-run", started=-5)
    scenario.followup(short_task, 2, -60)
    scenario.followup(short_task, 3, 0)

    running = scenario.read()
    assert slots(running, EXPERT) == {job.id: ("background", "running") for job in long_jobs}
    assert slots(running, DEVELOPER) == {"ui-run": ("interactive", "recent_activity")}
    assert set(items(running, REVIEWER, "expected_check")) == check_ids
    assert items(running, REVIEWER, "check") == {}
    assert len(items(running, EXPERT, "ongoing")) == len(check_ids)

    finish(long_tasks[0], long_jobs[0], 1)
    first_return = scenario.read(1)
    assert len(slots(first_return, EXPERT)) == 2
    assert len(items(first_return, REVIEWER, "expected_check")) == (1 if shared_output else 2)
    assert len(items(first_return, REVIEWER, "check")) == (0 if shared_output else 1)

    for task, job in zip(long_tasks[1:], long_jobs[1:], strict=True):
        finish(task, job, 3)
    returned = scenario.read(3)
    assert slots(returned, EXPERT) == {}
    assert slots(returned, DEVELOPER) == {"ui-run": ("interactive", "recent_activity")}
    assert items(returned, REVIEWER, "expected_check") == {}
    assert set(items(returned, REVIEWER, "check")) == check_ids
    assert len(items(returned, EXPERT, "ongoing")) == len(check_ids)


def test_pending_acceptance_keeps_followup_signal_until_normal_decay(scenario):
    task = scenario.task("sustained-work")
    job = scenario.job(task, "continuing", started=-5)
    requirement = scenario.requirement("awaiting-acceptance", task, status=RequirementStatus.PENDING_ACCEPTANCE)
    scenario.audit(requirement, "acceptance-submit", -80, acceptance_action="submit")
    for index, when in enumerate(range(-900, 1, 45), start=2):
        scenario.followup(task, index, when)
    for when in (5, 29, 55, 110):
        scenario.message(task, when, MessageRole.ASSISTANT, {"diff": "+ autogenerated"})

    while_frequent = scenario.read()
    assert slots(while_frequent, EXPERT) == {job.id: ("interactive", "recent_activity")}
    assert while_frequent.next_evaluate_at == at(120).replace(tzinfo=timezone.utc)
    assert set(items(while_frequent, ACCEPTOR, "acceptance")) == {"acceptance:acceptance-submit"}
    assert items(while_frequent, EXPERT, "reply", "check", "acceptance", "failure") == {}

    assert slots(scenario.read(119), EXPERT) == {job.id: ("interactive", "recent_activity")}
    quiet = scenario.read(120)
    assert slots(quiet, EXPERT) == {job.id: ("background", "running")}
    assert quiet.next_evaluate_at is None
    assert set(items(quiet, ACCEPTOR, "acceptance")) == {"acceptance:acceptance-submit"}


def test_check_and_actual_restart_reset_only_the_linked_context(scenario):
    task = scenario.task("change-phase")
    parallel = scenario.task("keep-debugging")
    old = scenario.job(task, "first-phase")
    other = scenario.job(parallel, "independent-run")
    for subject in (task, parallel):
        scenario.followup(subject, 2, -45)
        scenario.followup(subject, 3, -5, client_id="latest-submit")
    requirement = scenario.requirement("known-checkpoint", task)
    finish(task, old)
    assert slots(scenario.read(), EXPERT) == {other.id: ("interactive", "recent_activity")}

    scenario.audit(requirement, "check-complete", 1, checked_cycle="initial", check_task_ids=[task.id])
    scenario.job(task, "queued-phase", started=None, status=AiJobStatus.PENDING)
    assert slots(scenario.read(2), EXPERT) == {other.id: ("interactive", "recent_activity")}

    task.status = TaskStatus.RUNNING
    next_run = scenario.job(task, "new-phase", started=4)
    scenario.followup(task, 4, 6, client_id="latest-submit")
    scenario.followup(task, 5, 7)
    entered = scenario.read(7)
    assert slots(entered, EXPERT) == {
        other.id: ("interactive", "recent_activity"),
        next_run.id: ("background", "started"),
    }
    assert items(entered, REVIEWER, "check", "expected_check") == {}

    scenario.followup(task, 6, 12)
    assert slots(scenario.read(12), EXPERT)[next_run.id] == ("interactive", "recent_activity")


def test_result_return_starts_one_new_check_without_resetting_debug_signal(scenario):
    task = scenario.task("revision")
    starting = scenario.job(task, "first-result", started=-90)
    requirement = scenario.requirement("revise-result", task)
    scenario.followup(task, 2, -40)
    scenario.followup(task, 3, -5)
    finish(task, starting)
    assert set(items(scenario.read(), REVIEWER, "check")) == {"check:revise-result:initial"}

    scenario.audit(requirement, "returned", 1, result_check_action="return", returned_cycle="initial")
    assert items(scenario.read(2), REVIEWER, "check", "expected_check") == {}

    task.status = TaskStatus.RUNNING
    revised = scenario.job(task, "revision-run", started=3)
    revising = scenario.read(3)
    assert slots(revising, EXPERT) == {revised.id: ("interactive", "recent_activity")}
    assert set(items(revising, REVIEWER, "expected_check")) == {"check:revise-result:returned"}
    assert len(items(revising, EXPERT, "ongoing")) == 1
    finish(task, revised, 4)
    assert set(items(scenario.read(4), REVIEWER, "check")) == {"check:revise-result:returned"}


def test_quality_filters_and_conversation_generation_isolation(scenario):
    task = scenario.task("clean-signal", session_generation=3)
    job = scenario.job(task, "recent-run")
    # A first turn, unaccepted messages, bot events, replies, reverted turns and old generations are not followups.
    scenario.followup(task, 1, -20)
    scenario.message(task, -15, MessageRole.USER)
    scenario.followup(task, 2, -10, role=MessageRole.ASSISTANT)
    approval = scenario.question(task, job, "approval", -10)
    scenario.followup(
        task,
        3,
        -9,
        metadata={
            "interaction_id": "approval",
            "reply_to_message_id": approval.id,
            "confirmation_context": {"prompt": "permission"},
        },
    )
    scenario.followup(task, 4, -8, status=TaskSessionTurnStatus.REVERTED)
    scenario.followup(task, 5, -7, session_generation=2)
    scenario.followup(task, 6, -6, client_id="accepted-once")
    scenario.followup(task, 7, -5, client_id="accepted-once")
    scenario.followup(task, 8, 10)
    assert slots(scenario.read(), EXPERT) == {job.id: ("background", "started")}

    # Genuine independent human followup enters using the same operator.
    scenario.followup(task, 9, 0)
    assert slots(scenario.read(), EXPERT) == {job.id: ("interactive", "recent_activity")}

    # Old behavior cannot cross a restart that starts a new conversation generation.
    task.session_generation = 4
    next_job = scenario.job(task, "new-generation", started=1)
    assert slots(scenario.read(2), EXPERT) == {next_job.id: ("background", "started")}


def test_first_persisted_followup_after_initial_result_counts(scenario):
    task = scenario.task("after-first-result")
    scenario.job(task, "initial-launch", started=-120, status=AiJobStatus.SUCCESS, finished_at=at(-70))
    job = scenario.job(task, "next-open-round", started=-5)
    scenario.followup(task, 1, -60)
    scenario.followup(task, 2, 0)
    assert slots(scenario.read(), EXPERT) == {job.id: ("interactive", "recent_activity")}


def test_partial_reply_preserves_other_requests_and_attribution(scenario):
    task = scenario.task("parallel-questions", status=TaskStatus.AWAITING_INPUT)
    job = scenario.job(task, "multi-question-run", started=-2400)
    scenario.question(task, job, "first", -2200)
    scenario.question(task, job, "first", -2100)
    scenario.question(task, job, "other-recipient", -2100, recipient_id=REVIEWER)
    scenario.question(task, job, "last", -10)
    scenario.resolve(task, job, "first", -5)
    # A provider outcome may be replayed. It should remain idempotent.
    scenario.resolve(task, job, "first", -4)
    scenario.followup(task, 2, -20)
    scenario.followup(task, 3, -10)
    running = scenario.read(240)
    assert slots(running, EXPERT) == {job.id: ("interactive", "reply")}
    assert set(items(running, EXPERT, "reply")) == {"reply:multi-question-run:last"}
    assert items(running, REVIEWER, "reply")["reply:multi-question-run:other-recipient"].overdue

    scenario.resolve(task, job, "other-recipient", 241)
    assert len(items(scenario.read(241), EXPERT, "reply")) == 1
    scenario.resolve(task, job, "last", 242)
    task.status = TaskStatus.RUNNING
    resumed = scenario.read(242)
    assert slots(resumed, EXPERT) == {job.id: ("background", "running")}
    assert items(resumed, EXPERT, "reply") == items(resumed, REVIEWER, "reply") == {}


def test_retry_filters_stale_requests_and_acknowledges_a_replayed_prompt(scenario):
    task = scenario.task("retry")
    job = scenario.job(task, "retry-run", started=-60, attempt_count=2)
    scenario.question(task, job, "previous-attempt", -65)
    scenario.question(task, job, "in-future", 5)
    scenario.question(task, job, "current", -20)
    duplicate = scenario.question(task, job, "current", -19)
    scenario.message(
        task,
        -10,
        MessageRole.USER,
        {
            "reply_to_message_id": duplicate.id,
            "interaction_id": "other",
            "confirmation_context": {"prompt": "question"},
        },
    )
    assert set(items(scenario.read(), EXPERT, "reply")) == {"reply:retry-run:current"}

    scenario.message(
        task,
        -5,
        MessageRole.USER,
        {
            "reply_to_message_id": duplicate.id,
            "interaction_id": "current",
            "confirmation_context": {"prompt": "question"},
        },
    )
    assert items(scenario.read(), EXPERT, "reply") == {}


def test_suspended_request_counts_as_todo_but_occupies_no_active_slot(scenario):
    task = scenario.task("paused-question", status=TaskStatus.AWAITING_INPUT)
    job = scenario.job(task, "paused", status=AiJobStatus.WAITING_HITL)
    scenario.question(task, job, "blocked", -5, delivery_mode="turn")
    missing = scenario.task("missing-request", status=TaskStatus.AWAITING_INPUT)
    scenario.job(missing, "paused-without-ledger", status=AiJobStatus.WAITING_HITL)
    view = scenario.read()
    assert slots(view, EXPERT) == {}
    assert set(items(view, EXPERT, "reply")) == {"reply:paused:blocked"}
    assert view.observation_gaps == 1


def test_unknown_execution_is_separate_and_missing_coverage_keeps_known_facts(scenario):
    expired = scenario.task("expired")
    scenario.job(expired, "expired-lease", lease_expires_at=at())
    stopping = scenario.task("stopping")
    scenario.job(stopping, "not-yet-stopped", status=AiJobStatus.TERMINATING)
    incomplete = scenario.task("missing-question", status=TaskStatus.AWAITING_INPUT)
    scenario.job(incomplete, "missing-ledger")
    unknown_provider = scenario.task("other-provider")
    known_run = scenario.job(unknown_provider, "unsupported", agent_backend="unknown")
    scenario.question(unknown_provider, known_run, "known-request", -10)
    view = scenario.read()
    assert slots(view, EXPERT) == {
        "expired-lease": ("uncertain", "uncertain"),
        "not-yet-stopped": ("uncertain", "uncertain"),
        "missing-ledger": ("incomplete", "incomplete"),
        "unsupported": ("interactive", "reply"),
    }
    assert set(items(view, EXPERT, "reply")) == {"reply:unsupported:known-request"}


def test_preparing_failed_and_retried_execution_preserve_business_obligation(scenario):
    task = scenario.task("producer", status=TaskStatus.INITIALIZED)
    requirement = scenario.requirement("failure-retry", task)
    queued = scenario.job(task, "retryable", started=None, status=AiJobStatus.PENDING)
    before_start = scenario.read()
    assert slots(before_start, EXPERT) == {}
    assert set(items(before_start, EXPERT, "planned")) == {requirement.id}
    assert items(before_start, REVIEWER, "expected_check", "check", "paused_check") == {}

    queued.started_at = at(-120)
    queued.status = AiJobStatus.FAILED
    queued.finished_at = at(-10)
    task.status = TaskStatus.FAILED
    failed = scenario.read()
    assert slots(failed, EXPERT) == {}
    assert set(items(failed, EXPERT, "failure")) == {"failure:retryable"}
    check_id = "check:failure-retry:initial"
    assert set(items(failed, REVIEWER, "paused_check")) == {check_id}

    queued.status = AiJobStatus.RUNNING
    queued.started_at = at(1)
    queued.finished_at = None
    queued.attempt_count = 2
    task.status = TaskStatus.RUNNING
    retried = scenario.read(2)
    assert slots(retried, EXPERT) == {queued.id: ("background", "started")}
    assert items(retried, EXPERT, "failure") == {}
    assert set(items(retried, REVIEWER, "expected_check")) == {check_id}

    queued.status = AiJobStatus.CANCELLED
    task.status = TaskStatus.INTERRUPTED
    stopped = scenario.read(3)
    assert slots(stopped, EXPERT) == {}
    assert set(items(stopped, REVIEWER, "paused_check")) == {check_id}


def test_assignment_and_reviewer_changes_do_not_reassign_execution_or_acceptance(scenario):
    task = scenario.task("producer")
    scenario.job(task, "live")
    review = scenario.requirement("review-owned", task)
    acceptance = scenario.requirement("client-acceptance", status=RequirementStatus.PENDING_ACCEPTANCE)
    scenario.audit(acceptance, "submission", -1800, acceptance_action="submit")
    original = scenario.read()
    review.owner_id = DEVELOPER
    acceptance.owner_id = DEVELOPER
    changed_owner = scenario.read()
    assert slots(original, EXPERT) == slots(changed_owner, EXPERT)
    assert set(items(changed_owner, DEVELOPER, "ongoing")) == {review.id, acceptance.id}
    assert set(items(changed_owner, REVIEWER, "expected_check")) == {"check:review-owned:initial"}
    assert items(changed_owner, ACCEPTOR, "acceptance")["acceptance:submission"].overdue
    review.reviewer_id = DEVELOPER
    transferred = scenario.read()
    assert items(transferred, REVIEWER, "expected_check") == {}
    assert set(items(transferred, DEVELOPER, "expected_check")) == {"check:review-owned:initial"}


def test_unassigned_and_undefined_check_requirements_are_distinct(scenario):
    assigned_later = scenario.task("reviewer-unknown")
    scenario.job(assigned_later, "run-with-check")
    scenario.requirement("unassigned-check", assigned_later, reviewer_id=None)
    undefined = scenario.task("check-not-declared")
    scenario.job(undefined, "run-without-check")
    scenario.requirement("undefined-check", undefined, result_check_required=False)
    view = scenario.read()
    assert len(slots(view, EXPERT)) == 2
    assert set(items(view, None, "expected_check")) == {"check:unassigned-check:initial"}
    assert items(view, None, "check") == {}
    assert view.observation_gaps == 1


def test_wait_age_uses_actual_result_event_and_review_due_date(scenario):
    task = scenario.task("results")
    job = scenario.job(task, "returned-result", started=-2100)
    scenario.requirement("aging-check", task)
    finish(task, job, -1800)
    # An unrelated asset update must not restart the waiting clock.
    task.name = "renamed after return"
    task.updated_at = at(-120)
    scenario.db.add(
        SddHumanReview(
            id="review-due",
            workspace_id=WORKSPACE,
            task_id=task.id,
            reviewer_id=REVIEWER,
            status=HumanReviewStatus.OPEN,
            due_date=at(),
            created_at=at(-60),
        )
    )
    before = items(scenario.read(-1), REVIEWER, "check")
    assert not before["check:aging-check:initial"].overdue and not before["review:review-due"].overdue
    after = items(scenario.read(), REVIEWER, "check")
    assert after["check:aging-check:initial"].since == at(-1800)
    assert after["check:aging-check:initial"].overdue and after["review:review-due"].overdue


def test_limits_do_not_change_calculated_facts_and_snapshot_replays(scenario):
    task = scenario.task("executing")
    scenario.job(task, "live")
    scenario.requirement("producing", task)
    before = scenario.read()
    assert scenario.read().model_dump() == before.model_dump()
    membership = scenario.db.query(WorkspaceMember).filter_by(workspace_id=WORKSPACE, user_id=EXPERT).one()
    membership.workload_limits = {"background": 0, "interactive": 0, "ongoing": 0}
    after = scenario.read()
    assert member(after, EXPERT).limits.background == 0
    assert slots(after, EXPERT) == slots(before, EXPERT)
    assert items(after, EXPERT) == items(before, EXPERT)
    assert items(after, REVIEWER) == items(before, REVIEWER)


def test_workspace_and_job_channel_boundaries(scenario):
    scenario.db.add(Workspace(id="other-workspace", name="Other", owner_id=EXPERT))
    scenario.db.flush()
    outside_task = scenario.task("outside", workspace_id="other-workspace")
    scenario.job(outside_task, "outside-run")
    own_task = scenario.task("inside")
    scenario.job(own_task, "ordinary-run")
    scenario.job(own_task, "private-asset-assistant", visibility="private", current=False)
    scenario.job(own_task, "background-tool", channel=AiJobChannel.BACKGROUND, current=False)
    assert slots(scenario.read(), EXPERT) == {"ordinary-run": ("background", "started")}


def test_cross_workspace_workload_counts_borrowed_members_without_granting_asset_access(scenario):
    hidden, visible, unrelated = "workload-hidden", "workload-visible", "workload-unrelated"
    outsider = User(id="other-member", display_name=EXPERT, email="other@example.test", hashed_password="fixture")
    scenario.db.add(outsider)
    scenario.db.flush()
    scenario.db.add_all(
        Workspace(id=identifier, name=name, owner_id=outsider.id)
        for identifier, name in ((hidden, "Borrowed work"), (visible, "Shared work"), (unrelated, "Unrelated work"))
    )
    scenario.db.flush()
    scenario.db.add_all(
        WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=WorkspaceRole.DEVELOPER)
        for workspace_id, user_id in (
            (hidden, EXPERT),
            (hidden, DEVELOPER),
            (hidden, outsider.id),
            (visible, EXPERT),
            (unrelated, outsider.id),
        )
    )
    scenario.db.add(
        WorkspaceMember(
            workspace_id=visible,
            user_id=ACCEPTOR,
            role=WorkspaceRole.VIEWER,
            permissions_json='["VIEW_ASSETS"]',
        )
    )
    anchor_viewer = scenario.db.query(WorkspaceMember).filter_by(workspace_id=WORKSPACE, user_id=ACCEPTOR).one()
    anchor_viewer.role = WorkspaceRole.VIEWER
    anchor_viewer.permissions_json = '["VIEW_ASSETS"]'
    local = scenario.task("local-execution")
    scenario.job(local, "local-run")
    borrowed = scenario.task("private-execution-title", workspace_id=hidden, status=TaskStatus.AWAITING_INPUT)
    borrowed_job = scenario.job(borrowed, "private-run")
    scenario.question(borrowed, borrowed_job, "private-question", -10, recipient_id=DEVELOPER)
    scenario.requirement(
        "private-requirement-title", borrowed, workspace_id=hidden, owner_id=EXPERT, reviewer_id=DEVELOPER
    )

    # Work by an external member still produces review work for a member of the anchor.
    foreign = scenario.task("foreign-execution", workspace_id=hidden, creator_id=outsider.id)
    scenario.job(foreign, "foreign-run")
    scenario.followup(foreign, 2, -110)
    scenario.followup(foreign, 3, -100)
    scenario.requirement(
        "foreign-requirement", foreign, workspace_id=hidden, owner_id=outsider.id, reviewer_id=DEVELOPER
    )
    shared = scenario.task("visible-review-target", workspace_id=visible)
    scenario.job(shared, "visible-run")
    scenario.followup(shared, 2, -25)
    scenario.followup(shared, 3, -5)
    waiting = scenario.task("borrowed-missing-question", workspace_id=hidden, status=TaskStatus.AWAITING_INPUT)
    scenario.job(waiting, "borrowed-missing-question-run", status=AiJobStatus.WAITING_HITL)
    scenario.db.add_all(
        SddHumanReview(
            id=f"{workspace_id}-review",
            workspace_id=workspace_id,
            task_id=task.id,
            reviewer_id=reviewer,
            status=HumanReviewStatus.OPEN,
            title=f"{workspace_id}-review-title",
            created_at=at(-1900),
        )
        for workspace_id, task, reviewer in (
            (visible, shared, EXPERT),
            (hidden, foreign, None),
            (WORKSPACE, local, None),
        )
    )
    scenario.db.flush()
    scenario.db.expire_all()

    view = get_workspace_member_workload(scenario.db, WORKSPACE, ACCEPTOR, can_edit_limits=False, as_of=at())
    expert = member(view, EXPERT)
    assert {person.user_id for person in view.members} == {EXPERT, DEVELOPER, REVIEWER, ACCEPTOR}
    assert expert.counts.slots == {"background": 1, "interactive": 2}
    assert expert.counts.items == {"ongoing": 1, "check": 1}
    assert expert.counts.overdue == 1
    assert [source.workspace_id for source in expert.sources] == [WORKSPACE, hidden, visible]
    assert expert.sources[1].workspace_name == "Borrowed work"
    assert expert.sources[1].counts.slots == {"interactive": 1}
    assert expert.sources[1].details is None
    assert [run.id for run in expert.sources[2].details.executions] == ["visible-run"]
    assert member(view, DEVELOPER).counts.items == {"reply": 1, "expected_check": 2}
    assert not member(view, DEVELOPER).counts.slots
    assert [item.id for item in view.unassigned] == [f"review:{WORKSPACE}-review"]
    assert view.observation_gaps == 1
    shared_deadline = get_workload(scenario.db, visible, can_edit_limits=False, as_of=at()).next_evaluate_at
    assert shared_deadline is not None and view.next_evaluate_at == shared_deadline

    app = FastAPI()
    app.include_router(routes.router)
    viewer = scenario.db.get(User, ACCEPTOR)
    app.dependency_overrides[routes.get_current_user] = lambda: viewer
    app.dependency_overrides[routes.get_db] = lambda: scenario.db
    with TestClient(app) as client:
        url = f"/workspaces/{WORKSPACE}/workspace-assets/workload"
        aggregate = client.get(url + "/members")
        assert aggregate.status_code == 200
        assert aggregate.json()["can_edit_limits"] is False
        assert "Borrowed work" in aggregate.text and "visible-review-target" in aggregate.text
        for private in ("private-execution-title", "private-requirement-title", "private-run", "foreign-requirement"):
            assert private not in aggregate.text
        assert "Unrelated work" not in aggregate.text
        assert "Borrowed work" not in client.get(url).text
        hidden_url = f"/workspaces/{hidden}/workspace-assets/workload"
        assert client.get(hidden_url).status_code == 403
        assert client.get(hidden_url + "/members").status_code == 403
        assert client.put(hidden_url + f"/members/{EXPERT}/limits", json={"background": 4}).status_code == 403
