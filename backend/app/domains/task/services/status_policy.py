"""Task collaboration states, independent of provider/job execution states."""

from app.domains.task.models.task import TaskStatus

TERMINAL_STATUSES = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED})


def is_terminal(status: TaskStatus | str) -> bool:
    return status in TERMINAL_STATUSES
