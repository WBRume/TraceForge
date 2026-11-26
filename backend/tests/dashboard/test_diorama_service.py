"""2.5D 多仓沙盘后端聚合服务单元测试。"""

from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.orm import Session

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.core.subprocess_runner import run_git  # noqa: E402
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob  # noqa: E402
from app.domains.auth.models.user import User, Workspace, WorkspaceMember, WorkspaceRole  # noqa: E402
from app.domains.dashboard.services import diorama_repository, diorama_service  # noqa: E402
from app.domains.task.models.chat import ChatMessage, MessageRole, MessageType  # noqa: E402
from app.domains.task.models.session_turn import TaskSessionTurn, TaskSessionTurnStatus  # noqa: E402
from app.domains.task.models.task import SddTask, TaskStatus  # noqa: E402
from app.domains.task.models.task_repository import SddTaskRepository, TaskRepositoryState  # noqa: E402
from app.domains.workflow.models.task_change import (  # noqa: E402
    ChangeProposalFileType,
    ChangeProposalStatus,
    SddTaskChangeProposal,
    SddTaskChangeProposalFile,
    SddTaskChangeProposalRepo,
)
from app.domains.workspace.models.workspace_repository import (  # noqa: E402
    SddWorkspaceRepository,
    WorkspaceRepositoryState,
)


class _MemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.unavailable = False

    def getex(self, key: str, *, ex: int) -> bytes | None:
        assert ex > 0
        if self.unavailable:
            raise RedisConnectionError("offline")
        return self.values.get(key)

    def set(self, key: str, value: bytes, *, ex: int) -> bool:
        assert ex > 0
        if self.unavailable:
            raise RedisConnectionError("offline")
        self.values[key] = value
        return True


@pytest.fixture(autouse=True)
def _isolate_dashboard_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _MemoryRedis()
    monkeypatch.setattr(diorama_repository, "get_sync_redis_cache_client", lambda: redis)


def _init_git_repo(repo_dir: Path, files: dict[str, str], message: str) -> None:
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@traceforge.dev"], cwd=repo_dir, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "TraceForge Test"], cwd=repo_dir, check=True, capture_output=True)
    for rel, content in files.items():
        full = repo_dir / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo_dir, check=True, capture_output=True)


def _task_message(
    task: SddTask,
    created_at: datetime | None = None,
    *,
    role: MessageRole = MessageRole.USER,
    message_type: MessageType = MessageType.TEXT,
    session_generation: int | None = None,
    session_turn_id: str | None = None,
) -> ChatMessage:
    return ChatMessage(
        task_id=task.id,
        workspace_id=task.workspace_id,
        creator_id=task.creator_id,
        role=role,
        message_type=message_type,
        content="Task conversation activity",
        created_at=created_at,
        session_generation=session_generation,
        session_turn_id=session_turn_id,
    )


def test_infer_module_name_handles_nested_containers():
    assert diorama_service.infer_module_name("README.py") == "(root)"
    assert diorama_service.infer_module_name("src/components/chat/Bubble.vue") == "components/chat"
    assert diorama_service.infer_module_name("app/domains/task/service.py") == "domains/task"
    assert diorama_service.infer_module_name("electron/main.ts") == "electron"
    assert (
        diorama_service.infer_module_name("backend/app/config.py") == "backend/config.py"
        or diorama_service.infer_module_name("backend/app/config.py") == "backend"
    )


