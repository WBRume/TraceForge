import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

import app.domains.api_mock.models.api_mock  # noqa: F401,E402
import app.domains.task.models.test_result  # noqa: F401,E402
import app.domains.workflow.models.task_change  # noqa: F401,E402
import app.domains.workspace_asset.models.workspace_asset  # noqa: F401,E402
from app.database import Base  # noqa: E402
from app.domains.auth.models.user import User, Workspace  # noqa: E402
from app.domains.task.models.task import SddTask, TaskStatus  # noqa: E402
from app.domains.task.models.task_cli_bootstrap import (  # noqa: E402
    SddTaskCliBootstrap,
    TaskCliBootstrapStatus,
)
from app.domains.task.services import task_cli_state_service as service  # noqa: E402


def _build_session(*, expire_on_commit=False):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=expire_on_commit)


def _seed_bootstrap(db, *, status=TaskCliBootstrapStatus.PENDING):
    user = User(id="user-1", email="user@example.com", hashed_password="x", display_name="User")
    workspace = Workspace(id="ws-1", name="Workspace", owner_id=user.id)
    task = SddTask(
        id="task-1",
        workspace_id=workspace.id,
        creator_id=user.id,
        name="Task",
        project_path="G:/tmp/task-1",
        status=TaskStatus.PENDING,
    )
    record = SddTaskCliBootstrap(
        workspace_id=workspace.id,
        task_id=task.id,
        status=status,
        progress=0,
        message=None,
        baseline_dir="G:/tmp/task-1",
        refresh_mode="FULL",
    )
    db.add_all([user, workspace, task, record])
    db.commit()
    db.refresh(record)
    return record  # noqa: E402


