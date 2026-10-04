"""Task model preferences and provider-owned model catalogues.

Preferences are stored in task metadata; each accepted turn takes its own copy.
Runtime model observations remain separate from the requested model.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ModelSelection(BaseModel):
    backend: Literal["claude-code", "opencode", "dsh"]
    model: str = Field(min_length=1, max_length=500)

    @field_validator("model")
    @classmethod
    def clean_model(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError("模型名称无效")
        return value


def task_selection(task) -> dict | None:
    value = (task.task_meta_json or {}).get("agent_model")
    return dict(value) if isinstance(value, dict) else None


def validate_selection(value, backend: str) -> dict:
    selection = ModelSelection.model_validate(value)
    if selection.backend != backend:
        raise ValueError("Agent 引擎已改变，请重新选择模型")
    if backend in {"opencode", "dsh"}:
        provider, sep, model = selection.model.partition("/")
        if not sep or not provider or not model:
            raise ValueError("模型必须包含 provider/model")
    return selection.model_dump()


def apply_task_selection(db, task, value) -> dict | None:
    from app.agents.selection import normalize_backend_name, resolve_workspace_backend

    if value is None:
        return task_selection(task)
    backend = normalize_backend_name(task.agent_backend) or resolve_workspace_backend(db, task.workspace_id)
    selected = validate_selection(value, backend)
    task.agent_backend = backend
    task.task_meta_json = {**(task.task_meta_json or {}), "agent_model": selected}
    return selected


def model_option(value: str, label: str | None = None) -> dict:
    return {"value": value, "label": label or value}