def test_get_repo_diorama_scans_real_multi_repos_and_links_tasks(db: Session, tmp_path: Path):
    diorama_service.invalidate_diorama_cache()

    fe_dir = tmp_path / "web-fe"
    be_dir = tmp_path / "core-be"
    _init_git_repo(
        fe_dir,
        {
            "src/views/DashboardView.vue": "<template>\n<div>hi</div>\n</template>\n",
            "src/components/chat/ChatBox.vue": "<script setup>\nconst x = 1\n</script>\n",
        },
        "feat(ui): add dashboard and chat",
    )
    _init_git_repo(
        be_dir,
        {
            "app/domains/task/service.py": "def run():\n    return 1\n",
            "app/domains/dashboard/router.py": "def route():\n    return 2\n",
        },
        "feat(api): add task and dashboard domains",
    )

    user = User(id="u-1", email="dev@example.com", hashed_password="x", display_name="林工")
    ws = Workspace(id="ws-dio-1", name="MultiRepo WS", owner_id=user.id)
    member = WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.OWNER)
    repo_fe = SddWorkspaceRepository(
        id="wr-fe",
        workspace_id=ws.id,
        repo_url="https://git.local/web-fe.git",
        repo_name="web-fe",
        repo_slug="web-fe",
        branch_name="main",
        base_dir=str(fe_dir),
        state=WorkspaceRepositoryState.READY,
    )
    repo_be = SddWorkspaceRepository(
        id="wr-be",
        workspace_id=ws.id,
        repo_url="https://git.local/core-be.git",
        repo_name="core-be",
        repo_slug="core-be",
        branch_name="main",
        base_dir=str(be_dir),
        state=WorkspaceRepositoryState.READY,
    )
    repo_missing = SddWorkspaceRepository(
        id="wr-missing",
        workspace_id=ws.id,
        repo_url="https://git.local/uncloned.git",
        repo_name="uncloned",
        repo_slug="uncloned",
        branch_name="main",
        base_dir=str(tmp_path / "does-not-exist"),
        state=WorkspaceRepositoryState.PENDING,
    )
    task = SddTask(
        id="task-dio-1",
        workspace_id=ws.id,
        creator_id=user.id,
        name="打通多仓看板接口与页面",
        status=TaskStatus.RUNNING,
    )
    binding = SddTaskRepository(
        task_id=task.id,
        repo_url=repo_fe.repo_url,
        repo_name=repo_fe.repo_name,
        repo_slug=repo_fe.repo_slug,
        branch_name="main",
        rel_path="web-fe",
        state=TaskRepositoryState.READY,
    )
    proposal = SddTaskChangeProposal(
        id="prop-1",
        task_id=task.id,
        workspace_id=ws.id,
        proposal_no=1,
        patch_set_no=1,
        status=ChangeProposalStatus.GENERATED,
        base_branch="main",
        base_commit_sha="abc123",
        cloud_task_branch="task/task-dio-1",
    )
    prop_repo = SddTaskChangeProposalRepo(
        id="pr-1",
        proposal_id=proposal.id,
        repo_url=repo_fe.repo_url,
        repo_name=repo_fe.repo_name,
        repo_slug=repo_fe.repo_slug,
        base_branch="main",
        base_commit_sha="abc123",
        cloud_task_branch="task/task-dio-1",
    )
    prop_file = SddTaskChangeProposalFile(
        id="pf-1",
        proposal_id=proposal.id,
        proposal_repo_id=prop_repo.id,
        file_path="src/components/chat/ChatBox.vue",
        change_type=ChangeProposalFileType.MODIFIED,
        insertions=18,
        deletions=4,
    )

    db.add_all(
        [
            user,
            ws,
            member,
            repo_fe,
            repo_be,
            repo_missing,
            task,
            binding,
            proposal,
            prop_repo,
            prop_file,
            _task_message(task),
        ]
    )
    db.commit()

    result = diorama_service.get_repo_diorama(db, ws.id, days=30, refresh=True)

    assert result.workspace_id == ws.id
    assert len(result.repos) == 3
    by_id = {r.id: r for r in result.repos}
    assert by_id["wr-fe"].available is True
    assert by_id["wr-fe"].loc == 6
    assert by_id["wr-be"].available is True
    assert by_id["wr-be"].loc == 4
    assert by_id["wr-missing"].available is False
    assert result.total_commits == 2
    assert len(result.timeline) >= 1
    day = result.timeline[-1]
    assert day.repo_heat["wr-fe"].commits == 1
    assert day.module_heat["wr-fe::src/views"].commits == 1
    assert day.module_heat["wr-fe::components/chat"].commits == 1
    assert len(result.members) == 1
    assert len(result.tasks) == 1
    assert "wr-fe" in result.tasks[0].repos
    assert "wr-fe::components/chat" in result.tasks[0].modules
    assert result.tasks[0].added == 18
    assert result.tasks[0].deleted == 4

    ambiguous_file = SddTaskChangeProposalFile(
        proposal_id=proposal.id,
        file_path="app/domains/task/service.py",
        change_type=ChangeProposalFileType.MODIFIED,
        insertions=7,
        deletions=1,
    )
    second_binding = SddTaskRepository(
        task_id=task.id,
        repo_url=repo_be.repo_url,
        repo_name=repo_be.repo_name,
        repo_slug=repo_be.repo_slug,
        branch_name="main",
        rel_path="core-be",
        state=TaskRepositoryState.READY,
    )
    db.add_all([ambiguous_file, second_binding])
    db.commit()
    older_patch = diorama_service.get_repo_diorama(db, ws.id, days=14)
    assert older_patch.tasks[0].repos == ["wr-be", "wr-fe"]
    assert older_patch.tasks[0].modules == ["wr-fe::components/chat"]
    assert older_patch.tasks[0].added == 25

    db.add(
        SddTaskChangeProposal(
            task_id=task.id,
            workspace_id=ws.id,
            proposal_no=2,
            patch_set_no=2,
            status=ChangeProposalStatus.GENERATED,
            base_branch="main",
            base_commit_sha="abc123",
            cloud_task_branch="task/task-dio-1",
        )
    )
    db.commit()
    latest = diorama_service.get_repo_diorama(db, ws.id, days=60)
    assert latest.tasks[0].added == 0
    assert latest.tasks[0].files == []


