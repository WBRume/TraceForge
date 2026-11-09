"""Read-only domain facades over the unified execution record.

Domain tables contain input and artifacts only. The shared primary key is the
job identity; deleting an artifact deliberately retains its execution history.
"""

from sqlalchemy import select
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import declared_attr, foreign, relationship

from app.domains.ai.models.ai_job import SddAiJob


def execution_field(name):
    @hybrid_property
    def field(self):
        job = self.execution
        return getattr(job, name) if job is not None else None

    @field.expression
    def field(cls):
        return select(getattr(SddAiJob, name)).where(SddAiJob.id == cls.id).scalar_subquery()

    return field


class JobExecutionProjection:
    @declared_attr
    def execution(cls):
        return relationship(
            SddAiJob,
            primaryjoin=lambda: foreign(cls.id) == SddAiJob.id,
            lazy="selectin",
        )

    status = execution_field("status")
    progress = execution_field("progress")
    stage = execution_field("stage")
    message = execution_field("message")
    error_message = execution_field("error_message")
    started_at = execution_field("started_at")
    finished_at = execution_field("finished_at")
    updated_at = execution_field("state_changed_at")
    version = execution_field("version")
    attempt_count = execution_field("attempt_count")
    completion = execution_field("completion_json")

    @property
    def cancel_requested(self):
        return bool(self.execution and self.execution.cancel_requested_at)


class JobResultProjection(JobExecutionProjection):
    result_json = execution_field("result_json")
