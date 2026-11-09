"""Execution backend contract.

The platform owns identity, authorization, input, completion and history. A
backend owns dispatch, attempt recovery and its single automatic retry policy.
An external worker must persist its external_task_id before executing, report
through the fenced result transaction and reconcile committed evidence before
retrying an uncertain side effect. Transport acknowledgement is never success.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


@dataclass(frozen=True)
class BackendCapabilities:
    cooperative_cancel: bool
    human_interaction: bool
    remote_resume: bool
    retry_owner: str


class ExecutionBackend(Protocol):
    capabilities: BackendCapabilities

    def wake(self, queue_key: str) -> None: ...


class DurableBackend:
    capabilities = BackendCapabilities(True, True, True, "durable")

    def wake(self, queue_key: str) -> None:
        from app.domains.ai.services.jobs.registry import runtime

        runtime.schedule_queue(queue_key)


BACKENDS: dict[str, ExecutionBackend] = {"durable": DurableBackend()}


def dispatch(job) -> None:
    backend = BACKENDS.get(job.execution_backend)
    if backend is None:
        raise ValueError(f"Execution backend is unavailable: {job.execution_backend}")
    backend.wake(job.queue_key)


def schedule_trigger_key(schedule_id: str, scheduled_for: datetime) -> str:
    """Stable trigger identity; plans own timezone, catch-up and overlap policy.

    Normal and manual triggers for the same logical instant share this key.
    Pausing/changing a plan never edits already accepted job instances. A future
    scheduler supplies its intended time, not message arrival time, to submit.
    """
    if not schedule_id or scheduled_for.tzinfo is None:
        raise ValueError("A schedule ID and timezone-aware intended time are required")
    return f"schedule:{schedule_id}:{scheduled_for.astimezone(timezone.utc).isoformat()}"