def test_repository_history_and_source_are_shared_across_ranges(db: Session, tmp_path: Path):
    repo_dir = tmp_path / "repo"
    _init_git_repo(
        repo_dir,
        {f"module{i}/source.py": f"line {i}\n" for i in range(25)} | {"src/旧.py": "print('test')\n"},
        "initial source",
    )
    now = datetime.now(timezone.utc)
    old_date = (now - timedelta(days=21)).isoformat()
    assert (
        run_git(
            ["commit", "--amend", "--no-edit", f"--date={old_date}"],
            cwd=str(repo_dir),
            env_extra={"GIT_COMMITTER_DATE": old_date},
        ).returncode
        == 0
    )
    assert run_git(["mv", "src/旧.py", "src/新.py"], cwd=str(repo_dir)).returncode == 0
    assert run_git(["commit", "-m", "rename source"], cwd=str(repo_dir)).returncode == 0
    user = User(id="repo-cache-user", email="cache@example.com", hashed_password="x", display_name="Cache test")
    db.add_all(
        [
            user,
            Workspace(id="repo-cache-workspace", name="Cache", owner_id=user.id, project_path=str(repo_dir)),
        ]
    )
    db.commit()
    workspace_id = "repo-cache-workspace"
    with (
        patch.object(diorama_repository, "_scan_repo_files", wraps=diorama_repository._scan_repo_files) as scan_files,
        patch.object(
            diorama_repository,
            "_scan_repo_commits",
            wraps=diorama_repository._scan_repo_commits,
        ) as scan_commits,
    ):
        recent = diorama_service.get_repo_diorama(db, workspace_id, days=14)
        month = diorama_service.get_repo_diorama(db, workspace_id, days=30)
        extended = diorama_service.get_repo_diorama(db, workspace_id, days=60)
        assert (recent.total_commits, month.total_commits, extended.total_commits) == (1, 2, 2)
        assert scan_files.call_count == scan_commits.call_count == 1
        bundle = diorama_service.get_repo_diorama(db, workspace_id, days=30, include_windows=True)
        assert set(bundle.windows) == {14, 60}
        assert bundle.windows[14].repos == recent.repos
        assert bundle.windows[14].timeline == recent.timeline
        assert bundle.windows[60].repos == extended.repos
        assert bundle.windows[60].timeline == extended.timeline
        assert scan_files.call_count == scan_commits.call_count == 1
        assert recent.total_files == recent.total_modules == 26
        assert len(recent.repos[0].modules) == 24
        renamed = next(module for module in recent.repos[0].modules if module.name == "src").files[0]
        assert renamed.path == "src/新.py"
        assert (renamed.commits, renamed.added, renamed.deleted) == (1, 0, 0)

        (repo_dir / "src/新.py").write_text("first\nsecond\n", encoding="utf-8")
        refreshed = diorama_service.get_repo_diorama(db, workspace_id, days=14, refresh=True)
        assert refreshed.total_loc == recent.total_loc + 1
        assert scan_files.call_count == scan_commits.call_count == 2

        older = diorama_service.get_repo_diorama(db, workspace_id, days=90)
        assert older.total_commits == 2
        assert scan_files.call_count == 2
        assert scan_commits.call_count == 3


