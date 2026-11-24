"""2.5D multi-repository codebase diorama aggregation service.

Scans actual workspace repositories on disk (respecting .gitignore via `git ls-files`),
extracts recent commit activity via `git log --numstat`, and links real workspace
members, tasks, requirements, and task change proposals without calling any LLM.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session, joinedload

from app.core.subprocess_runner import ProcessTimeoutError, run_git
from app.domains.auth.models.user import Workspace, WorkspaceMember
from app.domains.dashboard.schemas.diorama import (
    DashboardDioramaResponse,
    DioramaCommitItem,
    DioramaDayHeat,
    DioramaFileItem,
    DioramaMemberItem,
    DioramaModuleItem,
    DioramaRepoItem,
    DioramaTaskItem,
    DioramaTimelineDay,
)
from app.domains.task.models.task import SddTask
from app.domains.workflow.models.task_change import SddTaskChangeProposal
from app.domains.workspace.models.workspace_repository import SddWorkspaceRepository

_CACHE_TTL_SECONDS = 20.0
_CACHE: dict[tuple[str, int], tuple[float, DashboardDioramaResponse]] = {}

_REPO_COLORS = ("#0284c7", "#0ea5e9", "#6366f1", "#0d9488", "#2563eb", "#0891b2")
_MEMBER_COLORS = ("#0284c7", "#059669", "#d97706", "#7c3aed", "#0891b2", "#e11d48")

_SOURCE_EXTS: dict[str, str] = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".vue": "Vue",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".h": "C/C++",
    ".css": "CSS",
    ".scss": "CSS",
    ".less": "CSS",
    ".html": "HTML",
    ".sql": "SQL",
    ".sh": "Shell",
    ".yml": "Config",
    ".yaml": "Config",
    ".toml": "Config",
    ".json": "JSON",
}

_SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".git",
        "venv",
        ".venv",
        "__pycache__",
        "dist",
        "dist-electron",
        "dist-desktop-host",
        "build",
        "target",
        "release",
        ".vite",
        ".pytest_cache",
        ".ruff_cache",
        "coverage",
        "backups",
        "uploads",
        "tmp",
        "output",
        "vendor",
    }
)

_CONTAINER_DIRS = frozenset(
    {"src", "app", "lib", "pkg", "internal", "packages", "apps", "services", "modules", "domains", "components"}
)

_MAX_FILES_PER_REPO = 4000
_MAX_FILE_BYTES = 1_500_000
_MAX_COMMITS_PER_REPO = 180
_MAX_MODULES_PER_REPO = 24
_MAX_FILES_PER_MODULE = 18


@dataclass(frozen=True)
class _RepoDescriptor:
    id: str
    name: str
    slug: str
    branch: str
    state: str
    base_dir: str | None
    repo_url: str
    color: str


@dataclass
class _ScannedFile:
    path: str
    name: str
    module: str
    loc: int
    lang: str


@dataclass
class _ParsedCommit:
    hash: str
    date: str
    subject: str
    files: list[tuple[str, int, int]]


def invalidate_diorama_cache(workspace_id: str | None = None) -> None:
    if workspace_id is None:
        _CACHE.clear()
        return
    stale = [key for key in _CACHE if key[0] == workspace_id]
    for key in stale:
        _CACHE.pop(key, None)


def _normalize_rel_path(raw: str) -> str:
    return raw.replace("\\", "/").lstrip("./").strip()


def _is_ignored_source_path(rel_path: str) -> bool:
    parts = rel_path.split("/")
    if any(part in _SKIP_DIRS or part.startswith(".") for part in parts[:-1]):
        return True
    low = rel_path.lower()
    if low.endswith((".d.ts", ".min.js", ".min.css")):
        return True
    return Path(rel_path).suffix.lower() not in _SOURCE_EXTS


def infer_module_name(rel_path: str) -> str:
    """Derive a readable 1-to-2 level module bucket for any repository layout."""
    parts = [p for p in _normalize_rel_path(rel_path).split("/") if p]
    if len(parts) <= 1:
        return "(root)"
    dirs = parts[:-1]
    if len(dirs) == 1:
        return dirs[0]
    if dirs[0] in _CONTAINER_DIRS:
        if len(dirs) >= 3 and dirs[1] in _CONTAINER_DIRS:
            return f"{dirs[1]}/{dirs[2]}"
        return f"{dirs[0]}/{dirs[1]}"
    if len(dirs) >= 3 and dirs[1] in _CONTAINER_DIRS:
        return f"{dirs[0]}/{dirs[2]}"
    return dirs[0]


def _safe_count_lines(full_path: Path) -> int:
    try:
        stat = full_path.stat()
        if not full_path.is_file() or stat.st_size <= 0 or stat.st_size > _MAX_FILE_BYTES:
            return 0
        with full_path.open("rb") as fh:
            data = fh.read()
        if b"\x00" in data[:1024]:
            return 0
        breaks = data.count(b"\n")
        return breaks + (0 if data.endswith(b"\n") else 1)
    except OSError:
        return 0


def _list_repo_source_paths(repo_dir: Path) -> tuple[list[str], bool]:
    """List relative source paths using `git ls-files` when available, else bounded os.walk."""
    try:
        res = run_git(["ls-files", "-z"], cwd=str(repo_dir), timeout_seconds=8)
        if res.returncode == 0 and res.stdout:
            raw_paths = [p for p in res.stdout.split("\0") if p]
            filtered = [_normalize_rel_path(p) for p in raw_paths if not _is_ignored_source_path(p)]
            return filtered[:_MAX_FILES_PER_REPO], True
    except (OSError, ProcessTimeoutError):
        pass

    collected: list[str] = []
    for dirpath, dirnames, filenames in os.walk(repo_dir):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if Path(fn).suffix.lower() not in _SOURCE_EXTS:
                continue
            rel = _normalize_rel_path(os.path.relpath(os.path.join(dirpath, fn), repo_dir))
            if _is_ignored_source_path(rel):
                continue
            collected.append(rel)
            if len(collected) >= _MAX_FILES_PER_REPO:
                return collected, False
    return collected, False


def _scan_repo_files(repo_dir: Path) -> tuple[list[_ScannedFile], bool]:
    rel_paths, is_git = _list_repo_source_paths(repo_dir)
    scanned: list[_ScannedFile] = []
    for rel in rel_paths:
        loc = _safe_count_lines(repo_dir / rel)
        if loc <= 0:
            continue
        ext = Path(rel).suffix.lower()
        scanned.append(
            _ScannedFile(
                path=rel,
                name=Path(rel).name,
                module=infer_module_name(rel),
                loc=loc,
                lang=_SOURCE_EXTS.get(ext, "Other"),
            )
        )
    return scanned, is_git


def _parse_git_numstat_log(raw_output: str) -> list[_ParsedCommit]:
    commits: list[_ParsedCommit] = []
    current: _ParsedCommit | None = None
    for line in raw_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("@@C@@"):
            if current and current.files:
                commits.append(current)
            parts = stripped[5:].split("|", 2)
            if len(parts) < 3:
                current = None
                continue
            current = _ParsedCommit(hash=parts[0], date=parts[1], subject=parts[2], files=[])
            continue
        if current is None:
            continue
        cols = line.split("\t")
        if len(cols) != 3 or "=>" in cols[2]:
            continue
        rel = _normalize_rel_path(cols[2])
        if _is_ignored_source_path(rel):
            continue
        ins = int(cols[0]) if cols[0].isdigit() else 0
        dels = int(cols[1]) if cols[1].isdigit() else 0
        current.files.append((rel, ins, dels))
    if current and current.files:
        commits.append(current)
    commits.reverse()
    return commits


def _scan_repo_commits(repo_dir: Path, days: int) -> list[_ParsedCommit]:
    try:
        res = run_git(
            [
                "log",
                f"--since={days} days ago",
                f"-n{_MAX_COMMITS_PER_REPO}",
                "--date=short",
                "--numstat",
                "--format=@@C@@%h|%ad|%s",
            ],
            cwd=str(repo_dir),
            timeout_seconds=10,
        )
        if res.returncode != 0 or not res.stdout:
            return []
        return _parse_git_numstat_log(res.stdout)
    except (OSError, ProcessTimeoutError):
        return []


def _build_module_items(
    repo_id: str,
    files: list[_ScannedFile],
    commits: list[_ParsedCommit],
) -> tuple[list[DioramaModuleItem], dict[str, list[DioramaCommitItem]], dict[str, dict[str, list[int]]]]:
    file_stats: dict[str, list[int | str]] = defaultdict(lambda: [0, 0, 0, ""])
    mod_commits: dict[str, list[DioramaCommitItem]] = defaultdict(list)
    day_commits: dict[str, list[DioramaCommitItem]] = defaultdict(list)
    day_mod_heat: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))

    for commit in commits:
        per_mod: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for rel, ins, dels in commit.files:
            st = file_stats[rel]
            st[0] = int(st[0]) + 1
            st[1] = int(st[1]) + ins
            st[2] = int(st[2]) + dels
            st[3] = commit.date
            mod_name = infer_module_name(rel)
            per_mod[mod_name][0] += ins
            per_mod[mod_name][1] += dels

        touched_ids = sorted(f"{repo_id}::{m}" for m in per_mod)
        total_ins = sum(v[0] for v in per_mod.values())
        total_del = sum(v[1] for v in per_mod.values())
        day_commits[commit.date].append(
            DioramaCommitItem(
                hash=commit.hash,
                date=commit.date,
                subject=commit.subject,
                added=total_ins,
                deleted=total_del,
                modules=touched_ids,
            )
        )
        for mod_name, (ins, dels) in per_mod.items():
            mid = f"{repo_id}::{mod_name}"
            mod_commits[mod_name].append(
                DioramaCommitItem(
                    hash=commit.hash,
                    date=commit.date,
                    subject=commit.subject,
                    added=ins,
                    deleted=dels,
                    modules=[mid],
                )
            )
            dh = day_mod_heat[commit.date][mid]
            dh[0] += 1
            dh[1] += ins
            dh[2] += dels

    by_mod: dict[str, list[_ScannedFile]] = defaultdict(list)
    for f in files:
        by_mod[f.module].append(f)

    sorted_mods = sorted(
        by_mod.items(),
        key=lambda kv: -(len(mod_commits.get(kv[0], [])) * 400 + sum(x.loc for x in kv[1])),
    )[:_MAX_MODULES_PER_REPO]

    module_items: list[DioramaModuleItem] = []
    for mod_name, flist in sorted_mods:
        flist_sorted = sorted(flist, key=lambda x: -(int(file_stats[x.path][0]) * 350 + x.loc))
        kept_files = _pack_module_files(flist_sorted, file_stats)
        mc_list = mod_commits.get(mod_name, [])
        module_items.append(
            DioramaModuleItem(
                id=f"{repo_id}::{mod_name}",
                repo_id=repo_id,
                name=mod_name,
                loc=sum(x.loc for x in flist),
                file_count=len(flist),
                commits=len(mc_list),
                added=sum(c.added for c in mc_list),
                deleted=sum(c.deleted for c in mc_list),
                recent_commits=list(reversed(mc_list[-8:])),
                files=kept_files,
            )
        )
    return module_items, day_commits, day_mod_heat


def _pack_module_files(
    flist_sorted: list[_ScannedFile],
    file_stats: dict[str, list[int | str]],
) -> list[DioramaFileItem]:
    items: list[DioramaFileItem] = []
    for f in flist_sorted[:_MAX_FILES_PER_MODULE]:
        st = file_stats[f.path]
        items.append(
            DioramaFileItem(
                path=f.path,
                name=f.name,
                loc=f.loc,
                lang=f.lang,
                commits=int(st[0]),
                added=int(st[1]),
                deleted=int(st[2]),
                last_date=str(st[3]),
            )
        )
    rest = flist_sorted[_MAX_FILES_PER_MODULE:]
    if rest:
        items.append(
            DioramaFileItem(
                path=f"{rest[0].module}/__other__",
                name=f"+{len(rest)} files",
                loc=sum(x.loc for x in rest),
                lang=rest[0].lang,
                commits=sum(int(file_stats[x.path][0]) for x in rest),
                added=sum(int(file_stats[x.path][1]) for x in rest),
                deleted=sum(int(file_stats[x.path][2]) for x in rest),
                is_aggregate=True,
                file_count=len(rest),
            )
        )
    return items


def _discover_workspace_repos(db: Session, workspace: Workspace) -> list[_RepoDescriptor]:
    rows = (
        db.query(SddWorkspaceRepository)
        .filter(SddWorkspaceRepository.workspace_id == workspace.id)
        .order_by(SddWorkspaceRepository.created_at.asc())
        .all()
    )
    if rows:
        return [
            _RepoDescriptor(
                id=row.id,
                name=row.repo_name or row.repo_slug,
                slug=row.repo_slug,
                branch=row.branch_name or "",
                state=row.state.value if hasattr(row.state, "value") else str(row.state),
                base_dir=row.base_dir,
                repo_url=row.repo_url or "",
                color=_REPO_COLORS[idx % len(_REPO_COLORS)],
            )
            for idx, row in enumerate(rows)
        ]

    raw_path = str(workspace.project_path or "").strip()
    if raw_path:
        p = Path(raw_path)
        name = p.name or workspace.name
        return [
            _RepoDescriptor(
                id=f"ws-legacy-{workspace.id[:8]}",
                name=name,
                slug=name.lower().replace(" ", "-"),
                branch="",
                state="READY" if p.is_dir() else "PENDING",
                base_dir=raw_path,
                repo_url=workspace.git_repo_url or "",
                color=_REPO_COLORS[0],
            )
        ]
    return []


def _load_workspace_members(db: Session, workspace_id: str) -> list[DioramaMemberItem]:
    rows = (
        db.query(WorkspaceMember)
        .options(joinedload(WorkspaceMember.user))
        .filter(WorkspaceMember.workspace_id == workspace_id)
        .order_by(WorkspaceMember.joined_at.asc())
        .all()
    )
    members: list[DioramaMemberItem] = []
    for idx, row in enumerate(rows):
        user = row.user
        if not user:
            continue
        role_val = row.role.value if hasattr(row.role, "value") else str(row.role)
        members.append(
            DioramaMemberItem(
                id=user.id,
                display_name=user.display_name or user.email,
                email=user.email,
                avatar_url=user.avatar_url,
                avatar_svg=user.avatar_svg,
                role=role_val,
                color=_MEMBER_COLORS[idx % len(_MEMBER_COLORS)],
            )
        )
    return members


def _resolve_repo_id_for_binding(
    repo_slug: str | None,
    repo_name: str | None,
    repo_url: str | None,
    repo_lookup: dict[str, str],
    default_repo_id: str | None,
) -> str | None:
    for candidate in (repo_slug, repo_name, (repo_url or "").rstrip("/").removesuffix(".git").lower()):
        key = str(candidate or "").strip().lower()
        if key and key in repo_lookup:
            return repo_lookup[key]
    return default_repo_id


def _load_workspace_tasks(
    db: Session,
    workspace_id: str,
    repos: list[DioramaRepoItem],
    descriptors: list[_RepoDescriptor],
) -> list[DioramaTaskItem]:
    tasks = (
        db.query(SddTask)
        .options(
            joinedload(SddTask.creator),
            joinedload(SddTask.repo_bindings),
            joinedload(SddTask.requirement_links),
        )
        .filter(SddTask.workspace_id == workspace_id)
        .order_by(SddTask.updated_at.desc(), SddTask.created_at.desc())
        .limit(18)
        .all()
    )
    if not tasks:
        return []

    task_ids = [t.id for t in tasks]
    proposals = (
        db.query(SddTaskChangeProposal)
        .options(joinedload(SddTaskChangeProposal.files), joinedload(SddTaskChangeProposal.repo_patches))
        .filter(SddTaskChangeProposal.task_id.in_(task_ids))
        .order_by(SddTaskChangeProposal.proposal_no.desc())
        .all()
    )
    latest_proposal: dict[str, SddTaskChangeProposal] = {}
    for prop in proposals:
        latest_proposal.setdefault(prop.task_id, prop)

    repo_lookup: dict[str, str] = {}
    valid_modules: dict[str, set[str]] = {r.id: {m.id for m in r.modules} for r in repos}
    for desc in descriptors:
        for key in (desc.slug, desc.name, desc.repo_url.rstrip("/").removesuffix(".git")):
            norm = key.strip().lower()
            if norm:
                repo_lookup[norm] = desc.id
    default_repo_id = repos[0].id if len(repos) == 1 else None

    result: list[DioramaTaskItem] = []
    for task in tasks:
        result.append(
            _build_task_item(
                task,
                latest_proposal.get(task.id),
                repo_lookup,
                valid_modules,
                default_repo_id,
            )
        )
    return result


def _build_task_item(
    task: SddTask,
    proposal: SddTaskChangeProposal | None,
    repo_lookup: dict[str, str],
    valid_modules: dict[str, set[str]],
    default_repo_id: str | None,
) -> DioramaTaskItem:
    repo_set: set[str] = set()
    mod_churn: dict[str, int] = defaultdict(int)
    file_set: set[str] = set()
    added_sum = 0
    deleted_sum = 0

    for binding in task.repo_bindings or []:
        rid = _resolve_repo_id_for_binding(
            binding.repo_slug, binding.repo_name, binding.repo_url, repo_lookup, default_repo_id
        )
        if rid:
            repo_set.add(rid)

    if proposal:
        prop_repo_map: dict[str, str] = {}
        for pr in proposal.repo_patches or []:
            rid = _resolve_repo_id_for_binding(pr.repo_slug, pr.repo_name, pr.repo_url, repo_lookup, default_repo_id)
            if rid:
                prop_repo_map[pr.id] = rid
                repo_set.add(rid)

        fallback_rid = next(iter(repo_set), default_repo_id)
        for pf in proposal.files or []:
            rid = prop_repo_map.get(pf.proposal_repo_id or "", fallback_rid)
            if not rid:
                continue
            repo_set.add(rid)
            rel = _normalize_rel_path(pf.file_path)
            file_set.add(rel)
            mid = f"{rid}::{infer_module_name(rel)}"
            if mid in valid_modules.get(rid, set()):
                mod_churn[mid] += max(1, (pf.insertions or 0) + (pf.deletions or 0))
            added_sum += pf.insertions or 0
            deleted_sum += pf.deletions or 0

    # If a task is bound to repos but has no generated change proposal yet, anchor lightly to top modules
    if not mod_churn and repo_set:
        for rid in sorted(repo_set):
            mods = sorted(valid_modules.get(rid, set()))
            if mods:
                mod_churn[mods[0]] = 1

    sorted_mods = [m for m, _ in sorted(mod_churn.items(), key=lambda kv: -kv[1])]
    reqs = [link.requirement for link in (task.requirement_links or []) if getattr(link, "requirement", None)]
    status_val = task.status.value if hasattr(task.status, "value") else str(task.status)

    return DioramaTaskItem(
        id=task.id,
        name=task.name,
        status=status_val,
        interrupt_kind=task.interrupt_kind,
        task_type=str(task.task_type or "DEVELOPMENT"),
        creator_id=task.creator_id,
        creator_name=task.creator.display_name if task.creator else None,
        requirement_ids=[r.id for r in reqs],
        requirement_titles=[r.title for r in reqs],
        repos=sorted(repo_set),
        modules=sorted_mods,
        primary_modules=sorted_mods[:3],
        files=sorted(file_set)[:40],
        added=added_sum,
        deleted=deleted_sum,
        updated_at=task.updated_at or task.created_at,
    )


def get_repo_diorama(
    db: Session,
    workspace_id: str,
    *,
    days: int = 30,
    refresh: bool = False,
) -> DashboardDioramaResponse:
    cache_key = (workspace_id, days)
    now_mono = time.monotonic()
    if not refresh and cache_key in _CACHE:
        cached_at, cached_payload = _CACHE[cache_key]
        if now_mono - cached_at < _CACHE_TTL_SECONDS:
            return cached_payload

    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        return DashboardDioramaResponse(
            workspace_id=workspace_id,
            workspace_name="",
            days=days,
            generated_at=datetime.now(timezone.utc),
        )

    descriptors = _discover_workspace_repos(db, workspace)
    repo_items: list[DioramaRepoItem] = []
    merged_day_commits: dict[str, list[DioramaCommitItem]] = defaultdict(list)
    merged_day_heat: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))

    for desc in descriptors:
        repo_path = Path(desc.base_dir) if desc.base_dir else None
        available = bool(repo_path and repo_path.is_dir())
        if not available or repo_path is None:
            repo_items.append(
                DioramaRepoItem(
                    id=desc.id,
                    name=desc.name,
                    slug=desc.slug,
                    branch=desc.branch,
                    state=desc.state,
                    color=desc.color,
                    available=False,
                )
            )
            continue

        scanned_files, is_git = _scan_repo_files(repo_path)
        commits = _scan_repo_commits(repo_path, days) if is_git else []
        modules, day_commits, day_heat = _build_module_items(desc.id, scanned_files, commits)

        for d, clist in day_commits.items():
            merged_day_commits[d].extend(clist)
        for d, mdict in day_heat.items():
            for mid, vals in mdict.items():
                slot = merged_day_heat[d][mid]
                slot[0] += vals[0]
                slot[1] += vals[1]
                slot[2] += vals[2]

        repo_items.append(
            DioramaRepoItem(
                id=desc.id,
                name=desc.name,
                slug=desc.slug,
                branch=desc.branch,
                state=desc.state,
                color=desc.color,
                loc=sum(m.loc for m in modules),
                file_count=sum(m.file_count for m in modules),
                module_count=len(modules),
                available=True,
                modules=modules,
            )
        )

    timeline: list[DioramaTimelineDay] = []
    for date_str in sorted(merged_day_commits.keys()):
        clist = merged_day_commits[date_str]
        mheat = {
            mid: DioramaDayHeat(commits=vals[0], added=vals[1], deleted=vals[2])
            for mid, vals in merged_day_heat[date_str].items()
        }
        timeline.append(
            DioramaTimelineDay(
                date=date_str,
                commit_count=len(clist),
                total_churn=sum(c.added + c.deleted for c in clist),
                commits=clist[:12],
                module_heat=mheat,
            )
        )

    members = _load_workspace_members(db, workspace_id)
    tasks = _load_workspace_tasks(db, workspace_id, repo_items, descriptors)
    date_range = [timeline[0].date, timeline[-1].date] if timeline else []

    payload = DashboardDioramaResponse(
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        days=days,
        date_range=date_range,
        total_loc=sum(r.loc for r in repo_items),
        total_files=sum(r.file_count for r in repo_items),
        total_modules=sum(r.module_count for r in repo_items),
        total_commits=sum(d.commit_count for d in timeline),
        repos=repo_items,
        members=members,
        tasks=tasks,
        timeline=timeline,
        generated_at=datetime.now(timezone.utc),
    )
    _CACHE[cache_key] = (now_mono, payload)
    return payload
