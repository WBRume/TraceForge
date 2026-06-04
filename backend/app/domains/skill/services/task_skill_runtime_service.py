"""
Runtime skill service for task/session execution.

This module operates only on task-local materialized skill copies:
<task.project_path>/.claude/skills/<materialized_dir>/...
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.domains.task.models.chat import ChatMessage, MessageType
from app.domains.skill.models.skill import SddSkill, SddSkillRuntimeEvent, SkillRuntimeEventType
from app.domains.task.models.task import SddTask
from app.domains.skill.services import skill_service
from app.domains.skill.services.skill import storage_service


@dataclass(frozen=True)
class RuntimeSkillRecord:
    skill_id: str
    name: str
    description: Optional[str]
    dimension: str
    materialized_dir: str
    skill: Optional[SddSkill] = None
    config_deleted: bool = False


def _task_skills_root(task: SddTask) -> str:
    return os.path.abspath(os.path.join(task.project_path, ".claude", "skills"))


def _runtime_manifest_path(task: SddTask) -> str:
    return os.path.join(_task_skills_root(task), skill_service.TASK_SKILLS_MANIFEST)


def _read_runtime_manifest(task: SddTask) -> List[Dict[str, Any]]:
    manifest_path = _runtime_manifest_path(task)
    if not os.path.isfile(manifest_path):
        return []
    try:
        with open(manifest_path, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except Exception:
        return []
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _record_from_manifest_item(item: Dict[str, Any], *, root: str) -> Optional[RuntimeSkillRecord]:
    skill_id = str(item.get("skill_id") or "").strip()
    folder = str(item.get("materialized_dir") or "").strip()
    if not skill_id or not folder:
        return None
    skill_root = os.path.abspath(os.path.join(root, folder))
    root_abs = os.path.abspath(root)
    try:
        if os.path.commonpath([root_abs, skill_root]) != root_abs:
            return None
    except ValueError:
        return None
    if not os.path.isdir(skill_root):
        return None
    return RuntimeSkillRecord(
        skill_id=skill_id,
        name=str(item.get("name") or folder),
        description=str(item.get("description")) if item.get("description") is not None else None,
        dimension=str(item.get("dimension") or "TASK_RUNTIME"),
        materialized_dir=folder,
        skill=None,
        config_deleted=True,
    )


def _fallback_runtime_dir_records(root: str, existing_folders: set[str]) -> List[RuntimeSkillRecord]:
    if not os.path.isdir(root):
        return []
    records: List[RuntimeSkillRecord] = []
    for entry_name in sorted(os.listdir(root), key=str.lower):
        if entry_name.startswith(".") or entry_name in existing_folders:
            continue
        entry_path = os.path.abspath(os.path.join(root, entry_name))
        if not os.path.isdir(entry_path) or os.path.islink(entry_path):
            continue
        records.append(
            RuntimeSkillRecord(
                skill_id=f"runtime:{entry_name}",
                name=entry_name,
                description=None,
                dimension="TASK_RUNTIME",
                materialized_dir=entry_name,
                skill=None,
                config_deleted=True,
            )
        )
    return records


def get_task_runtime_skill_records(db: Session, task: SddTask) -> List[RuntimeSkillRecord]:
    root = _task_skills_root(task)
    skills = skill_service.get_task_skills(db, task.id)
    folder_map = skill_service.build_task_skill_folder_map(skills)
    records: List[RuntimeSkillRecord] = []
    seen_skill_ids: set[str] = set()
    seen_folders: set[str] = set()

    for skill in skills:
        folder = str(folder_map.get(skill.id) or "").strip()
        if not folder:
            continue
        records.append(
            RuntimeSkillRecord(
                skill_id=skill.id,
                name=skill.name,
                description=skill.description,
                dimension=skill.dimension.value if hasattr(skill.dimension, "value") else str(skill.dimension),
                materialized_dir=folder,
                skill=skill,
                config_deleted=False,
            )
        )
        seen_skill_ids.add(skill.id)
        seen_folders.add(folder)

    for item in _read_runtime_manifest(task):
        record = _record_from_manifest_item(item, root=root)
        if not record or record.skill_id in seen_skill_ids or record.materialized_dir in seen_folders:
            continue
        records.append(record)
        seen_skill_ids.add(record.skill_id)
        seen_folders.add(record.materialized_dir)

    records.extend(_fallback_runtime_dir_records(root, seen_folders))
    return records


def _resolve_runtime_skill_root(db: Session, task: SddTask, skill_id: str) -> Tuple[RuntimeSkillRecord, str, str]:
    records = get_task_runtime_skill_records(db, task)
    target = next((record for record in records if record.skill_id == skill_id), None)
    if not target:
        raise ValueError("Skill runtime copy is not available for this task")

    folder_name = target.materialized_dir
    if not folder_name:
        raise ValueError("Failed to resolve materialized skill folder")

    skill_root = os.path.abspath(os.path.join(_task_skills_root(task), folder_name))
    return target, folder_name, skill_root


def _safe_join_runtime_skill_root(skill_root: str, relative_path: str) -> Tuple[str, str]:
    normalized = storage_service.normalize_relative_path(relative_path)
    target = os.path.abspath(os.path.join(skill_root, normalized))
    root_abs = os.path.abspath(skill_root)
    if os.path.commonpath([root_abs, target]) != root_abs:
        raise ValueError("Path escapes runtime skill root")
    return normalized, target


def _latest_usage_scope_start(db: Session, task: SddTask) -> Optional[datetime]:
    latest_init = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.task_id == task.id,
            ChatMessage.workspace_id == task.workspace_id,
            ChatMessage.message_type == MessageType.INIT_REASON.value,
        )
        .order_by(ChatMessage.created_at.desc())
        .first()
    )
    if latest_init and latest_init.created_at:
        return latest_init.created_at
    return task.created_at


def _build_usage_stats(
    db: Session,
    task: SddTask,
    *,
    records: List[RuntimeSkillRecord],
    scope_start_at: Optional[datetime],
) -> Dict[str, Dict[str, object]]:
    usage: Dict[str, Dict[str, object]] = {
        record.skill_id: {
            "is_used": False,
            "used_count": 0,
            "last_used_at": None,
            "usage_scope_start_at": scope_start_at,
        }
        for record in records
    }
    if not records:
        return usage
    folder_to_skill_id = {
        record.materialized_dir: record.skill_id
        for record in records
        if record.materialized_dir
    }

    event_scope_query = db.query(SddSkillRuntimeEvent).filter(
        SddSkillRuntimeEvent.task_id == task.id,
        SddSkillRuntimeEvent.workspace_id == task.workspace_id,
    )
    if scope_start_at:
        event_scope_query = event_scope_query.filter(SddSkillRuntimeEvent.created_at >= scope_start_at)
    effective_types = [
        SkillRuntimeEventType.ENTRY_READ,
        SkillRuntimeEventType.FILE_READ,
        SkillRuntimeEventType.DIR_LIST,
        SkillRuntimeEventType.FILE_SEARCH,
        SkillRuntimeEventType.SCRIPT_EXEC,
        SkillRuntimeEventType.FILE_WRITE,
        SkillRuntimeEventType.USAGE_CONFIRMED,
    ]
    rows = (
        event_scope_query.filter(SddSkillRuntimeEvent.event_type.in_(effective_types))
        .order_by(SddSkillRuntimeEvent.created_at.asc())
        .all()
    )
    for row in rows:
        target_skill_id = row.skill_id if row.skill_id in usage else folder_to_skill_id.get(row.materialized_dir or "")
        if not target_skill_id or target_skill_id not in usage:
            continue
        skill_usage = usage[target_skill_id]
        skill_usage["is_used"] = True
        skill_usage["used_count"] = int(skill_usage.get("used_count") or 0) + 1
        skill_usage["last_used_at"] = row.created_at

    return usage


def list_task_runtime_skills(db: Session, task: SddTask) -> Dict[str, object]:
    records = get_task_runtime_skill_records(db, task)
    scope_start_at = _latest_usage_scope_start(db, task)
    usage_by_skill = _build_usage_stats(
        db,
        task,
        records=records,
        scope_start_at=scope_start_at,
    )
    root = _task_skills_root(task)

    items: List[Dict[str, object]] = []
    for record in records:
        folder = record.materialized_dir
        skill_root = os.path.join(root, folder) if folder else ""
        is_materialized = bool(folder) and os.path.isdir(skill_root)
        if record.skill is not None:
            try:
                publish = skill_service.get_skill_package_publish_status(record.skill)
            except Exception:
                publish = {
                    "publish_state": "PUBLISHED",
                    "has_pending_changes": False,
                    "changed_files_count": 0,
                }
        else:
            publish = {
                "publish_state": "PUBLISHED",
                "has_pending_changes": False,
                "changed_files_count": 0,
            }

        items.append(
            {
                "skill_id": record.skill_id,
                "name": record.name,
                "description": record.description,
                "dimension": record.dimension,
                "publish_state": str(publish.get("publish_state") or "PUBLISHED"),
                "has_pending_changes": bool(publish.get("has_pending_changes") or False),
                "changed_files_count": int(publish.get("changed_files_count") or 0),
                "materialized_dir": folder,
                "is_materialized": is_materialized,
                "config_deleted": bool(record.config_deleted),
                "usage": usage_by_skill.get(record.skill_id, {
                    "is_used": False,
                    "used_count": 0,
                    "last_used_at": None,
                    "usage_scope_start_at": scope_start_at,
                }),
            }
        )

    return {
        "task_id": task.id,
        "items": items,
        "total": len(items),
        "usage_scope_start_at": scope_start_at,
    }


def build_task_runtime_skill_file_tree(
    db: Session,
    task: SddTask,
    *,
    skill_id: str,
) -> List[Dict[str, object]]:
    _, _, skill_root = _resolve_runtime_skill_root(db, task, skill_id)
    if not os.path.isdir(skill_root):
        return []

    entries: List[Dict[str, str]] = []
    for walk_root, dir_names, file_names in os.walk(skill_root):
        dir_names.sort(key=str.lower)
        file_names.sort(key=str.lower)

        visible_dirs: List[str] = []
        for dir_name in dir_names:
            abs_dir = os.path.join(walk_root, dir_name)
            if os.path.islink(abs_dir):
                continue
            visible_dirs.append(dir_name)
            rel_dir = storage_service.normalize_path(os.path.relpath(abs_dir, skill_root))
            entries.append({"path": rel_dir, "node_type": "directory"})
        dir_names[:] = visible_dirs

        for file_name in file_names:
            abs_file = os.path.join(walk_root, file_name)
            if os.path.islink(abs_file):
                continue
            rel_file = storage_service.normalize_path(os.path.relpath(abs_file, skill_root))
            entries.append({"path": rel_file, "node_type": "file"})

    return storage_service.build_tree(entries)


def read_task_runtime_skill_file(
    db: Session,
    task: SddTask,
    *,
    skill_id: str,
    path: str,
) -> Dict[str, object]:
    _, _, skill_root = _resolve_runtime_skill_root(db, task, skill_id)
    if not os.path.isdir(skill_root):
        raise FileNotFoundError("Skill runtime directory not found")

    normalized, target = _safe_join_runtime_skill_root(skill_root, path)
    if not os.path.isfile(target):
        raise FileNotFoundError("File not found")
    if os.path.islink(target):
        raise ValueError("Symlink is not allowed in runtime skill directory")

    with open(target, "rb") as file:
        payload = file.read()
    is_binary = storage_service.is_binary_bytes(payload)
    if is_binary:
        return {"path": normalized, "content": None, "is_binary": True, "size": len(payload)}
    try:
        content = payload.decode("utf-8")
    except UnicodeDecodeError:
        return {"path": normalized, "content": None, "is_binary": True, "size": len(payload)}
    return {"path": normalized, "content": content, "is_binary": False, "size": len(payload)}


def write_task_runtime_skill_file(
    db: Session,
    task: SddTask,
    *,
    skill_id: str,
    path: str,
    content: str,
) -> Dict[str, object]:
    _, _, skill_root = _resolve_runtime_skill_root(db, task, skill_id)
    if not os.path.isdir(skill_root):
        raise FileNotFoundError("Skill runtime directory not found")

    normalized, target = _safe_join_runtime_skill_root(skill_root, path)

    if os.path.lexists(target):
        if os.path.islink(target):
            raise ValueError("Symlink is not allowed in runtime skill directory")
        if os.path.isdir(target):
            raise ValueError("Cannot overwrite a directory path")
        with open(target, "rb") as file:
            existing = file.read()
        if storage_service.is_binary_bytes(existing):
            raise ValueError("Binary file is read-only in runtime skill editor")

    normalized_content = str(content or "").replace("\r\r\n", "\r\n")
    encoded = normalized_content.encode("utf-8")
    max_size = int(getattr(settings, "SKILL_MAX_TEXT_FILE_SIZE_BYTES", 10 * 1024 * 1024))
    if len(encoded) > max_size:
        raise ValueError(f"File exceeds max text size ({max_size} bytes)")

    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="") as file:
        file.write(normalized_content)

    return {
        "path": normalized,
        "content": normalized_content,
        "is_binary": False,
        "size": len(encoded),
    }