def test_expired_snapshot_reads_only_modified_source_files(tmp_path: Path):
    repo_dir = tmp_path / "incremental"
    _init_git_repo(repo_dir, {"unchanged.py": "value = 1\n", "changed.py": "value = 2\n"}, "source")
    since = int((datetime.now(timezone.utc) - timedelta(days=60)).timestamp())
    with (
        patch.object(diorama_repository, "_CACHE_TTL_SECONDS", 0),
        patch.object(diorama_repository, "_count_source_lines", wraps=diorama_repository._count_source_lines) as read,
    ):
        first = diorama_repository.read_repositories(
            "incremental-requests",
            [repo_dir],
            since=since,
            refresh_started_at=None,
        )[repo_dir]
        assert sum(f.loc for f in first.files) == 2
        assert read.call_count == 2
        (repo_dir / "changed.py").write_text("value = 2\nsecond = 3\n", encoding="utf-8")
        second = diorama_repository.read_repositories(
            "incremental-requests",
            [repo_dir],
            since=since,
            refresh_started_at=None,
        )[repo_dir]
        assert read.call_count == 3
        assert sum(f.loc for f in second.files) == 3


def test_overlapping_repository_reads_share_the_same_scan(tmp_path: Path):
    repo_dir = tmp_path / "parallel"
    _init_git_repo(repo_dir, {"source.py": "value = 1\n"}, "source")
    since = int((datetime.now(timezone.utc) - timedelta(days=60)).timestamp())
    with (
        patch.object(diorama_repository, "_scan_repo_files", wraps=diorama_repository._scan_repo_files) as scan_files,
        ThreadPoolExecutor(max_workers=2) as requests,
    ):
        jobs = [
            requests.submit(
                diorama_repository.read_repositories,
                "parallel-requests",
                [repo_dir],
                since=since,
                refresh_started_at=None,
            )
            for _ in range(2)
        ]
        first, second = (job.result()[repo_dir] for job in jobs)
        assert first is second
        assert scan_files.call_count == 1


def test_redis_reuses_git_history_and_line_counts_across_local_cache_resets(tmp_path: Path):
    repo_dir = tmp_path / "redis"
    _init_git_repo(repo_dir, {"code.py": "value = 1\n"}, "source")
    workspace_id = "redis-workspace"
    since = int((datetime.now(timezone.utc) - timedelta(days=60)).timestamp())
    redis = _MemoryRedis()

    def read() -> diorama_repository.RepositorySnapshot:
        return diorama_repository.read_repositories(
            workspace_id,
            [repo_dir],
            since=since,
            refresh_started_at=None,
        )[repo_dir]

    with (
        patch.object(diorama_repository, "get_sync_redis_cache_client", return_value=redis),
        patch.object(diorama_repository, "_count_source_lines", wraps=diorama_repository._count_source_lines) as count,
        patch.object(diorama_repository, "_scan_repo_commits", wraps=diorama_repository._scan_repo_commits) as history,
    ):
        first = read()
        assert first.persisted and first.revision is not None
        assert len(redis.values) == 1
        assert count.call_count == history.call_count == 1

        diorama_repository.invalidate_diorama_cache(workspace_id)
        hit = read()
        assert (hit.files, hit.commits) == (first.files, first.commits)
        assert count.call_count == history.call_count == 1

        file = repo_dir / "code.py"
        file.write_text("value = 1\nsecond = 2\n", encoding="utf-8")
        diorama_repository.invalidate_diorama_cache(workspace_id)
        dirty = read()
        assert dirty.files[0].loc == 2
        assert dirty.revision == first.revision
        assert count.call_count == 2 and history.call_count == 1

        assert run_git(["add", "code.py"], cwd=str(repo_dir)).returncode == 0
        assert run_git(["commit", "-m", "add a line"], cwd=str(repo_dir)).returncode == 0
        changed = read()
        assert changed.revision != first.revision
        assert changed.persisted and len(redis.values) == 2
        assert len(changed.commits or []) == 2
        assert count.call_count == history.call_count == 2


