"""Aggregate repository activity and workspace collaboration for the dashboard."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, or_, select, union_all
from sqlalchemy.orm import Session, joinedload, load_only, selectinload

from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.auth.models.user import User, Workspace, WorkspaceMember
from app.domains.dashboard.schemas.diorama import (
    DashboardDioramaResponse,
    DioramaCommitItem,
    DioramaDayHeat,
    DioramaFileItem,
    DioramaMemberItem,
    DioramaModuleItem,
    DioramaPeriod,
    DioramaRepoItem,
    DioramaTaskItem,
    DioramaTimelineDay,
)
from app.domains.dashboard.services.diorama_repository import (
    ParsedCommit,
    RepositorySnapshot,
    ScannedFile,
    infer_module_name,
    normalize_rel_path,
    read_repositories,
)
from app.domains.dashboard.services.diorama_repository import (
    invalidate_diorama_cache as invalidate_diorama_cache,
)
from app.domains.task.models.chat import ChatMessage, MessageRole, MessageType
from app.domains.task.models.session_turn import TaskSessionTurn
from app.domains.task.models.task import SddTask
from app.domains.task.models.task_repository import SddTaskRepository
from app.domains.task.services.task_activity import active_task_chat_turn, task_chat_job_scope
from app.domains.workflow.models.task_change import (
    SddTaskChangeProposal,
    SddTaskChangeProposalFile,
    SddTaskChangeProposalRepo,
)
from app.domains.workspace.models.workspace_repository import SddWorkspaceRepository
from app.domains.workspace_asset.models.workspace_asset import SddRequirement, SddTaskRequirement

_REPO_COLORS = ("#0284c7", "#0ea5e9", "#6366f1", "#0d9488", "#2563eb", "#0891b2")
_MEMBER_COLORS = ("#0284c7", "#059669", "#d97706", "#7c3aed", "#0891b2", "#e11d48")

_MAX_MODULES_PER_REPO = 24
_MAX_FILES_PER_MODULE = 18
_MAX_DASHBOARD_TASKS = 18
_DASHBOARD_WINDOWS = (14, 30, 60)


@dataclass(frozen=True)
class _RepoDescriptor:
    id: str
    repository_id: str | None
    name: str
    slug: str
    branch: str
    state: str
    base_dir: str | None
    repo_url: str
    color: str


@dataclass(frozen=True)
class _RecentTask:
    task: SddTask
    last_activity_at: datetime
    proposal: SddTaskChangeProposal | None


def _build_module_items(
    repo_id: str,
    files: list[ScannedFile],
    commits: list[ParsedCommit],
) -> tuple[list[DioramaModuleItem], dict[str, list[tuple[int, DioramaCommitItem]]], dict[str, dict[str, list[int]]]]:
    file_stats: dict[str, list[int | str]] = defaultdict(lambda: [0, 0, 0, ""])
    mod_commits: dict[str, list[DioramaCommitItem]] = defaultdict(list)
    day_commits: dict[str, list[tuple[int, DioramaCommitItem]]] = defaultdict(list)
    day_mod_heat: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))

    for commit in commits:
        per_mod: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for rel, ins, dels in commit.files:
            st = file_stats[rel]
            st[0] = int(st[0]) + 1
            st[1] = int(st[1]) + ins
            st[2] = int(st[2]) + dels
            st[3] = max(str(st[3]), commit.date)
            mod_name = infer_module_name(rel)
            per_mod[mod_name][0] += ins
            per_mod[mod_name][1] += dels

        touched_ids = sorted(f"{repo_id}::{m}" for m in per_mod)
        total_ins = sum(v[0] for v in per_mod.values())
        total_del = sum(v[1] for v in per_mod.values())
        item = DioramaCommitItem(
            hash=commit.hash,
            date=commit.date,
            subject=commit.subject,
            added=total_ins,
            deleted=total_del,
            modules=touched_ids,
        )
        day_commits[commit.date].append((commit.timestamp, item))
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

    by_mod: dict[str, list[ScannedFile]] = defaultdict(list)
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
    flist_sorted: list[ScannedFile],
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


def _discover_workspace_repos(db: Session, workspace: Workspace) -> tuple[list[_RepoDescriptor], bool]:
    rows = (
        db.query(SddWorkspaceRepository)
        .filter(SddWorkspaceRepository.workspace_id == workspace.id)
        .order_by(SddWorkspaceRepository.created_at.asc())
        .all()
    )
    if rows:
        return (
            [
                _RepoDescriptor(
                    id=row.id,
                    repository_id=row.repository_id,
                    name=row.repo_name or row.repo_slug,
                    slug=row.repo_slug,
                    branch=row.branch_name or "",
                    state=row.state.value if hasattr(row.state, "value") else str(row.state),
                    base_dir=row.base_dir,
                    repo_url=row.repo_url or "",
                    color=_REPO_COLORS[idx % len(_REPO_COLORS)],
                )
                for idx, row in enumerate(rows)
            ],
            True,
        )

    raw_path = str(workspace.project_path or "").strip()
    git_url = str(workspace.git_repo_url or "").strip()
    if raw_path:
        p = Path(raw_path)
        name = p.name or workspace.name
        return (
            [
                _RepoDescriptor(
                    id=f"ws-legacy-{workspace.id[:8]}",
                    repository_id=None,
                    name=name,
                    slug=name.lower().replace(" ", "-"),
                    branch="",
                    state="READY" if p.is_dir() else "PENDING",
                    base_dir=raw_path,
                    repo_url=git_url,
                    color=_REPO_COLORS[0],
                )
            ],
            bool(git_url),
        )
    return ([], False)


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
    binding: SddTaskRepository | SddTaskChangeProposalRepo,
    repositories_by_id: dict[str, str],
    repo_lookup: dict[tuple[str, str], str | None],
    default_repo_id: str | None,
) -> str | None:
    if binding.repository_id in repositories_by_id:
        return repositories_by_id[binding.repository_id]
    for alias in _repo_aliases(binding.repo_url, binding.repo_slug, binding.repo_name):
        if repo_id := repo_lookup.get(alias):
            return repo_id
    return default_repo_id if not binding.repository_id else None


def _repo_aliases(url: str | None, slug: str | None, name: str | None) -> list[tuple[str, str]]:
    return [
        ("url", (url or "").strip().lower().rstrip("/").removesuffix(".git")),
        ("slug", (slug or "").strip().lower()),
        ("name", (name or "").strip().lower()),
    ]


def _load_recent_workspace_tasks(
    db: Session,
    workspace_id: str,
    *,
    since: datetime,
    as_of: datetime,
) -> list[_RecentTask]:
    chat_activity = (
        select(ChatMessage.task_id, func.max(ChatMessage.created_at).label("occurred_at"))
        .join(SddTask, SddTask.id == ChatMessage.task_id)
        .outerjoin(TaskSessionTurn, TaskSessionTurn.id == ChatMessage.session_turn_id)
        .where(
            ChatMessage.workspace_id == workspace_id,
            SddTask.workspace_id == workspace_id,
            ChatMessage.role.in_((MessageRole.USER, MessageRole.ASSISTANT)),
            ChatMessage.message_type != MessageType.INIT_REASON,
            ChatMessage.created_at.between(since, as_of),
            func.coalesce(ChatMessage.session_generation, TaskSessionTurn.session_generation, 0)
            == SddTask.session_generation,
            or_(ChatMessage.session_turn_id.is_(None), active_task_chat_turn()),
        )
        .group_by(ChatMessage.task_id)
    )
    job_activity_at = func.coalesce(SddAiJob.finished_at, SddAiJob.started_at)
    job_activity = (
        select(SddAiJob.task_id, func.max(job_activity_at).label("occurred_at"))
        .join(SddTask, SddTask.id == SddAiJob.task_id)
        .outerjoin(TaskSessionTurn, TaskSessionTurn.id == SddAiJob.session_turn_id)
        .where(
            *task_chat_job_scope(workspace_id, include_legacy_history=True),
            SddAiJob.started_at.is_not(None),
            SddAiJob.status != AiJobStatus.REVERTED,
            or_(SddAiJob.session_turn_id.is_(None), active_task_chat_turn()),
            job_activity_at.between(since, as_of),
        )
        .group_by(SddAiJob.task_id)
    )
    activity = union_all(chat_activity, job_activity).subquery()
    latest = (
        select(activity.c.task_id, func.max(activity.c.occurred_at).label("last_activity_at"))
        .group_by(activity.c.task_id)
        .subquery()
    )
    tasks = (
        db.query(SddTask, latest.c.last_activity_at)
        .join(latest, latest.c.task_id == SddTask.id)
        .options(
            load_only(
                SddTask.id,
                SddTask.name,
                SddTask.description,
                SddTask.status,
                SddTask.interrupt_kind,
                SddTask.task_type,
                SddTask.creator_id,
                SddTask.updated_at,
                SddTask.created_at,
            ),
            joinedload(SddTask.creator).load_only(User.display_name),
            selectinload(SddTask.repo_bindings).load_only(
                SddTaskRepository.repository_id,
                SddTaskRepository.repo_url,
                SddTaskRepository.repo_slug,
                SddTaskRepository.repo_name,
            ),
            selectinload(SddTask.requirement_links)
            .joinedload(SddTaskRequirement.requirement)
            .load_only(SddRequirement.title),
        )
        .filter(SddTask.workspace_id == workspace_id)
        .order_by(latest.c.last_activity_at.desc(), SddTask.id)
        .limit(_MAX_DASHBOARD_TASKS)
        .all()
    )
    if not tasks:
        return []

    task_ids = [task.id for task, _ in tasks]
    latest_patch_sets = (
        db.query(SddTaskChangeProposal.task_id, func.max(SddTaskChangeProposal.patch_set_no).label("patch_set_no"))
        .filter(SddTaskChangeProposal.task_id.in_(task_ids))
        .group_by(SddTaskChangeProposal.task_id)
        .subquery()
    )
    proposals = (
        db.query(SddTaskChangeProposal)
        .join(
            latest_patch_sets,
            (SddTaskChangeProposal.task_id == latest_patch_sets.c.task_id)
            & (SddTaskChangeProposal.patch_set_no == latest_patch_sets.c.patch_set_no),
        )
        .options(
            load_only(SddTaskChangeProposal.task_id),
            selectinload(SddTaskChangeProposal.files).load_only(
                SddTaskChangeProposalFile.proposal_repo_id,
                SddTaskChangeProposalFile.repository_id,
                SddTaskChangeProposalFile.file_path,
                SddTaskChangeProposalFile.insertions,
                SddTaskChangeProposalFile.deletions,
            ),
            selectinload(SddTaskChangeProposal.repo_patches).load_only(
                SddTaskChangeProposalRepo.repository_id,
                SddTaskChangeProposalRepo.repo_url,
                SddTaskChangeProposalRepo.repo_slug,
                SddTaskChangeProposalRepo.repo_name,
            ),
        )
        .all()
    )
    latest_proposal = {prop.task_id: prop for prop in proposals}
    return [_RecentTask(task, last_activity_at, latest_proposal.get(task.id)) for task, last_activity_at in tasks]


def _build_workspace_tasks(
    tasks: list[_RecentTask],
    repos: list[DioramaRepoItem],
    descriptors: list[_RepoDescriptor],
) -> list[DioramaTaskItem]:
    repositories_by_id = {desc.repository_id: desc.id for desc in descriptors if desc.repository_id}
    repo_lookup: dict[tuple[str, str], str | None] = {}
    for desc in descriptors:
        for alias in _repo_aliases(desc.repo_url, desc.slug, desc.name):
            if alias[1] and repo_lookup.setdefault(alias, desc.id) != desc.id:
                repo_lookup[alias] = None
    modules_by_repo = {repo.id: [module.id for module in repo.modules] for repo in repos}
    default_repo_id = repos[0].id if len(repos) == 1 else None

    return [
        _build_task_item(
            entry,
            repositories_by_id,
            repo_lookup,
            modules_by_repo,
            default_repo_id,
        )
        for entry in tasks
    ]


def _build_task_item(
    entry: _RecentTask,
    repositories_by_id: dict[str, str],
    repo_lookup: dict[tuple[str, str], str | None],
    modules_by_repo: dict[str, list[str]],
    default_repo_id: str | None,
) -> DioramaTaskItem:
    task = entry.task
    proposal = entry.proposal
    repo_set: set[str] = set()
    mod_churn: dict[str, int] = defaultdict(int)
    file_set: set[str] = set()
    added_sum = 0
    deleted_sum = 0

    for binding in task.repo_bindings or []:
        rid = _resolve_repo_id_for_binding(binding, repositories_by_id, repo_lookup, default_repo_id)
        if rid:
            repo_set.add(rid)

    if proposal:
        prop_repo_map: dict[str, str] = {}
        for pr in proposal.repo_patches or []:
            rid = _resolve_repo_id_for_binding(pr, repositories_by_id, repo_lookup, default_repo_id)
            if rid:
                prop_repo_map[pr.id] = rid
                repo_set.add(rid)

        fallback_rid = next(iter(repo_set)) if len(repo_set) == 1 else default_repo_id
        for pf in proposal.files or []:
            rel = normalize_rel_path(pf.file_path)
            file_set.add(rel)
            added_sum += pf.insertions or 0
            deleted_sum += pf.deletions or 0

            rid = prop_repo_map.get(pf.proposal_repo_id) or repositories_by_id.get(pf.repository_id)
            if not rid and not pf.proposal_repo_id and not pf.repository_id:
                rid = fallback_rid
            if not rid:
                continue
            repo_set.add(rid)
            mid = f"{rid}::{infer_module_name(rel)}"
            if mid in modules_by_repo[rid]:
                mod_churn[mid] += max(1, (pf.insertions or 0) + (pf.deletions or 0))

    # If a task is bound to repos but has no generated change proposal yet, anchor lightly to top modules
    if not file_set:
        for rid in sorted(repo_set):
            if modules := modules_by_repo[rid]:
                mod_churn[modules[0]] = 1

    sorted_mods = sorted(mod_churn, key=lambda mid: (-mod_churn[mid], mid))
    reqs = [link.requirement for link in task.requirement_links if link.requirement is not None]
    status_val = task.status.value if hasattr(task.status, "value") else str(task.status)
    raw_desc = str(task.description or "").strip()
    short_desc = raw_desc[:240] if raw_desc else None

    return DioramaTaskItem(
        id=task.id,
        name=task.name,
        description=short_desc,
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
        created_at=task.created_at,
        updated_at=task.updated_at or task.created_at,
        last_activity_at=entry.last_activity_at,
    )


def _build_period(
    *,
    days: int,
    cutoff: datetime,
    has_repositories: bool,
    descriptors: list[_RepoDescriptor],
    snapshots: dict[str, RepositorySnapshot],
    tasks: list[_RecentTask],
) -> DioramaPeriod:
    commit_cutoff = int(cutoff.timestamp())
    repo_items: list[DioramaRepoItem] = []
    merged_day_commits: dict[str, list[tuple[int, DioramaCommitItem]]] = defaultdict(list)
    merged_day_heat: dict[str, dict[str, DioramaDayHeat]] = defaultdict(dict)
    merged_repo_heat: dict[str, dict[str, DioramaDayHeat]] = defaultdict(dict)
    for desc in descriptors:
        snapshot = snapshots.get(desc.id)
        if snapshot is None:
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

        files = snapshot.files
        commits = [commit for commit in snapshot.commits or [] if commit.timestamp >= commit_cutoff]
        modules, day_commits, day_heat = _build_module_items(desc.id, files, commits)

        for d, clist in day_commits.items():
            merged_day_commits[d].extend(clist)
            merged_repo_heat[d][desc.id] = DioramaDayHeat(
                commits=len(clist),
                added=sum(c.added for _, c in clist),
                deleted=sum(c.deleted for _, c in clist),
            )
        for d, mdict in day_heat.items():
            merged_day_heat[d].update(
                {mid: DioramaDayHeat(commits=vals[0], added=vals[1], deleted=vals[2]) for mid, vals in mdict.items()}
            )

        repo_items.append(
            DioramaRepoItem(
                id=desc.id,
                name=desc.name,
                slug=desc.slug,
                branch=desc.branch,
                state=desc.state,
                color=desc.color,
                loc=sum(file.loc for file in files),
                file_count=len(files),
                module_count=len({file.module for file in files}),
                available=True,
                modules=modules,
            )
        )

    timeline: list[DioramaTimelineDay] = []
    for date_str in sorted(merged_day_commits):
        clist = sorted(merged_day_commits[date_str], key=lambda entry: entry[0], reverse=True)
        timeline.append(
            DioramaTimelineDay(
                date=date_str,
                commit_count=len(clist),
                total_churn=sum(c.added + c.deleted for _, c in clist),
                commits=[commit for _, commit in clist[:12]],
                module_heat=merged_day_heat[date_str],
                repo_heat=merged_repo_heat[date_str],
            )
        )

    activity_cutoff = cutoff.replace(tzinfo=None)
    return DioramaPeriod(
        days=days,
        date_range=[timeline[0].date, timeline[-1].date] if timeline else [],
        has_repositories=has_repositories,
        total_loc=sum(r.loc for r in repo_items),
        total_files=sum(r.file_count for r in repo_items),
        total_modules=sum(r.module_count for r in repo_items),
        total_commits=sum(d.commit_count for d in timeline),
        repos=repo_items,
        tasks=_build_workspace_tasks(
            [entry for entry in tasks if entry.last_activity_at >= activity_cutoff],
            repo_items,
            descriptors,
        ),
        timeline=timeline,
    )


def get_repo_diorama(
    db: Session,
    workspace_id: str,
    *,
    days: int = 30,
    refresh: bool = False,
    include_windows: bool = False,
) -> DashboardDioramaResponse:
    refresh_started_at = time.monotonic() if refresh else None
    now = datetime.now(timezone.utc)
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        return DashboardDioramaResponse(workspace_id=workspace_id, workspace_name="", days=days, generated_at=now)

    descriptors, has_bound_repos = _discover_workspace_repos(db, workspace)
    repo_paths = {desc.id: Path(desc.base_dir) for desc in descriptors if desc.base_dir}
    scans = read_repositories(
        workspace_id,
        [path for path in repo_paths.values() if path.is_dir()],
        since=int((now - timedelta(days=max(days, _DASHBOARD_WINDOWS[-1]))).timestamp()),
        refresh_started_at=refresh_started_at,
    )
    snapshots = {repo_id: scans[path] for repo_id, path in repo_paths.items() if path in scans}
    has_legacy_code = any(snapshot.files for snapshot in snapshots.values())
    has_repositories = has_bound_repos or has_legacy_code
    if not has_repositories:
        # Repo-less workspaces initialize a local git directory for documents/snapshots;
        # avoid surfacing that fallback directory as an empty white-box repository slab.
        descriptors = []
        snapshots = {}
    periods = dict.fromkeys((days, *_DASHBOARD_WINDOWS) if include_windows else (days,))
    cutoffs = {period: now - timedelta(days=period) for period in periods}
    # Any task in a narrower window's newest set is already in the widest window's newest set.
    tasks = _load_recent_workspace_tasks(
        db,
        workspace_id,
        since=min(cutoffs.values()).replace(tzinfo=None),
        as_of=now.replace(tzinfo=None),
    )
    members = _load_workspace_members(db, workspace_id)
    windows = {
        period: _build_period(
            days=period,
            cutoff=cutoff,
            has_repositories=has_repositories,
            descriptors=descriptors,
            snapshots=snapshots,
            tasks=tasks,
        )
        for period, cutoff in cutoffs.items()
    }
    selected = windows.pop(days)
    return DashboardDioramaResponse(
        **dict(selected),
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        members=members,
        generated_at=datetime.now(timezone.utc),
        windows=windows,
    )
