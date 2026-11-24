"""2.5D 多仓沙盘后端聚合服务单元测试。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy.orm import Session

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.auth.models.user import User, Workspace, WorkspaceMember, WorkspaceRole  # noqa: E402
from app.domains.dashboard.services import diorama_service  # noqa: E402
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

    db.add_all([user, ws, member, repo_fe, repo_be, repo_missing, task, binding, proposal, prop_repo, prop_file])
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
    assert len(result.members) == 1
    assert len(result.tasks) == 1
    assert "wr-fe" in result.tasks[0].repos
    assert "wr-fe::components/chat" in result.tasks[0].modules
    assert result.tasks[0].added == 18
    assert result.tasks[0].deleted == 4


def test_get_repo_diorama_missing_workspace_returns_empty(db: Session):
    diorama_service.invalidate_diorama_cache()
    result = diorama_service.get_repo_diorama(db, "missing-ws-id", days=30, refresh=True)
    assert result.workspace_id == "missing-ws-id"
    assert result.repos == []
    assert result.tasks == []
