"""Small shared helpers for task session turns and undo records."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.orm import Session

from app.domains.task.models.session_turn import TaskSessionTurn
from app.domains.task.models.task import SddTask


def _enum_text(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def _secret_fingerprint(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="replace")).hexdigest()[:12]


def _repo_rel_paths(task: SddTask) -> list[str]:
    paths: list[str] = []
    for repo in list(getattr(task, "repo_bindings", None) or []):
        value = str(getattr(repo, "rel_path", "") or "").strip()
        if value and value not in paths:
            paths.append(value)
    return paths


def _next_turn_index(db: Session, task_id: str, generation: int) -> int:
    rows = (
        db.query(TaskSessionTurn.turn_index)
        .filter(
            TaskSessionTurn.task_id == task_id,
            TaskSessionTurn.session_generation == generation,
        )
        .all()
    )
    return max((int(row[0] or 0) for row in rows), default=0) + 1
