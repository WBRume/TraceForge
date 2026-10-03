"""Atomically materialize published skills into server or local task runtimes."""

from __future__ import annotations
import os
import json
import shutil
import uuid
from datetime import datetime
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from app.domains.skill.models.skill import SddSkill
from app.domains.task.models.task import SddTask
from app.domains.skill.services.packages import git as git_service, storage as storage_service
from app.domains.skill.services.runtime import bindings as skill_runtime_bindings
from app.domains.skill.services.runtime import layout as skill_runtime_layout


TASK_SKILLS_MANIFEST = ".sdd-runtime-skills.json"


def build_task_skill_folder_map(skills: List[SddSkill]) -> Dict[str, str]:
    used_names: set[str] = set()
    mapping: Dict[str, str] = {}
    for skill in skills:
        base_name = storage_service.sanitize_name_for_folder(skill.name)
        folder_name = base_name
        if folder_name in used_names:
            folder_name = f"{base_name}-{skill.id[:8]}"
        used_names.add(folder_name)
        mapping[skill.id] = folder_name
    return mapping


def _runtime_skill_manifest_item(skill: SddSkill, folder_name: str) -> Dict[str, object]:
    return {
        "skill_id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "dimension": skill.dimension.value if hasattr(skill.dimension, "value") else str(skill.dimension),
        "workspace_id": skill.workspace_id,
        "materialized_dir": folder_name,
        "source_type": skill.source_type,
        "source_repo_url": skill.source_repo_url,
        "source_skill_name": skill.source_skill_name,
        "source_subdir": skill.source_subdir,
        "source_commit_sha": skill.source_commit_sha,
        "materialized_at": datetime.utcnow().isoformat(),
    }


def _runtime_manifest_path(target_dir: str) -> str:
    return os.path.join(target_dir, TASK_SKILLS_MANIFEST)


def _read_runtime_manifest(target_dir: str) -> List[Dict[str, object]]:
    manifest_path = _runtime_manifest_path(target_dir)
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


def _write_runtime_manifest(target_dir: str, items: List[Dict[str, object]]) -> None:
    manifest_path = _runtime_manifest_path(target_dir)
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as file:
        json.dump({"version": 1, "items": items}, file, ensure_ascii=False, indent=2)


def _copy_runtime_dir_without_symlinks(source_dir: str, target_dir: str) -> None:
    source_abs = os.path.abspath(source_dir)
    target_abs = os.path.abspath(target_dir)
    for walk_root, dir_names, file_names in os.walk(source_abs):
        visible_dirs: List[str] = []
        for dir_name in dir_names:
            abs_dir = os.path.join(walk_root, dir_name)
            if os.path.islink(abs_dir):
                continue
            visible_dirs.append(dir_name)
        dir_names[:] = visible_dirs

        rel_walk = os.path.relpath(walk_root, source_abs)
        rel_prefix = "" if rel_walk in {"", "."} else storage_service.normalize_relative_path(rel_walk)
        for file_name in file_names:
            abs_file = os.path.join(walk_root, file_name)
            if os.path.islink(abs_file):
                continue
            rel_file = storage_service.normalize_relative_path(
                os.path.join(rel_prefix, file_name) if rel_prefix else file_name
            )
            dst = _safe_join_target_root(target_abs, rel_file)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(abs_file, dst)


def _preserve_existing_runtime_skill_dirs(
    *,
    source_dir: str,
    target_dir: str,
    current_skill_ids: set[str],
    used_folders: set[str],
) -> List[Dict[str, object]]:
    if not os.path.isdir(source_dir):
        return []

    preserved: List[Dict[str, object]] = []
    seen_folders = set(used_folders)
    manifest_items = _read_runtime_manifest(source_dir)
    for item in manifest_items:
        skill_id = str(item.get("skill_id") or "").strip()
        folder = str(item.get("materialized_dir") or "").strip()
        if not skill_id or skill_id in current_skill_ids or not folder or folder in seen_folders:
            continue
        source_skill_dir = os.path.abspath(os.path.join(source_dir, folder))
        if os.path.commonpath([os.path.abspath(source_dir), source_skill_dir]) != os.path.abspath(source_dir):
            continue
        if not os.path.isdir(source_skill_dir):
            continue
        target_skill_dir = os.path.abspath(os.path.join(target_dir, folder))
        _copy_runtime_dir_without_symlinks(source_skill_dir, target_skill_dir)
        preserved_item = dict(item)
        preserved_item["materialized_dir"] = folder
        preserved_item["config_deleted"] = True
        preserved.append(preserved_item)
        seen_folders.add(folder)

    for entry_name in sorted(os.listdir(source_dir), key=str.lower):
        if entry_name.startswith(".") or entry_name in seen_folders:
            continue
        source_skill_dir = os.path.abspath(os.path.join(source_dir, entry_name))
        if not os.path.isdir(source_skill_dir) or os.path.islink(source_skill_dir):
            continue
        target_skill_dir = os.path.abspath(os.path.join(target_dir, entry_name))
        _copy_runtime_dir_without_symlinks(source_skill_dir, target_skill_dir)
        preserved.append(
            {
                "skill_id": f"runtime:{entry_name}",
                "name": entry_name,
                "description": None,
                "dimension": "TASK_RUNTIME",
                "materialized_dir": entry_name,
                "config_deleted": True,
            }
        )
        seen_folders.add(entry_name)

    return preserved


