import os
import subprocess
import sys
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.database import Base  # noqa: E402
from app.domains.auth.models.user import (
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)
from app.domains.task.models.task import SddTask
from app.domains.task.models.task import TaskStatus  # noqa: E402
from app.domains.workflow.services import change_proposal_service


def _run_git(args, cwd):
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed with code {result.returncode}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    return result


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _seed_repo(repo_path: str):
    _run_git(["init"], cwd=repo_path)
    _run_git(["config", "user.email", "tester@example.com"], cwd=repo_path)
    _run_git(["config", "user.name", "tester"], cwd=repo_path)
    with open(os.path.join(repo_path, "README.md"), "w", encoding="utf-8") as handle:
        handle.write("hello\n")
    _run_git(["add", "README.md"], cwd=repo_path)
    _run_git(["commit", "-m", "seed"], cwd=repo_path)
    _run_git(["branch", "-M", "main"], cwd=repo_path)


def _seed_db(db, repo_path: str):
    user = User(id="user-1", email="user@example.com", hashed_password="x", display_name="User")
    workspace = Workspace(
        id="ws-1",
        name="Workspace",
        owner_id=user.id,
        project_path=repo_path,
        git_repo_url="https://example.com/repo.git",
    )
    member = WorkspaceMember(
        id="member-1",
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.OWNER,
        permissions_json="[]",
        is_expert=True,
    )
    task = SddTask(
        id="task-1",
        workspace_id=workspace.id,
        creator_id=user.id,
        name="Task",
        project_path=repo_path,
        git_repo_url=workspace.git_repo_url,
        status=TaskStatus.PENDING,
    )
    db.add_all([user, workspace, member, task])
    db.commit()
    return user, workspace, task


def test_change_proposal_service_creates_assets_and_records_local_results(db_session):
    with tempfile.TemporaryDirectory() as repo_path:
        _seed_repo(repo_path)
        user, workspace, task = _seed_db(db_session, repo_path)
        with open(os.path.join(repo_path, "README.md"), "a", encoding="utf-8") as handle:
            handle.write("world\n")
        with open(os.path.join(repo_path, "feature.txt"), "w", encoding="utf-8") as handle:
            handle.write("feature\n")

        proposal = change_proposal_service.create_change_proposal(
            db_session,
            task=task,
            workspace=workspace,
            creator_id=user.id,
            summary="Ready for local apply",
            risk_notes="Low risk",
        )

        assert proposal.status.value == "generated"
        assert proposal.proposal_no == 1
        assert proposal.patch_set_no == 1
        assert proposal.base_commit_sha
        assert proposal.patch_asset_id
        assert proposal.patch_asset_version_id
        assert proposal.changed_files_count == 2
        assert len(change_proposal_service.list_proposal_files(db_session, proposal_id=proposal.id)) == 2

        raw_patch, filename = change_proposal_service.read_patch_file(db_session, proposal)
        assert b"feature.txt" in raw_patch
        assert filename.endswith(".patch")

        latest = change_proposal_service.get_latest_task_proposal(db_session, task_id=task.id)
        assert latest.id == proposal.id

        change_proposal_service.mark_patch_downloaded(db_session, proposal)
        db_session.refresh(proposal)
        assert proposal.status.value == "downloaded"

        with pytest.raises(change_proposal_service.ChangeProposalError) as mismatch:
            change_proposal_service.record_apply_result(
                db_session,
                task=task,
                user=user,
                proposal_id=proposal.id,
                status="applied",
                base_commit_sha="bad-base",
            )
        assert mismatch.value.status_code == 409

        applied = change_proposal_service.record_apply_result(
            db_session,
            task=task,
            user=user,
            proposal_id=proposal.id,
            status="applied",
            base_commit_sha=proposal.base_commit_sha,
            local_head_sha="local-head",
        )
        assert applied.status.value == "applied"

        run = change_proposal_service.create_verification_run(
            db_session,
            task=task,
            user=user,
            proposal_id=proposal.id,
            agent_id="agent-1",
            machine_name="devbox",
            os_name="Windows",
            command="pytest",
            status="success",
            duration_ms=1200,
            base_commit_sha=proposal.base_commit_sha,
            local_head_sha="local-head",
            log_excerpt="ok",
            started_at=None,
            finished_at=None,
        )
        assert run.status.value == "success"
        db_session.refresh(proposal)
        assert proposal.status.value == "verified"

        run = change_proposal_service.attach_verification_log(
            db_session,
            task=task,
            run_id=run.id,
            user=user,
            file_name="pytest.log",
            file_content=b"pytest ok",
        )
        assert run.log_asset_id
        assert "pytest ok" in (run.log_excerpt or "")

        report = change_proposal_service.create_conflict_report(
            db_session,
            task=task,
            user=user,
            proposal_id=proposal.id,
            agent_id="agent-1",
            machine_name="devbox",
            base_commit_sha=proposal.base_commit_sha,
            local_head_sha="local-head",
            conflicted_files=["README.md"],
            git_apply_stderr="patch failed",
            conflict_excerpt=None,
            report_file_name="conflict.log",
            report_file_content=b"conflict details",
        )
        assert report.report_asset_id
        db_session.refresh(proposal)
        assert proposal.status.value == "conflict"