def test_redis_failure_falls_back_to_local_scan_and_can_publish_later(tmp_path: Path):
    repo_dir = tmp_path / "redis-offline"
    _init_git_repo(repo_dir, {"code.py": "value = 1\n"}, "source")
    since = int((datetime.now(timezone.utc) - timedelta(days=60)).timestamp())
    redis = _MemoryRedis()
    redis.unavailable = True
    with (
        patch.object(diorama_repository, "get_sync_redis_cache_client", return_value=redis),
        patch.object(diorama_repository, "_CACHE_TTL_SECONDS", 0),
        patch.object(diorama_repository, "_scan_repo_commits", wraps=diorama_repository._scan_repo_commits) as history,
    ):
        first = diorama_repository.read_repositories(
            "redis-offline",
            [repo_dir],
            since=since,
            refresh_started_at=None,
        )[repo_dir]
        assert not first.persisted
        assert first.files[0].loc == 1 and len(first.commits or []) == 1
        redis.unavailable = False
        retried = diorama_repository.read_repositories(
            "redis-offline",
            [repo_dir],
            since=since,
            refresh_started_at=None,
        )[repo_dir]
        assert retried.persisted and len(redis.values) == 1
        assert history.call_count == 1


def test_get_repo_diorama_missing_workspace_returns_empty(db: Session):
    diorama_service.invalidate_diorama_cache()
    result = diorama_service.get_repo_diorama(db, "missing-ws-id", days=30, refresh=True)
    assert result.workspace_id == "missing-ws-id"
    assert result.repos == []
    assert result.tasks == []
    assert result.has_repositories is False


def test_get_repo_diorama_repo_less_workspace_omits_empty_legacy_slab(db: Session, tmp_path: Path):
    diorama_service.invalidate_diorama_cache()
    ws_dir = tmp_path / "workspace"
    _init_git_repo(ws_dir, {"docs/plan.md": "# Repo-less workspace plan\n"}, "feat(workspace): init")

    user = User(id="u-rl", email="rl@example.com", hashed_password="x", display_name="yk")
    ws = Workspace(id="ws-repoless-1", name="workspace", owner_id=user.id, project_path=str(ws_dir))
    member = WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.OWNER)
    task = SddTask(
        id="task-rl-1",
        workspace_id=ws.id,
        creator_id=user.id,
        name="OpenCode-资产同步验证",
        description="验证无仓工作区任务展示",
        status=TaskStatus.AWAITING_INPUT,
    )
    db.add_all([user, ws, member, task, _task_message(task)])
    db.commit()

    result = diorama_service.get_repo_diorama(db, ws.id, days=30, refresh=True)

    assert result.has_repositories is False
    assert result.repos == []
    assert result.timeline == []
    assert result.total_commits == 0
    assert len(result.members) == 1
    assert len(result.tasks) == 1
    assert result.tasks[0].name == "OpenCode-资产同步验证"
    assert result.tasks[0].description == "验证无仓工作区任务展示"