def test_session_context_uses_cli_project_store_snapshot(tmp_path, monkeypatch):
    claude_home = tmp_path / "claude-home"
    monkeypatch.setenv("CLAUDE_HOME", str(claude_home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

    project_path = tmp_path / "workspace" / "base"
    local_claude = project_path / ".claude"
    local_claude.mkdir(parents=True)

    session_id = "23aa02a5-0499-480c-9083-55a4ba59277b"
    project_store = Path(service._claude_project_store_dir(str(project_path)))
    project_store.mkdir(parents=True)
    (project_store / f"{session_id}.jsonl").write_text(
        '{"type":"result","subtype":"success"}\n',
        encoding="utf-8",
    )

    source_kind, source_dir = service._resolve_session_context_location(
        str(project_path),
        session_id,
    )

    assert source_kind == "project_store"
    assert Path(source_dir) == project_store


def test_session_context_does_not_fallback_to_workspace_claude(
    tmp_path,
    monkeypatch,
):
    claude_home = tmp_path / "claude-home"
    monkeypatch.setenv("CLAUDE_HOME", str(claude_home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

    project_path = tmp_path / "workspace" / "base"
    local_claude = project_path / ".claude"
    local_claude.mkdir(parents=True)

    session_id = "local-session"
    (local_claude / f"{session_id}.jsonl").write_text(
        '{"type":"result","subtype":"success"}\n',
        encoding="utf-8",
    )

    source_kind, source_dir = service._resolve_session_context_location(
        str(project_path),
        session_id,
    )

    assert source_kind == "project_store"
    assert Path(source_dir) == Path(service._claude_project_store_dir(str(project_path)))
    assert Path(source_dir) != local_claude
    assert service._session_snapshot_exists(source_dir, session_id) is False


def test_claude_project_store_uses_config_dir_override(tmp_path, monkeypatch):
    claude_config = tmp_path / "custom-claude"
    monkeypatch.delenv("CLAUDE_HOME", raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_config))

    project_path = tmp_path / "workspace" / "base"

    assert Path(service._claude_project_store_dir(str(project_path))).parent == (
        claude_config / "projects"
    )


def test_resolve_bootstrap_spec_path_returns_original_doc_without_staging(tmp_path):
    spec = tmp_path / "uploads" / "需求.docx"
    spec.parent.mkdir(parents=True)
    spec.write_bytes(b"spec-bytes")

    resolved = service._resolve_bootstrap_spec_path(
        task_spec_doc_path=str(spec),
        version_original_path="",
    )

    assert resolved == os.path.abspath(str(spec))
    # 纯路径解析：不再在任务目录创建 .sdd 副本或复制 skills
    assert not (tmp_path / ".sdd").exists()
    assert not (tmp_path / ".claude" / "skills").exists()


def test_resolve_bootstrap_spec_path_prefers_version_original(tmp_path):
    task_spec = tmp_path / "uploads" / "需求.docx"
    task_spec.parent.mkdir(parents=True)
    task_spec.write_bytes(b"task-spec")
    version_original = tmp_path / "versions" / "需求-v2.docx"
    version_original.parent.mkdir(parents=True)
    version_original.write_bytes(b"version-spec")

    resolved = service._resolve_bootstrap_spec_path(
        task_spec_doc_path=str(task_spec),
        version_original_path=str(version_original),
    )

    assert resolved == os.path.abspath(str(version_original))


def test_request_bootstrap_run_resets_and_returns_record():
    SessionLocal = _build_session()
    db = SessionLocal()
    record = _seed_bootstrap(db, status=TaskCliBootstrapStatus.FAILED)
    record.progress = 100
    record.error_message = "CLI crashed"
    db.commit()

    updated = service.request_bootstrap_run(db, workspace_id="ws-1", task_id="task-1")

    assert updated.status == TaskCliBootstrapStatus.PENDING
    assert updated.progress == 0
    assert updated.message == "Baseline build requested"
    assert updated.error_message is None


def test_request_bootstrap_run_running_is_idempotent():
    SessionLocal = _build_session()
    db = SessionLocal()
    record = _seed_bootstrap(db, status=TaskCliBootstrapStatus.RUNNING)
    record.progress = 55
    record.message = "Reading specification"
    db.commit()

    updated = service.request_bootstrap_run(db, workspace_id="ws-1", task_id="task-1")

    assert updated.status == TaskCliBootstrapStatus.RUNNING
    assert updated.progress == 55


def test_request_bootstrap_run_rejects_ready_and_missing():
    SessionLocal = _build_session()
    db = SessionLocal()
    _seed_bootstrap(db, status=TaskCliBootstrapStatus.READY)

    with pytest.raises(ValueError):
        service.request_bootstrap_run(db, workspace_id="ws-1", task_id="task-1")
    with pytest.raises(KeyError):
        service.request_bootstrap_run(db, workspace_id="ws-1", task_id="task-missing")


def test_ensure_bootstrap_ready_or_start_lazy_starts_pending(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    _seed_bootstrap(db, status=TaskCliBootstrapStatus.PENDING)

    scheduled = []
    monkeypatch.setattr(service, "schedule_bootstrap", lambda task_id: scheduled.append(task_id))

    with pytest.raises(service.BootstrapNotReadyError) as exc_info:
        service.ensure_bootstrap_ready_or_start(db, workspace_id="ws-1", task_id="task-1")

    assert "Baseline build started" in str(exc_info.value)
    assert scheduled == ["task-1"]


def test_ensure_bootstrap_ready_or_start_ready_returns_record():
    SessionLocal = _build_session()
    db = SessionLocal()
    record = _seed_bootstrap(db, status=TaskCliBootstrapStatus.READY)

    result = service.ensure_bootstrap_ready_or_start(db, workspace_id="ws-1", task_id="task-1")

    assert result.id == record.id


def test_ensure_bootstrap_ready_or_start_running_reports_progress():
    SessionLocal = _build_session()
    db = SessionLocal()
    _seed_bootstrap(db, status=TaskCliBootstrapStatus.RUNNING)
    record = db.query(SddTaskCliBootstrap).filter(SddTaskCliBootstrap.task_id == "task-1").one()
    record.progress = 42
    db.commit()

    with pytest.raises(service.BootstrapNotReadyError) as exc_info:
        service.ensure_bootstrap_ready_or_start(db, workspace_id="ws-1", task_id="task-1")

    assert "42%" in str(exc_info.value)


def test_ensure_bootstrap_ready_or_start_failed_requires_manual_retry(monkeypatch):
    SessionLocal = _build_session()
    db = SessionLocal()
    _seed_bootstrap(db, status=TaskCliBootstrapStatus.FAILED)

    scheduled = []
    monkeypatch.setattr(service, "schedule_bootstrap", lambda task_id: scheduled.append(task_id))

    with pytest.raises(service.BootstrapNotReadyError):
        service.ensure_bootstrap_ready_or_start(db, workspace_id="ws-1", task_id="task-1")

    assert scheduled == []

