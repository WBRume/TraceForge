"""
Filesystem helpers for package-based skill storage.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import time
import unicodedata
from typing import Dict, Iterable, List, Optional

from app.config import settings
from app.domains.skill.models.skill import SddSkill, SkillDimension


class SkillStorageError(ValueError):
    pass


_WINDOWS_INVALID_CHARS = set('<>:"/\\|?*')
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}
_WINDOWS_SAFE_MAX_PATH = 240
_POSIX_SAFE_MAX_PATH = 4096
_WINDOWS_COMPONENT_MAX = 255
_POSIX_COMPONENT_MAX_BYTES = 255
_SKILL_PACKAGE_REL_PATH_MAX_CHARS = 500


def _skills_root() -> str:
    root_value = str(settings.SKILLS_STORAGE_ROOT or "").strip()
    if not root_value:
        raise SkillStorageError("SKILLS_STORAGE_ROOT is not configured")
    root = os.path.abspath(root_value)
    os.makedirs(root, exist_ok=True)
    return root


def is_windows_platform() -> bool:
    return os.name == "nt"


def os_path_limit() -> int:
    return _WINDOWS_SAFE_MAX_PATH if is_windows_platform() else _POSIX_SAFE_MAX_PATH


def measure_path_length(path: str) -> int:
    normalized = os.path.abspath(str(path or ""))
    if is_windows_platform():
        return len(normalized)
    return len(normalized.encode("utf-8", errors="ignore"))


def _measure_component_length(name: str) -> int:
    normalized = str(name or "")
    if is_windows_platform():
        return len(normalized)
    return len(normalized.encode("utf-8", errors="ignore"))


def _truncate_component_by_limit(value: str, limit: int) -> str:
    text = str(value or "")
    if limit <= 0 or not text:
        return ""
    if is_windows_platform():
        return text[:limit]

    current = 0
    kept: List[str] = []
    for ch in text:
        cost = len(ch.encode("utf-8", errors="ignore"))
        if current + cost > limit:
            break
        kept.append(ch)
        current += cost
    return "".join(kept)


def _sanitize_folder_component(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("/", "_").replace("\\", "_")
    sanitized_chars: List[str] = []
    for ch in text:
        code = ord(ch)
        if code == 0 or code < 32:
            sanitized_chars.append("_")
            continue
        if is_windows_platform() and ch in _WINDOWS_INVALID_CHARS:
            sanitized_chars.append("_")
            continue
        sanitized_chars.append(ch)

    normalized = "".join(sanitized_chars)
    normalized = re.sub(r"\s+", "_", normalized, flags=re.UNICODE)
    normalized = re.sub(r"_+", "_", normalized, flags=re.UNICODE)
    normalized = normalized.strip("._- ")
    if is_windows_platform():
        normalized = normalized.rstrip(" .")

    if not normalized:
        return ""

    if is_windows_platform():
        stem = normalized.split(".", 1)[0].upper()
        if stem in _WINDOWS_RESERVED_NAMES:
            normalized = f"_{normalized}"

    return normalized


def build_id_named_folder(
    entity_id: str,
    display_name: Optional[str],
    *,
    parent_abs_path: Optional[str] = None,
    rel_parent_path: Optional[str] = None,
    max_rel_path_chars: Optional[int] = None,
) -> str:
    base_id = str(entity_id or "").strip()
    if not base_id:
        raise SkillStorageError("entity_id is required for folder naming")

    name_part = _sanitize_folder_component(str(display_name or ""))
    if not name_part:
        return base_id

    prefix = f"{base_id}__"
    allowed = (
        _WINDOWS_COMPONENT_MAX - _measure_component_length(prefix)
        if is_windows_platform()
        else _POSIX_COMPONENT_MAX_BYTES - _measure_component_length(prefix)
    )
    if allowed <= 0:
        return base_id

    if parent_abs_path:
        prefix_abs = os.path.abspath(os.path.join(parent_abs_path, prefix))
        allowed = min(allowed, os_path_limit() - measure_path_length(prefix_abs))
    if rel_parent_path is not None and max_rel_path_chars is not None:
        rel_prefix = normalize_path(os.path.join(rel_parent_path, prefix))
        allowed = min(allowed, max_rel_path_chars - len(rel_prefix))

    if allowed <= 0:
        return base_id

    truncated_name = _truncate_component_by_limit(name_part, allowed).strip("._- ")
    if not truncated_name:
        return base_id

    candidate = f"{prefix}{truncated_name}"
    if parent_abs_path:
        candidate_abs = os.path.abspath(os.path.join(parent_abs_path, candidate))
        if measure_path_length(candidate_abs) > os_path_limit():
            return base_id
    if rel_parent_path is not None and max_rel_path_chars is not None:
        rel_candidate = normalize_path(os.path.join(rel_parent_path, candidate))
        if len(rel_candidate) > max_rel_path_chars:
            return base_id

    return candidate


def normalize_path(path: str) -> str:
    return str(path or "").replace("\\", "/")


def normalize_relative_path(path: str) -> str:
    normalized = normalize_path(path).strip().strip("/")
    if not normalized:
        raise SkillStorageError("Path is required")
    if os.path.isabs(normalized):
        raise SkillStorageError("Absolute path is not allowed")
    segments = [seg for seg in normalized.split("/") if seg]
    if not segments:
        raise SkillStorageError("Path is invalid")
    for seg in segments:
        if seg in {".", ".."}:
            raise SkillStorageError("Path traversal is not allowed")
        if "\x00" in seg:
            raise SkillStorageError("Path is invalid")
    return "/".join(segments)


def ensure_root_relative(path: str) -> str:
    root = _skills_root()
    rel = normalize_relative_path(path)
    abs_path = os.path.abspath(os.path.join(root, rel))
    if os.path.commonpath([root, abs_path]) != root:
        raise SkillStorageError("Path escapes skill storage root")
    return abs_path


def package_relative_path(
    skill_id: str,
    dimension: SkillDimension,
    workspace_id: Optional[str],
    skill_name: Optional[str] = None,
) -> str:
    if dimension == SkillDimension.GLOBAL:
        parent_rel = "global"
    else:
        if not workspace_id:
            raise SkillStorageError("workspace_id is required for WORKSPACE skill")
        parent_rel = normalize_path(os.path.join("workspace", workspace_id))

    parent_abs = os.path.join(_skills_root(), parent_rel)
    folder = build_id_named_folder(
        skill_id,
        skill_name,
        parent_abs_path=parent_abs,
        rel_parent_path=parent_rel,
        max_rel_path_chars=_SKILL_PACKAGE_REL_PATH_MAX_CHARS,
    )
    rel_path = normalize_path(os.path.join(parent_rel, folder))
    if len(rel_path) > _SKILL_PACKAGE_REL_PATH_MAX_CHARS:
        raise SkillStorageError("Skill package path exceeds max length")
    abs_path = os.path.abspath(os.path.join(_skills_root(), rel_path))
    if measure_path_length(abs_path) > os_path_limit():
        raise SkillStorageError("Skill package path is too long for current operating system")
    return rel_path


def package_abs_path(skill: SddSkill) -> str:
    return ensure_root_relative(skill.package_path)


def package_abs_path_from_relative(package_path: str) -> str:
    return ensure_root_relative(package_path)


def remove_package_dir(package_abs_path: str) -> None:
    root = _skills_root()
    target = os.path.abspath(str(package_abs_path or "").strip())
    if not target:
        raise SkillStorageError("Package path is required")
    if os.path.commonpath([root, target]) != root:
        raise SkillStorageError("Path escapes skill storage root")
    if not os.path.lexists(target):
        return

    def _onerror(func, path, _exc_info):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception:
            pass

    last_error: Optional[Exception] = None
    for attempt in range(5):
        try:
            shutil.rmtree(target, onerror=_onerror)
            break
        except FileNotFoundError:
            return
        except Exception as exc:  # pragma: no cover - runtime filesystem specific
            last_error = exc
            time.sleep(0.12 * (attempt + 1))

    if os.path.exists(target):
        if last_error:
            raise SkillStorageError(f"Failed to delete skill package directory: {last_error}") from last_error
        raise SkillStorageError("Failed to delete skill package directory")


def safe_join_package_file(skill: SddSkill, relative_path: str) -> str:
    package_root = package_abs_path(skill)
    rel = normalize_relative_path(relative_path)
    target = os.path.abspath(os.path.join(package_root, rel))
    if os.path.commonpath([package_root, target]) != package_root:
        raise SkillStorageError("Path escapes skill package root")
    return target


def init_package_layout(
    *,
    skill: SddSkill,
    entry_file_path: str,
    manifest_path: Optional[str],
    entry_content: str,
    manifest_content: Optional[str] = None,
    initial_entries: Optional[List[Dict[str, object]]] = None,
) -> None:
    root = package_abs_path(skill)
    if os.path.exists(root):
        shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root, exist_ok=True)

    normalized_entry = normalize_relative_path(entry_file_path)
    entry_abs = safe_join_package_file(skill, normalized_entry)
    entries = list(initial_entries or [])

    if entries:
        seen_paths: set[str] = set()
        for item in entries:
            raw_path = str((item or {}).get("path") or "").strip()
            if not raw_path:
                raise SkillStorageError("Initial entry path is required")
            normalized_path = normalize_relative_path(raw_path)
            if normalized_path in seen_paths:
                raise SkillStorageError(f"Duplicate initial entry path: {normalized_path}")
            seen_paths.add(normalized_path)

            node_type = str((item or {}).get("node_type") or "file").strip().lower()
            if node_type not in {"file", "directory"}:
                raise SkillStorageError(f"Unsupported initial entry node_type: {node_type}")

            target_abs = safe_join_package_file(skill, normalized_path)
            if node_type == "directory":
                os.makedirs(target_abs, exist_ok=True)
                continue

            os.makedirs(os.path.dirname(target_abs), exist_ok=True)
            payload = _normalize_text_for_storage(str((item or {}).get("content") or ""))
            with open(target_abs, "w", encoding="utf-8", newline="") as file:
                file.write(payload)
    else:
        os.makedirs(os.path.dirname(entry_abs), exist_ok=True)
        with open(entry_abs, "w", encoding="utf-8", newline="") as file:
            file.write(_normalize_text_for_storage(str(entry_content or "")))

    if not os.path.isfile(entry_abs):
        os.makedirs(os.path.dirname(entry_abs), exist_ok=True)
        with open(entry_abs, "w", encoding="utf-8", newline="") as file:
            file.write(_normalize_text_for_storage(str(entry_content or "")))

    if manifest_content is not None:
        if not manifest_path:
            raise SkillStorageError("manifest_path is required when manifest_content is provided")
        normalized_manifest = normalize_relative_path(manifest_path)
        manifest_abs = safe_join_package_file(skill, normalized_manifest)
        os.makedirs(os.path.dirname(manifest_abs), exist_ok=True)
        with open(manifest_abs, "w", encoding="utf-8", newline="") as file:
            file.write(_normalize_text_for_storage(str(manifest_content)))


def import_package_from_directory(*, skill: SddSkill, source_dir: str) -> None:
    source_root = os.path.abspath(str(source_dir or "").strip())
    if not source_root or not os.path.isdir(source_root):
        raise SkillStorageError("Source skill directory does not exist")
    if os.path.islink(source_root):
        raise SkillStorageError("Symlink is not allowed in skill package")

    target_root = package_abs_path(skill)
    if os.path.exists(target_root):
        shutil.rmtree(target_root, ignore_errors=True)
    os.makedirs(target_root, exist_ok=True)

    for walk_root, dir_names, file_names in os.walk(source_root, topdown=True, followlinks=False):
        rel_walk = os.path.relpath(walk_root, source_root)
        rel_prefix = "" if rel_walk in {".", ""} else normalize_path(rel_walk)

        filtered_dirs: List[str] = []
        for dir_name in dir_names:
            src_dir = os.path.join(walk_root, dir_name)
            if os.path.islink(src_dir):
                raise SkillStorageError("Symlink is not allowed in skill package")
            if dir_name == ".git":
                continue
            filtered_dirs.append(dir_name)

            rel_dir = normalize_path(os.path.join(rel_prefix, dir_name)) if rel_prefix else dir_name
            dst_dir = safe_join_package_file(skill, rel_dir)
            os.makedirs(dst_dir, exist_ok=True)
        dir_names[:] = filtered_dirs

        for file_name in file_names:
            src_file = os.path.join(walk_root, file_name)
            if os.path.islink(src_file):
                raise SkillStorageError("Symlink is not allowed in skill package")

            rel_file = normalize_path(os.path.join(rel_prefix, file_name)) if rel_prefix else file_name
            if rel_file == ".git" or rel_file.startswith(".git/"):
                continue
            dst_file = safe_join_package_file(skill, rel_file)
            os.makedirs(os.path.dirname(dst_file), exist_ok=True)
            with open(src_file, "rb") as src_handle:
                payload = src_handle.read()
            with open(dst_file, "wb") as dst_handle:
                dst_handle.write(payload)


def replace_package_contents_from_directory(*, skill: SddSkill, source_dir: str) -> None:
    source_root = os.path.abspath(str(source_dir or "").strip())
    if not source_root or not os.path.isdir(source_root):
        raise SkillStorageError("Source skill directory does not exist")
    if os.path.islink(source_root):
        raise SkillStorageError("Symlink is not allowed in skill package")

    # Validate before deleting the existing package so a hostile or malformed
    # upstream repo cannot leave the local package half-replaced.
    for walk_root, dir_names, file_names in os.walk(source_root, topdown=True, followlinks=False):
        dir_names[:] = [dir_name for dir_name in dir_names if dir_name != ".git"]
        for dir_name in dir_names:
            if os.path.islink(os.path.join(walk_root, dir_name)):
                raise SkillStorageError("Symlink is not allowed in skill package")
        for file_name in file_names:
            if os.path.islink(os.path.join(walk_root, file_name)):
                raise SkillStorageError("Symlink is not allowed in skill package")

    target_root = package_abs_path(skill)
    os.makedirs(target_root, exist_ok=True)

    for name in os.listdir(target_root):
        if name in {".git", ".sdd-internal"}:
            continue
        abs_path = os.path.join(target_root, name)
        if os.path.isdir(abs_path) and not os.path.islink(abs_path):
            shutil.rmtree(abs_path)
        else:
            os.remove(abs_path)

    for walk_root, dir_names, file_names in os.walk(source_root, topdown=True, followlinks=False):
        rel_walk = os.path.relpath(walk_root, source_root)
        rel_prefix = "" if rel_walk in {".", ""} else normalize_path(rel_walk)

        filtered_dirs: List[str] = []
        for dir_name in dir_names:
            src_dir = os.path.join(walk_root, dir_name)
            if os.path.islink(src_dir):
                raise SkillStorageError("Symlink is not allowed in skill package")
            if dir_name == ".git":
                continue
            filtered_dirs.append(dir_name)

            rel_dir = normalize_path(os.path.join(rel_prefix, dir_name)) if rel_prefix else dir_name
            os.makedirs(safe_join_package_file(skill, rel_dir), exist_ok=True)
        dir_names[:] = filtered_dirs

        for file_name in file_names:
            src_file = os.path.join(walk_root, file_name)
            if os.path.islink(src_file):
                raise SkillStorageError("Symlink is not allowed in skill package")

            rel_file = normalize_path(os.path.join(rel_prefix, file_name)) if rel_prefix else file_name
            if rel_file == ".git" or rel_file.startswith(".git/"):
                continue
            dst_file = safe_join_package_file(skill, rel_file)
            os.makedirs(os.path.dirname(dst_file), exist_ok=True)
            with open(src_file, "rb") as src_handle:
                payload = src_handle.read()
            with open(dst_file, "wb") as dst_handle:
                dst_handle.write(payload)


def list_worktree_files(skill: SddSkill) -> List[str]:
    root = package_abs_path(skill)
    if not os.path.isdir(root):
        return []
    result: List[str] = []
    for walk_root, dir_names, file_names in os.walk(root):
        dir_names[:] = [name for name in dir_names if name not in {".git", ".sdd-internal"}]
        for file_name in file_names:
            abs_file = os.path.join(walk_root, file_name)
            rel = normalize_path(os.path.relpath(abs_file, root))
            if rel.startswith(".git/"):
                continue
            result.append(rel)
    result.sort(key=str.lower)
    return result


def list_worktree_entries(skill: SddSkill) -> List[Dict[str, str]]:
    root = package_abs_path(skill)
    if not os.path.isdir(root):
        return []
    result: List[Dict[str, str]] = []
    for walk_root, dir_names, file_names in os.walk(root):
        dir_names[:] = [name for name in dir_names if name not in {".git", ".sdd-internal"}]

        for dir_name in dir_names:
            abs_dir = os.path.join(walk_root, dir_name)
            rel_dir = normalize_path(os.path.relpath(abs_dir, root))
            if rel_dir.startswith(".git/"):
                continue
            result.append({"path": rel_dir, "node_type": "directory"})

        for file_name in file_names:
            abs_file = os.path.join(walk_root, file_name)
            rel_file = normalize_path(os.path.relpath(abs_file, root))
            if rel_file.startswith(".git/"):
                continue
            result.append({"path": rel_file, "node_type": "file"})

    result.sort(key=lambda item: (item["path"].lower(), 0 if item["node_type"] == "directory" else 1))
    return result


def build_tree(paths: Iterable[object]) -> List[Dict[str, object]]:
    root: Dict[str, Dict[str, object]] = {}

    for raw_item in paths:
        node_type = "file"
        raw_path = raw_item
        if isinstance(raw_item, dict):
            raw_path = raw_item.get("path")  # type: ignore[assignment]
            raw_type = str(raw_item.get("node_type") or "file").lower()
            node_type = "directory" if raw_type == "directory" else "file"

        rel = normalize_relative_path(str(raw_path or ""))
        segments = rel.split("/")
        cursor = root
        for index, segment in enumerate(segments):
            is_last = index == len(segments) - 1
            inferred_type = node_type if is_last else "directory"
            if segment not in cursor:
                cursor[segment] = {
                    "name": segment,
                    "node_type": inferred_type,
                    "_children": {},
                }
            node = cursor[segment]
            if not is_last:
                node["node_type"] = "directory"
                cursor = node["_children"]  # type: ignore[index]
            elif inferred_type == "directory":
                node["node_type"] = "directory"

    def _to_nodes(children_map: Dict[str, Dict[str, object]], prefix: str = "") -> List[Dict[str, object]]:
        nodes: List[Dict[str, object]] = []
        for name in sorted(children_map.keys(), key=str.lower):
            node = children_map[name]
            path = f"{prefix}/{name}" if prefix else name
            payload: Dict[str, object] = {
                "name": name,
                "path": path,
                "node_type": str(node.get("node_type") or "file"),
                "children": [],
            }
            nested = node.get("_children")
            if isinstance(nested, dict) and nested:
                payload["children"] = _to_nodes(nested, path)
            else:
                payload["children"] = []
            nodes.append(payload)
        return nodes

    return _to_nodes(root)


def read_worktree_file(skill: SddSkill, path: str) -> bytes:
    abs_path = safe_join_package_file(skill, path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"File not found: {path}")
    with open(abs_path, "rb") as file:
        return file.read()


def is_binary_bytes(data: bytes) -> bool:
    if not data:
        return False
    if b"\x00" in data:
        return True
    try:
        data.decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True


def write_worktree_text_file(skill: SddSkill, path: str, content: str) -> int:
    normalized = normalize_relative_path(path)
    payload = _normalize_text_for_storage(str(content or ""))
    max_size = int(getattr(settings, "SKILL_MAX_TEXT_FILE_SIZE_BYTES", 10 * 1024 * 1024))
    encoded = payload.encode("utf-8")
    if len(encoded) > max_size:
        raise SkillStorageError(f"File exceeds max text size ({max_size} bytes)")
    target = safe_join_package_file(skill, normalized)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="") as file:
        file.write(payload)
    return len(encoded)


def create_worktree_node(skill: SddSkill, path: str, node_type: str, content: Optional[str] = None) -> None:
    normalized = normalize_relative_path(path)
    target = safe_join_package_file(skill, normalized)
    if os.path.exists(target):
        raise SkillStorageError("Path already exists")
    if node_type == "directory":
        os.makedirs(target, exist_ok=False)
        return
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="") as file:
        file.write(_normalize_text_for_storage(str(content or "")))


def delete_worktree_path(skill: SddSkill, path: str) -> None:
    normalized = normalize_relative_path(path)
    target = safe_join_package_file(skill, normalized)
    if not os.path.lexists(target):
        raise FileNotFoundError("Path not found")
    if os.path.islink(target):
        raise SkillStorageError("Symlink is not allowed in skill package")
    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=False)
    else:
        os.remove(target)


def move_worktree_path(skill: SddSkill, old_path: str, new_path: str) -> None:
    old_normalized = normalize_relative_path(old_path)
    new_normalized = normalize_relative_path(new_path)
    source = safe_join_package_file(skill, old_normalized)
    target = safe_join_package_file(skill, new_normalized)
    if not os.path.lexists(source):
        raise FileNotFoundError("Source path not found")
    if os.path.lexists(target):
        raise SkillStorageError("Target path already exists")
    if os.path.islink(source):
        raise SkillStorageError("Symlink is not allowed in skill package")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.move(source, target)


def sanitize_name_for_folder(name: str) -> str:
    normalized = _sanitize_folder_component(name)
    if not normalized:
        return "skill"
    limit = min(96, _WINDOWS_COMPONENT_MAX if is_windows_platform() else _POSIX_COMPONENT_MAX_BYTES)
    truncated = _truncate_component_by_limit(normalized, limit).strip("._- ")
    return truncated or "skill"


def _normalize_text_for_storage(value: str) -> str:
    text = str(value or "")
    # Defensive normalization for previously introduced CR duplication on Windows.
    text = text.replace("\r\r\n", "\r\n")
    return text
