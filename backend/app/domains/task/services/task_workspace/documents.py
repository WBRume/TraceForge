"""Create workspace-local plan and specification documents."""

from datetime import datetime
from pathlib import Path

from app.domains.task.models.task import SddTask
from app.domains.task.services.task_doc_scan import TASK_DOC_EXTENSIONS, plan_doc_root_label, plan_doc_root_parts

SUPERPOWERS_DOC_SECTIONS = {"plans", "specs"}


def _normalize_superpowers_doc_section(section: str) -> str:
    normalized = str(section or "").strip().lower()
    if normalized not in SUPERPOWERS_DOC_SECTIONS:
        raise ValueError("Invalid section. Expected 'plans' or 'specs'")
    return normalized


def _normalize_superpowers_doc_section_path(*, name: str | None = None, path: str | None = None) -> str:
    raw = str(path or "").strip() or str(name or "").strip()
    if not raw:
        raise ValueError("Document path is required")

    normalized = raw.replace("\\", "/").strip("/")
    if not normalized:
        raise ValueError("Document path is invalid")

    segments = normalized.split("/")
    for segment in segments:
        if not segment or segment in {".", ".."}:
            raise ValueError("Document path is invalid")
        if "\x00" in segment:
            raise ValueError("Document path is invalid")

    if Path(segments[-1]).suffix.lower() not in TASK_DOC_EXTENSIONS:
        raise ValueError("Only markdown files (.md/.markdown) are supported")
    return "/".join(segments)


def _task_project_root(task: SddTask) -> Path:
    project_path = str(task.project_path or "").strip()
    if not project_path:
        raise ValueError("Task project path is missing")
    return Path(project_path).resolve()


def _superpowers_docs_root_candidates(task: SddTask) -> list[Path]:
    project_root = _task_project_root(task)
    seen: set[str] = set()
    roots: list[Path] = []
    for rel_parts in plan_doc_root_parts():
        root = (project_root.joinpath(*rel_parts)).resolve()
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        roots.append(root)
    return roots


def _is_path_within(base: Path, target: Path) -> bool:
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False


def _resolve_superpowers_doc_path(
    task: SddTask,
    section: str,
    *,
    name: str | None = None,
    path: str | None = None,
    for_write: bool = False,
) -> tuple[Path, str]:
    normalized_section = _normalize_superpowers_doc_section(section)
    normalized_section_path = _normalize_superpowers_doc_section_path(name=name, path=path)
    project_root = _task_project_root(task)

    fallback_candidate: Path | None = None
    existing_parent_candidate: Path | None = None
    existing_section_candidate: Path | None = None

    for root in _superpowers_docs_root_candidates(task):
        section_dir = (root / normalized_section).resolve()
        file_path = (section_dir / normalized_section_path).resolve()
        if not _is_path_within(section_dir, file_path):
            continue
        if not _is_path_within(project_root, file_path):
            continue
        if fallback_candidate is None:
            fallback_candidate = file_path
        if file_path.exists() and file_path.is_file():
            return file_path, normalized_section_path
        if section_dir.exists() and section_dir.is_dir():
            if file_path.parent.exists() and file_path.parent.is_dir() and existing_parent_candidate is None:
                existing_parent_candidate = file_path
            if existing_section_candidate is None:
                existing_section_candidate = file_path

    if for_write:
        if existing_parent_candidate is not None:
            return existing_parent_candidate, normalized_section_path
        if existing_section_candidate is not None:
            return existing_section_candidate, normalized_section_path
        if fallback_candidate is not None:
            return fallback_candidate, normalized_section_path
        raise ValueError("Cannot resolve target path for plan document")

    raise FileNotFoundError(f"Plan document not found: {normalized_section}/{normalized_section_path}")


def _serialize_superpowers_doc_entry(
    project_root: Path,
    section: str,
    section_root: Path,
    file_path: Path,
) -> dict:
    stat = file_path.stat()
    resolved = file_path.resolve()
    return {
        "section": section,
        "name": resolved.name,
        "section_path": resolved.relative_to(section_root.resolve()).as_posix(),
        "relative_path": resolved.relative_to(project_root).as_posix(),
        "size": int(stat.st_size),
        "updated_at": datetime.fromtimestamp(stat.st_mtime),
    }


def _list_superpowers_docs_in_section(task: SddTask, section: str) -> list[dict]:
    normalized_section = _normalize_superpowers_doc_section(section)
    project_root = _task_project_root(task)
    seen_paths: set[str] = set()
    entries: list[dict] = []
    for root in _superpowers_docs_root_candidates(task):
        section_dir = (root / normalized_section).resolve()
        if not section_dir.exists() or not section_dir.is_dir():
            continue
        if not _is_path_within(project_root, section_dir):
            continue
        for child in sorted(section_dir.rglob("*"), key=lambda item: item.as_posix().lower()):
            if not child.is_file():
                continue
            if child.suffix.lower() not in TASK_DOC_EXTENSIONS:
                continue
            resolved_child = child.resolve()
            if not _is_path_within(project_root, resolved_child):
                continue
            rel = resolved_child.relative_to(project_root).as_posix()
            rel_key = rel.lower()
            if rel_key in seen_paths:
                continue
            seen_paths.add(rel_key)
            entries.append(
                _serialize_superpowers_doc_entry(
                    project_root,
                    normalized_section,
                    section_dir,
                    resolved_child,
                )
            )

    entries.sort(key=lambda item: item["section_path"].lower())
    return entries


def list_superpowers_docs(task: SddTask) -> dict:
    from app.domains.local_resource.service import is_local, task_operation

    if is_local(task):
        return task_operation(task.id, "documents", {"action": "list"})
    return {
        "task_id": task.id,
        "root_relative_path": plan_doc_root_label(),
        "plans": _list_superpowers_docs_in_section(task, "plans"),
        "specs": _list_superpowers_docs_in_section(task, "specs"),
    }


def read_superpowers_doc(
    task: SddTask,
    section: str,
    name: str | None = None,
    path: str | None = None,
) -> dict:
    from app.domains.local_resource.service import is_local, task_operation

    if is_local(task):
        return task_operation(task.id, "documents", {"action": "read", "section": section, "path": path or name})
    file_path, section_path = _resolve_superpowers_doc_path(
        task,
        section,
        name=name,
        path=path,
        for_write=False,
    )
    project_root = _task_project_root(task)
    content = file_path.read_text(encoding="utf-8")
    return {
        "task_id": task.id,
        "section": _normalize_superpowers_doc_section(section),
        "name": file_path.name,
        "section_path": section_path,
        "relative_path": file_path.resolve().relative_to(project_root).as_posix(),
        "content": content,
        "updated_at": datetime.fromtimestamp(file_path.stat().st_mtime),
    }


def save_superpowers_doc(
    task: SddTask,
    section: str,
    content: str,
    name: str | None = None,
    path: str | None = None,
) -> dict:
    from app.domains.local_resource.service import is_local, task_operation

    if is_local(task):
        return task_operation(
            task.id, "documents", {"action": "save", "section": section, "path": path or name, "content": content}
        )
    file_path, section_path = _resolve_superpowers_doc_path(
        task,
        section,
        name=name,
        path=path,
        for_write=True,
    )
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(str(content or ""), encoding="utf-8")
    project_root = _task_project_root(task)

    return {
        "task_id": task.id,
        "section": _normalize_superpowers_doc_section(section),
        "name": file_path.name,
        "section_path": section_path,
        "relative_path": file_path.resolve().relative_to(project_root).as_posix(),
        "content": str(content or ""),
        "updated_at": datetime.fromtimestamp(file_path.stat().st_mtime),
    }
