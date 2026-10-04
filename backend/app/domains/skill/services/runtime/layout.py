"""Resolve selected agent runtime skill roots and materialized names."""

from __future__ import annotations

import os

from sqlalchemy.orm import Session

from app.domains.task.models.task import SddTask

SKILL_LAYOUT_ROOTS: dict[str, str] = {
    "claude-code": ".claude/skills",
    "mock": ".claude/skills",
    "opencode": ".agents/skills",
    "dsh": ".agents/skills",
}


DEFAULT_TASK_SKILLS_REL_ROOT = ".claude/skills"


def task_skills_rel_root(backend_name: str | None) -> str:
    """Return the task-local skills directory for an agent backend."""
    name = str(backend_name or "").strip().lower()
    return SKILL_LAYOUT_ROOTS.get(name, DEFAULT_TASK_SKILLS_REL_ROOT)


def resolve_task_skills_rel_root(db: Session | None, task: SddTask) -> str:
    """Resolve the task-local skills root (relative to project_path) for a task."""
    from app.agents.selection import normalize_backend_name, resolve_workspace_backend

    sticky = normalize_backend_name(getattr(task, "agent_backend", None))
    if sticky:
        return task_skills_rel_root(sticky)
    try:
        workspace_backend = resolve_workspace_backend(db, getattr(task, "workspace_id", None))
    except Exception:
        workspace_backend = None
    return task_skills_rel_root(workspace_backend)


def resolve_task_skills_root(db: Session | None, task: SddTask) -> str:
    """Return the absolute task-local skills root for a task."""
    rel_root = resolve_task_skills_rel_root(db, task)
    return os.path.abspath(os.path.join(task.project_path or ".", rel_root))
