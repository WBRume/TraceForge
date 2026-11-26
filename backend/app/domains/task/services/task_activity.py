"""Shared workspace and session checks for durable task activity."""

from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import ColumnElement

from app.domains.ai.models.ai_job import AiJobChannel, SddAiJob
from app.domains.task.models.session_turn import TaskSessionTurn, TaskSessionTurnStatus
from app.domains.task.models.task import SddTask


def task_chat_job_scope(workspace_id: str, *, include_legacy_history: bool = False) -> tuple[ColumnElement[bool], ...]:
    """Scope joined job and task records to the visible, current task session."""
    legacy_job_matches: ColumnElement[bool] = SddTask.status_run_id == SddAiJob.id
    if include_legacy_history:
        # Jobs predating generation tracking belong to the initial session unless it has been reset.
        legacy_job_matches = or_(legacy_job_matches, SddTask.session_generation == 0)
    return (
        SddAiJob.workspace_id == workspace_id,
        SddTask.workspace_id == workspace_id,
        SddAiJob.channel == AiJobChannel.TASK_CHAT,
        SddAiJob.visibility == "workspace",
        or_(
            SddAiJob.session_generation == SddTask.session_generation,
            and_(SddAiJob.session_generation.is_(None), legacy_job_matches),
        ),
    )


def active_task_chat_turn() -> ColumnElement[bool]:
    """Verify that a joined turn belongs to the task's current session and is still effective."""
    return and_(
        TaskSessionTurn.task_id == SddTask.id,
        TaskSessionTurn.workspace_id == SddTask.workspace_id,
        TaskSessionTurn.session_generation == SddTask.session_generation,
        TaskSessionTurn.status == TaskSessionTurnStatus.ACTIVE,
    )
