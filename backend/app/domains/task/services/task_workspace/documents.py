"""List and edit task document changes in workspace-configured directories."""

import os
from datetime import datetime
from pathlib import Path

from app.domains.task.models.task import SddTask
from app.domains.task.services.plan_doc_baseline import document_changed, load_baseline
from app.domains.task.services.plan_doc_paths import normalize_plan_doc_roots
from app.domains.task.services.task_doc_scan import TASK_DOC_EXTENSIONS


def _roots(task: SddTask) -> list[str]:
    return normalize_plan_doc_roots(list(task.workspace.plan_doc_roots or []))


def _project_root(task: SddTask) -> Path:
    if not task.project_path:
        raise ValueError("Task project path is missing")
    return Path(task.project_path).resolve()


def _directories(task: SddTask) -> list[Path]:
    project = _project_root(task)
    directories = []
    for relative in _roots(task):
        directory = (project / relative).resolve()
        if not directory.is_relative_to(project):
            raise ValueError("Document directory is outside the task root")
        directories.append(directory)
    return directories


def _section(relative: str) -> str:
    return "specs" if "specs" in relative.lower().split("/")[:-1] else "plans"


def _entry(project: Path, file_path: Path) -> dict:
    relative = file_path.relative_to(project).as_posix()
    stat = file_path.stat()
    return {
        "section": _section(relative),
        "name": file_path.name,
        "section_path": relative,
        "relative_path": relative,
        "size": stat.st_size,
        "updated_at": datetime.fromtimestamp(stat.st_mtime),
    }


def _local_operation(task: SddTask, action: str, **kwargs) -> dict:
    from app.domains.local_resource.service import task_operation
    from app.domains.local_resource.snapshots import decode

    checkpoint = (task.task_meta_json or {}).get("initial_workspace_checkpoint")
    initial = None
    if checkpoint:
        owner, initial = decode(checkpoint)
        if owner != task.id:
            raise ValueError("Plan document baseline belongs to a different task")
    return task_operation(
        task.id,
        "documents",
        {
            "action": action,
            "roots": _roots(task),
            "initial_checkpoint": initial,
            **kwargs,
        },
    )


def list_plan_docs(task: SddTask) -> dict:
    from app.domains.local_resource.service import is_local

    roots = _roots(task)
    payload = {
        "task_id": task.id,
        "root_relative_path": ", ".join(roots),
        "configured": bool(roots),
        "baseline_available": False,
        "plans": [],
        "specs": [],
    }
    if not roots:
        return payload
    if is_local(task):
        return _local_operation(task, "list")
    baseline = load_baseline(task)
    if baseline is None:
        return payload
    payload["baseline_available"] = True
    project = _project_root(task)
    seen: set[str] = set()
    excluded = set(baseline.get("policy", {}).get("excluded_dirs", [])) | {".git"}
    for directory in _directories(task):
        for parent, dirs, files in os.walk(directory, followlinks=False):
            dirs[:] = [name for name in dirs if name not in excluded and not (Path(parent) / name).is_symlink()]
            for name in files:
                file_path = Path(parent) / name
                if file_path.is_symlink() or file_path.suffix.lower() not in TASK_DOC_EXTENSIONS:
                    continue
                file_path = file_path.resolve()
                if not file_path.is_relative_to(directory) or not file_path.is_relative_to(project):
                    continue
                relative = file_path.relative_to(project).as_posix()
                seen_key = os.path.normcase(relative)
                if seen_key in seen:
                    continue
                seen.add(seen_key)
                try:
                    if document_changed(baseline, relative, file_path):
                        entry = _entry(project, file_path)
                        payload[entry["section"]].append(entry)
                except FileNotFoundError:
                    continue
    for section in ("plans", "specs"):
        payload[section].sort(key=lambda item: item["relative_path"].lower())
    return payload


def _resolve_path(task: SddTask, section: str, name: str | None, path: str | None) -> Path:
    if section not in {"plans", "specs"}:
        raise ValueError("Invalid document section")
    relative = str(path or name or "").strip().replace("\\", "/")
    normalize_plan_doc_roots([relative])
    if Path(relative).suffix.lower() not in TASK_DOC_EXTENSIONS:
        raise ValueError("Only markdown files (.md/.markdown) are supported")
    project = _project_root(task)
    candidate = (project / relative).resolve()
    if not candidate.is_relative_to(project) or not any(candidate.is_relative_to(root) for root in _directories(task)):
        raise ValueError("Document is outside configured directories")
    if _section(relative) != section:
        raise ValueError("Document section differs")
    return candidate


def read_plan_doc(task: SddTask, section: str, name: str | None = None, path: str | None = None) -> dict:
    from app.domains.local_resource.service import is_local

    if is_local(task):
        return _local_operation(task, "read", section=section, path=path or name)
    file_path = _resolve_path(task, section, name, path)
    return {
        "task_id": task.id,
        **_entry(_project_root(task), file_path),
        "content": file_path.read_text(encoding="utf-8"),
    }


def save_plan_doc(task: SddTask, section: str, content: str, name: str | None = None, path: str | None = None) -> dict:
    from app.domains.local_resource.service import is_local

    if is_local(task):
        return _local_operation(task, "save", section=section, path=path or name, content=content)
    file_path = _resolve_path(task, section, name, path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return {"task_id": task.id, **_entry(_project_root(task), file_path), "content": content}