def _is_internal_skill_path(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/").strip("/")
    if not normalized:
        return False
    first_segment = normalized.split("/", 1)[0]
    return first_segment in {".git", ".sdd-internal"}


def _safe_join_target_root(target_root: str, rel_path: str) -> str:
    normalized = storage_service.normalize_relative_path(rel_path)
    abs_target = os.path.abspath(os.path.join(target_root, normalized))
    abs_root = os.path.abspath(target_root)
    if os.path.commonpath([abs_root, abs_target]) != abs_root:
        raise ValueError("Materialization target path escaped root")
    return abs_target


def _copy_single_skill_package(skill: SddSkill, skill_target_dir: str) -> None:
    source_root = storage_service.package_abs_path(skill)
    if not os.path.isdir(source_root):
        raise FileNotFoundError(f"Skill package not found: {skill.package_path}")

    os.makedirs(skill_target_dir, exist_ok=True)
    published_ref = str(skill.head_commit_sha or "").strip()
    if not published_ref:
        # No published commit yet (draft-only skill): do not materialize draft
        # into task session skills.
        return

    # Materialize from published git snapshot to avoid copying un-published drafts
    # into SSD task sessions.
    for rel_file in git_service.list_files_at_ref(source_root, published_ref):
        if _is_internal_skill_path(rel_file):
            continue
        payload = git_service.read_file_at_ref(source_root, published_ref, rel_file)
        target_file = _safe_join_target_root(skill_target_dir, rel_file)
        os.makedirs(os.path.dirname(target_file), exist_ok=True)
        with open(target_file, "wb") as file:
            file.write(payload)


def _copy_skills_to_target(
    skills: List[SddSkill],
    target_dir: str,
    *,
    preserve_from_dir: Optional[str] = None,
    preserve_deleted_runtime_skills: bool = True,
) -> None:
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
    os.makedirs(target_dir, exist_ok=True)

    folder_map = build_task_skill_folder_map(skills)
    manifest_items: List[Dict[str, object]] = []
    for skill in skills:
        folder_name = folder_map.get(skill.id) or storage_service.sanitize_name_for_folder(skill.name)
        skill_target_dir = os.path.join(target_dir, folder_name)
        _copy_single_skill_package(skill, skill_target_dir)
        manifest_items.append(_runtime_skill_manifest_item(skill, folder_name))

    if preserve_from_dir and preserve_deleted_runtime_skills:
        manifest_items.extend(
            _preserve_existing_runtime_skill_dirs(
                source_dir=preserve_from_dir,
                target_dir=target_dir,
                current_skill_ids={skill.id for skill in skills},
                used_folders=set(folder_map.values()),
            )
        )

    _write_runtime_manifest(target_dir, manifest_items)


def _replace_skills_atomically(
    skills: List[SddSkill],
    target_dir: str,
    *,
    preserve_deleted_runtime_skills: bool = True,
) -> None:
    parent_dir = os.path.dirname(os.path.abspath(target_dir))
    os.makedirs(parent_dir, exist_ok=True)

    suffix = uuid.uuid4().hex
    tmp_dir = f"{target_dir}.__tmp__.{suffix}"
    old_dir = f"{target_dir}.__old__.{suffix}"
    moved_old = False

    try:
        _copy_skills_to_target(
            skills,
            tmp_dir,
            preserve_from_dir=target_dir,
            preserve_deleted_runtime_skills=preserve_deleted_runtime_skills,
        )
        if os.path.exists(target_dir):
            os.replace(target_dir, old_dir)
            moved_old = True
        os.replace(tmp_dir, target_dir)
        if moved_old and os.path.exists(old_dir):
            shutil.rmtree(old_dir, ignore_errors=True)
    except Exception:
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)
        if moved_old and os.path.exists(old_dir) and not os.path.exists(target_dir):
            os.replace(old_dir, target_dir)
        raise


def materialize_task_skills(
    db: Session,
    task_id: str,
    *,
    preserve_deleted_runtime_skills: bool = True,
) -> List[str]:
    task = db.query(SddTask).filter(SddTask.id == task_id).first()
    if not task:
        raise ValueError("Task not found")

    from app.domains.local_resource.service import is_local, execute
    if is_local(task):
        import tempfile
        import base64
        import hashlib
        from pathlib import Path
        with tempfile.TemporaryDirectory(prefix="tf-skills-") as staging:
            destination = Path(staging) / "skills"
            _replace_skills_atomically(skill_runtime_bindings.get_task_skills(db, task_id), str(destination), preserve_deleted_runtime_skills=False)
            rel_root = skill_runtime_layout.resolve_task_skills_rel_root(db, task).replace("\\", "/")
            files = []
            for path in destination.rglob("*"):
                if path.is_file():
                    content = path.read_bytes()
                    files.append({"path": rel_root + "/" + path.relative_to(destination).as_posix(),
                                  "content": base64.b64encode(content).decode(), "sha256": hashlib.sha256(content).hexdigest()})
            execute(db, task, "skills", {"action": "replace", "files": files, "preserve": preserve_deleted_runtime_skills})
        return [rel_root]

    skills = skill_runtime_bindings.get_task_skills(db, task_id)
    copied_targets = [skill_runtime_layout.resolve_task_skills_root(db, task)]

    for target in copied_targets:
        _replace_skills_atomically(
            skills,
            target,
            preserve_deleted_runtime_skills=preserve_deleted_runtime_skills,
        )

    return copied_targets
