"""Configurable task document scanning paths.

The platform historically scanned Superpowers-style directories
(``docs/superpowers``).  Task execution no longer hard-depends on that
layout, so the scan roots/entries are read from settings and can be
pointed at any project-relative markdown directories or files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from app.config import settings

TASK_DOC_EXTENSIONS = {".md", ".markdown"}


def _split_csv(raw: Optional[str]) -> List[str]:
    return [part.strip() for part in str(raw or "").split(",") if part.strip()]


def plan_doc_root_parts() -> List[Tuple[str, ...]]:
    """Return plan/spec markdown root directories as relative path tuples.

    ``.`` is normalized to an empty tuple (project root itself).
    """
    roots: List[Tuple[str, ...]] = []
    for rel in _split_csv(settings.TASK_PLAN_DOC_ROOTS):
        normalized = rel.replace("\\", "/").strip("/")
        if normalized in ("", "."):
            roots.append(())
        else:
            roots.append(tuple(part for part in normalized.split("/") if part))
    return roots


def plan_doc_root_label() -> str:
    """Human/UI friendly representation of configured plan/spec roots."""
    labels = []
    for parts in plan_doc_root_parts():
        labels.append("/".join(parts) if parts else ".")
    return ", ".join(labels) if labels else "docs/superpowers"


def rule_doc_scan_paths() -> List[str]:
    """Project-relative files/directories scanned into task context."""
    return _split_csv(settings.TASK_RULE_DOC_SCAN_PATHS)


def iter_task_rule_docs(project_path: Path) -> Iterable[Path]:
    """Yield markdown files from configured rule/document scan entries.

    Files are yielded if their extension is markdown.  Directories are
    recursed and only markdown files are yielded.  Duplicates across
    overlapping entries are removed.
    """
    project_root = Path(project_path).resolve()
    seen: set[str] = set()
    for rel in rule_doc_scan_paths():
        rel = rel.replace("\\", "/")
        if not rel:
            continue
        candidate = project_root.joinpath(*rel.split("/")).resolve()
        if not candidate.exists():
            continue
        if candidate.is_file():
            if candidate.suffix.lower() not in TASK_DOC_EXTENSIONS:
                continue
            key = str(candidate).lower()
            if key not in seen:
                seen.add(key)
                yield candidate
            continue
        if candidate.is_dir():
            for path in candidate.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in TASK_DOC_EXTENSIONS:
                    continue
                resolved = path.resolve()
                key = str(resolved).lower()
                if key not in seen:
                    seen.add(key)
                    yield resolved