def test_get_repo_diorama_ranks_recent_conversation_and_execution_activity(db: Session):
    user = User(id="u-active", email="active@example.com", hashed_password="x", display_name="Active")
    workspace = Workspace(id="ws-active", name="Active", owner_id=user.id)
    other_workspace = Workspace(id="ws-other", name="Other", owner_id=user.id)
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    old = now - timedelta(days=90)

    def make_task(task_id: str, status: TaskStatus, timestamp: datetime = old) -> SddTask:
        return SddTask(
            id=task_id,
            workspace_id=workspace.id,
            creator_id=user.id,
            name=task_id,
            status=status,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def make_job(
        task: SddTask,
        *,
        status: AiJobStatus = AiJobStatus.SUCCESS,
        channel: AiJobChannel = AiJobChannel.TASK_CHAT,
        started_at: datetime | None = old,
        finished_at: datetime | None = None,
        visibility: str = "workspace",
        session_generation: int | None = None,
        session_turn_id: str | None = None,
    ) -> SddAiJob:
        return SddAiJob(
            task_id=task.id,
            workspace_id=task.workspace_id,
            creator_id=task.creator_id,
            queue_key=f"TASK_CHAT:{task.id}",
            status=status,
            channel=channel,
            started_at=started_at,
            finished_at=finished_at,
            visibility=visibility,
            session_generation=session_generation,
            session_turn_id=session_turn_id,
        )

    completed = make_task("completed", TaskStatus.COMPLETED)
    completed.session_generation = 2
    failed = make_task("failed", TaskStatus.FAILED)
    running = make_task("running", TaskStatus.RUNNING)
    round_completed = make_task("round", TaskStatus.ROUND_COMPLETED)
    interrupted = make_task("interrupted", TaskStatus.INTERRUPTED)
    stale = make_task("stale", TaskStatus.RUNNING, now)
    system_only = make_task("system-only", TaskStatus.RUNNING, now)
    ignored_jobs = make_task("ignored-jobs", TaskStatus.RUNNING, now)
    other_task = make_task("other-completed", TaskStatus.COMPLETED)
    other_task.workspace_id = other_workspace.id
    latest_message = now - timedelta(days=1)
    latest_execution = now - timedelta(days=2)
    current_turn, reverted_turn = [
        TaskSessionTurn(
            id=f"turn-{index}",
            task_id=completed.id,
            workspace_id=workspace.id,
            session_generation=completed.session_generation,
            session_revision=0,
            turn_index=index,
            provider="opencode",
            status=status,
        )
        for index, status in enumerate((TaskSessionTurnStatus.ACTIVE, TaskSessionTurnStatus.REVERTED), 1)
    ]
    db.add_all(
        [
            user,
            workspace,
            other_workspace,
            completed,
            failed,
            running,
            round_completed,
            interrupted,
            stale,
            system_only,
            ignored_jobs,
            other_task,
            current_turn,
            reverted_turn,
            *(make_task(f"metadata-only-{i}", TaskStatus.INITIALIZED, now) for i in range(20)),
            _task_message(completed, latest_message, role=MessageRole.ASSISTANT, session_turn_id=current_turn.id),
            _task_message(completed, now - timedelta(days=3), session_generation=2),
            make_job(completed, finished_at=now - timedelta(days=4), session_generation=2),
            _task_message(completed, now, session_generation=1),
            make_job(completed, finished_at=now, session_generation=1),
            _task_message(completed, now, session_generation=2, session_turn_id=reverted_turn.id),
            make_job(completed, finished_at=now, session_generation=2, session_turn_id=reverted_turn.id),
            _task_message(failed, now - timedelta(days=6)),
            make_job(failed, status=AiJobStatus.FAILED, finished_at=latest_execution),
            make_job(running, status=AiJobStatus.RUNNING, started_at=now - timedelta(days=8)),
            _task_message(round_completed, now - timedelta(days=20)),
            _task_message(interrupted, now - timedelta(days=40)),
            _task_message(stale, now - timedelta(days=65)),
            _task_message(system_only, now, role=MessageRole.SYSTEM),
            _task_message(system_only, now, role=MessageRole.ASSISTANT, message_type=MessageType.INIT_REASON),
            make_job(ignored_jobs, status=AiJobStatus.CANCELLED, started_at=None, finished_at=now),
            make_job(ignored_jobs, channel=AiJobChannel.BACKGROUND, finished_at=now),
            make_job(ignored_jobs, status=AiJobStatus.REVERTED, finished_at=now),
            make_job(ignored_jobs, visibility="private", finished_at=now),
            _task_message(other_task, now),
        ]
    )
    db.commit()

    result = diorama_service.get_repo_diorama(db, workspace.id, days=30, include_windows=True)

    expected_ids = ["completed", "failed", "running", "round"]
    assert [task.id for task in result.tasks] == expected_ids
    assert [task.id for task in result.windows[14].tasks] == expected_ids[:3]
    assert [task.id for task in result.windows[60].tasks] == [*expected_ids, "interrupted"]
    task_json = result.model_dump(mode="json")["tasks"]
    assert task_json[0]["last_activity_at"] == latest_message.replace(tzinfo=timezone.utc).isoformat()
    assert task_json[1]["last_activity_at"] == latest_execution.replace(tzinfo=timezone.utc).isoformat()

    for i in range(20):
        task = make_task(f"active-{i:02d}", TaskStatus.COMPLETED)
        db.add_all([task, _task_message(task, now - timedelta(days=4))])
    db.commit()

    limited = diorama_service.get_repo_diorama(db, workspace.id)

    assert [task.id for task in limited.tasks] == [*expected_ids[:2], *(f"active-{i:02d}" for i in range(16))]
